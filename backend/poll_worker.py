"""
Render Cron Job — runs every 15 minutes.

Queries GHL for all clinics with google_ads_data_status = Pending,
attempts to find their Google Ads account, and fires the audit report
when access is confirmed.

Replaces the in-process asyncio polling loop that was fragile across
deploys and memory crashes.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

MAX_POLL_HOURS = 72


async def main():
    from ghl import setup_custom_fields, get_pending_polls, add_tag_to_contact, update_contact_field
    from google_ads import run_ads_report_now

    logger.info("Poll worker starting...")
    await setup_custom_fields()

    pending = await get_pending_polls()
    logger.info(f"Found {len(pending)} pending clinic(s)")

    if not pending:
        logger.info("Nothing to do. Exiting.")
        return

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
        else:
            logger.error(f"Error for {clinic_name}: {result.get('detail')}")

    logger.info("Poll worker complete.")


if __name__ == "__main__":
    asyncio.run(main())
