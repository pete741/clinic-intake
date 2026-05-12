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

import asyncio
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


# ── Retry helper ──────────────────────────────────────────────────────────────

async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    max_attempts: int = 3,
    **kwargs,
) -> httpx.Response:
    """
    Wraps an httpx request with exponential backoff retry.
    Retries on 429 (rate limit) and 5xx (server errors).
    Raises on final failure.
    """
    for attempt in range(1, max_attempts + 1):
        resp = await client.request(method, url, **kwargs)
        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt == max_attempts:
                return resp
            wait = 2 ** attempt  # 2s, 4s, 8s
            logger.warning(
                f"GHL API {method} {url} returned {resp.status_code} "
                f"— retrying in {wait}s (attempt {attempt}/{max_attempts})"
            )
            await asyncio.sleep(wait)
        else:
            return resp
    return resp


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

def _normalise_name(s: str) -> str:
    """Lowercase, strip punctuation and surrounding whitespace for fuzzy
    comparison of clinic names / specialties."""
    import re as _re
    return _re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


async def _detect_collision(client: httpx.AsyncClient, contact_id: str, submission) -> Optional[dict]:
    """Before we PUT new data over an existing contact, fetch its current
    custom field values and check whether they look like the SAME clinic
    or a DIFFERENT one that just happens to share the matched phone/email.

    Returns a dict describing the collision when the existing values for
    primary_specialty or clinic_name differ from the incoming submission;
    returns None when the data looks consistent.

    Triggered by the CWC ← Hfg incident on 2026-05-03 where a test
    submission overwrote a real client's contact because both used the
    same phone number.
    """
    try:
        resp = await client.get(f"{BASE_URL}/contacts/{contact_id}", headers=_headers())
        if resp.status_code != 200:
            return None
        data = resp.json().get("contact", {})
    except Exception as exc:
        logger.warning(f"Collision check failed for {contact_id}: {exc}")
        return None

    cf = {f["id"]: f.get("value") for f in data.get("customFields", [])}
    spec_id = _field_id_map.get("primary_specialty")
    name_id = _field_id_map.get("clinic_name")
    existing_spec = (cf.get(spec_id) or "") if spec_id else ""
    existing_clinic = (cf.get(name_id) or "") if name_id else ""

    # If neither field was set previously, this is the first time the
    # contact has gone through the intake form — not a collision.
    if not existing_spec and not existing_clinic:
        return None

    incoming_spec = submission.primary_specialty or ""
    incoming_clinic = submission.clinic_name or ""

    spec_changed = (existing_spec
                    and _normalise_name(existing_spec) != _normalise_name(incoming_spec))
    clinic_changed = (existing_clinic
                      and _normalise_name(existing_clinic) != _normalise_name(incoming_clinic))

    if not (spec_changed or clinic_changed):
        return None

    return {
        "contact_id": contact_id,
        "matched_via": "phone" if submission.phone else "email",
        "phone": submission.phone or "",
        "incoming_email": submission.email,
        "existing_email": data.get("email", ""),
        "existing_clinic": existing_clinic,
        "incoming_clinic": incoming_clinic,
        "existing_specialty": existing_spec,
        "incoming_specialty": incoming_spec,
        "spec_changed": spec_changed,
        "clinic_changed": clinic_changed,
    }


async def create_or_update_contact(
    submission,  # IntakeSubmission model instance
    ads_invite_tag: str,
) -> tuple[Optional[str], Optional[dict]]:
    """
    Creates or updates a GHL contact for the incoming intake submission.

    Matching priority:
      1. Phone number — if provided, search GHL by phone first
      2. Email — search by email second
      3. Create new — if no existing contact found

    For existing contacts: custom fields are updated but tags and source are
    never overwritten. New tags are added additively so existing programme tags
    (e.g. Elevate) and contact type are preserved.

    Returns (contact_id, collision_info). collision_info is a dict when the
    matched-by-phone (or email) contact's existing data looks like a
    different clinic from the incoming submission — surfaced in the
    notification email so Pete can spot phone-number reuse before it
    silently corrupts a contact.
    """
    new_tags = [
        "intake-submitted",
        "G Ads Intake Form Completed",
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

    async with httpx.AsyncClient() as client:
        contact_id = None

        # 1. Search by phone
        if submission.phone:
            contact_id = await _find_contact_by_phone(client, submission.phone)
            if contact_id:
                logger.info(f"Found existing contact {contact_id} by phone")

        # 2. Search by email
        if not contact_id:
            contact_id = await _find_contact_by_email(client, submission.email)
            if contact_id:
                logger.info(f"Found existing contact {contact_id} by email")

        collision: Optional[dict] = None

        if contact_id:
            # Detect potential phone-collision BEFORE we overwrite the
            # contact's custom fields. We don't block the update (a clinic
            # rebrand is a legitimate change), but we do flag it loudly.
            collision = await _detect_collision(client, contact_id, submission)
            if collision:
                logger.warning(
                    "POSSIBLE PHONE COLLISION: contact %s previously stored "
                    "clinic=%r specialty=%r email=%r. New submission says "
                    "clinic=%r specialty=%r email=%r. Phone=%r matched both. "
                    "Updating anyway, but flagging on notification email.",
                    contact_id,
                    collision["existing_clinic"], collision["existing_specialty"],
                    collision["existing_email"],
                    collision["incoming_clinic"], collision["incoming_specialty"],
                    collision["incoming_email"],
                    collision["phone"],
                )

            # Existing contact: update custom fields only — never touch tags or
            # source, so programme tags and contact type are preserved.
            # Note: PUT /contacts/{id} does not accept locationId in the body.
            update_payload = {
                "name": submission.clinic_name,
                "email": submission.email,
                "customFields": custom_fields,
            }
            if submission.first_name:
                update_payload["firstName"] = submission.first_name
            if submission.phone:
                update_payload["phone"] = submission.phone

            resp = await _request_with_retry(
                client, "PUT",
                f"{BASE_URL}/contacts/{contact_id}",
                headers=_headers(),
                json=update_payload,
            )

            # GHL may reject with 400 "duplicated contacts" when the phone search
            # returns contact A but the email already belongs to contact B.
            # The error body includes meta.contactId pointing to the correct contact.
            if resp.status_code == 400:
                try:
                    err = resp.json()
                    if "duplicated" in err.get("message", "").lower():
                        canonical_id = err.get("meta", {}).get("contactId")
                        if canonical_id and canonical_id != contact_id:
                            logger.warning(
                                f"Phone→{contact_id} and email→{canonical_id} belong to "
                                f"different contacts. Retrying PUT against canonical contact."
                            )
                            # Strip phone — it belongs to the other contact and would
                            # trigger a second duplicate rejection on the canonical contact.
                            retry_payload = {k: v for k, v in update_payload.items() if k != "phone"}
                            resp = await _request_with_retry(
                                client, "PUT",
                                f"{BASE_URL}/contacts/{canonical_id}",
                                headers=_headers(),
                                json=retry_payload,
                            )
                            contact_id = canonical_id
                except Exception as exc:
                    logger.warning(f"Could not parse duplicate-contact error: {exc}")

            if resp.status_code not in (200, 201):
                logger.error(
                    f"Failed to update GHL contact {contact_id}: {resp.status_code} - {resp.text}"
                )
                return None, None

            # Add intake tags additively — existing tags are never removed
            for tag in new_tags:
                await _add_tag_with_client(client, contact_id, tag)

            logger.info(f"Updated existing GHL contact {contact_id} for {submission.clinic_name}")
            return contact_id, collision

        # 3. New contact: upsert without tags or source so that if GHL internally
        # matches an existing contact, we never overwrite their tag list or
        # reset their contact type. Tags are always added additively below.
        create_payload = {
            "locationId": GHL_LOCATION_ID,
            "name": submission.clinic_name,
            "email": submission.email,
            "customFields": custom_fields,
        }
        if submission.first_name:
            create_payload["firstName"] = submission.first_name
        if submission.phone:
            create_payload["phone"] = submission.phone

        resp = await _request_with_retry(
            client, "POST",
            f"{BASE_URL}/contacts/upsert",
            headers=_headers(),
            json=create_payload,
        )
        if resp.status_code not in (200, 201):
            logger.error(
                f"Failed to create GHL contact: {resp.status_code} - {resp.text}"
            )
            return None, None
        data = resp.json()
        contact_id = (
            data.get("contact", {}).get("id")
            or data.get("id")
        )
        logger.info(f"Created new GHL contact {contact_id} for {submission.clinic_name}")

        # Add intake tags additively — safe for new and existing contacts alike
        for tag in new_tags:
            await _add_tag_with_client(client, contact_id, tag)

        return contact_id, None


async def _add_tag_with_client(client: httpx.AsyncClient, contact_id: str, tag: str) -> None:
    """Adds a single tag to a contact using an already-open client."""
    resp = await _request_with_retry(
        client, "POST",
        f"{BASE_URL}/contacts/{contact_id}/tags",
        headers=_headers(),
        json={"tags": [tag]},
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Failed to add tag '{tag}' to contact {contact_id}: {resp.status_code}")
    else:
        logger.info(f"Added tag '{tag}' to contact {contact_id}")


async def _find_contact_by_phone(client: httpx.AsyncClient, phone: str) -> Optional[str]:
    """
    Searches GHL for a contact with the given phone number.
    Returns the contact ID if found, None otherwise.
    """
    resp = await _request_with_retry(
        client, "POST",
        f"{BASE_URL}/contacts/search",
        headers=_headers(),
        json={
            "locationId": GHL_LOCATION_ID,
            "filters": [{"field": "phone", "operator": "eq", "value": phone}],
            "pageLimit": 1,
        },
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
    resp = await _request_with_retry(
        client, "POST",
        f"{BASE_URL}/contacts/search",
        headers=_headers(),
        json={
            "locationId": GHL_LOCATION_ID,
            "filters": [{"field": "email", "operator": "eq", "value": email}],
            "pageLimit": 1,
        },
    )
    if resp.status_code != 200:
        logger.error(f"GHL contact search failed: {resp.status_code} — {resp.text}")
        return None
    contacts = resp.json().get("contacts", [])
    return contacts[0].get("id") if contacts else None


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
        resp = await _request_with_retry(
            client, "PUT",
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


async def get_contact(contact_id: str) -> dict:
    """
    Fetches a GHL contact by ID and returns name + email.
    Used to personalise the draft email in the ads report.
    """
    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "GET",
            f"{BASE_URL}/contacts/{contact_id}",
            headers=_headers(),
        )
        if resp.status_code != 200:
            logger.warning(f"Could not fetch contact {contact_id}: {resp.status_code}")
            return {}
        data = resp.json().get("contact", {})
        return {
            "first_name": data.get("firstName", ""),
            "last_name":  data.get("lastName", ""),
            "email":      data.get("email", ""),
            "phone":      data.get("phone", ""),
        }


async def add_tag_to_contact(contact_id: str, tag: str) -> bool:
    """
    Adds a tag to an existing GHL contact.
    Tags trigger GHL workflows — this is how we fire follow-up emails.

    Returns True on success, False on failure.
    """
    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "POST",
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


async def get_pending_polls() -> list[dict]:
    """
    Queries GHL for all contacts tagged 'ads-invite-confirmed' where
    google_ads_data_status is 'Pending'. Used on startup to resume any
    polling tasks that were lost in a deploy or crash.

    Returns a list of dicts compatible with poll_for_access() arguments.
    """
    status_field_id  = _field_id_map.get("google_ads_data_status", "")
    fee_field_id     = _field_id_map.get("avg_appointment_fee", "")
    visits_field_id  = _field_id_map.get("avg_visits_per_patient", "")
    name_field_id    = _field_id_map.get("clinic_name", "")
    intake_field_id  = _field_id_map.get("intake_date", "")

    if not status_field_id:
        logger.warning("get_pending_polls: field ID map not loaded yet — skipping")
        return []

    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "POST",
            f"{BASE_URL}/contacts/search",
            headers=_headers(),
            json={
                "locationId": GHL_LOCATION_ID,
                "filters": [
                    {
                        "field": "tags",
                        "operator": "contains_set",
                        "value": ["ads-invite-confirmed"],
                    }
                ],
                "pageLimit": 100,
            },
        )

    if resp.status_code != 200:
        logger.error(f"get_pending_polls GHL search failed: {resp.status_code} — {resp.text}")
        return []

    contacts = resp.json().get("contacts", [])
    now = datetime.now(timezone.utc)
    pending = []

    for contact in contacts:
        custom = {f["id"]: f.get("value") for f in contact.get("customFields", [])}
        status = custom.get(status_field_id, "")
        if status != "Pending":
            continue

        # Check the clinic is still within the 72-hour polling window
        intake_raw = custom.get(intake_field_id, "")
        try:
            started = datetime.fromisoformat(intake_raw)
            elapsed = (now - started).total_seconds()
            if elapsed >= 72 * 3600:
                logger.info(
                    f"Skipping {contact.get('id')} — past 72-hour polling window "
                    f"({elapsed / 3600:.1f}h elapsed)"
                )
                continue
        except (ValueError, TypeError):
            pass  # No intake_date — include anyway, polling will self-limit

        clinic_name  = custom.get(name_field_id) or contact.get("companyName") or contact.get("contactName", "Unknown")
        avg_fee      = float(custom.get(fee_field_id) or 0)
        avg_visits   = float(custom.get(visits_field_id) or 0)

        pending.append({
            "clinic_name":          clinic_name,
            "ghl_contact_id":       contact["id"],
            "avg_appointment_fee":  avg_fee,
            "avg_visits_per_patient": avg_visits,
            "intake_date":          intake_raw or "",
            "email":                contact.get("email") or "",
        })
        logger.info(f"Resuming poll for {clinic_name} ({contact['id']})")

    logger.info(f"get_pending_polls: found {len(pending)} contacts needing poll resumption")
    return pending
