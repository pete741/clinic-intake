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
from typing import Optional

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from emailer import send_submission_notification
from ghl import create_or_update_contact, setup_custom_fields
from google_ads import run_ads_report_now
from models import IntakeSubmission

load_dotenv()

# ── Sentry ────────────────────────────────────────────────────────────────────
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN", ""),
    integrations=[FastApiIntegration(), AsyncioIntegration()],
    traces_sample_rate=0.2,   # 20% of requests traced — enough for debugging
    send_default_pii=False,
)

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
    logger.info("Server starting — running GHL custom field setup...")
    await setup_custom_fields()
    asyncio.create_task(_check_token_expiry())
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


def _is_google_ads_token_valid() -> bool:
    """
    Validates the Google Ads refresh token by attempting to mint an access
    token. Returns True if Google accepted the token, False otherwise.

    This replaces age-based expiry checks. Once the OAuth app is in
    Production status (verified or not), refresh tokens issued by it do not
    expire on a 7-day cycle, so age is no longer a useful proxy. Actual
    minting is the only reliable signal.
    """
    client_id     = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
    refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")
    if not all([client_id, client_secret, refresh_token]):
        logger.warning("Google Ads OAuth env vars not all set, treating as invalid")
        return False
    try:
        import httpx
        with httpx.Client(timeout=15) as c:
            r = c.post("https://oauth2.googleapis.com/token", data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            })
        if r.status_code == 200:
            return True
        logger.warning(f"Google Ads token validation rejected (status={r.status_code}): {r.text[:200]}")
        return False
    except Exception as exc:
        # Transient network errors are NOT a validity signal. Log but do not
        # fire the warning email, otherwise a flaky network triggers spam.
        logger.warning(f"Google Ads token validation network error (treating as still valid): {exc}")
        return True


async def _check_token_expiry() -> None:
    """
    Validates the Google Ads refresh token. If validation fails, emails pete
    a warning to re-run reauth.py. Runs once on startup, also called by
    /token-health daily.
    """
    if _is_google_ads_token_valid():
        logger.info("Google Ads refresh token validated OK")
    else:
        logger.warning("Google Ads refresh token failed validation, sending warning")
        _send_token_expiry_warning()


def _send_token_expiry_warning() -> None:
    """Emails pete a warning that the Google Ads token failed validation."""
    from emailer import _send

    subject = "Action needed: Google Ads refresh token failed validation"
    html = """
<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto;padding:24px;">
  <div style="background:#dc2626;padding:14px 20px;border-radius:8px 8px 0 0;">
    <h2 style="color:#fff;margin:0;font-size:16px;">Google Ads Token Failed Validation</h2>
  </div>
  <div style="background:#fef2f2;border:1px solid #fecaca;border-top:none;
              padding:20px;border-radius:0 0 8px 8px;">
    <p style="color:#374151;margin:0 0 12px;">
      Google rejected the configured refresh token when validated just now.
      The cold-audit pipeline cannot pull Google Ads data until this is fixed.
    </p>
    <p style="color:#374151;margin:0 0 12px;">
      Run this command to mint a fresh token (takes 30 seconds):
    </p>
    <div style="background:#1a1a2e;border-radius:6px;padding:12px 16px;
                font-family:monospace;font-size:13px;color:#a5f3fc;">
      source /Users/elitepete/clinic-intake/backend/venv/bin/activate &amp;&amp;
      python3 /Users/elitepete/clinic-intake/backend/reauth.py
    </div>
    <p style="color:#6b7280;font-size:12px;margin:12px 0 0;">
      After running, update GOOGLE_ADS_REFRESH_TOKEN and
      GOOGLE_ADS_TOKEN_REFRESHED_AT in Render environment variables.
    </p>
  </div>
</div>
"""
    text = (
        "Google rejected the configured refresh token when validated. "
        "The cold-audit pipeline is offline until this is fixed.\n\n"
        "Run: source /Users/elitepete/clinic-intake/backend/venv/bin/activate && "
        "python3 /Users/elitepete/clinic-intake/backend/reauth.py\n\n"
        "Then update GOOGLE_ADS_REFRESH_TOKEN and GOOGLE_ADS_TOKEN_REFRESHED_AT "
        "in Render environment variables."
    )
    if _send(subject, html, text=text):
        logger.info("Token validation warning email sent to pete@clinicmastery.com")
    else:
        logger.error("Failed to send token validation warning")


@app.get("/health")
async def health():
    """Simple liveness check. Returns 200 if the server is running."""
    return {"status": "ok"}


@app.get("/token-health")
async def token_health():
    """
    Validates the Google Ads refresh token by attempting to mint an access
    token. Called by UptimeRobot daily. Sends pete a warning email only if
    Google rejects the token (no more age-based false alarms).
    """
    from datetime import datetime, timezone

    refreshed_at_str = os.getenv("GOOGLE_ADS_TOKEN_REFRESHED_AT", "")
    age_days = None
    if refreshed_at_str:
        try:
            refreshed_at = datetime.fromisoformat(refreshed_at_str)
            age_days = (datetime.now(timezone.utc) - refreshed_at).days
        except Exception:
            pass

    is_valid = _is_google_ads_token_valid()
    if not is_valid:
        _send_token_expiry_warning()

    return {
        "status":         "ok" if is_valid else "invalid",
        "token_age_days": age_days,
        "refreshed_at":   refreshed_at_str or None,
    }


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

    # Google Ads polling is handled by the cron job (poll_worker.py) — nothing to start here.
    # The contact is tagged ads-invite-confirmed and google_ads_data_status=Pending in GHL,
    # which is all the cron job needs to pick it up within 15 minutes.

    if ads_tag == "ads-not-applicable":
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
    google_ads_customer_id: Optional[str] = None  # skip name matching if provided


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
        customer_id_override=req.google_ads_customer_id,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("detail"))

    return result


class ResendNotificationRequest(BaseModel):
    submission: dict
    admin_key: str


@app.post("/resend-notification")
async def resend_notification(req: ResendNotificationRequest, background_tasks: BackgroundTasks):
    """Admin endpoint: re-sends the submission notification email for a given submission dict."""
    if ADMIN_KEY and req.admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    background_tasks.add_task(send_submission_notification, req.submission)
    return {"status": "ok", "message": "Notification queued"}
