"""
FastAPI backend for the clinic intake system.

Endpoints:
  POST /submit  — receives the intake form, writes to GHL, starts Ads polling if needed
  GET  /health  — simple liveness check

All emails are handled by GHL workflows triggered by contact tags.
No email code lives here.
"""

import asyncio
import logging
import os

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from emailer import send_submission_notification
from ghl import create_or_update_contact, setup_custom_fields
from google_ads import add_to_polling_state, get_resumable_polls, poll_for_access, run_ads_report_now
from models import IntakeSubmission

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Clinic Intake API",
    description="Receives clinic intake forms and pushes data into GoHighLevel.",
    version="1.0.0",
)

# CORS — allow the Next.js frontend to call this API
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # open to all origins so GHL-hosted form can POST
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    """
    Runs when the FastAPI server starts.
    Ensures all required GHL custom fields exist before we accept any submissions.
    Resumes any polling tasks that were running before a deploy restarted the server.
    """
    logger.info("Server starting — running GHL custom field setup...")
    await setup_custom_fields()

    # Resume polls killed by a deploy restart — GHL is the source of truth
    pending = await get_resumable_polls()
    if pending:
        logger.info(f"Resuming {len(pending)} pending poll(s) after restart")
        for entry in pending:
            asyncio.create_task(poll_for_access(
                entry["clinic_name"],
                entry["ghl_contact_id"],
                entry.get("avg_appointment_fee", 0.0),
                entry.get("avg_visits_per_patient", 0.0),
            ))

    logger.info("Startup complete.")


# ── Routes ────────────────────────────────────────────────────────────────────

def _send_intake_brief_task(clinic_name: str, submission_dict: dict) -> None:
    """
    Background task: generates a short intake brief PDF and emails it to pete.
    Called for clinics that skipped or don't have Google Ads.
    """
    try:
        from pdf_report import generate_intake_brief
        from emailer import send_intake_brief
        pdf_bytes = generate_intake_brief(submission_dict)
        sent = send_intake_brief(clinic_name, pdf_bytes, submission_dict)
        if sent:
            logger.info(f"Intake brief emailed for {clinic_name}")
        else:
            logger.warning(f"Intake brief generated but email failed for {clinic_name}")
    except Exception as exc:
        logger.error(f"Intake brief task failed for {clinic_name}: {exc}")


@app.get("/health")
async def health():
    """Simple liveness check. Returns 200 if the server is running."""
    return {"status": "ok"}


@app.post("/submit")
async def submit_intake(
    submission: IntakeSubmission,
    background_tasks: BackgroundTasks,
):
    """
    Receives the completed intake form and:

    1. Creates or updates a GHL contact with all form fields.
    2. Tags the contact appropriately so GHL workflows fire the right emails.
    3. If the clinic confirmed sending a Google Ads invite, starts a background
       polling task that checks every 15 minutes until access appears (up to 72h).

    Always returns immediately — GHL write and tagging are fast,
    and the Ads polling runs in the background.
    """
    logger.info(f"Intake received for: {submission.clinic_name} ({submission.email})")

    # Determine which Google Ads tag to apply
    # These tags trigger GHL workflows — no email code here
    if submission.has_google_ads_yes():
        if submission.invite_confirmed():
            ads_tag = "ads-invite-confirmed"
        else:
            ads_tag = "ads-invite-pending"  # GHL workflow sends follow-up instructions
    else:
        ads_tag = "ads-not-applicable"

    # Write to GHL — this always happens regardless of Ads status
    ghl_contact_id = await create_or_update_contact(submission, ads_tag)

    if ghl_contact_id is None:
        logger.error(f"GHL contact creation failed for {submission.clinic_name}")
        raise HTTPException(
            status_code=502,
            detail="Failed to create contact in CRM. Please try again.",
        )

    logger.info(
        f"GHL contact {ghl_contact_id} created/updated for {submission.clinic_name} "
        f"with tags: intake-submitted, {ads_tag}"
    )

    # Immediate notification to pete — fires before any PDF generation
    background_tasks.add_task(send_submission_notification, submission.model_dump())

    # If the clinic confirmed sending the Google Ads invite, start polling
    if submission.has_google_ads_yes() and submission.invite_confirmed():
        logger.info(
            f"Starting Google Ads access polling for {submission.clinic_name} "
            f"(contact: {ghl_contact_id})"
        )
        # Register in polling state first (so it's trackable + resumable after deploy)
        add_to_polling_state(
            submission.clinic_name, ghl_contact_id,
            submission.avg_appointment_fee, submission.avg_visits_per_patient,
        )

        # Add the background polling task — runs async, doesn't block this response
        background_tasks.add_task(
            poll_for_access,
            submission.clinic_name,
            ghl_contact_id,
            submission.avg_appointment_fee,
            submission.avg_visits_per_patient,
        )

    elif ads_tag == "ads-not-applicable":
        # No Google Ads access — generate a standard intake brief and email it
        background_tasks.add_task(
            _send_intake_brief_task, submission.clinic_name, submission.model_dump()
        )

    return {
        "status": "success",
        "message": "Brief being generated",
        "contact_id": ghl_contact_id,
    }


# ── Admin: force-trigger Google Ads report ────────────────────────────────────

ADMIN_KEY = os.getenv("ADMIN_API_KEY", "")


class TriggerAdsRequest(BaseModel):
    contact_id: str
    clinic_name: str
    avg_appointment_fee: float = 0.0
    avg_visits_per_patient: float = 0.0
    admin_key: str


@app.post("/trigger-ads-report")
async def trigger_ads_report(req: TriggerAdsRequest):
    """
    Admin endpoint: immediately runs the Google Ads report for a given contact
    without waiting for the polling loop.

    Requires the ADMIN_API_KEY env var to be set and passed in the request body.
    """
    if ADMIN_KEY and req.admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    logger.info(
        f"Manual ads trigger requested for {req.clinic_name} / {req.contact_id}"
    )

    result = await run_ads_report_now(
        req.clinic_name,
        req.contact_id,
        req.avg_appointment_fee,
        req.avg_visits_per_patient,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("detail"))

    return result
