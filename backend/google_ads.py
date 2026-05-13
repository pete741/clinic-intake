"""
Google Ads integration for the clinic intake system.

Responsibilities:
  1. pull_account_data() - pulls campaign + keyword data for the last 90 days
                           and returns a summary dict.
  2. run_ads_report_now() - finds the clinic's Ads account, generates a PDF,
                            and emails it. Called by poll_worker.py and the
                            /trigger-ads-report admin endpoint.

Credentials (all in .env):
  GOOGLE_ADS_DEVELOPER_TOKEN  - your developer token
  GOOGLE_ADS_CLIENT_ID        - OAuth2 client ID
  GOOGLE_ADS_CLIENT_SECRET    - OAuth2 client secret
  GOOGLE_ADS_REFRESH_TOKEN    - refresh token for pete@clinicmastery.com
  GOOGLE_ADS_LOGIN_CUSTOMER_ID - leave blank for no MCC

The google-ads Python library is configured via a dict rather than a yaml file
so we don't need to manage a separate config file.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Conversion-tracking quality tiers based on cost per conversion. In allied
# health, a real patient acquisition almost always costs $60+. The thresholds
# below are calibrated to that reality and drive how the audit interprets
# conversion data:
#
#   < $20         -> "broken"      micro-conversion (button click, page scroll,
#                                   phone reveal). Conversion data is unusable;
#                                   the wasted-spend analysis is suppressed
#                                   because every keyword would falsely look
#                                   like it converts.
#   $20 to $50    -> "uncertain"   probably mixing some real bookings with
#                                   non-booking events. Wasted-spend analysis
#                                   still runs but flagged as low-confidence.
#   >= $50        -> "realistic"   plausible patient acquisition cost. Full
#                                   confidence in the analysis.
CONVERSION_BROKEN_THRESHOLD    = 20.0
CONVERSION_UNCERTAIN_THRESHOLD = 50.0

# Minimum spend to flag a keyword or search term as wasted/irrelevant.
WASTED_SPEND_THRESHOLD = 20.0


def classify_conversion_tracking(cost_per_conversion: float) -> str:
    """Return 'broken' | 'uncertain' | 'realistic' | 'no_data'."""
    if not cost_per_conversion or cost_per_conversion <= 0:
        return "no_data"
    if cost_per_conversion < CONVERSION_BROKEN_THRESHOLD:
        return "broken"
    if cost_per_conversion < CONVERSION_UNCERTAIN_THRESHOLD:
        return "uncertain"
    return "realistic"




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

# UNIVERSAL irrelevance patterns - apply to every clinic regardless of vertical.
# These are the highest-conversion-impact buckets: a private clinic paying for
# "bulk bill", "how much", "free", "korean", or "jobs" clicks is bleeding budget
# at people who will never book at full fee.
_IRRELEVANT_PATTERNS = [
    # Job/career - wrong intent (looking to BECOME a practitioner, not see one).
    (r'\bjobs?\b|\bcareers?\b|\brecruit\b|\bhiring\b|\bsalary\b|\bwages?\b|\bhow to become\b|\bbecome a\b',
     "Job/career search - not a patient"),
    # Education / training - same wrong intent.
    (r'\bcourses?\b|\bdegree\b|\bstudy\b|\buniversity\b|\btafe\b|\btraining\b|\bapprentice|\bcertif',
     "Education/course search - not a patient"),
    # Free / funded / scheme - for a private (non bulk-billing) clinic, every
    # one of these clicks is from someone shopping for a free or subsidised
    # alternative. They will not book at private fees.
    (r'\bfree\b|\bbulk\s*bill\w*\b|\bbulkbill\w*\b|\bmedicare\b|\bno\s*gap\b|\bsubsid\w*\b|\bcentrelink\b|\bgovernment\b',
     "Free / bulk-bill / subsidised - won't book at private fee"),
    # Price-shopping / informational - researching cost, not booking.
    (r'\bhow\s*much\b|\bcost\s*of\b|\bprices?\b|\bfees?\b|\brates?\b|\bpricing\b|\bdoes\s+it\s+cost\b|\bcheap\b|\bcheaper\b|\bcheapest\b|\baffordable\b|\bsliding\s*scale\b|\bdiscount\w*\b|\blow\s*cost\b',
     "Price-shopping / informational - not booking intent"),
    # DIY / self-help / research.
    (r'\bdiy\b|\byoutube\b|\breddit\b|\btiktok\b|\btutorial\b|\bself.?help\b|\bexercises?\b|\bstretches?\b|\bhome\s*remed\w*\b',
     "DIY / self-help - not a paying patient"),
    # Language / cultural-specific - unless the clinic explicitly markets to
    # that community, the searcher is looking for someone else.
    (r'\bvietnamese\b|\bkorean\b|\bmandarin\b|\bchinese\b|\bcantonese\b|\barabic\b|\bspanish\b|\bjapanese\b|\bhindi\b|\burdu\b|\bturkish\b|\bgreek\b|\bitalian\b|\bportuguese\b|\bfilipino\b|\btagalog\b|\bbilingual\b|\binterpreter\b|\btranslator\b',
     "Language / culture-specific - looking for a different practitioner"),
    # Wikipedia / news / research.
    (r'\bwikipedia\b|\bnews\b|\bresearch paper\b|\bstatistic\b',
     "Research/information, not booking intent"),
    # Definitional / informational.
    (r'\bdefinition\b|\bwhat is\b|\bmeaning of\b|\bhistory of\b|\bsymptoms?\b|\bcauses?\b',
     "Informational query - no booking intent"),
    # Templates / forms.
    (r'\btemplate\b|\bexample\b|\bsample\b|\bform\s+pdf\b',
     "Template/document search - not a patient"),
    # Animal / vet - wrong audience entirely.
    (r'\bdog\b|\bcat\b|\bpet\b|\bvet(erinary)?\b|\banimal\b|\bhorse\b|\bbird\b',
     "Veterinary/animal - wrong audience"),
    # Unrelated industries.
    (r'\breal estate\b|\bproperty\b|\binsurance\b|\baccountant\b|\blawyer\b|\blegal\b|\bfinance\b',
     "Unrelated industry"),
    # Product purchases.
    (r'\bshop\b|\bstore\b|\bbuy\b|\bproduct\b|\bequipment\b|\bsupplies\b|\bwholesale\b',
     "Product purchase - not a patient"),
    # Volunteering / placements.
    (r'\bvolunteer\b|\binternship\b|\bplacement\b|\bwork experience\b',
     "Placement/volunteering - not a patient"),
]

# Per-vertical wrong-profession patterns. These catch the "looks similar but
# wrong service" searches - e.g. a private psychology clinic paying for
# "psychiatrist" or "life coach" clicks. Specialty is inferred from clinic name
# at runtime via _infer_specialty().
_SPECIALTY_PATTERNS = {
    "psychology": [
        (r'\bpsychiatr\w*\b|\blife\s*coach\w*\b|\bsocial\s*work\w*\b|\bmental\s*health\s*nurse\b|\bgeneral\s*practitioner\b|\bhypnotherap\w*\b|\bsomatic\s*(?:therapy|practitioner|healer)\b|\benergy\s*healer\b|\breiki\b|\bkinesiolog\w*\b|\bnaturopath\w*\b|\bspiritual\s*healer\b',
         "Wrong profession - not a psychologist"),
    ],
    "physio": [
        (r'\bchiropract\w*\b|\bosteopath\w*\b|\bmassage\s*therap\w*\b|\bremedial\s*massag\w*\b|\bacupunctur\w*\b|\bnaturopath\w*\b|\bphysician\b|\bsurgeon\b',
         "Wrong profession - not a physiotherapist"),
    ],
    "chiropractic": [
        (r'\bphysio\w*\b|\bosteopath\w*\b|\bmassage\s*therap\w*\b|\bsurgeon\b',
         "Wrong profession - not a chiropractor"),
    ],
    "podiatry": [
        (r'\borthop\w*\b(?!\s*(?:shoes|insole))|\bphysio\w*\b|\bsurgeon\b',
         "Wrong profession - not a podiatrist"),
    ],
    "osteopathy": [
        (r'\bphysio\w*\b|\bchiropract\w*\b|\bmassage\s*therap\w*\b',
         "Wrong profession - not an osteopath"),
    ],
    "speech": [
        (r'\bot\b|\boccupational\s*therap\w*\b|\bpsycholog\w*\b',
         "Wrong profession - not a speech pathologist"),
    ],
    "exercise_physiology": [
        (r'\bpersonal\s*train\w*\b|\bgym\b|\bphysio\w*\b(?!\s*therapist)|\bchiropract\w*\b',
         "Wrong profession - not an exercise physiologist"),
    ],
}

# Map clinic-name keywords to specialty buckets. Mirrors google-ads-intel's
# config.json specialties dict so cold-audit detection stays consistent with
# Pete's retained-client classification.
_SPECIALTY_NAME_HINTS = {
    "psychology": ["psychology", "psychologist", "counselling", "counsellor",
                   "therapy", "therapist", "wellbeing", "mood", "mind", "mental"],
    "physio": ["physiotherapy", "physiotherapist", "physio", "spine", "sports"],
    "podiatry": ["podiatry", "podiatrist", "pod", "foot"],
    "chiropractic": ["chiro", "chiropractic", "chiropractor", "spinal"],
    "osteopathy": ["osteopathy", "osteopath", "osteo"],
    "speech": ["speech", "speechie", "chatterbox"],
    "exercise_physiology": ["exercise physiology", "ex physiology", "rehab", "movement", "strength"],
}


def _infer_specialty(clinic_name: str) -> str:
    """Best-effort specialty inference from the clinic's name.

    Falls back to 'general' when no hints match - in which case only universal
    irrelevance patterns apply (no wrong-profession rules).
    """
    if not clinic_name:
        return "general"
    name_lower = clinic_name.lower()
    for specialty, hints in _SPECIALTY_NAME_HINTS.items():
        for hint in hints:
            if hint in name_lower:
                return specialty
    return "general"


def _classify_irrelevant_terms(terms: list[dict], clinic_name: str = "") -> list[dict]:
    """
    Flags search terms that have spend but are clearly not from potential patients.

    Two-layer detection:
      1. Universal patterns + per-specialty wrong-profession patterns (primary).
         Catches the highest-impact waste regardless of CTR.
      2. Low-CTR fallback for terms that didn't match a rule but look noisy.
    """
    specialty = _infer_specialty(clinic_name)
    patterns = list(_IRRELEVANT_PATTERNS) + list(_SPECIALTY_PATTERNS.get(specialty, []))

    flagged = []
    for t in terms:
        term = t.get("term", "").lower()
        spend = t.get("spend", 0)
        clicks = t.get("clicks", 0)
        # Audit threshold: $1+ OR any click. Catches small-but-real waste.
        if spend < 1 and clicks == 0:
            continue

        matched = False
        for pattern, reason in patterns:
            if _re.search(pattern, term, _re.IGNORECASE):
                flagged.append({**t, "reason": reason})
                matched = True
                break
        if matched:
            continue

        # Low CTR with meaningful spend - shown to many, almost all ignored.
        ctr = t.get("ctr", 0)
        impressions = t.get("impressions", 0)
        if spend >= WASTED_SPEND_THRESHOLD and ctr < 0.5 and impressions > 100:
            flagged.append({**t, "reason": f"Very low CTR ({ctr:.2f}%) - searchers ignored these ads"})

    return sorted(flagged, key=lambda x: x.get("spend", 0), reverse=True)


# ── Brand-keyword waste classifier ───────────────────────────────────────────

# Stripped from the clinic name before extracting distinctive brand tokens.
# Generic words that match thousands of search terms cannot be brand markers.
_BRAND_STOPWORDS = {
    "the", "and", "of", "a", "an", "&", "for", "to", "at", "in", "on", "by",
    "clinic", "clinics", "health", "healthcare", "group", "hub", "centre",
    "center", "therapy", "therapies", "therapist", "therapists",
    "physio", "physios", "physiotherapy", "physiotherapist", "physiotherapists",
    "chiro", "chiropractic", "chiropractor", "chiropractors",
    "psychology", "psychologist", "psychologists", "psychological",
    "counselling", "counsellor", "counselors", "counseling",
    "podiatry", "podiatrist", "podiatrists",
    "osteopathy", "osteopath", "osteopaths", "osteo",
    "exercise", "physiology", "physiologist",
    "speech", "pathology", "pathologist",
    "rehab", "rehabilitation", "wellness", "wellbeing", "medical", "services",
    "service", "care", "practice", "allied", "multi", "disciplinary",
    "studio", "co", "company", "ltd", "pty", "australia", "australian",
}


def _extract_brand_tokens(clinic_name: str) -> list[str]:
    """Distinctive brand tokens for matching, stripped of clinic-vertical fluff.

    'The Millennial Therapist' → ['millennial']
    'Apricus Health'           → ['apricus']
    'Alexandria & Redfern Physiotherapy' → ['alexandria', 'redfern']
    'Healthcare Wellness Hub'  → ['healthcare', 'wellness', 'hub']  (fallback)
    """
    if not clinic_name:
        return []
    raw = _re.sub(r"[^\w\s]", " ", clinic_name.lower())
    tokens = [t for t in raw.split() if t]
    distinctive = [t for t in tokens if t not in _BRAND_STOPWORDS and len(t) >= 3]
    if distinctive:
        return distinctive
    # All tokens were stopwords - fall back so we don't end up with empty brand list.
    fallback = [t for t in tokens if t not in _BRAND_STOPWORDS]
    return fallback or tokens


def _classify_branded_terms(terms: list[dict], brand_tokens: list[str]) -> list[dict]:
    """Returns search terms whose text contains any brand token (whole-word match).

    Branded clicks are recoverable for free via organic + Google Business
    Profile. Every dollar in this list is wasted ad spend on existing demand.
    """
    if not brand_tokens:
        return []
    branded = []
    for t in terms:
        term_text = (t.get("term") or "").lower()
        if not term_text:
            continue
        for tok in brand_tokens:
            if _re.search(rf"\b{_re.escape(tok)}\b", term_text):
                branded.append({**t, "matched_brand_tokens": [tok]})
                break
    return sorted(branded, key=lambda x: x.get("spend", 0), reverse=True)


# ── LLM contextual classifier ────────────────────────────────────────────────

# Sonnet is the right tier - Haiku misses nuance on clinical-context calls
# (e.g. "is somatic therapy in-scope for THIS clinic?"), Opus is overkill at
# 5x the cost. Claude 4.6 is the latest Sonnet at time of writing.
LLM_CLASSIFIER_MODEL = "claude-sonnet-4-6"
# CLI fallback (local dev only) is highly variable, ~30-180s. SDK path on Render
# typically ~10-20s. Set generously; the audit is async anyway.
LLM_CLASSIFIER_TIMEOUT = 240
LLM_MAX_TERMS_PER_CALL = 100  # truncate top-by-spend if more terms exist


def _find_claude_cli() -> str:
    """Locate the Claude CLI for local-dev fallback when ANTHROPIC_API_KEY is unset.

    On Render this returns "" - the CLI isn't installed in the production image,
    so the SDK path is the only one available. ANTHROPIC_API_KEY must be set
    in Render env vars.
    """
    for path in ("/Users/elitepete/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if os.path.exists(path):
            return path
    return ""


def _build_ad_copy_themes(ad_copy: list[dict]) -> list[str]:
    """Flatten RSA headlines/descriptions into a deduplicated list of phrases.

    The LLM uses these as the canonical "what this clinic advertises" signal.
    Capped at 30 to keep prompt size manageable.
    """
    seen = set()
    themes = []
    for ad in ad_copy:
        for line in (ad.get("headlines") or []) + (ad.get("descriptions") or []):
            line = (line or "").strip()
            if not line or line.lower() in seen:
                continue
            seen.add(line.lower())
            themes.append(line)
            if len(themes) >= 30:
                return themes
    return themes


def _llm_classify_search_terms(
    clinic_name: str,
    specialty: str,
    ad_copy_themes: list[str],
    ad_group_names: list[str],
    search_terms: list[dict],
    already_flagged_terms: set[str],
    clinic_suburb: str = "",
    clinic_state: str = "",
) -> dict[str, str]:
    """Ask Claude to flag context-irrelevant search terms the rule library missed.

    Returns {term: reason} for terms judged IRRELEVANT by the LLM. Only sends
    terms not already flagged by the rule library, so the LLM focuses on
    contextual nuance (e.g. "EMDR therapy" when the clinic doesn't offer it)
    rather than re-finding things rules already caught.

    Graceful degradation:
      - Missing ANTHROPIC_API_KEY → return empty (rule library is the floor)
      - SDK import failure → return empty
      - API call failure / timeout → return empty
      - Malformed JSON response → return empty

    Never raises - the audit must always succeed even if the LLM is down.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    cli_path = os.getenv("CLAUDE_CLI_PATH", "").strip() or _find_claude_cli()
    use_cli_fallback = (not api_key) and bool(cli_path)

    if not api_key and not use_cli_fallback:
        logger.warning(
            "Neither ANTHROPIC_API_KEY nor a usable Claude CLI found - skipping "
            "LLM contextual classification (rule library is the only irrelevance signal)"
        )
        return {}

    candidates = [t for t in search_terms if t.get("term") and t["term"] not in already_flagged_terms]
    if not candidates:
        return {}

    candidates = sorted(candidates, key=lambda t: t.get("spend", 0), reverse=True)[:LLM_MAX_TERMS_PER_CALL]

    if not use_cli_fallback:
        try:
            from anthropic import Anthropic
        except ImportError:
            logger.warning("anthropic SDK not installed - skipping LLM classification")
            return {}

    ad_copy_str = " | ".join(ad_copy_themes) if ad_copy_themes else "(no ad copy available)"
    ad_groups_str = ", ".join(ad_group_names) if ad_group_names else "(no ad group structure available)"
    terms_block = "\n".join(f'{i+1}. "{t["term"]}"' for i, t in enumerate(candidates))

    system_prompt = (
        "You are an expert Google Ads auditor for healthcare clinics. Your job is "
        "to read the clinic's actual ad copy, infer what services they offer, then "
        "judge whether each search term aligns with that scope.\n\n"
        "Rules:\n"
        "- Mark IRRELEVANT only when the term clearly does not match the clinic's "
        "  apparent service scope, target profession, demographic, or fee structure.\n"
        "- When in doubt, mark RELEVANT. False positives hurt more than misses.\n"
        "- Reasons must be specific and short (max 12 words).\n"
        "- HARD WRITING RULE: NEVER use em dashes in reasons or anywhere else. "
        "Use a hyphen (-), comma, period, or parentheses instead. Em dashes are "
        "forbidden in this brand's copy and will cause the audit to be rejected.\n"
        "- GEOGRAPHIC CATCHMENT RULE: Allied health patients routinely travel 10-15 "
        "minutes for specialist care. If the term names a suburb that is within "
        "roughly 15 km of the clinic's stated location, mark it RELEVANT, not "
        "irrelevant. Only flag a suburb-named term as geographic mismatch when "
        "the suburb is clearly outside the catchment (different city, 30+ km "
        "away, or an obscure region the clinic plainly does not service).\n"
        "- Examples of contextual irrelevance:\n"
        "  - Wrong profession (psychiatrist vs psychology)\n"
        "  - Modality not in ad copy (e.g. EMDR if no EMDR mention anywhere)\n"
        "  - Demographic mismatch (child therapy if clinic only mentions adults)\n"
        "  - Funded or free seekers when clinic ad copy implies private fee\n"
        "  - Geographic mismatch ONLY when clearly outside the 15 km catchment\n"
        "  - Out-of-scope conditions (eating disorders if clinic only does anxiety or depression)\n\n"
        "Return ONLY a JSON array. No markdown, no preamble. Format:\n"
        '[{"term": "...", "verdict": "irrelevant", "reason": "..."},'
        ' {"term": "...", "verdict": "relevant"}]'
    )

    location_line = ""
    if clinic_suburb or clinic_state:
        location_line = f"CLINIC LOCATION: {clinic_suburb}{', ' + clinic_state if clinic_state else ''} (apply the 15 km catchment rule from any suburb-named search term)\n"

    user_prompt = (
        f"CLINIC: {clinic_name}\n"
        f"{location_line}"
        f"INFERRED SPECIALTY: {specialty}\n"
        f"AD COPY (what they advertise): {ad_copy_str}\n"
        f"AD GROUP NAMES: {ad_groups_str}\n\n"
        f"SEARCH TERMS (judge each one):\n{terms_block}\n\n"
        "Return the JSON array now."
    )

    text = ""
    if use_cli_fallback:
        # Local-dev fallback: shell out to the Claude CLI using Pete's existing
        # OAuth session. This path is only used when ANTHROPIC_API_KEY isn't set.
        # Render production must use the SDK path with an API key.
        import subprocess
        env = {
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/Users/elitepete/.local/bin",
            "HOME": os.environ.get("HOME", "/Users/elitepete"),
            "USER": os.environ.get("USER", "elitepete"),
            "TERM": "dumb",
            "LANG": os.environ.get("LANG", "en_AU.UTF-8"),
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8000",
        }
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            env["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
        try:
            proc = subprocess.run(
                [
                    cli_path, "-p", user_prompt,
                    "--model", "sonnet",
                    "--system-prompt", system_prompt,
                    "--tools", "",
                    "--disable-slash-commands",
                    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                ],
                capture_output=True, text=True, timeout=LLM_CLASSIFIER_TIMEOUT,
                stdin=subprocess.DEVNULL, env=env,
            )
            if proc.returncode != 0:
                logger.warning("Claude CLI failed (rc=%d): %s",
                               proc.returncode, (proc.stderr or proc.stdout)[:200])
                return {}
            text = (proc.stdout or "").strip()
            logger.info("LLM classifier used CLI fallback (no ANTHROPIC_API_KEY)")
        except subprocess.TimeoutExpired:
            logger.warning("Claude CLI timed out after %ds", LLM_CLASSIFIER_TIMEOUT)
            return {}
        except Exception as exc:
            logger.warning("Claude CLI invocation failed: %s", exc)
            return {}
    else:
        try:
            client = Anthropic(api_key=api_key, timeout=LLM_CLASSIFIER_TIMEOUT)
            msg = client.messages.create(
                model=LLM_CLASSIFIER_MODEL,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(
                block.text for block in msg.content if getattr(block, "type", "") == "text"
            ).strip()
        except Exception as exc:
            logger.warning(f"LLM classifier SDK call failed: {exc}")
            return {}

    if text.startswith("```"):
        # Strip fenced code block if Claude wrapped the JSON.
        text = "\n".join(line for line in text.splitlines() if not line.startswith("```")).strip()

    import json as _json
    try:
        verdicts = _json.loads(text)
    except _json.JSONDecodeError as exc:
        logger.warning(f"LLM returned non-JSON ({exc}); head={text[:200]!r}")
        return {}

    if not isinstance(verdicts, list):
        logger.warning(f"LLM returned non-list: {type(verdicts).__name__}")
        return {}

    irrelevant = {}
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        if v.get("verdict") == "irrelevant" and v.get("term"):
            reason = v.get("reason") or "Outside clinic's apparent service scope"
            # Strip em dashes defensively. The system prompt forbids them but
            # if Claude slips, the PDF must not show them.
            reason = reason.replace("—", "-").replace("–", "-")
            irrelevant[v["term"]] = reason
    logger.info(
        "LLM classifier reviewed %d candidate terms, flagged %d as irrelevant",
        len(candidates), len(irrelevant),
    )
    return irrelevant


# ── Account discovery ─────────────────────────────────────────────────────────

def _get_accessible_customer_ids(client) -> list[str]:
    """
    Returns a list of all customer account IDs accessible under the
    pete@clinicmastery.com credentials.

    When a clinic grants read-only access, their account appears here.
    """
    customer_service = client.get_service("CustomerService")
    accessible = customer_service.list_accessible_customers()
    # Returns strings like "customers/1234567890" - extract just the ID
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

def pull_account_data(
    customer_id: str,
    clinic_name: str = "",
    lookback_days: int = 90,
    clinic_suburb: str = "",
    clinic_state: str = "",
) -> dict:
    """
    Pulls the last `lookback_days` of campaign and keyword data for the given account.

    Args:
        customer_id: Google Ads customer ID (no dashes).
        clinic_name: Used to extract brand tokens for the brand-waste classifier
                     and to infer the clinic specialty for the irrelevance rules.
                     If empty, brand detection is skipped and only universal
                     irrelevance patterns apply.
        lookback_days: Window size in days. Default 90. Pass 180 for clinics
                     who paused ads recently and have no recent spend.

    Returns a summary dict with:
      - total_spend_90d, total_conversions_90d, cost_per_conversion
        (keys keep "_90d" suffix for backwards compatibility, even when lookback_days != 90)
      - top_campaigns (list of {name, spend, conversions})
      - wasted_keywords (keywords with spend > threshold and 0 conversions)
      - low_qs_keywords
      - irrelevant_terms (now using expanded rule library)
      - brand_keywords, brand_spend, non_brand_spend
      - avg_quality_score, num_active_campaigns
      - lookback_days: the window actually used
    """
    from datetime import timedelta
    client = _build_google_ads_client()
    ga_service = client.get_service("GoogleAdsService")

    # GAQL doesn't support LAST_N_DAYS - use explicit date range
    today = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
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

    # Classify tracking quality by cost per conversion. Drives how we interpret
    # the conversion data downstream and what the PDF says about it.
    tracking_quality = classify_conversion_tracking(cost_per_conversion)
    # Suppress wasted-spend analysis when the conversion signal is unreliable.
    # "broken" tier (cost per conv < $20) means tracking is firing on the wrong
    # action. "no_data" tier (zero conversions) means we cannot tell whether a
    # zero-conv keyword is genuinely wasted or just unable to fire conversions.
    # In both cases the irrelevant-search-terms classifier remains the trusted
    # source for the wasted-spend headline.
    if tracking_quality in ("broken", "no_data"):
        wasted_keywords = []
    else:
        wasted_keywords = [
            kw for kw in keywords
            if kw["spend"] > WASTED_SPEND_THRESHOLD and kw["conversions"] == 0
        ]
    wasted_keywords = sorted(wasted_keywords, key=lambda k: k["spend"], reverse=True)
    # Backward-compat field. True only for the "broken" tier so existing
    # callers and templates keep working unchanged.
    conversions_invalid = tracking_quality == "broken"

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

    # ── Ad copy (RSA headlines/descriptions) ──────────────────────────────────
    # Used as context for the LLM contextual classifier - what the clinic
    # actually advertises is the strongest available signal for what's
    # in-scope vs out-of-scope when judging search terms.
    ad_copy_query = f"""
        SELECT
            ad_group.name,
            ad_group_ad.ad.responsive_search_ad.headlines,
            ad_group_ad.ad.responsive_search_ad.descriptions,
            metrics.impressions
        FROM ad_group_ad
        WHERE {date_filter}
            AND ad_group_ad.status != 'REMOVED'
        ORDER BY metrics.impressions DESC
        LIMIT 30
    """
    ad_copy = []
    ad_group_name_set = set()
    try:
        ad_response = ga_service.search(customer_id=customer_id, query=ad_copy_query)
        for row in ad_response:
            headlines, descriptions = [], []
            try:
                for h in row.ad_group_ad.ad.responsive_search_ad.headlines:
                    if h.text:
                        headlines.append(h.text)
                for d in row.ad_group_ad.ad.responsive_search_ad.descriptions:
                    if d.text:
                        descriptions.append(d.text)
            except Exception:
                pass
            if not headlines and not descriptions:
                continue
            ag_name = row.ad_group.name
            ad_group_name_set.add(ag_name)
            ad_copy.append({
                "ad_group": ag_name,
                "headlines": headlines,
                "descriptions": descriptions,
            })
    except Exception as exc:
        logger.warning(f"Ad copy query failed: {exc}")
    ad_group_names = sorted(ad_group_name_set)

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

    # Layer 1: rule-library + CTR fallback. Fast, deterministic, catches the
    # universal patterns (free/medicare/jobs/language) and per-vertical
    # wrong-profession buckets.
    irrelevant_terms = _classify_irrelevant_terms(raw_terms, clinic_name=clinic_name)

    # Brand-keyword waste - drives PDF section 5. Branded search terms are
    # recoverable for free via organic + Google Business Profile, so every
    # dollar here is wasted ad spend on existing demand. The PDF section was
    # already in the template waiting for these fields; previously they were
    # always missing so the section rendered $0 brand spend.
    brand_tokens = _extract_brand_tokens(clinic_name)
    branded_terms = _classify_branded_terms(raw_terms, brand_tokens)
    brand_spend = round(sum(t.get("spend", 0) for t in branded_terms), 2)
    non_brand_spend = round(max(total_spend - brand_spend, 0), 2)

    # Layer 2: LLM contextual classifier. Reads the clinic's actual ad copy
    # and judges each remaining search term against the clinic's apparent
    # service scope. Catches things rules can't reach: modality mismatches
    # (EMDR when not offered), demographic mismatches (child when adult-only),
    # geographic mismatches, condition out-of-scope, etc.
    #
    # Skip terms already flagged by the rule library OR the brand classifier
    # so the LLM focuses on contextual nuance only. Branded terms are also
    # excluded - they get their own dedicated PDF section.
    specialty = _infer_specialty(clinic_name)
    ad_copy_themes = _build_ad_copy_themes(ad_copy)
    already_flagged = (
        {t["term"] for t in irrelevant_terms}
        | {t["term"] for t in branded_terms}
    )
    llm_flags = _llm_classify_search_terms(
        clinic_name=clinic_name,
        specialty=specialty,
        ad_copy_themes=ad_copy_themes,
        ad_group_names=ad_group_names,
        search_terms=raw_terms,
        already_flagged_terms=already_flagged,
        clinic_suburb=clinic_suburb,
        clinic_state=clinic_state,
    )
    if llm_flags:
        # Only flag terms with non-trivial spend so the audit stays signal-rich.
        for raw in raw_terms:
            term = raw.get("term", "")
            if term not in llm_flags:
                continue
            if raw.get("spend", 0) < 1 and raw.get("clicks", 0) == 0:
                continue
            irrelevant_terms.append({**raw, "reason": llm_flags[term]})
        irrelevant_terms = sorted(
            irrelevant_terms, key=lambda x: x.get("spend", 0), reverse=True
        )

    return {
        "customer_id": customer_id,
        "clinic_name": clinic_name,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "total_spend_90d": round(total_spend, 2),
        "total_conversions_90d": int(total_conversions),
        "cost_per_conversion": cost_per_conversion,
        "conversions_invalid": conversions_invalid,
        "tracking_quality": tracking_quality,
        "top_campaigns": top_campaigns,
        "all_campaigns_paused": all_campaigns_paused,
        "wasted_keywords": wasted_keywords[:20],
        "wasted_keywords_total_spend": round(sum(k.get("spend", 0) for k in wasted_keywords), 2),
        "wasted_keywords_total_count": len(wasted_keywords),
        "low_qs_keywords": low_qs_keywords,
        "avg_quality_score": avg_quality_score,
        "num_active_campaigns": num_active,
        "irrelevant_terms": irrelevant_terms[:30],
        "irrelevant_terms_total_spend": round(sum(t.get("spend", 0) for t in irrelevant_terms), 2),
        "irrelevant_terms_total_count": len(irrelevant_terms),
        "brand_keywords": branded_terms[:30],
        "brand_spend": brand_spend,
        "non_brand_spend": non_brand_spend,
        "brand_tokens": brand_tokens,
        "specialty": specialty,
        "ad_copy": ad_copy,
        "ad_group_names": ad_group_names,
        "lookback_days": lookback_days,
    }


# ── MCC clinic → account matcher ──────────────────────────────────────────────

# Words that ALL allied health accounts share. They carry no brand signal,
# so a match on them alone is meaningless and produces cross-clinic mistakes
# (RL Physiotherapy mismatching Embrace Physiotherapy because both contain
# "physiotherapy"). Excluded from the match scoring.
_GENERIC_CLINIC_WORDS = {
    # Specialties
    "physiotherapy", "physio", "physiotherapist",
    "psychology", "psychologist", "psychologists",
    "counselling", "counsellor", "counsellors",
    "podiatry", "podiatrist", "podiatrists",
    "chiropractic", "chiropractor",
    "osteopathy", "osteopath", "osteo",
    "naturopathy", "naturopath",
    "speech", "pathology", "pathologist",
    "occupational", "therapy", "therapist", "therapists",
    "dental", "dentist", "dentistry",
    "optometry", "optometrist",
    "dietitian", "dietitians", "nutrition", "nutritionist",
    # Generic clinic descriptors
    "wellbeing", "well-being", "wellness",
    "centre", "center", "clinic", "clinics", "practice",
    "medical", "health", "healthcare", "allied",
    "ndis", "aquatic", "sports", "family",
}


def _match_clinic_to_account(clinic_name: str, accounts: dict) -> Optional[tuple]:
    """Pick the most likely Google Ads customer ID for a given clinic name.

    Args:
        clinic_name: the clinic name from the intake form.
        accounts: {customer_id: descriptive_name} for all accessible accounts.

    Returns (customer_id, descriptive_name, score) if a confident match is
    found, otherwise None.

    Strategy: Jaccard similarity on the cleaned word sets. Rejects matches
    below 0.4 (loose tokens like "physiotherapy" alone score 0.25 to 0.33,
    so the threshold blocks specialty-only collisions). Also rejects ties
    at the top score (genuinely ambiguous, safer to ask for an override
    than to guess wrong).
    """
    stop = {"the", "a", "an", "and", "of", "for", "in", "at", "my", "our", "&"}

    def _words(s: str) -> set[str]:
        return set(_re.sub(r"[^a-z0-9\s]", " ", (s or "").lower()).split())

    clinic_words = _words(clinic_name) - stop
    if not clinic_words:
        return None
    clinic_brand = clinic_words - _GENERIC_CLINIC_WORDS

    candidates: list[tuple[float, str, str]] = []
    for cid, name in accounts.items():
        if not name:
            continue
        acc_words = _words(name) - stop
        if not acc_words:
            continue
        intersection = clinic_words & acc_words
        union = clinic_words | acc_words
        if not intersection:
            continue
        jaccard = len(intersection) / len(union)

        # If the clinic name carries any brand word, require brand-word
        # overlap with the account. This is what blocks "RL Physiotherapy"
        # collapsing to "Embrace Physiotherapy" via the shared "physiotherapy"
        # token.
        if clinic_brand:
            brand_overlap = intersection - _GENERIC_CLINIC_WORDS
            if not brand_overlap:
                continue
            if jaccard >= 0.4:
                candidates.append((jaccard, cid, name))
        else:
            # Edge case: the clinic name is 100% generic words, e.g.
            # "The Psychology, Counselling & Wellbeing Centre". No brand
            # token to gate on, so we require a near-exact match instead.
            if jaccard >= 0.8:
                candidates.append((jaccard, cid, name))

    if not candidates:
        return None

    candidates.sort(key=lambda c: (-c[0], c[1]))
    top = candidates[0]

    # Tied top score = ambiguous, refuse rather than guess.
    if len(candidates) > 1 and candidates[1][0] == top[0]:
        logger.warning(
            f"Ambiguous account match for {clinic_name!r}: tied at jaccard={top[0]:.2f} "
            f"between {top[2]!r} and {candidates[1][2]!r}. Returning no match."
        )
        return None

    return top  # (score, cid, name) — caller pulls cid + name


# ── Immediate report trigger ──────────────────────────────────────────────────

async def run_ads_report_now(
    clinic_name: str,
    ghl_contact_id: str,
    avg_appointment_fee: float = 0.0,
    avg_visits_per_patient: float = 0.0,
    customer_id_override: str = None,
    clinic_suburb: str = "",
    clinic_state: str = "",
) -> dict:
    """
    Immediately attempts to find the clinic's Google Ads account and generate
    the report - no polling loop, no waiting.

    clinic_suburb and clinic_state anchor the LLM classifier's geographic
    catchment rule so nearby-suburb search terms are not flagged as irrelevant.

    Returns {"status": "success", "customer_id": ...} or {"status": "error", "detail": ...}.
    Called by the /trigger-ads-report admin endpoint.
    """
    from ghl import update_contact_field, add_tag_to_contact, get_contact

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

            account_names = {cid: _get_account_name(client, cid) for cid in customer_ids}
            for cid, name in account_names.items():
                logger.info(f"  [Force] Account: {cid} -> {name!r}")

            match = _match_clinic_to_account(clinic_name, account_names)
            if match is None:
                return {
                    "status": "not_found",
                    "detail": f"No confident Google Ads account match for '{clinic_name}'",
                    "accounts_checked": list(account_names.values()),
                }

            score, matched_id, matched_name = match
            logger.info(
                f"[Force] Matched '{clinic_name}' to '{matched_name}' "
                f"({matched_id}) at jaccard={score:.2f}"
            )

        # Pull full account data - clinic_name is required for brand-keyword
        # detection and specialty inference (drives the irrelevance rules).
        summary = pull_account_data(
            matched_id,
            clinic_name=clinic_name,
            clinic_suburb=clinic_suburb,
            clinic_state=clinic_state,
        )

        # Write snapshot to GHL. Recoverable spend combines zero-conv keywords
        # and LLM-flagged irrelevant search terms. Cap at total spend because
        # the two buckets overlap (a click is attributed to both a keyword and
        # a search term); naive summing can produce >100% which is indefensible.
        wasted_total = summary.get("wasted_keywords_total_spend") or 0
        wasted_count = summary.get("wasted_keywords_total_count") or 0
        irrel_total = summary.get("irrelevant_terms_total_spend") or 0
        irrel_count = summary.get("irrelevant_terms_total_count") or 0
        total_spend_90d = summary.get("total_spend_90d") or 0
        raw_recoverable = wasted_total + irrel_total
        recoverable_total = (
            min(raw_recoverable, total_spend_90d) if total_spend_90d else raw_recoverable
        )
        snapshot = (
            f"Total spend (90d): ${summary.get('total_spend_90d', 0):,.2f}\n"
            f"Conversions: {summary.get('total_conversions_90d', 0)} | "
            f"Cost per conversion: ${summary.get('cost_per_conversion', 0):,.2f}\n"
            f"Active campaigns: {summary.get('num_active_campaigns', 0)}\n"
            f"Wasted spend identified: ${recoverable_total:,.2f} "
            f"({wasted_count} zero-conv keywords + {irrel_count} irrelevant search terms)\n"
            f"Avg quality score: {summary.get('avg_quality_score', 0)}/10\n"
            f"Status: Full report emailed to pete@clinicmastery.com"
        )
        await update_contact_field(ghl_contact_id, "google_ads_summary", snapshot)

        # Generate PDF and email
        summary["avg_appointment_fee"] = avg_appointment_fee
        summary["avg_visits_per_patient"] = avg_visits_per_patient
        contact = await get_contact(ghl_contact_id)
        from pdf_report import generate_pdf
        from emailer import send_ads_report
        pdf_bytes = generate_pdf(summary, clinic_name)
        sent = send_ads_report(
            clinic_name, pdf_bytes, summary,
            contact_name=contact.get("first_name", ""),
            contact_email=contact.get("email", ""),
        )

        # Only mark Complete once the audit has actually been delivered. If the
        # email failed (eg. missing SMTP creds), leave status=Pending so the
        # cron picks it up again next cycle instead of silently moving on.
        if not sent:
            logger.error(
                f"[Force] PDF built for {clinic_name} but email failed, "
                f"leaving google_ads_data_status=Pending for retry"
            )
            return {
                "status": "error",
                "detail": "email_send_failed",
                "customer_id": matched_id,
                "email_sent": False,
            }

        await update_contact_field(ghl_contact_id, "google_ads_data_status", "Complete")
        logger.info(f"[Force] Report complete for {clinic_name}. Email sent: True")
        return {
            "status": "success",
            "customer_id": matched_id,
            "email_sent": True,
            "total_spend_90d": summary.get("total_spend_90d"),
            "total_conversions_90d": summary.get("total_conversions_90d"),
        }

    except Exception as exc:
        logger.error(f"[Force] Failed for {clinic_name}: {exc}", exc_info=True)
        return {"status": "error", "detail": str(exc)}

