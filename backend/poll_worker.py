"""
Render Cron Job — runs every 15 minutes.

Queries GHL for all clinics with google_ads_data_status = Pending,
attempts to find their Google Ads account, and fires the audit report
when access is confirmed.

Once per day (controlled by PENDING_DIGEST_UTC_HOUR, default 21:00 UTC ~
07:00 AEST) emails Pete a digest of any clinics still Pending so nothing
silently times out.

Replaces the in-process asyncio polling loop that was fragile across
deploys and memory crashes.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from dotenv import load_dotenv

load_dotenv()

# Sentry covers cron-side crashes. Without this init, unhandled exceptions in
# the poll worker only surface in Render logs, which Pete does not watch.
# SENTRY_DSN is already set on the cron service; init was the missing piece.
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN", ""),
    integrations=[AsyncioIntegration()],
    traces_sample_rate=0.0,
    send_default_pii=False,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

MAX_POLL_HOURS = 72
# Digest fires on the cron run that lands inside this UTC hour. Cron runs at
# minutes 0/15/30/45, so checking the hour alone gives us four "candidate"
# runs in that hour; we additionally restrict to minute < 15 so it sends once.
PENDING_DIGEST_UTC_HOUR = int(os.getenv("PENDING_DIGEST_UTC_HOUR", "21"))


async def main():
    from ghl import setup_custom_fields, get_pending_polls, add_tag_to_contact, update_contact_field
    from google_ads import run_ads_report_now
    from emailer import send_pending_summary

    logger.info("Poll worker starting...")
    await setup_custom_fields()

    pending = await get_pending_polls()
    logger.info(f"Found {len(pending)} pending clinic(s)")

    still_pending: list[dict] = []
    for entry in pending:
        clinic_name = entry["clinic_name"]
        contact_id  = entry["ghl_contact_id"]
        fee         = entry.get("avg_appointment_fee", 0.0)
        visits      = entry.get("avg_visits_per_patient", 0.0)

        logger.info(f"Checking: {clinic_name} ({contact_id})")

        result = await run_ads_report_now(clinic_name, contact_id, fee, visits)
        status = result.get("status")

        if status == "success":
            logger.info(f"✓ Report sent for {clinic_name}")
        elif status == "not_found":
            logger.info(f"No access yet for {clinic_name} — will retry next cycle")
            still_pending.append(entry)
        else:
            logger.error(f"Error for {clinic_name}: {result.get('detail')}")
            still_pending.append(entry)

    # Daily digest of clinics still waiting on access. Only one cron run per day
    # passes both checks below; the rest skip.
    now = datetime.now(timezone.utc)
    is_digest_run = now.hour == PENDING_DIGEST_UTC_HOUR and now.minute < 15
    if is_digest_run:
        logger.info(f"Digest run window: sending pending summary ({len(still_pending)} clinic(s))")
        send_pending_summary(still_pending)
    else:
        logger.info(
            f"Not in digest window (now={now.strftime('%H:%M')} UTC, "
            f"window={PENDING_DIGEST_UTC_HOUR:02d}:00-{PENDING_DIGEST_UTC_HOUR:02d}:14)"
        )

    logger.info("Poll worker complete.")


if __name__ == "__main__":
    asyncio.run(main())
