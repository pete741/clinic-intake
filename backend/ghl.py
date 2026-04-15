"""
GoHighLevel (GHL) API client.

Handles:
  - Custom field setup (run once on startup)
  - Creating or updating contacts with all intake form fields
  - Tagging contacts to trigger GHL workflows

Auth: Private Integration Token via GHL_API_KEY env var.
API version: 2021-07-28
Base URL: https://services.leadconnectorhq.com
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

GHL_API_KEY = os.getenv("GHL_API_KEY", "")
GHL_LOCATION_ID = os.getenv("GHL_LOCATION_ID", "")
BASE_URL = "https://services.leadconnectorhq.com"

# File that caches custom field IDs so we don't re-create them on every startup
FIELD_IDS_FILE = Path(__file__).parent / "field_ids.json"

# All custom fields this system needs. GHL dataType options: TEXT, NUMERICAL, DATE
REQUIRED_FIELDS = [
    {"name": "clinic_name",                "dataType": "TEXT"},
    {"name": "primary_specialty",          "dataType": "TEXT"},
    {"name": "suburb",                     "dataType": "TEXT"},
    {"name": "clinic_state",               "dataType": "TEXT"},  # "state" conflicts with GHL standard field
    {"name": "num_practitioners",          "dataType": "NUMERICAL"},
    {"name": "website_url",                "dataType": "TEXT"},
    {"name": "avg_appointment_fee",        "dataType": "NUMERICAL"},
    {"name": "avg_visits_per_patient",     "dataType": "NUMERICAL"},
    {"name": "new_patients_per_month",     "dataType": "NUMERICAL"},
    {"name": "monthly_ad_spend",           "dataType": "NUMERICAL"},
    {"name": "appointment_types_to_grow",  "dataType": "TEXT"},
    {"name": "main_goal",                  "dataType": "TEXT"},
    {"name": "additional_context",         "dataType": "TEXT"},
    {"name": "has_google_ads",             "dataType": "TEXT"},
    {"name": "invite_sent",                "dataType": "TEXT"},
    {"name": "intake_date",                "dataType": "TEXT"},
    {"name": "google_ads_data_status",     "dataType": "TEXT"},
    {"name": "google_ads_summary",         "dataType": "TEXT"},
]

# In-memory cache of field name → GHL field ID (populated by setup_custom_fields)
_field_id_map: dict[str, str] = {}


# ── Auth headers ──────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Version": "2021-07-28",
        "Content-Type": "application/json",
    }


# ── Custom field setup ────────────────────────────────────────────────────────

async def setup_custom_fields() -> None:
    """
    Ensures all required custom fields exist in GHL for this location.
    Loads cached field IDs from field_ids.json if available, then reconciles
    against the live GHL API. Creates any missing fields.

    Call this once at app startup.
    """
    global _field_id_map

    # Load any previously cached IDs
    if FIELD_IDS_FILE.exists():
        with open(FIELD_IDS_FILE) as f:
            _field_id_map = json.load(f)
        logger.info(f"Loaded {len(_field_id_map)} cached field IDs from {FIELD_IDS_FILE}")

    async with httpx.AsyncClient() as client:
        # Fetch existing custom fields from GHL
        resp = await client.get(
            f"{BASE_URL}/locations/{GHL_LOCATION_ID}/customFields",
            headers=_headers(),
        )
        if resp.status_code != 200:
            logger.error(f"Failed to fetch GHL custom fields: {resp.status_code} — {resp.text}")
            return

        raw_fields = resp.json().get("customFields", [])
        logger.info(f"Found {len(raw_fields)} existing custom fields in GHL")

        # Build a lookup that normalises field names for matching.
        # GHL sometimes stores names with spaces/capitals (e.g. "Clinic Name")
        # while we use snake_case — normalise both sides for comparison.
        def _normalise(s: str) -> str:
            return s.lower().replace(" ", "_").replace("-", "_")

        existing_by_norm = {_normalise(f["name"]): f["id"] for f in raw_fields}
        existing_by_exact = {f["name"]: f["id"] for f in raw_fields}

        # Create any fields that are missing
        for field_def in REQUIRED_FIELDS:
            name = field_def["name"]
            norm = _normalise(name)

            # 1. Exact match in GHL response
            if name in existing_by_exact:
                _field_id_map[name] = existing_by_exact[name]
            # 2. Normalised match (handles "Clinic Name" → "clinic_name")
            elif norm in existing_by_norm:
                _field_id_map[name] = existing_by_norm[norm]
                logger.info(f"Matched existing field '{name}' via normalised name")
            # 3. Already in our cache from a previous run
            elif name in _field_id_map:
                pass
            else:
                # Need to create it
                create_resp = await client.post(
                    f"{BASE_URL}/locations/{GHL_LOCATION_ID}/customFields",
                    headers=_headers(),
                    json={"name": name, "dataType": field_def["dataType"]},
                )
                if create_resp.status_code in (200, 201):
                    new_id = create_resp.json().get("customField", {}).get("id", "")
                    _field_id_map[name] = new_id
                    logger.info(f"Created custom field '{name}' with ID {new_id}")
                elif "already exists" in create_resp.text:
                    # GHL rejected creation because the field exists under a different
                    # name variant — log it and move on (won't block submissions)
                    logger.warning(
                        f"Field '{name}' already exists in GHL but couldn't be matched "
                        f"automatically. Check field_ids.json and add it manually if needed."
                    )
                else:
                    logger.error(
                        f"Failed to create custom field '{name}': "
                        f"{create_resp.status_code} — {create_resp.text}"
                    )

    # Persist the updated map to disk so we don't re-create on next startup
    with open(FIELD_IDS_FILE, "w") as f:
        json.dump(_field_id_map, f, indent=2)

    logger.info(f"Custom field setup complete. {len(_field_id_map)} fields mapped.")


def _build_custom_fields(data: dict) -> list[dict]:
    """
    Converts the flat intake data dict into the GHL customFields array format,
    using the field IDs resolved during setup_custom_fields().
    """
    mappings = {
        "clinic_name":               str(data.get("clinic_name", "")),
        "primary_specialty":         str(data.get("primary_specialty", "")),
        "suburb":                    str(data.get("suburb", "")),
        "clinic_state":              str(data.get("state", "")),  # maps form "state" → GHL "clinic_state"
        "num_practitioners":         str(data.get("num_practitioners", "")),
        "website_url":               str(data.get("website_url", "")),
        "avg_appointment_fee":       str(data.get("avg_appointment_fee", "")),
        "avg_visits_per_patient":    str(data.get("avg_visits_per_patient", "")),
        "new_patients_per_month":    str(data.get("new_patients_per_month", "")),
        "monthly_ad_spend":          str(data.get("monthly_ad_spend", "")),
        "appointment_types_to_grow": str(data.get("appointment_types_to_grow", "")),
        "main_goal":                 str(data.get("main_goal", "")),
        "additional_context":        str(data.get("additional_context") or ""),
        "has_google_ads":            str(data.get("has_google_ads") or "No"),
        "invite_sent":               str(data.get("invite_sent") or "Not sent"),
        "intake_date":               datetime.now(timezone.utc).isoformat(),
        "google_ads_data_status":    data.get("google_ads_data_status", "Not requested"),
        "google_ads_summary":        data.get("google_ads_summary", ""),
    }

    result = []
    for field_name, value in mappings.items():
        field_id = _field_id_map.get(field_name)
        if field_id:
            result.append({"id": field_id, "value": value})
        else:
            # If we don't have the ID yet, skip rather than crash
            logger.warning(f"No field ID found for '{field_name}' — skipping")
    return result


# ── Contact creation / update ─────────────────────────────────────────────────

async def create_or_update_contact(
    submission,  # IntakeSubmission model instance
    ads_invite_tag: str,
) -> Optional[str]:
    """
    Creates or updates a GHL contact for the incoming intake submission.

    Matching priority:
      1. Phone number — if provided, search GHL by phone first
      2. Email upsert — fallback if no phone match found

    Returns the GHL contact ID, or None on failure.
    """
    tags = [
        "intake-submitted",
        f"specialty-{submission.primary_specialty.lower().replace(' ', '-')}",
        ads_invite_tag,
    ]

    google_ads_data_status = (
        "Pending"
        if (submission.has_google_ads_yes() and submission.invite_confirmed())
        else "Not requested"
    )

    custom_fields = _build_custom_fields({
        **submission.model_dump(),
        "google_ads_data_status": google_ads_data_status,
    })

    contact_payload = {
        "locationId": GHL_LOCATION_ID,
        "name": submission.clinic_name,
        "email": submission.email,
        "tags": tags,
        "source": "Intake Form",
        "customFields": custom_fields,
    }
    if submission.phone:
        contact_payload["phone"] = submission.phone

    async with httpx.AsyncClient() as client:
        contact_id = None

        # 1. Phone-first: search for existing contact by phone number
        if submission.phone:
            contact_id = await _find_contact_by_phone(client, submission.phone)
            if contact_id:
                logger.info(f"Found existing contact {contact_id} by phone — updating")
                resp = await client.put(
                    f"{BASE_URL}/contacts/{contact_id}",
                    headers=_headers(),
                    json=contact_payload,
                )
                if resp.status_code not in (200, 201):
                    logger.error(
                        f"Failed to update GHL contact by phone: {resp.status_code} - {resp.text}"
                    )
                    return None
                logger.info(f"Updated GHL contact {contact_id} for {submission.clinic_name}")
                return contact_id

        # 2. Fall back to email upsert (creates if new, updates if email matches)
        resp = await client.post(
            f"{BASE_URL}/contacts/upsert",
            headers=_headers(),
            json=contact_payload,
        )
        if resp.status_code not in (200, 201):
            logger.error(
                f"Failed to upsert GHL contact: {resp.status_code} - {resp.text}"
            )
            return None
        data = resp.json()
        contact_id = (
            data.get("contact", {}).get("id")
            or data.get("id")
        )
        action = "Updated" if data.get("traceId") else "Created"
        logger.info(f"{action} GHL contact {contact_id} for {submission.clinic_name}")
        return contact_id


async def _find_contact_by_phone(client: httpx.AsyncClient, phone: str) -> Optional[str]:
    """
    Searches GHL for a contact with the given phone number.
    Returns the contact ID if found, None otherwise.
    """
    resp = await client.get(
        f"{BASE_URL}/contacts/search",
        headers=_headers(),
        params={"phone": phone, "locationId": GHL_LOCATION_ID},
    )
    if resp.status_code != 200:
        logger.error(f"GHL phone search failed: {resp.status_code} — {resp.text}")
        return None
    contacts = resp.json().get("contacts", [])
    return contacts[0].get("id") if contacts else None


async def _find_contact_by_email(client: httpx.AsyncClient, email: str) -> Optional[str]:
    """
    Searches GHL for a contact with the given email address.
    Returns the contact ID if found, None otherwise.
    """
    resp = await client.get(
        f"{BASE_URL}/contacts/search",
        headers=_headers(),
        params={"email": email, "locationId": GHL_LOCATION_ID},
    )
    if resp.status_code != 200:
        logger.error(f"GHL contact search failed: {resp.status_code} — {resp.text}")
        return None

    contacts = resp.json().get("contacts", [])
    if contacts:
        return contacts[0].get("id")
    return None


async def update_contact_field(contact_id: str, field_name: str, value: str) -> bool:
    """
    Updates a single custom field on an existing GHL contact.
    Used by the Google Ads polling task to write back the ads summary.

    Returns True on success, False on failure.
    """
    field_id = _field_id_map.get(field_name)
    if not field_id:
        logger.error(f"Cannot update field '{field_name}' — no field ID in map")
        return False

    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{BASE_URL}/contacts/{contact_id}",
            headers=_headers(),
            json={"customFields": [{"id": field_id, "value": value}]},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                f"Failed to update field '{field_name}' on contact {contact_id}: "
                f"{resp.status_code} — {resp.text}"
            )
            return False
        return True


async def add_tag_to_contact(contact_id: str, tag: str) -> bool:
    """
    Adds a tag to an existing GHL contact.
    Tags trigger GHL workflows — this is how we fire follow-up emails.

    Returns True on success, False on failure.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/contacts/{contact_id}/tags",
            headers=_headers(),
            json={"tags": [tag]},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                f"Failed to add tag '{tag}' to contact {contact_id}: "
                f"{resp.status_code} — {resp.text}"
            )
            return False
        logger.info(f"Added tag '{tag}' to contact {contact_id}")
        return True
