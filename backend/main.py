"""
FastAPI backend for the clinic intake system.

Endpoints:
  POST /submit  — receives the intake form, writes to GHL, starts Ads polling if needed
  GET  /health  — simple liveness check

All emails are handled by GHL workflows triggered by contact tags.
No email code lives here.
"""

import logging
import os

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from ghl import create_or_update_contact, setup_custom_fields
from google_ads import add_to_polling_state, poll_for_access
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
    """
    logger.info("Server starting — running GHL custom field setup...")
    await setup_custom_fields()
    logger.info("Startup complete.")


# ── Routes ────────────────────────────────────────────────────────────────────

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

    # If the clinic confirmed sending the Google Ads invite, start polling
    if submission.has_google_ads_yes() and submission.invite_confirmed():
        logger.info(
            f"Starting Google Ads access polling for {submission.clinic_name} "
            f"(contact: {ghl_contact_id})"
        )
        # Register in polling state first (so it's trackable immediately)
        add_to_polling_state(submission.clinic_name, ghl_contact_id)

        # Add the background polling task — runs async, doesn't block this response
        background_tasks.add_task(poll_for_access, submission.clinic_name, ghl_contact_id)

    return {
        "status": "success",
        "message": "Brief being generated",
        "contact_id": ghl_contact_id,
    }
