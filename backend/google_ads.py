"""
Google Ads integration for the clinic intake system.

Responsibilities:
  1. poll_for_access()  — background task that retries every 15 minutes (up to 72 hours)
                          until the clinic's account appears in the accessible accounts list.
  2. pull_account_data() — once access is confirmed, pulls campaign + keyword data
                           for the last 90 days and returns a summary dict.

Credentials (all in .env):
  GOOGLE_ADS_DEVELOPER_TOKEN  — your developer token
  GOOGLE_ADS_CLIENT_ID        — OAuth2 client ID
  GOOGLE_ADS_CLIENT_SECRET    — OAuth2 client secret
  GOOGLE_ADS_REFRESH_TOKEN    — refresh token for pete@clinicmastery.com
  GOOGLE_ADS_LOGIN_CUSTOMER_ID — leave blank for no MCC

The google-ads Python library is configured via a dict rather than a yaml file
so we don't need to manage a separate config file.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Polling state file ─────────────────────────────────────────────────────────
# Tracks which clinics we're currently waiting on + their status.
# Schema per entry:
#   {
#     "clinic_name": str,
#     "ghl_contact_id": str,
#     "status": "pending" | "complete" | "expired" | "cancelled",
#     "started_at": ISO timestamp,
#     "cancel": bool   ← set to true externally to stop the polling loop
#   }

POLLING_STATE_FILE = Path(__file__).parent / "polling_state.json"

POLL_INTERVAL_SECONDS = 15 * 60   # 15 minutes
MAX_POLL_DURATION_SECONDS = 72 * 60 * 60  # 72 hours

# If cost-per-conversion is below this, the account is tracking a micro-event
# (button click, scroll, phone reveal) not a real patient booking.
# In that case we ignore conversion counts when assessing wasted spend.
CONVERSION_VALIDITY_THRESHOLD = 20.0

# Minimum spend to flag a keyword or search term as wasted/irrelevant.
WASTED_SPEND_THRESHOLD = 20.0


# ── Polling state helpers ─────────────────────────────────────────────────────

def _load_state() -> dict:
    if POLLING_STATE_FILE.exists():
        with open(POLLING_STATE_FILE) as f:
            return json.load(f)
    return {}


def _save_state(state: dict) -> None:
    with open(POLLING_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def add_to_polling_state(
    clinic_name: str,
    ghl_contact_id: str,
    avg_appointment_fee: float = 0.0,
    avg_visits_per_patient: float = 0.0,
) -> None:
    """
    Registers a clinic as pending Google Ads access.
    Called from main.py before the background task is started.
    LTV fields are stored so polling can be resumed after a deploy restart.
    """
    state = _load_state()
    state[ghl_contact_id] = {
        "clinic_name": clinic_name,
        "ghl_contact_id": ghl_contact_id,
        "status": "pending",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cancel": False,
        "avg_appointment_fee": avg_appointment_fee,
        "avg_visits_per_patient": avg_visits_per_patient,
    }
    _save_state(state)
    logger.info(f"Added {clinic_name} ({ghl_contact_id}) to polling state")


async def get_resumable_polls() -> list[dict]:
    """
    Returns all contacts that still need polling, sourced directly from GHL.
    GHL is the source of truth — this survives deploys, crashes, and disk resets.
    Called on server startup.
    """
    from ghl import get_pending_polls
    return await get_pending_polls()


def cancel_polling(ghl_contact_id: str) -> None:
    """
    Sets the cancel flag for a contact so the polling loop stops on next check.
    Call this from external tooling or admin endpoints if needed.
    """
    state = _load_state()
    if ghl_contact_id in state:
        state[ghl_contact_id]["cancel"] = True
        _save_state(state)
        logger.info(f"Cancellation requested for contact {ghl_contact_id}")


# ── Google Ads client factory ─────────────────────────────────────────────────

_google_ads_client = None


def _build_google_ads_client():
    """
    Returns a cached GoogleAdsClient. Built once per process to avoid
    reloading heavy gRPC/protobuf stubs on every poll cycle.
    """
    global _google_ads_client
    if _google_ads_client is not None:
        return _google_ads_client

    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
    except ImportError:
        raise RuntimeError(
            "google-ads library not installed. Run: pip install google-ads"
        )

    config = {
        "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", ""),
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET", ""),
        "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN", ""),
        "use_proto_plus": True,
    }

    login_customer_id = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip()
    if login_customer_id:
        config["login_customer_id"] = login_customer_id

    _google_ads_client = GoogleAdsClient.load_from_dict(config)
    return _google_ads_client


# ── Irrelevant search term classifier ────────────────────────────────────────

import re as _re

_IRRELEVANT_PATTERNS = [
    (r'\bjobs?\b|\bcareers?\b|\brecruit\b|\bhiring\b|\bsalary\b|\bwages?\b|\bhow to become\b|\bbecome a\b', "Job/career search — not a patient"),
    (r'\bcourses?\b|\bdegree\b|\bstudy\b|\buniversity\b|\btafe\b|\btraining\b|\bapprentice|\bcertif', "Education/course search — not a patient"),
    (r'\bfree\b|\bdiy\b|\byoutube\b|\btutorial\b|\bhow to\b|\bself.?help\b', "Free/DIY search — not a paying patient"),
    (r'\bdog\b|\bcat\b|\bpet\b|\bvet(erinary)?\b|\banimal\b|\bhorse\b|\bbird\b', "Veterinary/animal — wrong audience"),
    (r'\breal estate\b|\bproperty\b|\binsurance\b|\baccountant\b|\blawyer\b|\blegal\b|\bfinance\b', "Unrelated industry"),
    (r'\bshop\b|\bstore\b|\bbuy\b|\bproduct\b|\bequipment\b|\bsupplies\b|\bwholesale\b', "Product purchase — not a patient"),
    (r'\bvolunteer\b|\binternship\b|\bplacement\b|\bwork experience\b', "Placement/volunteering — not a patient"),
    (r'\bwikipedia\b|\bnews\b|\bresearch paper\b|\bstatistic\b', "Research/information, not booking intent"),
    (r'\bdefinition\b|\bwhat is\b|\bmeaning of\b|\bhistory of\b', "Informational query — no booking intent"),
    (r'\btemplate\b|\bexample\b|\bsample\b|\bform\b', "Template/document search — not a patient"),
]


def _classify_irrelevant_terms(terms: list[dict]) -> list[dict]:
    """
    Flags search terms that have spend but are clearly not from potential patients.
    Uses pattern matching + low-CTR heuristics.
    """
    flagged = []
    for t in terms:
        term = t.get("term", "").lower()
        spend = t.get("spend", 0)
        if spend < 5:
            continue

        for pattern, reason in _IRRELEVANT_PATTERNS:
            if _re.search(pattern, term, _re.IGNORECASE):
                flagged.append({**t, "reason": reason})
                break
        else:
            # Low CTR with meaningful spend: shown to many people, almost all ignored it
            ctr = t.get("ctr", 0)
            impressions = t.get("impressions", 0)
            if spend >= WASTED_SPEND_THRESHOLD and ctr < 0.5 and impressions > 100:
                flagged.append({**t, "reason": f"Very low CTR ({ctr:.2f}%) — searchers are ignoring these ads"})

    return sorted(flagged, key=lambda x: x.get("spend", 0), reverse=True)


# ── Account discovery ─────────────────────────────────────────────────────────

def _get_accessible_customer_ids(client) -> list[str]:
    """
    Returns a list of all customer account IDs accessible under the
    pete@clinicmastery.com credentials.

    When a clinic grants read-only access, their account appears here.
    """
    customer_service = client.get_service("CustomerService")
    accessible = customer_service.list_accessible_customers()
    # Returns strings like "customers/1234567890" — extract just the ID
    return [r.split("/")[-1] for r in accessible.resource_names]


def _get_account_name(client, customer_id: str) -> str:
    """Fetches the descriptive name for a Google Ads account."""
    ga_service = client.get_service("GoogleAdsService")
    query = "SELECT customer.descriptive_name FROM customer LIMIT 1"
    try:
        response = ga_service.search(customer_id=customer_id, query=query)
        for row in response:
            return row.customer.descriptive_name
    except Exception:
        pass
    return ""


# ── Data pull ─────────────────────────────────────────────────────────────────

def pull_account_data(customer_id: str) -> dict:
    """
    Pulls the last 90 days of campaign and keyword data for the given account.

    Returns a summary dict with:
      - total_spend_90d
      - total_conversions_90d
      - cost_per_conversion
      - top_campaigns (list of {name, spend, conversions})
      - wasted_keywords (keywords with spend > $50 and 0 conversions)
      - avg_quality_score
      - num_active_campaigns
    """
    from datetime import timedelta
    client = _build_google_ads_client()
    ga_service = client.get_service("GoogleAdsService")

    # GAQL doesn't support LAST_90_DAYS — use explicit date range
    today = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    date_filter = f"segments.date BETWEEN '{start_date}' AND '{end_date}'"

    # ── Campaign performance ──────────────────────────────────────────────────
    campaign_query = f"""
        SELECT
            campaign.name,
            campaign.status,
            metrics.cost_micros,
            metrics.clicks,
            metrics.impressions,
            metrics.conversions,
            metrics.ctr,
            metrics.average_cpc,
            metrics.search_impression_share,
            metrics.search_budget_lost_impression_share,
            metrics.search_rank_lost_impression_share
        FROM campaign
        WHERE {date_filter}
        ORDER BY metrics.cost_micros DESC
    """
    campaigns = []
    total_spend_micros = 0
    total_conversions = 0.0
    num_active = 0

    campaign_response = ga_service.search(customer_id=customer_id, query=campaign_query)
    for row in campaign_response:
        spend = row.metrics.cost_micros / 1_000_000  # convert from micros to dollars
        conversions = row.metrics.conversions
        total_spend_micros += row.metrics.cost_micros
        total_conversions += conversions

        status_name = row.campaign.status.name if hasattr(row.campaign.status, "name") else str(row.campaign.status)
        if status_name == "ENABLED":
            num_active += 1

        # Impression share values can be None/sentinel when there's no search data
        def _safe_pct(val):
            try:
                f = float(val)
                return round(f * 100, 1) if 0 <= f <= 1 else None
            except (TypeError, ValueError):
                return None

        campaigns.append({
            "name": row.campaign.name,
            "status": status_name,
            "spend": round(spend, 2),
            "conversions": conversions,
            "clicks": row.metrics.clicks,
            "impressions": row.metrics.impressions,
            "ctr": round(row.metrics.ctr * 100, 2),  # as percentage
            "avg_cpc": round(row.metrics.average_cpc / 1_000_000, 2),
            "impression_share": _safe_pct(row.metrics.search_impression_share),
            "lost_to_budget": _safe_pct(row.metrics.search_budget_lost_impression_share),
            "lost_to_rank": _safe_pct(row.metrics.search_rank_lost_impression_share),
        })

    total_spend = total_spend_micros / 1_000_000
    cost_per_conversion = (
        round(total_spend / total_conversions, 2)
        if total_conversions > 0
        else 0.0
    )

    # Top 5 campaigns by spend
    top_campaigns = sorted(campaigns, key=lambda c: c["spend"], reverse=True)[:5]

    # ── Keyword analysis ──────────────────────────────────────────────────────
    keyword_query = f"""
        SELECT
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.quality_info.quality_score,
            metrics.cost_micros,
            metrics.conversions,
            metrics.clicks,
            metrics.impressions
        FROM keyword_view
        WHERE {date_filter}
        ORDER BY metrics.cost_micros DESC
        LIMIT 100
    """
    keywords = []
    quality_scores = []

    keyword_response = ga_service.search(customer_id=customer_id, query=keyword_query)
    for row in keyword_response:
        kw_spend = row.metrics.cost_micros / 1_000_000
        qs = row.ad_group_criterion.quality_info.quality_score
        match_type = (
            row.ad_group_criterion.keyword.match_type.name
            if hasattr(row.ad_group_criterion.keyword.match_type, "name")
            else str(row.ad_group_criterion.keyword.match_type)
        )
        keywords.append({
            "keyword": row.ad_group_criterion.keyword.text,
            "match_type": match_type,
            "spend": round(kw_spend, 2),
            "conversions": row.metrics.conversions,
            "clicks": row.metrics.clicks,
            "quality_score": qs,
        })
        if qs > 0:
            quality_scores.append(qs)

    # Wasted keywords — tougher criteria, $20 threshold.
    # When cost-per-conversion is implausibly low (< $20), the account is tracking
    # a micro-event (click, scroll, reveal) not a real patient booking.
    # In that case, ignore conversion counts entirely and flag by spend + low CTR.
    conversions_invalid = 0 < cost_per_conversion < CONVERSION_VALIDITY_THRESHOLD
    if conversions_invalid:
        wasted_keywords = [
            kw for kw in keywords
            if kw["spend"] > WASTED_SPEND_THRESHOLD
            and (kw.get("ctr", 0) < 1.0 or kw.get("clicks", 0) == 0)
        ]
    else:
        wasted_keywords = [
            kw for kw in keywords
            if kw["spend"] > WASTED_SPEND_THRESHOLD and kw["conversions"] == 0
        ]
    wasted_keywords = sorted(wasted_keywords, key=lambda k: k["spend"], reverse=True)

    # Low-QS keywords: rated 1-5 with any spend (QS 0 = unrated, skip those)
    low_qs_keywords = sorted(
        [kw for kw in keywords if 1 <= kw["quality_score"] <= 5 and kw["spend"] > 0],
        key=lambda k: k["spend"], reverse=True,
    )[:20]

    avg_quality_score = (
        round(sum(quality_scores) / len(quality_scores), 1)
        if quality_scores
        else 0.0
    )

    all_spend_campaigns = [c for c in campaigns if c["spend"] > 0]
    all_campaigns_paused = (
        bool(all_spend_campaigns)
        and all(c["status"] == "PAUSED" for c in all_spend_campaigns)
    )

    # ── Search term report ────────────────────────────────────────────────────
    search_term_query = f"""
        SELECT
            search_term_view.search_term,
            metrics.cost_micros,
            metrics.clicks,
            metrics.impressions,
            metrics.conversions,
            metrics.ctr
        FROM search_term_view
        WHERE {date_filter}
          AND metrics.cost_micros > 0
        ORDER BY metrics.cost_micros DESC
        LIMIT 300
    """
    raw_terms = []
    try:
        term_response = ga_service.search(customer_id=customer_id, query=search_term_query)
        for row in term_response:
            raw_terms.append({
                "term":        row.search_term_view.search_term,
                "spend":       round(row.metrics.cost_micros / 1_000_000, 2),
                "clicks":      row.metrics.clicks,
                "impressions": row.metrics.impressions,
                "conversions": row.metrics.conversions,
                "ctr":         round(row.metrics.ctr * 100, 2),
            })
    except Exception as exc:
        logger.warning(f"Search term query failed: {exc}")

    irrelevant_terms = _classify_irrelevant_terms(raw_terms)

    return {
        "customer_id": customer_id,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "total_spend_90d": round(total_spend, 2),
        "total_conversions_90d": int(total_conversions),
        "cost_per_conversion": cost_per_conversion,
        "conversions_invalid": conversions_invalid,
        "top_campaigns": top_campaigns,
        "all_campaigns_paused": all_campaigns_paused,
        "wasted_keywords": wasted_keywords[:20],
        "low_qs_keywords": low_qs_keywords,
        "avg_quality_score": avg_quality_score,
        "num_active_campaigns": num_active,
        "irrelevant_terms": irrelevant_terms[:30],
    }


# ── Immediate report trigger ──────────────────────────────────────────────────

async def run_ads_report_now(
    clinic_name: str,
    ghl_contact_id: str,
    avg_appointment_fee: float = 0.0,
    avg_visits_per_patient: float = 0.0,
    customer_id_override: str = None,
) -> dict:
    """
    Immediately attempts to find the clinic's Google Ads account and generate
    the report — no polling loop, no waiting.

    Returns {"status": "success", "customer_id": ...} or {"status": "error", "detail": ...}.
    Called by the /trigger-ads-report admin endpoint.
    """
    from ghl import update_contact_field, add_tag_to_contact

    logger.info(f"Force-triggering Google Ads report for {clinic_name} ({ghl_contact_id})")

    try:
        client = _build_google_ads_client()

        if customer_id_override:
            # Strip dashes (e.g. "516-224-4380" → "5162244380")
            matched_id = customer_id_override.replace("-", "").strip()
            logger.info(f"[Force] Using customer ID override: {matched_id}")
        else:
            customer_ids = _get_accessible_customer_ids(client)
            logger.info(f"[Force] Found {len(customer_ids)} accessible accounts")

            def _words(s):
                return set(_re.sub(r'[^a-z0-9\s]', '', s.lower()).split())

            stop = {'the', 'a', 'an', 'and', 'of', 'for', 'in', 'at', 'my', 'our'}
            clinic_words = _words(clinic_name) - stop

            matched_id = None
            account_names = {}
            for cid in customer_ids:
                account_name = _get_account_name(client, cid)
                account_names[cid] = account_name
                logger.info(f"  [Force] Account: {cid} -> '{account_name}'")
                account_words = _words(account_name) - stop
                if clinic_words & account_words:
                    matched_id = cid
                    logger.info(f"[Force] Matched '{clinic_name}' to account '{account_name}' ({cid})")
                    break

            if not matched_id:
                return {
                    "status": "not_found",
                    "detail": f"No Google Ads account found matching '{clinic_name}'",
                    "accounts_checked": list(account_names.values()),
                }

        # Pull full account data
        summary = pull_account_data(matched_id)

        # Write snapshot to GHL
        wasted_total = sum(k.get("spend", 0) for k in summary.get("wasted_keywords", []))
        snapshot = (
            f"Total spend (90d): ${summary.get('total_spend_90d', 0):,.2f}\n"
            f"Conversions: {summary.get('total_conversions_90d', 0)} | "
            f"Cost per conversion: ${summary.get('cost_per_conversion', 0):,.2f}\n"
            f"Active campaigns: {summary.get('num_active_campaigns', 0)}\n"
            f"Wasted spend identified: ${wasted_total:,.2f} "
            f"({len(summary.get('wasted_keywords', []))} keywords)\n"
            f"Avg quality score: {summary.get('avg_quality_score', 0)}/10\n"
            f"Status: Full report emailed to pete@clinicmastery.com"
        )
        await update_contact_field(ghl_contact_id, "google_ads_summary", snapshot)
        await update_contact_field(ghl_contact_id, "google_ads_data_status", "Complete")

        # Generate PDF and email
        summary["avg_appointment_fee"] = avg_appointment_fee
        summary["avg_visits_per_patient"] = avg_visits_per_patient
        from pdf_report import generate_pdf
        from emailer import send_ads_report
        pdf_bytes = generate_pdf(summary, clinic_name)
        sent = send_ads_report(clinic_name, pdf_bytes, summary)

        # Mark polling state complete if entry exists
        state = _load_state()
        if ghl_contact_id in state:
            state[ghl_contact_id]["status"] = "complete"
            state[ghl_contact_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            _save_state(state)

        logger.info(f"[Force] Report complete for {clinic_name}. Email sent: {sent}")
        return {
            "status": "success",
            "customer_id": matched_id,
            "email_sent": sent,
            "total_spend_90d": summary.get("total_spend_90d"),
            "total_conversions_90d": summary.get("total_conversions_90d"),
        }

    except Exception as exc:
        logger.error(f"[Force] Failed for {clinic_name}: {exc}", exc_info=True)
        return {"status": "error", "detail": str(exc)}


# ── Polling background task ───────────────────────────────────────────────────

async def poll_for_access(
    clinic_name: str,
    ghl_contact_id: str,
    avg_appointment_fee: float = 0.0,
    avg_visits_per_patient: float = 0.0,
) -> None:
    """
    Background task: polls accessible Google Ads accounts every 15 minutes
    for up to 72 hours, waiting for the clinic to appear after granting access.

    When found:
      - Pulls account data
      - Writes summary to GHL contact's google_ads_summary field
      - Updates polling_state.json to "complete"

    If 72 hours pass with no access:
      - Updates polling_state.json to "expired"
      - Tags the GHL contact "ads-invite-expired" (triggers GHL workflow)

    The loop respects a "cancel" flag in polling_state.json so it can be
    stopped externally without killing the process.
    """
    # Import here to avoid circular import (ghl imports nothing from here)
    from ghl import update_contact_field, add_tag_to_contact

    logger.info(f"Starting Google Ads polling for {clinic_name} ({ghl_contact_id})")
    elapsed = 0

    while elapsed < MAX_POLL_DURATION_SECONDS:
        # Check if cancellation was requested externally
        state = _load_state()
        entry = state.get(ghl_contact_id, {})
        if entry.get("cancel"):
            logger.info(f"Polling cancelled for {ghl_contact_id}")
            state[ghl_contact_id]["status"] = "cancelled"
            _save_state(state)
            return

        # Try to build a Google Ads client and check accessible accounts
        try:
            client = _build_google_ads_client()
            customer_ids = _get_accessible_customer_ids(client)
            logger.info(
                f"[Poll {ghl_contact_id}] Found {len(customer_ids)} accessible accounts"
            )

            # Try to match by clinic name in the account's descriptive name.
            # Strip punctuation before comparing so "Clinic#" matches "clinic".
            import re as _re
            def _words(s):
                return set(_re.sub(r'[^a-z0-9\s]', '', s.lower()).split())

            stop = {'the', 'a', 'an', 'and', 'of', 'for', 'in', 'at', 'my', 'our'}
            clinic_words = _words(clinic_name) - stop
            logger.info(f"  Matching against clinic_name='{clinic_name}' words={clinic_words}")

            matched_id = None
            for cid in customer_ids:
                account_name = _get_account_name(client, cid)
                logger.info(f"  Account: {cid} -> '{account_name}'")
                account_words = _words(account_name) - stop
                if clinic_words & account_words:  # any meaningful word overlap
                    matched_id = cid
                    logger.info(
                        f"Matched clinic '{clinic_name}' to Google Ads account "
                        f"'{account_name}' (ID: {cid})"
                    )
                    break

            if matched_id:
                # Pull the full account data
                logger.info(f"Pulling account data for {matched_id}")
                summary = pull_account_data(matched_id)

                # ── 1. Write a readable 6-line snapshot to the GHL field ──────
                wasted_total = sum(k.get("spend", 0) for k in summary.get("wasted_keywords", []))
                snapshot = (
                    f"Total spend (90d): ${summary.get('total_spend_90d', 0):,.2f}\n"
                    f"Conversions: {summary.get('total_conversions_90d', 0)} | "
                    f"Cost per conversion: ${summary.get('cost_per_conversion', 0):,.2f}\n"
                    f"Active campaigns: {summary.get('num_active_campaigns', 0)}\n"
                    f"Wasted spend identified: ${wasted_total:,.2f} "
                    f"({len(summary.get('wasted_keywords', []))} keywords)\n"
                    f"Avg quality score: {summary.get('avg_quality_score', 0)}/10\n"
                    f"Status: Full report emailed to pete@clinicmastery.com"
                )
                await update_contact_field(ghl_contact_id, "google_ads_summary", snapshot)
                await update_contact_field(ghl_contact_id, "google_ads_data_status", "Complete")

                # ── 2. Generate branded PDF and email it ──────────────────────
                try:
                    from pdf_report import generate_pdf
                    from emailer import send_ads_report
                    # Merge intake context so the PDF can show LTV
                    summary["avg_appointment_fee"]   = avg_appointment_fee
                    summary["avg_visits_per_patient"] = avg_visits_per_patient
                    pdf_bytes = generate_pdf(summary, clinic_name)
                    sent = send_ads_report(clinic_name, pdf_bytes, summary)
                    if sent:
                        logger.info(f"PDF audit report emailed for {clinic_name}")
                    else:
                        logger.warning(f"PDF generated but email failed for {clinic_name}")
                except Exception as pdf_exc:
                    logger.error(f"PDF/email step failed for {clinic_name}: {pdf_exc}")
                    # Don't crash — GHL snapshot is already saved

                # ── 3. Mark polling as complete ───────────────────────────────
                state = _load_state()
                if ghl_contact_id in state:
                    state[ghl_contact_id]["status"] = "complete"
                    state[ghl_contact_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                    _save_state(state)

                logger.info(f"Google Ads data pull complete for {clinic_name}")
                return

        except Exception as exc:
            # Don't crash the loop on API errors — log and keep trying
            logger.error(f"Error during Google Ads poll for {ghl_contact_id}: {exc}")

        # Wait 15 minutes before trying again
        logger.info(
            f"[Poll {ghl_contact_id}] No match yet. "
            f"Next check in {POLL_INTERVAL_SECONDS // 60} minutes. "
            f"Elapsed: {elapsed // 3600}h {(elapsed % 3600) // 60}m"
        )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

    # 72 hours elapsed — give up
    logger.warning(f"Google Ads access never confirmed for {clinic_name} after 72 hours")

    state = _load_state()
    if ghl_contact_id in state:
        state[ghl_contact_id]["status"] = "expired"
        state[ghl_contact_id]["expired_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)

    # Tag the contact — GHL workflow handles the follow-up email
    from ghl import add_tag_to_contact
    await add_tag_to_contact(ghl_contact_id, "ads-invite-expired")
    logger.info(f"Tagged {ghl_contact_id} as ads-invite-expired")
