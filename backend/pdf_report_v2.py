"""Google Ads audit PDF generator — HTML/CSS via Jinja2 + WeasyPrint.

Replaces the ReportLab generator in pdf_report.py for the new brand design
language (Lexend display, lavender hero, insight cards, action rows).

Design system reference: ~/.claude/cm_report_design/reference.html
Compatibility notes (hard-won during prototype): see comments inside the
template's CSS block.

Public surface:
    generate_pdf(summary: dict, clinic_name: str) -> bytes

`summary` must match the shape returned by google_ads.pull_account_data().
Edge cases handled:
  * empty wasted_keywords / irrelevant_terms / brand_keywords  (skip section)
  * tracking_quality in {"broken", "uncertain", "valid", "no_data"}
  * all_campaigns_paused == True
  * impression_share / lost_to_budget / lost_to_rank == None  (PMax)
  * single campaign or zero conversions
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, BaseLoader, select_autoescape
from weasyprint import HTML

log = logging.getLogger("clinic-intake.pdf_report_v2")

GENERATOR_VERSION = "v2.0.0"
LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


# ── Logo loaded once at import time so we don't re-read the file per call ──
def _load_logo_b64() -> str:
    try:
        return base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    except FileNotFoundError:
        log.warning("Logo not found at %s; rendering without it", LOGO_PATH)
        return ""

_LOGO_B64 = _load_logo_b64()


# ── Format helpers ──
def _fmt_money_round(n: float) -> str:
    """$90,468 — rounded to whole dollars when >= $1k."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "$0"
    return f"${n:,.0f}" if abs(n) >= 1000 else f"${n:,.2f}"


def _fmt_money_2dp(n: float) -> str:
    """$90,467.58 — always two decimals."""
    try:
        return f"${float(n):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_pct(n: Any) -> str:
    if n is None:
        return "-"
    try:
        return f"{float(n):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct_int(n: Any) -> str:
    if n is None:
        return "-"
    try:
        return f"{int(round(float(n)))}%"
    except (TypeError, ValueError):
        return "-"


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        return a / b if b else default
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def _title_match(match_type: str) -> str:
    """BROAD -> Broad, EXACT -> Exact. Real GA4 returns uppercase; mock is mixed."""
    if not match_type:
        return ""
    return str(match_type).replace("_", " ").title()


# ── Period label from pulled_at ISO timestamp ──
def _period_strings(pulled_at_iso: str | None) -> tuple[str, str]:
    """Returns (period_label, data_pulled_short).

    Example: ("Reporting period: 1 Feb 2026 to 1 May 2026", "1 May 2026")
    Falls back to today if pulled_at is missing or invalid.
    """
    end = datetime.now(timezone.utc)
    if pulled_at_iso:
        try:
            end = datetime.fromisoformat(pulled_at_iso.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    start = end - timedelta(days=90)

    def _short(d: datetime) -> str:
        return d.strftime("%-d %B %Y")  # 1 May 2026

    return (
        f"Reporting period: {_short(start)} to {_short(end)}",
        _short(end),
    )


# ── Hero stat narrative (templated, adapts to data) ──
def _hero_narrative(d: dict, clinic_name: str) -> dict:
    """Returns {headline, body} for the lavender hero stat block.

    Two variants:
      * 'broken' tracking → headline flags the tracking issue first
      * everything else → standard spend / conversions / leak summary
    """
    spend = d.get("total_spend_90d", 0) or 0
    conv = d.get("total_conversions_90d", 0) or 0
    cpc_conv = d.get("cost_per_conversion", 0) or 0
    n_campaigns = d.get("num_active_campaigns", 0) or 0
    avg_qs = d.get("avg_quality_score", 0) or 0
    tracking = d.get("tracking_quality", "")
    all_paused = d.get("all_campaigns_paused", False)

    wasted = sum(k.get("spend", 0) for k in d.get("wasted_keywords", []) or [])
    irrel = sum(t.get("spend", 0) for t in d.get("irrelevant_terms", []) or [])
    brand = d.get("brand_spend") or sum(k.get("spend", 0) for k in d.get("brand_keywords", []) or [])
    leak_total = wasted + irrel + brand

    if all_paused:
        return {
            "headline": (
                f"Every campaign is paused. No ads are running, so the historical "
                f"{_fmt_money_round(spend)} of spend is the last 90 days of activity, "
                f"not what is happening now."
            ),
            "body": (
                "The starting point is to review why each campaign was paused and "
                "decide which ones to reactivate, with a clear daily budget cap on "
                "each. Until then, every recommendation in this report is theoretical."
            ),
        }

    if tracking == "broken":
        return {
            "headline": (
                f"{_fmt_money_round(spend)} of spend over 90 days, but "
                f"<strong>conversion tracking is recording the wrong action</strong>. "
                f"At {_fmt_money_2dp(cpc_conv)} per conversion, Google is optimising "
                "toward a low-value event, not real patient bookings."
            ),
            "body": (
                "Before doing anything else with budgets or keywords, the conversion "
                "actions inside Google Ads need a review. Once tracking is honest, "
                "the algorithm has real signal to optimise on, and every other "
                "lever in this report becomes more powerful. The full fix sequence "
                "is at the end."
            ),
        }

    headline_lead = (
        f"{_fmt_money_round(spend)} of Google Ads spend brought in {_fmt_int(conv)} "
        f"conversions over the last 90 days."
    )
    if leak_total > spend * 0.03:  # >3% leak worth highlighting
        headline_tail = (
            f" The account is working, but roughly {_fmt_money_round(leak_total)} "
            "of that spend is leaking into keywords, search terms, and brand traffic "
            "that are not growing the patient base."
        )
    else:
        headline_tail = " Spend is going where it should, and the bigger gains from here are in efficiency."

    body_parts = [
        f"At a <strong>{_fmt_money_2dp(cpc_conv)} cost per conversion</strong> across "
        f"{n_campaigns} active campaigns, the account is delivering enquiries."
    ]
    if avg_qs and avg_qs < 6:
        body_parts.append(
            f"The bigger story is what is underneath. Average quality score is "
            f"<strong>{avg_qs}/10</strong>, which means every click is being "
            "charged at a premium."
        )
    body_parts.append(
        "There is a clear recovery path here, and most of it is fixable inside "
        "the existing budget."
    )

    return {
        "headline": headline_lead + headline_tail,
        "body": " ".join(body_parts),
    }


# ── Conversion tracking insight card variant ──
def _tracking_card(d: dict) -> dict:
    """Returns {variant, eyebrow, title, body} for the tracking insight card."""
    tracking = d.get("tracking_quality", "")
    cpc_conv = d.get("cost_per_conversion", 0) or 0
    conv = d.get("total_conversions_90d", 0) or 0

    if conv == 0:
        return {
            "variant": "amber",
            "eyebrow": "Conversion tracking",
            "title": "No conversions are being recorded. Google is optimising blind.",
            "body": (
                "Zero conversions over 90 days almost always means the tracking pixel "
                "is misconfigured, not that the account isn't generating leads. "
                "<strong>Check Google Ads → Tools → Conversions</strong>, confirm at "
                "least one action is set up correctly and recording, then revisit "
                "this report once the data is flowing."
            ),
        }
    if tracking == "broken":
        return {
            "variant": "amber",
            "eyebrow": "Conversion tracking · broken",
            "title": (
                f"Cost per conversion of {_fmt_money_2dp(cpc_conv)} is too cheap to be "
                "real patient bookings. Tracking is counting a low-value event."
            ),
            "body": (
                "A conversion this cheap usually means the account is recording a "
                "click, scroll, or phone reveal as a conversion, not a confirmed "
                "booking or completed enquiry. Google is optimising toward those "
                "cheap events instead of real patients. <strong>Audit the conversion "
                "actions in Tools → Conversions and replace anything that is not a "
                "booking or completed enquiry</strong> before doing anything else."
            ),
        }
    if tracking == "uncertain":
        return {
            "variant": "amber",
            "eyebrow": "Conversion tracking · mixed signal",
            "title": (
                f"Cost per conversion of {_fmt_money_2dp(cpc_conv)} sits below the "
                "$60+ range typical of allied health. Tracking is partly off."
            ),
            "body": (
                "The account is likely counting some real bookings but also some "
                "non-booking events such as button clicks or page scrolls. "
                "<strong>Audit the conversion actions in Tools → Conversions and "
                "remove anything that is not a confirmed booking or completed "
                "enquiry</strong>, so Google can optimise toward genuine patient "
                "acquisition."
            ),
        }
    # tracking == "valid" or anything else → green pass card
    return {
        "variant": "green",
        "eyebrow": "Conversion tracking",
        "title": (
            "Tracking checks pass. The numbers Google is seeing line up with reality, "
            "which means the algorithm is optimising on real signal."
        ),
        "body": (
            f"{_fmt_int(conv)} conversions recorded over 90 days at "
            f"{_fmt_money_2dp(cpc_conv)} per conversion sits inside the plausible "
            "range for allied health. <strong>Recommend confirming inside Google Ads "
            "(Tools → Measurement → Conversions) that every conversion action shows "
            "\"Recording conversions\" in green</strong>, and that no actions are "
            "flagged as inactive."
        ),
    }


# ── Quality-score bands (ported from pdf_report._section_quality) ──
def _qs_bands(d: dict) -> dict:
    """Returns {bands: [...], worst: [...], avg_qs, total} for the QS card."""
    all_kws = (d.get("low_qs_keywords") or []) + (d.get("wasted_keywords") or [])
    seen = set()
    deduped = []
    for k in all_kws:
        key = (k.get("keyword", ""), k.get("match_type", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(k)

    qs_scores = [k.get("quality_score", 0) for k in deduped if (k.get("quality_score") or 0) > 0]
    poor = sum(1 for q in qs_scores if q <= 4)
    avg = sum(1 for q in qs_scores if 5 <= q <= 6)
    good = sum(1 for q in qs_scores if q >= 7)
    total = len(qs_scores) or 1

    bands = [
        {"label": "Poor (1 to 4)", "count": poor, "pct": poor / total * 100, "impact": "Paying premium CPC"},
        {"label": "Average (5 to 6)", "count": avg, "pct": avg / total * 100, "impact": "Slightly above market"},
        {"label": "Good (7 to 10)", "count": good, "pct": good / total * 100, "impact": "Competitive CPC"},
    ]
    worst = [k for k in (d.get("low_qs_keywords") or []) if (k.get("quality_score") or 0) <= 4][:8]

    return {
        "bands": bands,
        "worst": worst,
        "avg_qs": d.get("avg_quality_score", 0) or 0,
        "has_data": len(qs_scores) > 0,
    }


# ── Priority list (ported from pdf_report._section_priorities, Pete-validated logic) ──
def _compute_priorities(d: dict, clinic_name: str) -> list[dict]:
    """Returns ordered list of {title, body} dicts for the action card."""
    wasted = d.get("wasted_keywords") or []
    irrelevant = d.get("irrelevant_terms") or []
    qs = d.get("avg_quality_score", 0) or 0
    cpc_conv = d.get("cost_per_conversion", 0) or 0
    total_conv = d.get("total_conversions_90d", 0) or 0
    tracking = d.get("tracking_quality", "")
    all_paused = d.get("all_campaigns_paused", False)
    brand_kws = d.get("brand_keywords") or []
    brand_spend = d.get("brand_spend") or sum(k.get("spend", 0) for k in brand_kws)
    total_spend = d.get("total_spend_90d", 0) or 0
    non_brand = d.get("non_brand_spend") or max(total_spend - brand_spend, 0)
    brand_pct = brand_spend / (brand_spend + non_brand + 0.01) * 100

    campaigns = d.get("top_campaigns") or []
    rank_losers = [c for c in campaigns if (c.get("lost_to_rank") or 0) > 20 and (c.get("spend") or 0) > 0]
    budget_losers = [c for c in campaigns if (c.get("lost_to_budget") or 0) > 20 and (c.get("spend") or 0) > 0]
    low_qs = d.get("low_qs_keywords") or []

    out: list[dict] = []

    if all_paused:
        out.append({
            "title": "Reactivate campaigns, every ad is currently paused",
            "body": (
                "Every campaign with historical spend is currently paused, so no ads "
                "are running. <strong>Review why each was paused and reactivate the "
                "ones that should be live, with a clear daily budget cap on each.</strong> "
                "Until that's done, every other lever in this report is theoretical."
            ),
        })

    if total_conv == 0:
        out.append({
            "title": "Fix conversion tracking",
            "body": (
                "Zero conversions recorded over 90 days. Google is optimising blind. "
                "<strong>Check Tools → Conversions in Google Ads</strong> and confirm "
                "the tracking pixel is firing on real bookings before increasing spend."
            ),
        })

    if tracking == "broken":
        out.append({
            "title": f"Fix conversion tracking, micro-conversion detected ({_fmt_money_2dp(cpc_conv)}/conv)",
            "body": (
                f"A cost per conversion of {_fmt_money_2dp(cpc_conv)} is not achievable "
                "for real patient bookings. The account is recording a low-value action "
                "(click, scroll, phone reveal) as a conversion. Google is optimising for "
                "these cheap events instead of actual patient enquiries. <strong>Go to "
                "Tools → Conversions, identify the action being tracked, and replace it "
                "with a booking confirmation or genuine form submission.</strong>"
            ),
        })
    elif tracking == "uncertain":
        out.append({
            "title": f"Tighten conversion tracking, mixed signal detected ({_fmt_money_2dp(cpc_conv)}/conv)",
            "body": (
                f"A cost per conversion of {_fmt_money_2dp(cpc_conv)} sits between $20 "
                "and $50, below the $60+ range typical of real patient acquisitions in "
                "allied health. The account is likely counting some real bookings but "
                "also some non-booking events such as button clicks, page scrolls, or "
                "phone reveals. <strong>Audit the conversion actions in Tools → "
                "Conversions and remove anything that is not a confirmed booking or "
                "completed enquiry</strong>, so Google can optimise toward genuine "
                "patient acquisition."
            ),
        })

    if rank_losers:
        names = ", ".join(c.get("name", "")[:40] for c in rank_losers[:2])
        n = len(rank_losers)
        out.append({
            "title": f"Improve ad quality on {n} campaign{'s' if n > 1 else ''} losing impressions to ad rank",
            "body": (
                f"Significant impression share lost to poor ad rank in: {names}. "
                "<strong>Rewrite headlines and descriptions to mirror the keywords more "
                "tightly, and confirm each landing page mentions the exact service in the "
                "H1.</strong> Higher quality scores lower your cost per click and increase "
                "how often your ads show, without spending another dollar."
            ),
        })

    if wasted:
        total_waste = sum(k.get("spend", 0) for k in wasted)
        out.append({
            "title": f"Pause {len(wasted)} wasted keywords and add the worst as account-level negatives",
            "body": (
                f"{_fmt_money_2dp(total_waste)} recoverable per 90 days. "
                "<strong>Pause them at the ad-group level and add the high-spend ones "
                "as exact-match negatives at the account level</strong> so they don't "
                "drift back in via match-type expansion."
            ),
        })

    if budget_losers:
        names = ", ".join(c.get("name", "")[:40] for c in budget_losers[:2])
        n = len(budget_losers)
        out.append({
            "title": f"Increase budget on {n} underfunded campaign{'s' if n > 1 else ''}",
            "body": (
                f"Ads running out of budget before end of day in: {names}. Losing "
                "patients to competitors who are still showing. <strong>Lift daily "
                "budgets by 20% to 30% and watch impression share lost to budget for "
                "two weeks</strong> before lifting further."
            ),
        })

    if irrelevant:
        irrel_waste = sum(t.get("spend", 0) for t in irrelevant)
        out.append({
            "title": f"Add {len(irrelevant)} irrelevant search terms as account-level negatives",
            "body": (
                f"{_fmt_money_2dp(irrel_waste)} spent on searches with zero patient intent. "
                "<strong>Add all of them as exact-match negatives at the account level in "
                "one batch.</strong> Budget the time once, save the spend forever."
            ),
        })

    if low_qs and qs and qs < 6:
        out.append({
            "title": f"Rewrite ad copy for the {len(low_qs)} keywords sitting at QS 1 to 5",
            "body": (
                f"Average quality score is {qs}/10. Keywords rated 1 to 5 cost more per "
                "click than competitors. <strong>Tighten keyword to ad copy to landing "
                "page alignment for each ad group</strong>, so the search query, the "
                "headline, and the H1 all say the same thing. Quality score climbs "
                "within 2 to 4 weeks."
            ),
        })

    if brand_pct > 0:
        out.append({
            "title": f"Stop intercepting brand traffic ({_fmt_money_2dp(brand_spend)} at risk)",
            "body": (
                f"{brand_pct:.0f}% of budget is being spent on people searching directly "
                f"for {clinic_name} and its variants. They were already booking. "
                "<strong>Cap brand keywords in their own low-budget campaign or remove "
                "them entirely from the growth campaigns.</strong> Your conversion rate "
                "will dip in the dashboard, but your real cost per new patient improves."
            ),
        })

    out.append({
        "title": "Set a monthly search-term review",
        "body": (
            "Broad and phrase match keywords accumulate irrelevant traffic over time. "
            "<strong>Block out 20 minutes on the first Monday of each month</strong> to "
            "skim the search terms report and add new negatives. This one habit prevents "
            "most of the leakage you'd otherwise see."
        ),
    })

    out.append({
        "title": "Confirm ad scheduling matches clinic hours",
        "body": (
            "Quick win, takes 5 minutes. Ads running outside opening hours waste budget "
            "on calls that go unanswered. <strong>Restrict campaigns to the clinic's "
            "actual booking hours</strong> and reclaim the after-hours spend."
        ),
    })

    return out


# ── Build all the row collections the template needs ──
def _build_top_campaign_rows(d: dict) -> list[dict]:
    """Adds computed share_pct and cost_per_conv to each top campaign."""
    campaigns = d.get("top_campaigns") or []
    total = d.get("total_spend_90d", 0) or sum(c.get("spend", 0) for c in campaigns)
    max_share = max((c.get("spend", 0) for c in campaigns), default=0) or 1
    rows = []
    for i, c in enumerate(campaigns[:5]):
        spend = c.get("spend", 0) or 0
        conv = c.get("conversions", 0) or 0
        rows.append({
            "name": c.get("name", "-"),
            "spend": spend,
            "share_pct": _safe_div(spend, total) * 100,
            "share_bar_pct": _safe_div(spend, max_share) * 100,
            "conv": conv,
            "cost_per_conv": _safe_div(spend, conv),
            "ctr": c.get("ctr", 0) or 0,
            "is_first": i == 0,
        })
    return rows


def _build_visibility_rows(d: dict) -> list[dict]:
    """Top campaigns with impression-share triple. Skips rows with no IS data."""
    campaigns = d.get("top_campaigns") or []
    rows = []
    for c in campaigns[:5]:
        is_pct = c.get("impression_share")
        lost_budget = c.get("lost_to_budget")
        lost_rank = c.get("lost_to_rank")
        # If all three are None (e.g., display-only or no search data), skip.
        if is_pct is None and lost_budget is None and lost_rank is None:
            continue
        bigger = "Rank" if (lost_rank or 0) > (lost_budget or 0) else "Budget"
        rows.append({
            "name": c.get("name", "-"),
            "is_pct": is_pct,
            "lost_budget": lost_budget,
            "lost_rank": lost_rank,
            "bigger_loss": bigger,
        })
    return rows


# ── Jinja2 environment ──
_jinja_env = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)
_jinja_env.filters["money_round"] = _fmt_money_round
_jinja_env.filters["money_2dp"] = _fmt_money_2dp
_jinja_env.filters["pint"] = _fmt_int
_jinja_env.filters["pct"] = _fmt_pct
_jinja_env.filters["pct_int"] = _fmt_pct_int
_jinja_env.filters["title_match"] = _title_match


# ── Master template ──
# Note: brand-voice rule — no em dashes (—) anywhere in this template.
# That rule applies to template copy only; user data flows through unchanged.
TEMPLATE_SRC = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{{ clinic_name }} · Google Ads Audit · {{ data_pulled }}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Lexend:wght@400;500;700&family=Work+Sans:wght@400;500;700&display=swap');

  :root {
    --cm-purple:       #2E0A78;
    --cm-yellow:       #F0D140;
    --cm-charcoal:     #2A2B2B;
    --cm-off-white:    #FEFEFE;
    --cm-body-grey:    #6E6E6E;
    --cm-orange:       #FF8E21;
    --cm-blue:         #24A3FF;
    --cm-magenta:      #A1129E;
    --cm-warm-red:     #FF7777;
    --cm-silver-grey:  #ABB1BA;
    --cm-light-grey-1: #F5F5F7;
    --cm-light-grey-2: #E3E5E8;
    --cm-light-grey-3: #F9F9F9;
    --cm-divider:      #EDEDED;
    --cm-lavender:     #E2D4FF;
    --cm-green:        #2E8B4A;
    --cm-green-bg:     #E5F4EA;
    --cm-amber-bg:     #FFE6CC;
    --cm-blue-bg:      #DEF1FF;
  }

  @page { size: A4; margin: 14mm 14mm; }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Work Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--cm-light-grey-1);
    color: var(--cm-charcoal);
    padding: 40px 24px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  /* Block layout (not flex). WeasyPrint cannot paginate flex containers,
     overflow children get silently clipped. Sibling margins replace gap. */
  .page { max-width: 760px; margin: 0 auto; }
  .page > * + * { margin-top: 12px; }

  /* HEADER */
  .header {
    background: var(--cm-purple);
    border-radius: 14px;
    padding: 28px 32px;
    color: var(--cm-off-white);
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    gap: 26px;
  }
  .header::after {
    content: ""; position: absolute; top: -40px; right: -40px;
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(240, 209, 64, 0.18) 0%, rgba(240, 209, 64, 0) 70%);
    pointer-events: none;
  }
  .header-logo { height: 68px; width: auto; flex-shrink: 0; position: relative; z-index: 1; }
  .header-content { flex: 1; min-width: 0; position: relative; z-index: 1; }
  .header-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--cm-yellow); margin-bottom: 10px;
  }
  .header-title {
    font-family: 'Lexend', sans-serif; font-size: 28px; font-weight: 500;
    color: var(--cm-off-white); margin-bottom: 6px; letter-spacing: -0.01em; line-height: 1.2;
  }
  .header-sub { font-size: 14px; color: var(--cm-lavender); margin-bottom: 4px; }
  .header-meta {
    font-size: 11px; color: var(--cm-yellow); margin-top: 14px;
    letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700;
  }

  /* SECTION LABEL */
  .section-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--cm-orange);
    margin-bottom: 8px; margin-top: 8px;
    break-after: avoid; page-break-after: avoid;
  }
  .section-group > * + * { margin-top: 8px; }

  /* HERO STAT */
  .stat-hero { background: var(--cm-lavender); border-radius: 12px; padding: 24px 28px; }
  .stat-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--cm-magenta); margin-bottom: 10px;
  }
  .stat-headline {
    font-family: 'Lexend', sans-serif; font-size: 20px; font-weight: 500;
    color: var(--cm-purple); margin-bottom: 12px; line-height: 1.35; letter-spacing: -0.01em;
  }
  .stat-body { font-size: 13px; color: var(--cm-charcoal); line-height: 1.65; }
  .stat-body strong, .stat-headline strong { color: var(--cm-purple); font-weight: 600; }

  /* PAUSED BANNER */
  .paused-banner {
    background: var(--cm-amber-bg);
    border: 1px solid var(--cm-orange);
    border-radius: 12px;
    padding: 14px 20px;
    color: var(--cm-charcoal);
    font-size: 13px;
    line-height: 1.55;
  }
  .paused-banner strong { color: var(--cm-orange); }

  /* KPI GRID */
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  /* Each KPI tile is itself an <a> so the entire card is the click target.
     Block display + inherited color + no underline keeps the card looking
     like a card, not a hyperlink. */
  .kpi-tile {
    display: block;
    background: var(--cm-off-white); border: 1px solid var(--cm-light-grey-2);
    border-radius: 10px; padding: 18px 20px;
    text-align: center;
    text-decoration: none;
    color: inherit;
  }
  .kpi-tile.featured {
    background: linear-gradient(135deg, var(--cm-purple) 0%, #4419a8 100%);
    border-color: var(--cm-purple);
  }
  .kpi-tile.featured .kpi-label { color: var(--cm-yellow); }
  .kpi-tile.featured .kpi-num { color: var(--cm-off-white); }
  .kpi-tile.featured .kpi-sub { color: var(--cm-lavender); }
  .kpi-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--cm-orange); margin-bottom: 8px;
  }
  .kpi-num {
    font-family: 'Lexend', sans-serif; font-size: 24px; font-weight: 700;
    color: var(--cm-purple); line-height: 1.1; margin-bottom: 6px; letter-spacing: -0.01em;
  }
  .kpi-sub { font-size: 11px; color: var(--cm-body-grey); line-height: 1.5; }
  .kpi-warn { color: var(--cm-warm-red); font-weight: 600; }

  /* In-doc links: keep the parent's styling, no underline. The PDF
     viewer still treats them as clickable jumps. */
  a.jump { color: inherit; text-decoration: none; }

  /* Book-a-call CTA card. Always sits just above the footer on every report.
     Pete asked for this on every PDF (audits, briefs, website audit). Naming
     prefix book-* avoids clashing with the .cta-button used by the hero. */
  .book-cta {
    background: var(--cm-purple);
    color: var(--cm-off-white);
    border-radius: 12px;
    padding: 26px 30px;
    text-align: center;
    page-break-inside: avoid; break-inside: avoid;
    margin-top: 4px;
  }
  .book-cta-headline {
    font-family: 'Lexend', sans-serif; font-size: 18px; font-weight: 500;
    color: var(--cm-off-white); margin-bottom: 8px; line-height: 1.3;
  }
  .book-cta-body {
    font-size: 13px; color: var(--cm-lavender); line-height: 1.6;
    margin-bottom: 16px;
  }
  .book-cta-btn {
    display: inline-block; background: var(--cm-yellow); color: var(--cm-purple);
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 13px;
    padding: 12px 26px; border-radius: 999px; text-decoration: none;
    letter-spacing: 0.04em;
  }

  /* CTA button below the hero stat that jumps to the priority list. */
  .cta-button {
    display: block;
    background: var(--cm-purple);
    color: var(--cm-yellow);
    padding: 18px 24px;
    border-radius: 12px;
    text-align: center;
    text-decoration: none;
    font-family: 'Lexend', sans-serif;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    page-break-inside: avoid; break-inside: avoid;
  }
  .cta-button .cta-arrow {
    display: inline-block;
    margin-left: 10px;
    color: var(--cm-yellow);
  }

  /* CARD: keep on one page when it fits on a fresh page.
     `.card-flow` is the escape hatch for cards that are intentionally
     longer than a page (e.g. the priority action list with 8 actions). */
  .card {
    background: var(--cm-off-white); border: 1px solid var(--cm-light-grey-2);
    border-radius: 12px; padding: 20px 24px;
    page-break-inside: avoid; break-inside: avoid;
  }
  .card.card-flow {
    page-break-inside: auto; break-inside: auto;
  }
  .card-title {
    font-family: 'Lexend', sans-serif; font-size: 15px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 4px;
  }
  .card-sub { font-size: 12px; color: var(--cm-body-grey); margin-bottom: 16px; }

  /* CAMPAIGN / VISIBILITY ROWS using HTML table with table-layout: fixed.
     Both flex and grid produced overflow in WeasyPrint when fixed-width
     stat columns met an auto-width campaign name column. Tables with
     fixed layout cannot exceed their container's width, period. */
  table.row-block {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    border-bottom: 0.5px solid var(--cm-divider);
    page-break-inside: avoid; break-inside: avoid;
  }
  table.row-block:last-of-type { border-bottom: none; }
  table.row-block td {
    vertical-align: middle;
    padding: 14px 0;
  }
  table.row-block td.row-info { padding-right: 16px; }
  table.row-block td.row-stat {
    width: 80px;
    text-align: right;
    padding-left: 6px;
    vertical-align: top;
  }
  .row-name {
    font-family: 'Lexend', sans-serif; font-size: 13px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 6px;
  }
  .row-meta { font-size: 11px; color: var(--cm-body-grey); line-height: 1.55; }
  .row-meta strong { color: var(--cm-charcoal); font-weight: 500; }
  .row-bar {
    width: 100%; height: 6px; background: var(--cm-light-grey-1);
    border-radius: 3px; margin-top: 8px; overflow: hidden;
  }
  .row-bar-fill { height: 100%; background: var(--cm-purple); border-radius: 3px; }
  .row-stat-num {
    font-family: 'Lexend', sans-serif; font-size: 16px; font-weight: 700;
    color: var(--cm-purple); line-height: 1.1;
    white-space: nowrap;
  }
  .row-stat-label {
    font-size: 9px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--cm-body-grey); margin-top: 4px;
    line-height: 1.25;
    white-space: nowrap; overflow: hidden;
  }

  /* INSIGHT CARDS: keep title, body and table together on one page. */
  .insight-card {
    border-radius: 12px; padding: 20px 24px;
    page-break-inside: avoid; break-inside: avoid;
  }
  .insight-card.green  { background: var(--cm-green-bg); border: 1px solid var(--cm-green); }
  .insight-card.amber  { background: var(--cm-amber-bg); border: 1px solid var(--cm-orange); }
  .insight-card.blue   { background: var(--cm-blue-bg);  border: 1px solid var(--cm-blue); }
  .insight-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; margin-bottom: 8px;
  }
  .insight-card.green .insight-eyebrow { color: var(--cm-green); }
  .insight-card.amber .insight-eyebrow { color: var(--cm-orange); }
  .insight-card.blue  .insight-eyebrow { color: var(--cm-blue); }
  .insight-title {
    font-family: 'Lexend', sans-serif; font-size: 15px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 10px; line-height: 1.4;
  }
  .insight-body { font-size: 13px; color: var(--cm-charcoal); line-height: 1.65; }
  .insight-body strong { font-weight: 600; }

  /* MINI TABLES */
  .mini-table {
    width: 100%; border-collapse: collapse; margin-top: 14px;
    background: rgba(255,255,255,0.55); border-radius: 8px; overflow: hidden;
  }
  .mini-table th {
    font-size: 9px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--cm-body-grey);
    text-align: left; padding: 8px 10px; border-bottom: 0.5px solid var(--cm-divider);
  }
  .mini-table th.r { text-align: right; }
  .mini-table td {
    font-size: 12px; padding: 8px 10px; border-bottom: 0.5px solid var(--cm-divider);
    vertical-align: top; line-height: 1.45;
  }
  .mini-table tr:last-child td { border-bottom: none; }
  .mini-table .t-name { font-family: 'Lexend', sans-serif; font-weight: 500; color: var(--cm-charcoal); }
  .mini-table .t-tag  { font-size: 11px; color: var(--cm-body-grey); }
  .mini-table .t-num  { font-family: 'Lexend', sans-serif; font-weight: 700; color: var(--cm-purple); text-align: right; white-space: nowrap; }
  .mini-table .t-meta { font-size: 11px; color: var(--cm-body-grey); }

  /* BRAND COMPARISON */
  .compare-row {
    display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0;
    padding: 14px 0; border-bottom: 0.5px solid var(--cm-divider);
    page-break-inside: avoid; break-inside: avoid;
  }
  .compare-row:last-child { border-bottom: none; padding-bottom: 4px; }
  .compare-row.header-row { border-bottom: 1px solid var(--cm-light-grey-2); padding-bottom: 10px; padding-top: 4px; }
  .compare-cell { padding: 0 12px; border-right: 0.5px solid var(--cm-divider); }
  .compare-cell:first-child { padding-left: 0; }
  .compare-cell:last-child { border-right: none; padding-right: 0; }
  .compare-num {
    font-family: 'Lexend', sans-serif; font-size: 18px; font-weight: 700;
    color: var(--cm-purple); line-height: 1.1; margin-bottom: 4px;
  }
  .compare-num.warn { color: var(--cm-warm-red); }
  .compare-sub { font-size: 11px; color: var(--cm-body-grey); }
  .compare-head {
    font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--cm-orange);
  }
  .compare-head.brand    { color: var(--cm-warm-red); }
  .compare-head.nonbrand { color: var(--cm-green); }
  .compare-name {
    font-family: 'Lexend', sans-serif; font-size: 12px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 2px;
  }

  /* ACTION ROWS */
  .action-row {
    display: flex; gap: 14px; align-items: flex-start;
    padding: 14px 0; border-bottom: 0.5px solid var(--cm-divider);
    page-break-inside: avoid; break-inside: avoid;
  }
  .action-row:last-child { border-bottom: none; padding-bottom: 4px; }
  .action-row:first-child { padding-top: 4px; }
  .action-num {
    font-family: 'Lexend', sans-serif; font-size: 13px; font-weight: 700;
    color: var(--cm-purple); background: var(--cm-lavender);
    width: 26px; height: 26px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; margin-top: 1px;
  }
  /* WeasyPrint: break-inside on flex parent does not propagate to children.
     Apply directly so action title and body never split across pages. */
  .action-content { flex: 1; break-inside: avoid; page-break-inside: avoid; }
  .action-title {
    font-family: 'Lexend', sans-serif; font-size: 14px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 4px;
  }
  .action-body { font-size: 12px; color: var(--cm-body-grey); line-height: 1.6; }
  .action-body strong { color: var(--cm-charcoal); font-weight: 500; }

  /* FOOTER */
  .footer {
    margin-top: 16px; padding: 18px 24px; background: var(--cm-off-white);
    border: 1px solid var(--cm-light-grey-2); border-radius: 12px;
    text-align: center; font-size: 11px; color: var(--cm-body-grey); line-height: 1.6;
    page-break-inside: avoid; break-inside: avoid;
  }
  .footer strong { color: var(--cm-purple); font-weight: 600; }

  @media print {
    body { background: white; padding: 0; }
    .page { max-width: 100%; }
  }
</style>
</head>
<body>
<div class="page">

  <div class="header">
    {% if logo_b64 %}
      <img src="data:image/png;base64,{{ logo_b64 }}" alt="Clinic Mastery" class="header-logo">
    {% endif %}
    <div class="header-content">
      <div class="header-eyebrow">Google Ads Audit Report</div>
      <div class="header-title">{{ clinic_name }}</div>
      <div class="header-sub">{{ period_label }}</div>
      <div class="header-meta">Prepared by Clinic Mastery</div>
    </div>
  </div>

  {% if all_paused %}
    <div class="paused-banner">
      <strong>Note:</strong> every campaign in this account is currently paused. The figures below reflect the last 90 days of activity, not what is happening right now.
    </div>
  {% endif %}

  <div class="stat-hero">
    <div class="stat-eyebrow">The headline</div>
    <div class="stat-headline">{{ hero.headline | safe }}</div>
    <div class="stat-body">{{ hero.body | safe }}</div>
  </div>

  <a href="#priorities" class="cta-button">
    What we would fix first<span class="cta-arrow">&rarr;</span>
  </a>

  <div class="section-group">
    <div class="section-label">The headline numbers · 90 days to {{ data_pulled }}</div>
    <div class="grid-3">
      <a class="kpi-tile featured" href="#campaigns">
        <div class="kpi-label">Total spend</div>
        <div class="kpi-num">{{ total_spend | money_2dp }}</div>
        <div class="kpi-sub">Across {{ num_active_campaigns }} active campaigns over the last 90 days.</div>
      </a>
      <a class="kpi-tile" href="#tracking">
        <div class="kpi-label">Conversions</div>
        <div class="kpi-num">{{ total_conv | pint }}</div>
        <div class="kpi-sub">At <strong>{{ cost_per_conv | money_2dp }}</strong> per conversion.</div>
      </a>
      <a class="kpi-tile" href="#visibility">
        <div class="kpi-label">Active campaigns</div>
        <div class="kpi-num">{{ num_active_campaigns }}</div>
        <div class="kpi-sub">Search and Performance Max, ranked by spend.</div>
      </a>
      <a class="kpi-tile" href="#wasted">
        <div class="kpi-label">Wasted spend</div>
        <div class="kpi-num">{{ wasted_total | money_2dp }}</div>
        <div class="kpi-sub">{% if wasted_total > 0 %}<span class="kpi-warn">Recoverable.</span> {% endif %}{{ wasted_count }} keywords with $20+ spend and zero conversions.</div>
      </a>
      <a class="kpi-tile" href="#quality">
        <div class="kpi-label">Avg quality score</div>
        <div class="kpi-num">{{ "%.1f"|format(avg_qs) }} / 10</div>
        <div class="kpi-sub">{% if avg_qs and avg_qs < 6 %}<span class="kpi-warn">Below average.</span> Premium CPC on most clicks.{% elif avg_qs >= 7 %}Above average. Maintaining well.{% else %}Room to improve.{% endif %}</div>
      </a>
      <a class="kpi-tile" href="#brand">
        <div class="kpi-label">Brand spend leak</div>
        <div class="kpi-num">{{ brand_spend | money_2dp }}</div>
        <div class="kpi-sub">{{ "%.1f"|format(brand_pct) }}% of budget intercepting people who already chose you.</div>
      </a>
    </div>
  </div>

  {% if top_campaigns %}
  <div class="section-group" id="campaigns">
    <div class="section-label">Where the budget went · top {{ top_campaigns|length }} campaign{{ 's' if top_campaigns|length > 1 else '' }}</div>
    <div class="card">
      <div class="card-title">Spend, conversions, and cost per conversion by campaign.</div>
      <div class="card-sub">Bars scaled to the largest campaign by spend.</div>
      {% for c in top_campaigns %}
      <table class="row-block">
        <tr>
          <td class="row-info">
            <div class="row-name">{{ c.name }}</div>
            <div class="row-meta">
              <strong>{{ "%.1f"|format(c.share_pct) }}%</strong> of spend · CTR <strong>{{ "%.1f"|format(c.ctr) }}%</strong>
            </div>
            <div class="row-bar"><div class="row-bar-fill" style="width: {{ "%.1f"|format(c.share_bar_pct) }}%; background: {% if c.is_first %}var(--cm-purple){% else %}var(--cm-orange){% endif %};"></div></div>
          </td>
          <td class="row-stat">
            <div class="row-stat-num">{{ c.spend | money_round }}</div>
            <div class="row-stat-label">Spend</div>
          </td>
          <td class="row-stat">
            <div class="row-stat-num">{{ c.conv | pint }}</div>
            <div class="row-stat-label">Conv</div>
          </td>
          <td class="row-stat">
            <div class="row-stat-num">{{ c.cost_per_conv | money_2dp }}</div>
            <div class="row-stat-label">Per conv</div>
          </td>
        </tr>
      </table>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  {% if visibility_rows %}
  <div class="section-group" id="visibility">
    <div class="section-label">Visibility · which auctions you are winning</div>
    <div class="card">
      <div class="card-title">Impression share won, vs share lost to budget and to ad rank.</div>
      <div class="card-sub">Lost to rank means quality scores or bids are too low. Lost to budget means the campaign ran out of money before end of day.</div>
      {% for v in visibility_rows %}
      <table class="row-block">
        <tr>
          <td class="row-info">
            <div class="row-name">{{ v.name }}</div>
            <div class="row-meta">
              Winning <strong>{{ v.is_pct | pct_int }}</strong> of eligible auctions · biggest loss: <strong>{{ v.bigger_loss }}</strong>
            </div>
            <div class="row-bar"><div class="row-bar-fill" style="width: {{ v.is_pct or 0 }}%; background: var(--cm-purple);"></div></div>
          </td>
          <td class="row-stat">
            <div class="row-stat-num">{{ v.is_pct | pct_int }}</div>
            <div class="row-stat-label">Won</div>
          </td>
          <td class="row-stat">
            <div class="row-stat-num">{{ v.lost_budget | pct_int }}</div>
            <div class="row-stat-label">Lost: budget</div>
          </td>
          <td class="row-stat">
            <div class="row-stat-num">{{ v.lost_rank | pct_int }}</div>
            <div class="row-stat-label">Lost: rank</div>
          </td>
        </tr>
      </table>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  {% if wasted_keywords %}
  <div class="insight-card amber" id="wasted">
    <div class="insight-eyebrow">Wasted spend</div>
    <div class="insight-title">{{ wasted_total | money_2dp }} went to {{ wasted_count }} keyword{{ 's' if wasted_count > 1 else '' }} with zero conversions. Pause them and add the worst as account-level negatives.</div>
    <div class="insight-body">These keywords have spent more than $20 each over the last 90 days without producing a single booking. Most are broad match, which means they are catching adjacent intent that is not converting. The action is to <strong>pause them at the ad-group level and add the high-spend ones as exact-match negatives at the account level</strong> so they do not drift back in via match-type expansion.</div>
    <table class="mini-table">
      <thead>
        <tr><th>Keyword</th><th>Match</th><th class="r">Spend</th><th class="r">Clicks</th><th class="r">QS</th></tr>
      </thead>
      <tbody>
        {% for w in wasted_keywords[:8] %}
        <tr>
          <td class="t-name">{{ w.keyword }}</td>
          <td class="t-tag">{{ w.match_type | title_match }}</td>
          <td class="t-num">{{ w.spend | money_2dp }}</td>
          <td class="t-num">{{ w.clicks | pint }}</td>
          <td class="t-num">{{ w.quality_score if w.quality_score else "–" }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {% if irrelevant_terms %}
  <div class="insight-card amber" id="irrelevant">
    <div class="insight-eyebrow">Irrelevant search terms</div>
    <div class="insight-title">{{ irrel_total | money_2dp }} was spent on {{ irrel_count }} search term{{ 's' if irrel_count > 1 else '' }} with zero patient intent.</div>
    <div class="insight-body">These are actual searches that triggered your ads. Most are competitor brand names, NDIS admin queries, or adjacent services that have nothing to do with booking therapy. Each click costs money with no chance of conversion. The fix is one batch job: <strong>add all of them as exact-match negatives at the account level</strong>. Then schedule a 20-minute monthly search-term review so new ones do not accumulate.</div>
    <table class="mini-table">
      <thead>
        <tr><th>Search term</th><th class="r">Spend</th><th class="r">Clicks</th><th>Why irrelevant</th></tr>
      </thead>
      <tbody>
        {% for t in irrelevant_terms[:8] %}
        <tr>
          <td class="t-name">{{ t.term }}</td>
          <td class="t-num">{{ t.spend | money_2dp }}</td>
          <td class="t-num">{{ t.clicks | pint }}</td>
          <td class="t-meta">{{ t.reason }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {% if brand_spend > 0 %}
  <div class="insight-card blue" id="brand">
    <div class="insight-eyebrow">Brand keyword leak</div>
    <div class="insight-title">In healthcare, brand keyword spend is almost always wasted. {{ brand_spend | money_2dp }} is intercepting people who already chose you.</div>
    <div class="insight-body">Unlike e-commerce, people searching directly for <strong>{{ clinic_name }}</strong> and its variants are existing patients, referrals, or people who already decided to book. They were going to find you anyway via organic results and your Google Business Profile, at zero cost. The fix is to <strong>cap brand keywords inside their own low-budget brand campaign</strong>, or eliminate them entirely from the growth campaigns. Conversion rate will dip in the dashboard, but the real cost per <em>new</em> patient improves.</div>

    <div style="margin-top: 18px;">
      <div class="compare-row header-row">
        <div class="compare-cell"><div class="compare-head">Spend type</div></div>
        <div class="compare-cell"><div class="compare-head brand">Brand keywords</div></div>
        <div class="compare-cell"><div class="compare-head nonbrand">Non-brand keywords</div></div>
      </div>
      <div class="compare-row">
        <div class="compare-cell">
          <div class="compare-name">90-day spend</div>
          <div class="compare-sub">Total invested</div>
        </div>
        <div class="compare-cell">
          <div class="compare-num warn">{{ brand_spend | money_2dp }}</div>
          <div class="compare-sub">{{ "%.1f"|format(brand_pct) }}% of budget</div>
        </div>
        <div class="compare-cell">
          <div class="compare-num">{{ non_brand_spend | money_2dp }}</div>
          <div class="compare-sub">{{ "%.1f"|format(100 - brand_pct) }}% of budget</div>
        </div>
      </div>
      <div class="compare-row">
        <div class="compare-cell">
          <div class="compare-name">Who is searching</div>
          <div class="compare-sub">Buyer intent</div>
        </div>
        <div class="compare-cell">
          <div class="compare-num warn" style="font-size: 13px;">Existing patients</div>
          <div class="compare-sub">Already chose you</div>
        </div>
        <div class="compare-cell">
          <div class="compare-num" style="font-size: 13px;">New patients</div>
          <div class="compare-sub">Actively searching for help</div>
        </div>
      </div>
    </div>
  </div>
  {% endif %}

  <div class="insight-card {{ tracking_card.variant }}" id="tracking">
    <div class="insight-eyebrow">{{ tracking_card.eyebrow }}</div>
    <div class="insight-title">{{ tracking_card.title | safe }}</div>
    <div class="insight-body">{{ tracking_card.body | safe }}</div>
  </div>

  {% if qs.has_data %}
  <div class="card" id="quality">
    <div class="card-title">Quality score is the lever with the most leverage.{% if qs.avg_qs and qs.avg_qs < 6 %} Right now it is dragging.{% endif %}</div>
    <div class="card-sub">Distribution of keywords across QS bands, and the worst performers ranked by spend.</div>
    <table class="mini-table" style="margin-top: 4px;">
      <thead>
        <tr><th>Quality score band</th><th class="r">Keywords</th><th class="r">% of total</th><th>Impact</th></tr>
      </thead>
      <tbody>
        {% for b in qs.bands %}
        <tr>
          <td class="t-name">{{ b.label }}</td>
          <td class="t-num">{{ b.count }}</td>
          <td class="t-num">{{ "%.1f"|format(b.pct) }}%</td>
          <td class="t-meta">{{ b.impact }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <div style="margin-top: 18px; font-size: 12px; color: var(--cm-body-grey); line-height: 1.6;">
      Average quality score is <strong style="color: {% if qs.avg_qs and qs.avg_qs < 6 %}var(--cm-warm-red){% else %}var(--cm-purple){% endif %};">{{ "%.1f"|format(qs.avg_qs) }}/10</strong>. The fastest fix is keyword-to-ad-copy-to-landing-page alignment: when the search query, the headline, and the H1 on the page all say the same thing, quality score climbs within 2 to 4 weeks.
    </div>

    {% if qs.worst %}
    <div style="margin-top: 16px; font-family: 'Lexend', sans-serif; font-size: 12px; font-weight: 500; color: var(--cm-purple); text-transform: uppercase; letter-spacing: 0.06em;">Worst performers ranked by spend</div>
    <table class="mini-table" style="margin-top: 8px; background: var(--cm-light-grey-3);">
      <thead>
        <tr><th>Keyword</th><th>Match</th><th class="r">QS</th><th class="r">Spend</th><th class="r">Conv</th></tr>
      </thead>
      <tbody>
        {% for w in qs.worst %}
        <tr>
          <td class="t-name">{{ w.keyword }}</td>
          <td class="t-tag">{{ w.match_type | title_match }}</td>
          <td class="t-num">{{ w.quality_score }}</td>
          <td class="t-num">{{ w.spend | money_2dp }}</td>
          <td class="t-num">{{ w.conversions | pint }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </div>
  {% endif %}

  <div class="section-group" id="priorities">
    <div class="section-label">What we would fix first · ranked by impact</div>
    <div class="card card-flow">
      {% for a in priorities %}
      <div class="action-row">
        <div class="action-num">{{ loop.index }}</div>
        <div class="action-content">
          <div class="action-title">{{ a.title }}</div>
          <div class="action-body">{{ a.body | safe }}</div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="book-cta">
    <div class="book-cta-headline">Want to walk through this together?</div>
    <p class="book-cta-body">Twenty minutes with Pete to walk through this audit, prioritise the actions that matter most, and decide what to tackle first.</p>
    <a class="book-cta-btn" href="https://bookings.clinicmastery.com/pete-flynn-google-ads">Book a 20-minute call</a>
  </div>

  <div class="footer">
    <strong>{{ clinic_name }} · Google Ads Audit · 90 days to {{ data_pulled }}</strong><br>
    Confidential. Prepared by Clinic Mastery on the basis of read-only Google Ads access.<br>
    Read-only access can be revoked at any time via Google Ads → Admin → Access and security.
  </div>

</div>
</body>
</html>
"""

# Brand-voice safety net: catch em dashes accidentally introduced into the
# template. Applies to template copy only — user data flows through unchanged.
assert "—" not in TEMPLATE_SRC, (
    "Em dash (\\u2014) found in CM audit template. "
    "Brand voice rule: no em dashes. Use 'to' or commas instead."
)

_TEMPLATE = _jinja_env.from_string(TEMPLATE_SRC)


# ── Public entry point ──
def generate_pdf(summary: dict, clinic_name: str) -> bytes:
    """Render the audit report to PDF bytes.

    `summary` shape: see google_ads.pull_account_data() docstring.
    Missing keys are tolerated; sections render conditionally.
    """
    d = summary or {}
    clinic_name = clinic_name or d.get("clinic_name") or "Your Clinic"

    period_label, data_pulled = _period_strings(d.get("pulled_at"))

    total_spend = d.get("total_spend_90d", 0) or 0
    brand_spend = d.get("brand_spend") or sum(k.get("spend", 0) for k in (d.get("brand_keywords") or []))
    non_brand_spend = d.get("non_brand_spend") or max(total_spend - brand_spend, 0)
    brand_pct = (brand_spend / (brand_spend + non_brand_spend + 0.01)) * 100

    wasted_keywords = d.get("wasted_keywords") or []
    wasted_total = sum(k.get("spend", 0) for k in wasted_keywords)
    irrelevant_terms = d.get("irrelevant_terms") or []
    irrel_total = sum(t.get("spend", 0) for t in irrelevant_terms)

    ctx = {
        "logo_b64": _LOGO_B64,
        "clinic_name": clinic_name,
        "period_label": period_label,
        "data_pulled": data_pulled,
        "all_paused": d.get("all_campaigns_paused", False),
        "hero": _hero_narrative(d, clinic_name),
        # KPI grid
        "total_spend": total_spend,
        "total_conv": d.get("total_conversions_90d", 0) or 0,
        "cost_per_conv": d.get("cost_per_conversion", 0) or 0,
        "num_active_campaigns": d.get("num_active_campaigns", 0) or 0,
        "wasted_total": wasted_total,
        "wasted_count": len(wasted_keywords),
        "avg_qs": d.get("avg_quality_score", 0) or 0,
        "brand_spend": brand_spend,
        "non_brand_spend": non_brand_spend,
        "brand_pct": brand_pct,
        # Sections
        "top_campaigns": _build_top_campaign_rows(d),
        "visibility_rows": _build_visibility_rows(d),
        "wasted_keywords": wasted_keywords,
        "irrelevant_terms": irrelevant_terms,
        "irrel_total": irrel_total,
        "irrel_count": len(irrelevant_terms),
        "tracking_card": _tracking_card(d),
        "qs": _qs_bands(d),
        "priorities": _compute_priorities(d, clinic_name),
    }

    html_text = _TEMPLATE.render(**ctx)
    pdf_bytes = HTML(string=html_text).write_pdf()
    log.info(
        "Generated v2 audit PDF: clinic=%s, %d bytes, %d priorities, %d campaigns",
        clinic_name, len(pdf_bytes), len(ctx["priorities"]), len(ctx["top_campaigns"]),
    )
    return pdf_bytes


def generator_version() -> str:
    return GENERATOR_VERSION


# ─── INTAKE BRIEF v2 ─────────────────────────────────────────────────────────
# A separate growth-focused PDF for clinics that submitted the intake form
# but do not run Google Ads. Same brand design system as the audit; different
# content (revenue context, keyword targets, suggested campaign structure,
# next steps), all derived from the form data alone.

# Keyword helpers live in pdf_report.py — reuse them rather than duplicating.
def _kw_helpers():
    from pdf_report import _condition_keywords, _service_keywords, _negative_keywords
    return _condition_keywords, _service_keywords, _negative_keywords


_SPEC_ABBREV = {
    "physiotherapy": "physio", "chiropractic": "chiropractor", "chiro": "chiropractor",
    "psychology": "psychologist", "osteopathy": "osteopath", "osteo": "osteopath",
    "podiatry": "podiatrist", "naturopathy": "naturopath", "dentistry": "dentist",
    "dental": "dentist", "optometry": "optometrist", "dietitian": "dietitian",
    "speech pathology": "speech pathologist",
    "occupational therapy": "occupational therapist",
}


def _spec_abbrev(spec: str) -> str:
    spec_lc = (spec or "").lower()
    for k, v in _SPEC_ABBREV.items():
        if k in spec_lc:
            return v
    return spec_lc.split()[0] if spec_lc else "clinic"


def _brief_hero(s: dict) -> dict:
    """Top-of-doc narrative for the intake brief. Adapts to the data."""
    fee = float(s.get("avg_appointment_fee") or 0)
    visits = float(s.get("avg_visits_per_patient") or 0)
    ltv = fee * visits
    new_pts = int(s.get("new_patients_per_month") or 0)
    monthly_rev = ltv * new_pts
    annual_per_extra = ltv * 12
    goal = (s.get("main_goal") or "").strip().rstrip(".")
    clinic = s.get("clinic_name") or "the clinic"

    headline = (
        f"At a {_fmt_money_2dp(ltv)} estimated patient lifetime value, "
        f"{new_pts} new patients a month is "
        f"<strong>{_fmt_money_round(monthly_rev)}</strong> of ongoing revenue. "
        f"Each additional patient per month is worth around "
        f"<strong>{_fmt_money_round(annual_per_extra)}</strong> a year."
    )

    body_parts = [
        f"This brief is built from {clinic}'s intake form alone. "
        f"Google Ads is not currently running, so there is no account to audit. "
        f"What follows is the growth blueprint we would put in front of a clinic at this stage:"
        f" the revenue maths, the keyword groups we would target,"
        f" a starting campaign structure, and the next steps."
    ]
    if goal:
        body_parts.append(
            f"The stated goal is <strong>{goal.lower() if not goal.isupper() else goal}</strong>, "
            "and every recommendation below is filtered through that."
        )

    return {"headline": headline, "body": " ".join(body_parts)}


def _brief_revenue_metrics(s: dict) -> dict:
    fee = float(s.get("avg_appointment_fee") or 0)
    visits = float(s.get("avg_visits_per_patient") or 0)
    ltv = fee * visits
    new_pts = int(s.get("new_patients_per_month") or 0)
    monthly_rev = ltv * new_pts
    ad_spend = float(s.get("monthly_ad_spend") or 0)
    return {
        "fee": fee, "visits": visits, "ltv": ltv,
        "new_pts": new_pts, "monthly_rev": monthly_rev,
        "ad_spend": ad_spend,
    }


def _brief_keyword_groups(s: dict) -> list[dict]:
    """Returns four keyword groups: location, condition, service, negatives."""
    cond_kw, serv_kw, neg_kw = _kw_helpers()
    suburb = (s.get("suburb") or "").strip()
    state = (s.get("state") or "").strip()
    spec = (s.get("primary_specialty") or "").strip()
    spec_lc = spec.lower()
    appt = s.get("appointment_types_to_grow") or ""
    abbrev = _spec_abbrev(spec)

    return [
        {
            "variant": "green",
            "label": "Location intent · highest conversion",
            "match": "Exact / Phrase",
            "keywords": [
                f"{abbrev} {suburb.lower()}",
                f"{abbrev} near me",
                f"best {abbrev} {suburb.lower()}",
                f"{abbrev} {state.lower()}",
                f"{spec_lc} clinic {suburb.lower()}",
            ],
            "note": (
                "Searchers with strong local intent. They already know what they need "
                "and are looking for the closest place to get it. Highest conversion rate, "
                "tight match types, expect to spend more per click but earn it back fast."
            ),
        },
        {
            "variant": "blue",
            "label": "Condition / symptom · high volume",
            "match": "Phrase",
            "keywords": cond_kw(spec_lc, suburb, appt),
            "note": (
                "Patients describing the problem, not the solution. Higher search volume, "
                "slightly lower intent, and the search terms report needs weekly review to "
                "block irrelevant traffic. Where the brand-awareness gains live."
            ),
        },
        {
            "variant": "amber",
            "label": "Service-specific · known want",
            "match": "Exact / Phrase",
            "keywords": serv_kw(spec_lc, suburb, appt),
            "note": (
                "Built from the appointment types you want to grow. Patients searching "
                "this already know the service. Smaller volume, very high intent."
            ),
        },
        {
            "variant": "warn",
            "label": "Negative keywords · block before launch",
            "match": "Exact negative",
            "keywords": neg_kw(spec_lc),
            "note": (
                "Add these as account-level negatives on day one. Blocks job seekers, "
                "students, free-service hunters, and competitor research traffic that would "
                "otherwise eat budget without ever booking."
            ),
        },
    ]


def _brief_campaigns(s: dict) -> list[dict]:
    """Returns the suggested campaign structure rows."""
    spec = (s.get("primary_specialty") or "").strip()
    spec_lc = spec.lower()
    suburb = (s.get("suburb") or "").strip()
    appt = s.get("appointment_types_to_grow") or ""
    abbrev = _spec_abbrev(spec)
    ad_spend = float(s.get("monthly_ad_spend") or 0)
    cond_kw, _, _ = _kw_helpers()

    # 70% / 30% split between location-core and condition campaigns
    core_budget = ad_spend * 0.70 if ad_spend else None
    cond_budget = ad_spend * 0.30 if ad_spend else None

    return [
        {
            "name": f"Search · {spec} · {suburb} (Core)",
            "budget": _fmt_money_round(core_budget) + "/mo" if core_budget else "≈ 70% of budget",
            "type": "Search",
            "bidding": "Maximise Conversions, switch to Target CPA after 30 conversions",
            "ad_groups": [
                f"{abbrev} {suburb.lower()} · exact location terms",
                f"{abbrev} near me · proximity intent",
                f"best {abbrev} · quality seekers",
            ],
            "note": (
                "Tightest control. Exact and phrase match only. "
                "Enable location and call extensions on day one."
            ),
        },
        {
            "name": f"Search · {spec} · Condition / symptom",
            "budget": _fmt_money_round(cond_budget) + "/mo" if cond_budget else "≈ 30% of budget",
            "type": "Search",
            "bidding": "Maximise Clicks initially, then Maximise Conversions",
            "ad_groups": [g for g in cond_kw(spec_lc, suburb, appt)[:3]],
            "note": (
                "Higher volume, lower intent. Review the search terms report weekly "
                "and add negatives aggressively. Separate ad groups per condition."
            ),
        },
    ]


def _brief_next_steps(s: dict) -> list[dict]:
    clinic = s.get("clinic_name") or "the clinic"
    goal = (s.get("main_goal") or "").strip()
    new_pts = int(s.get("new_patients_per_month") or 0)
    ad_spend = float(s.get("monthly_ad_spend") or 0)
    suburb = s.get("suburb") or ""
    state = s.get("state") or ""
    spec = s.get("primary_specialty") or ""

    steps = []
    steps.append({
        "title": "Schedule the strategy call",
        "body": (
            f"Walk {clinic} through this brief and pressure-test the goal "
            f'("{goal}"). Identify the single biggest growth lever before any '
            "campaign goes live."
        ),
    })
    steps.append({
        "title": "Benchmark current spend against market",
        "body": (
            f"Current monthly Google Ads spend is "
            f"<strong>{_fmt_money_round(ad_spend)}</strong> for "
            f"<strong>{new_pts}</strong> new patients a month. "
            f"Run a market-rate comparison for {spec} clinics in "
            f"{suburb}, {state} to confirm the budget envelope is realistic."
        ),
    })
    steps.append({
        "title": "Build the day-one negatives list",
        "body": (
            "Before any campaign goes live, the negatives in the warning card "
            "above need to be loaded as account-level exact-match negatives. "
            "This step prevents most of the wasted spend we usually see in the "
            "first 30 days."
        ),
    })
    steps.append({
        "title": "Stand up tracking before launch",
        "body": (
            "Confirm a booking-confirmation conversion action is firing in Google "
            "Ads (not a button click or scroll), the GA4 link is healthy, and call "
            "tracking is in place. Without honest tracking the rest of the system "
            "is optimising blind."
        ),
    })
    steps.append({
        "title": "Launch the core campaign first, watch for two weeks",
        "body": (
            "Spin up the location-intent core campaign on a controlled budget. "
            "Hold the condition campaign back for two weeks so we can baseline "
            "cost per booking on the highest-intent traffic before introducing "
            "more variability."
        ),
    })
    return steps


# ─── INTAKE BRIEF TEMPLATE ───────────────────────────────────────────────────

TEMPLATE_BRIEF_SRC = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{{ clinic_name }} · Clinic Growth Brief</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Lexend:wght@400;500;700&family=Work+Sans:wght@400;500;700&display=swap');

  :root {
    --cm-purple:       #2E0A78;
    --cm-yellow:       #F0D140;
    --cm-charcoal:     #2A2B2B;
    --cm-off-white:    #FEFEFE;
    --cm-body-grey:    #6E6E6E;
    --cm-orange:       #FF8E21;
    --cm-blue:         #24A3FF;
    --cm-magenta:      #A1129E;
    --cm-warm-red:     #FF7777;
    --cm-silver-grey:  #ABB1BA;
    --cm-light-grey-1: #F5F5F7;
    --cm-light-grey-2: #E3E5E8;
    --cm-light-grey-3: #F9F9F9;
    --cm-divider:      #EDEDED;
    --cm-lavender:     #E2D4FF;
    --cm-green:        #2E8B4A;
    --cm-green-bg:     #E5F4EA;
    --cm-amber-bg:     #FFE6CC;
    --cm-blue-bg:      #DEF1FF;
    --cm-warn-bg:      #FFE2E2;
  }

  @page { size: A4; margin: 14mm 14mm; }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Work Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--cm-light-grey-1);
    color: var(--cm-charcoal);
    padding: 40px 24px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .page { max-width: 760px; margin: 0 auto; }
  .page > * + * { margin-top: 12px; }

  /* HEADER */
  .header {
    background: var(--cm-purple);
    border-radius: 14px;
    padding: 28px 32px;
    color: var(--cm-off-white);
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    gap: 26px;
  }
  .header::after {
    content: ""; position: absolute; top: -40px; right: -40px;
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(240, 209, 64, 0.18) 0%, rgba(240, 209, 64, 0) 70%);
    pointer-events: none;
  }
  .header-logo { height: 68px; width: auto; flex-shrink: 0; position: relative; z-index: 1; }
  .header-content { flex: 1; min-width: 0; position: relative; z-index: 1; }
  .header-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--cm-yellow); margin-bottom: 10px;
  }
  .header-title {
    font-family: 'Lexend', sans-serif; font-size: 28px; font-weight: 500;
    color: var(--cm-off-white); margin-bottom: 6px; letter-spacing: -0.01em; line-height: 1.2;
  }
  .header-sub { font-size: 14px; color: var(--cm-lavender); margin-bottom: 4px; }
  .header-meta {
    font-size: 11px; color: var(--cm-yellow); margin-top: 14px;
    letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700;
  }

  .section-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--cm-orange);
    margin-bottom: 8px; margin-top: 8px;
    break-after: avoid; page-break-after: avoid;
  }
  .section-group > * + * { margin-top: 8px; }

  /* HERO STAT */
  .stat-hero { background: var(--cm-lavender); border-radius: 12px; padding: 24px 28px; }
  .stat-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--cm-magenta); margin-bottom: 10px;
  }
  .stat-headline {
    font-family: 'Lexend', sans-serif; font-size: 20px; font-weight: 500;
    color: var(--cm-purple); margin-bottom: 12px; line-height: 1.35; letter-spacing: -0.01em;
  }
  .stat-body { font-size: 13px; color: var(--cm-charcoal); line-height: 1.65; }
  .stat-body strong, .stat-headline strong { color: var(--cm-purple); font-weight: 600; }

  /* Book-a-call CTA card. Sits just above the footer on every report.
     Naming prefix book-* avoids clashing with the .cta-button used in-page. */
  .book-cta {
    background: var(--cm-purple);
    color: var(--cm-off-white);
    border-radius: 12px;
    padding: 26px 30px;
    text-align: center;
    page-break-inside: avoid; break-inside: avoid;
    margin-top: 4px;
  }
  .book-cta-headline {
    font-family: 'Lexend', sans-serif; font-size: 18px; font-weight: 500;
    color: var(--cm-off-white); margin-bottom: 8px; line-height: 1.3;
  }
  .book-cta-body {
    font-size: 13px; color: var(--cm-lavender); line-height: 1.6;
    margin-bottom: 16px;
  }
  .book-cta-btn {
    display: inline-block; background: var(--cm-yellow); color: var(--cm-purple);
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 13px;
    padding: 12px 26px; border-radius: 999px; text-decoration: none;
    letter-spacing: 0.04em;
  }

  /* CTA button */
  .cta-button {
    display: block;
    background: var(--cm-purple);
    color: var(--cm-yellow);
    padding: 18px 24px;
    border-radius: 12px;
    text-align: center;
    text-decoration: none;
    font-family: 'Lexend', sans-serif;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    page-break-inside: avoid; break-inside: avoid;
  }
  .cta-button .cta-arrow { display: inline-block; margin-left: 10px; color: var(--cm-yellow); }

  /* KPI GRID */
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  /* Keep the whole 6-tile KPI grid on one page when it fits. */
  .grid-keep-together { page-break-inside: avoid; break-inside: avoid; }
  .kpi-tile {
    display: block;
    background: var(--cm-off-white); border: 1px solid var(--cm-light-grey-2);
    border-radius: 10px; padding: 18px 20px;
    text-align: center;
    text-decoration: none;
    color: inherit;
  }
  .kpi-tile.featured {
    background: linear-gradient(135deg, var(--cm-purple) 0%, #4419a8 100%);
    border-color: var(--cm-purple);
  }
  .kpi-tile.featured .kpi-label { color: var(--cm-yellow); }
  .kpi-tile.featured .kpi-num { color: var(--cm-off-white); }
  .kpi-tile.featured .kpi-sub { color: var(--cm-lavender); }
  .kpi-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--cm-orange); margin-bottom: 8px;
  }
  .kpi-num {
    font-family: 'Lexend', sans-serif; font-size: 24px; font-weight: 700;
    color: var(--cm-purple); line-height: 1.1; margin-bottom: 6px; letter-spacing: -0.01em;
  }
  .kpi-sub { font-size: 11px; color: var(--cm-body-grey); line-height: 1.5; }

  /* CARD */
  .card {
    background: var(--cm-off-white); border: 1px solid var(--cm-light-grey-2);
    border-radius: 12px; padding: 20px 24px;
    page-break-inside: avoid; break-inside: avoid;
  }
  .card.card-flow { page-break-inside: auto; break-inside: auto; }
  .card-title {
    font-family: 'Lexend', sans-serif; font-size: 15px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 4px;
  }
  .card-sub { font-size: 12px; color: var(--cm-body-grey); margin-bottom: 16px; }

  /* SNAPSHOT (clinic basics, two-column key/value) */
  .snapshot-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    column-gap: 32px;
    margin-top: 4px;
  }
  .snap-row {
    display: grid; grid-template-columns: 1fr auto;
    gap: 8px;
    padding: 10px 0;
    border-bottom: 0.5px solid var(--cm-divider);
    align-items: baseline;
  }
  .snap-row:nth-last-child(-n+2) { border-bottom: none; }
  .snap-row.full { grid-column: 1 / -1; }
  .snap-key {
    font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--cm-body-grey);
  }
  .snap-val {
    font-family: 'Lexend', sans-serif; font-size: 13px; font-weight: 500;
    color: var(--cm-charcoal); text-align: right; word-break: break-word;
  }

  /* INSIGHT CARDS */
  .insight-card {
    border-radius: 12px; padding: 20px 24px;
    page-break-inside: avoid; break-inside: avoid;
  }
  .insight-card.green  { background: var(--cm-green-bg); border: 1px solid var(--cm-green); }
  .insight-card.amber  { background: var(--cm-amber-bg); border: 1px solid var(--cm-orange); }
  .insight-card.blue   { background: var(--cm-blue-bg);  border: 1px solid var(--cm-blue); }
  .insight-card.warn   { background: var(--cm-warn-bg);  border: 1px solid var(--cm-warm-red); }
  .insight-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; margin-bottom: 8px;
  }
  .insight-card.green .insight-eyebrow { color: var(--cm-green); }
  .insight-card.amber .insight-eyebrow { color: var(--cm-orange); }
  .insight-card.blue  .insight-eyebrow { color: var(--cm-blue); }
  .insight-card.warn  .insight-eyebrow { color: var(--cm-warm-red); }
  .insight-title {
    font-family: 'Lexend', sans-serif; font-size: 15px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 10px; line-height: 1.4;
  }
  .insight-body { font-size: 13px; color: var(--cm-charcoal); line-height: 1.65; }
  .insight-body strong { font-weight: 600; }

  /* keyword pills inside an insight card */
  .kw-list {
    margin-top: 14px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .kw-pill {
    background: rgba(255,255,255,0.7);
    border: 0.5px solid var(--cm-divider);
    border-radius: 6px;
    padding: 5px 10px;
    font-family: 'Lexend', sans-serif;
    font-size: 11px;
    font-weight: 500;
    color: var(--cm-charcoal);
  }
  .kw-meta {
    margin-top: 14px;
    font-size: 11px;
    color: var(--cm-body-grey);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .kw-meta strong { color: var(--cm-charcoal); font-weight: 600; }

  /* Campaign rows (HTML table, identical pattern to audit) */
  table.row-block {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    border-bottom: 0.5px solid var(--cm-divider);
    page-break-inside: avoid; break-inside: avoid;
  }
  table.row-block:last-of-type { border-bottom: none; }
  table.row-block td { vertical-align: top; padding: 14px 0; }
  table.row-block td.row-info { padding-right: 16px; }
  table.row-block td.row-stat {
    width: 100px; text-align: right; padding-left: 6px;
  }
  .row-name {
    font-family: 'Lexend', sans-serif; font-size: 13px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 6px;
  }
  .row-meta { font-size: 11px; color: var(--cm-body-grey); line-height: 1.55; }
  .row-meta strong { color: var(--cm-charcoal); font-weight: 500; }
  .row-stat-num {
    font-family: 'Lexend', sans-serif; font-size: 14px; font-weight: 700;
    color: var(--cm-purple); line-height: 1.1; white-space: nowrap;
  }
  .row-stat-label {
    font-size: 9px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--cm-body-grey);
    margin-top: 4px; line-height: 1.25; white-space: nowrap;
  }
  .ag-list {
    margin-top: 8px;
    font-size: 11px;
    color: var(--cm-body-grey);
    line-height: 1.55;
  }
  .ag-list .ag {
    display: block;
    padding: 2px 0 2px 12px;
    position: relative;
  }
  .ag-list .ag::before {
    content: "·";
    position: absolute;
    left: 0;
    color: var(--cm-purple);
    font-weight: 700;
  }

  /* Action rows (next steps) */
  .action-row {
    display: flex; gap: 14px; align-items: flex-start;
    padding: 14px 0; border-bottom: 0.5px solid var(--cm-divider);
    page-break-inside: avoid; break-inside: avoid;
  }
  .action-row:last-child { border-bottom: none; padding-bottom: 4px; }
  .action-row:first-child { padding-top: 4px; }
  .action-num {
    font-family: 'Lexend', sans-serif; font-size: 13px; font-weight: 700;
    color: var(--cm-purple); background: var(--cm-lavender);
    width: 26px; height: 26px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; margin-top: 1px;
  }
  .action-content {
    flex: 1;
    break-inside: avoid; page-break-inside: avoid;
  }
  .action-title {
    font-family: 'Lexend', sans-serif; font-size: 14px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 4px;
  }
  .action-body { font-size: 12px; color: var(--cm-body-grey); line-height: 1.6; }
  .action-body strong { color: var(--cm-charcoal); font-weight: 500; }

  .footer {
    margin-top: 16px; padding: 18px 24px; background: var(--cm-off-white);
    border: 1px solid var(--cm-light-grey-2); border-radius: 12px;
    text-align: center; font-size: 11px; color: var(--cm-body-grey); line-height: 1.6;
    page-break-inside: avoid; break-inside: avoid;
  }
  .footer strong { color: var(--cm-purple); font-weight: 600; }

  @media print {
    body { background: white; padding: 0; }
    .page { max-width: 100%; }
  }
</style>
</head>
<body>
<div class="page">

  <div class="header">
    {% if logo_b64 %}
      <img src="data:image/png;base64,{{ logo_b64 }}" alt="Clinic Mastery" class="header-logo">
    {% endif %}
    <div class="header-content">
      <div class="header-eyebrow">Clinic Growth Brief</div>
      <div class="header-title">{{ clinic_name }}</div>
      <div class="header-sub">{{ submitted_label }}</div>
      <div class="header-meta">Prepared by Clinic Mastery</div>
    </div>
  </div>

  <div class="stat-hero">
    <div class="stat-eyebrow">The growth picture</div>
    <div class="stat-headline">{{ hero.headline | safe }}</div>
    <div class="stat-body">{{ hero.body | safe }}</div>
  </div>

  <a href="#next-steps" class="cta-button">
    What we would do first<span class="cta-arrow">&rarr;</span>
  </a>

  <div class="section-group">
    <div class="section-label">The clinic at a glance</div>
    <div class="card">
      <div class="snapshot-grid">
        <div class="snap-row"><div class="snap-key">Specialty</div><div class="snap-val">{{ submission.primary_specialty or "-" }}</div></div>
        <div class="snap-row"><div class="snap-key">Location</div><div class="snap-val">{{ submission.suburb or "-" }}{% if submission.state %}, {{ submission.state }}{% endif %}</div></div>
        <div class="snap-row"><div class="snap-key">Practitioners</div><div class="snap-val">{{ submission.num_practitioners or "-" }}</div></div>
        <div class="snap-row"><div class="snap-key">Website</div><div class="snap-val">{{ submission.website_url or "-" }}</div></div>
        <div class="snap-row"><div class="snap-key">Email</div><div class="snap-val">{{ submission.email or "-" }}</div></div>
        <div class="snap-row"><div class="snap-key">Phone</div><div class="snap-val">{{ submission.phone or "-" }}</div></div>
      </div>
    </div>
  </div>

  <div class="section-group revenue-section">
    <div class="section-label">The revenue maths</div>
    <div class="grid-3 grid-keep-together">
      <a class="kpi-tile featured" href="#kw-targets">
        <div class="kpi-label">Patient LTV</div>
        <div class="kpi-num">{{ rev.ltv | money_round }}</div>
        <div class="kpi-sub">{{ rev.fee | money_round }} per visit · {{ "%.1f"|format(rev.visits) }} visits per patient.</div>
      </a>
      <a class="kpi-tile" href="#campaigns">
        <div class="kpi-label">New patients / month</div>
        <div class="kpi-num">{{ rev.new_pts }}</div>
        <div class="kpi-sub">Coming through the door from all sources.</div>
      </a>
      <a class="kpi-tile" href="#campaigns">
        <div class="kpi-label">Monthly new-patient revenue</div>
        <div class="kpi-num">{{ rev.monthly_rev | money_round }}</div>
        <div class="kpi-sub">LTV times new patients. The number every lever moves.</div>
      </a>
      <a class="kpi-tile" href="#kw-targets">
        <div class="kpi-label">Avg appointment fee</div>
        <div class="kpi-num">{{ rev.fee | money_round }}</div>
        <div class="kpi-sub">As reported on the intake form.</div>
      </a>
      <a class="kpi-tile" href="#kw-targets">
        <div class="kpi-label">Visits per patient</div>
        <div class="kpi-num">{{ "%.1f"|format(rev.visits) }}</div>
        <div class="kpi-sub">Average treatment journey length.</div>
      </a>
      <a class="kpi-tile" href="#campaigns">
        <div class="kpi-label">Current ad spend</div>
        <div class="kpi-num">{{ rev.ad_spend | money_round }}</div>
        <div class="kpi-sub">Monthly Google Ads spend at intake.</div>
      </a>
    </div>
  </div>

  <div class="section-group" id="kw-targets">
    <div class="section-label">Keyword targets · ranked by intent</div>
    {% for g in kw_groups %}
    <div class="insight-card {{ g.variant }}">
      <div class="insight-eyebrow">{{ g.label }}</div>
      <div class="insight-body">{{ g.note }}</div>
      <div class="kw-list">
        {% for kw in g.keywords[:8] %}
        <span class="kw-pill">{{ kw }}</span>
        {% endfor %}
      </div>
      <div class="kw-meta">Match type · <strong>{{ g.match }}</strong></div>
    </div>
    {% endfor %}
  </div>

  <div class="section-group" id="campaigns">
    <div class="section-label">Suggested campaign structure · first 90 days</div>
    <div class="card">
      <div class="card-title">Two campaigns, two intents, separated by design.</div>
      <div class="card-sub">A well-structured account lets Google optimise each intent independently. Below is how we would set the first 90 days.</div>
      {% for c in campaigns %}
      <table class="row-block">
        <tr>
          <td class="row-info">
            <div class="row-name">{{ c.name }}</div>
            <div class="row-meta">
              <strong>{{ c.type }}</strong> · {{ c.bidding }}
            </div>
            <div class="ag-list">
              {% for ag in c.ad_groups %}
              <span class="ag">{{ ag }}</span>
              {% endfor %}
            </div>
            <div class="row-meta" style="margin-top: 8px;">{{ c.note }}</div>
          </td>
          <td class="row-stat">
            <div class="row-stat-num">{{ c.budget }}</div>
            <div class="row-stat-label">Budget</div>
          </td>
        </tr>
      </table>
      {% endfor %}
    </div>
  </div>

  <div class="section-group" id="next-steps">
    <div class="section-label">What we would do first · in order</div>
    <div class="card card-flow">
      {% for a in next_steps %}
      <div class="action-row">
        <div class="action-num">{{ loop.index }}</div>
        <div class="action-content">
          <div class="action-title">{{ a.title }}</div>
          <div class="action-body">{{ a.body | safe }}</div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="book-cta">
    <div class="book-cta-headline">Want to walk through this together?</div>
    <p class="book-cta-body">Twenty minutes with Pete to walk through this growth brief, prioritise the channels that matter most for your clinic, and decide what to launch first.</p>
    <a class="book-cta-btn" href="https://bookings.clinicmastery.com/pete-flynn-google-ads">Book a 20-minute call</a>
  </div>

  <div class="footer">
    <strong>{{ clinic_name }} · Clinic Growth Brief · {{ submitted_label }}</strong><br>
    Confidential. Prepared by Clinic Mastery from intake form data alone.<br>
    No Google Ads account access was required to generate this brief.
  </div>

</div>
</body>
</html>
"""

assert "—" not in TEMPLATE_BRIEF_SRC, (
    "Em dash found in CM intake brief template. Brand voice rule: no em dashes."
)

_TEMPLATE_BRIEF = _jinja_env.from_string(TEMPLATE_BRIEF_SRC)


def generate_intake_brief(submission: dict) -> bytes:
    """Render the growth brief PDF for a clinic that submitted the intake
    form but does not run Google Ads.

    Same output contract as pdf_report.generate_intake_brief (PDF bytes).
    """
    s = submission or {}
    clinic_name = s.get("clinic_name") or "Your Clinic"
    submitted_label = "Received " + datetime.now(timezone.utc).strftime("%-d %B %Y")

    ctx = {
        "logo_b64": _LOGO_B64,
        "clinic_name": clinic_name,
        "submitted_label": submitted_label,
        "submission": s,
        "hero": _brief_hero(s),
        "rev": _brief_revenue_metrics(s),
        "kw_groups": _brief_keyword_groups(s),
        "campaigns": _brief_campaigns(s),
        "next_steps": _brief_next_steps(s),
    }

    html_text = _TEMPLATE_BRIEF.render(**ctx)
    pdf_bytes = HTML(string=html_text).write_pdf()
    log.info(
        "Generated v2 intake brief PDF: clinic=%s, %d bytes, %d kw groups, %d steps",
        clinic_name, len(pdf_bytes), len(ctx["kw_groups"]), len(ctx["next_steps"]),
    )
    return pdf_bytes


# ═══════════════════════════════════════════════════════════════════════════
# WEBSITE AUDIT (v2)
# ═══════════════════════════════════════════════════════════════════════════
#
# Generates the Clinic Mastery website audit PDF in the v2 brand design
# (HTML + WeasyPrint). Replaces the legacy ReportLab generator in
# pdf_report.py. Same input contract: a single audit_data dict with the
# keys documented in run_raisethebar_audit.py / run_website_audit.py.

# ── Status helpers ────────────────────────────────────────────────────────────

def _ws_status_text(status: str) -> str:
    return {"pass": "GOOD", "warn": "REVIEW", "fail": "FIX"}.get(status, "REVIEW")


def _ws_speed_status(d: dict) -> str:
    ttfb = d.get("ttfb_ms", 0) or 0
    js = d.get("js_files", 0) or 0
    css = d.get("css_files", 0) or 0
    fails = (ttfb >= 600) + (js > 20) + (css > 15)
    warns = (200 <= ttfb < 600) + (10 < js <= 20) + (8 < css <= 15) + (not d.get("has_lazy_load")) + (not d.get("has_webp"))
    if fails >= 1:
        return "fail"
    if warns >= 2:
        return "warn"
    return "pass"


def _ws_seo_status(d: dict) -> str:
    fails = sum([
        d.get("h1_count", 1) != 1,
        not d.get("og_image_ok", True),
        not d.get("schema_ok", True),
        d.get("images_missing_alt", 0) > 5,
        not d.get("has_ssl", True),
        not d.get("has_sitemap", True),
    ])
    warns = sum([
        d.get("homepage_word_count", 500) < 500,
        0 < d.get("images_missing_alt", 0) <= 5,
    ])
    if fails >= 2:
        return "fail"
    if fails == 1 or warns >= 2:
        return "warn"
    return "pass"


def _ws_ux_status(d: dict) -> str:
    fails = sum([
        bool(d.get("mobile_hero_overlap")),
        bool(d.get("cta_label_mismatch")),
        not d.get("social_proof_above_fold", True),
    ])
    warns = sum([
        (d.get("booking_steps", 0) or 0) >= 4,
        bool(d.get("no_pricing_on_service_pages")),
        bool(d.get("external_links_dilute")),
    ])
    if fails >= 2:
        return "fail"
    if fails == 1 or warns >= 2:
        return "warn"
    return "pass"


# Map status to insight-card variant class (defined in the v2 audit template:
# green = pass, amber = warn, rose/warn-red = fail).
_STATUS_VARIANT = {"pass": "green", "warn": "amber", "fail": "rose"}


# ── Audience + specialty helpers ──────────────────────────────────────────────

def _ws_audience(spec_lc: str) -> tuple[str, str]:
    """Returns (audience_term, action_term) for the hero/UX copy."""
    if "speech" in spec_lc or "paediatric" in spec_lc or "child" in spec_lc:
        return ("parents", "book an assessment for their child")
    if "psychol" in spec_lc or "counsel" in spec_lc:
        return ("clients", "book an appointment")
    return ("patients", "book an appointment")


def _ws_schema_type(spec_lc: str) -> str:
    if "psychol" in spec_lc or "counsel" in spec_lc:
        return "PsychologistService"
    if "physio" in spec_lc:
        return "MedicalBusiness (Physiotherapy)"
    if "speech" in spec_lc:
        return "MedicalBusiness (SpeechTherapist)"
    return "LocalBusiness or MedicalBusiness"


def _ws_locations(d: dict) -> tuple[list[str], str]:
    location = d.get("location", "") or ""
    locs = [l.strip() for l in location.replace("&", ",").split(",")
            if l.strip() and len(l.strip()) < 35]
    primary = locs[0] if locs else location
    return locs, primary


# ── Section builders ──────────────────────────────────────────────────────────

def _ws_hero(d: dict) -> dict:
    """Top-of-doc verdict, data-driven so the report opens with the right
    tone (mostly green vs needs attention). Mirrors the legacy intro
    paragraph but punchier."""
    speed = _ws_speed_status(d)
    seo = _ws_seo_status(d)
    ux = _ws_ux_status(d)
    spec = d.get("specialty", "") or ""
    spec_lc = spec.lower()
    audience, _ = _ws_audience(spec_lc)
    locs, primary = _ws_locations(d)
    fails = sum(s == "fail" for s in (speed, seo, ux))
    warns = sum(s == "warn" for s in (speed, seo, ux))

    speed_phrase = {
        "pass": "Site speed is in good shape",
        "warn": "Site speed has a couple of issues worth tightening",
        "fail": "Site speed is the biggest blocker",
    }[speed]
    seo_phrase = {
        "pass": "the SEO structure is solid",
        "warn": "the SEO structure needs a couple of fixes",
        "fail": "the SEO structure has critical gaps",
    }[seo]
    ux_phrase = {
        "pass": "the conversion flow is well laid out",
        "warn": "the conversion flow has friction worth removing",
        "fail": "the conversion flow is leaking visits at the booking step",
    }[ux]

    if fails >= 2:
        framing = "There are a handful of high-impact items to address before this site is pulling its weight on patient acquisition."
    elif fails == 1:
        framing = (
            "One area is dragging the rest down. Fix it and the existing "
            "strengths of the site start showing up in bookings."
        )
    elif warns >= 2:
        framing = (
            "The fundamentals are in place. The fixes below are the next layer "
            "of polish that will lift conversions without a redesign."
        )
    else:
        framing = "The fundamentals are strong. The fixes below are smaller, sharper levers to add on top."

    headline = (
        f"<strong>{speed_phrase}</strong>, and "
        f"<strong>{seo_phrase}</strong>. The story this audit tells is that "
        f"<strong>{ux_phrase}</strong>."
    )

    body = (
        f"This audit covers <strong>{d.get('website_url', 'the site')}</strong>"
        + (f" for {audience} searching '{spec_lc} {primary}'." if primary else f" for {audience}.")
        + " It scores three pillars (speed, SEO, conversion) and ends with a prioritised fix list. "
        + framing
    )

    return {
        "eyebrow": "THE VERDICT",
        "headline": headline,
        "body": body,
    }


def _ws_scorecard(d: dict) -> list[dict]:
    speed = _ws_speed_status(d)
    seo = _ws_seo_status(d)
    ux = _ws_ux_status(d)
    return [
        {"label": "Site Speed",     "status": speed, "text": _ws_status_text(speed)},
        {"label": "SEO Structure",  "status": seo,   "text": _ws_status_text(seo)},
        {"label": "UX & Conversion", "status": ux,    "text": _ws_status_text(ux)},
    ]


def _ws_speed_card(d: dict) -> dict:
    ttfb = d.get("ttfb_ms", 0) or 0
    load = d.get("full_load_ms", 0) or 0
    js = d.get("js_files", 0) or 0
    css = d.get("css_files", 0) or 0
    resources = d.get("total_resources", 0) or 0
    has_webp = d.get("has_webp", False)
    has_lazy = d.get("has_lazy_load", False)
    status = _ws_speed_status(d)

    bullets: list[str] = []
    if ttfb < 200:
        bullets.append(
            f"<strong>TTFB {ttfb}ms.</strong> Server response is well within Google's 200ms target."
        )
    elif ttfb < 600:
        bullets.append(
            f"<strong>TTFB {ttfb}ms.</strong> Slower than ideal. A caching plugin "
            "(WP Rocket, LiteSpeed Cache) usually brings this under 200ms without changing hosts."
        )
    else:
        bullets.append(
            f"<strong>TTFB {ttfb}ms.</strong> Critically slow. The host needs a caching layer "
            "or an upgrade before any other speed work matters."
        )

    if js > 20 or css > 15:
        bullets.append(
            f"<strong>{js} JavaScript files and {css} CSS stylesheets</strong> on every page. "
            "Healthy range is under 10 JS and 8 CSS. This is almost always WordPress plugin bloat. "
            "WP Rocket asset minification reduces these to 2-4 files each and cuts mobile load by 50-70%."
        )
    elif js > 10 or css > 8:
        bullets.append(
            f"<strong>{js} JavaScript files, {css} CSS stylesheets.</strong> A bit above ideal. "
            "Asset minification via the existing SEO plugin would tidy this up."
        )

    if not has_webp:
        bullets.append(
            "<strong>No WebP images detected.</strong> WebP is 25-35% smaller than PNG/JPG at the "
            "same visible quality. Smush or ShortPixel converts existing images automatically."
        )
    if not has_lazy:
        bullets.append(
            "<strong>Lazy loading is off.</strong> Images load on first page load whether they're "
            "visible or not. Adding loading='lazy' on below-the-fold images is a five-minute win."
        )

    if not bullets:
        bullets.append(
            "Speed fundamentals are clean. Keep the lazy loading and image format settings as they "
            "are; revisit when the next major theme/template update lands."
        )

    metrics = [
        {"v": f"{ttfb}ms", "l": "Time to first byte"},
        {"v": f"{load}ms", "l": "Full page load"},
        {"v": str(resources), "l": "Total resources"},
        {"v": str(js), "l": "JS files"},
        {"v": str(css), "l": "CSS sheets"},
        {"v": "Yes" if has_webp else "No", "l": "WebP"},
    ]

    return {
        "variant": _STATUS_VARIANT[status],
        "status_text": _ws_status_text(status),
        "title": (
            "Page speed is the lever that turns search rankings into bookings. "
            "Google uses Core Web Vitals as a direct mobile ranking signal."
        ),
        "bullets": bullets,
        "metrics": metrics,
    }


def _ws_seo_card(d: dict) -> dict:
    spec = d.get("specialty", "") or ""
    spec_lc = spec.lower()
    schema_type = _ws_schema_type(spec_lc)
    locs, primary = _ws_locations(d)
    is_multi = len(locs) > 1
    h1_count = d.get("h1_count", 1) or 0
    imgs_no_alt = d.get("images_missing_alt", 0) or 0
    total_imgs = d.get("total_images", 1) or 1
    word_count = d.get("homepage_word_count", 0) or 0
    pages_indexed = d.get("pages_indexed", 0) or 0
    h1_example = f"{spec} in {primary}" if primary else spec

    checks: list[dict] = []

    if h1_count == 1:
        checks.append({"label": "H1 tag", "status": "pass",
                       "detail": "Single H1 correctly set on the homepage."})
    else:
        checks.append({"label": "H1 tag", "status": "fail",
                       "detail": (
                           f"{h1_count} H1 headings on the homepage. Google uses the H1 as the "
                           f"primary topic signal per page; multiple H1s split that signal. Set one "
                           f"H1 per page targeting the main keyword (for example <em>{h1_example}</em>) "
                           "and demote everything else to H2 or H3. Practitioner names listed as H1 "
                           "on team pages are a common cause of this."
                       )})

    if d.get("og_image_ok"):
        checks.append({"label": "Open Graph image", "status": "pass",
                       "detail": "Real clinic image set for social sharing previews."})
    else:
        checks.append({"label": "Open Graph image", "status": "fail",
                       "detail": (
                           "Social sharing previews show an icon rather than a real clinic photo. "
                           "Replace with a 1200x630 photo of the clinic or team in the SEO plugin's "
                           "social settings. Five-minute fix."
                       )})

    if d.get("schema_ok"):
        checks.append({"label": "Schema markup", "status": "pass",
                       "detail": f"{schema_type} schema correctly configured."})
    else:
        checks.append({"label": "Schema markup", "status": "fail",
                       "detail": (
                           f"No valid schema markup is set. Google uses {schema_type} schema to "
                           "power rich results: star ratings, opening hours, address and phone "
                           "in search listings. Configure via the SEO plugin (Rank Math or Yoast). "
                           f"{'One entry per location.' if is_multi else 'Single entry with full address, hours, phone.'} "
                           "30 to 45 minutes; no design change needed."
                       )})

    if imgs_no_alt == 0:
        checks.append({"label": "Image alt text", "status": "pass",
                       "detail": "All images carry alt text."})
    elif imgs_no_alt > 5:
        checks.append({"label": "Image alt text", "status": "fail",
                       "detail": (
                           f"{imgs_no_alt} of {total_imgs} images have no alt text. Alt text feeds "
                           "image search and screen readers. Add descriptive alt text to every "
                           "clinic, team, and service image in the media library."
                       )})
    else:
        checks.append({"label": "Image alt text", "status": "warn",
                       "detail": f"{imgs_no_alt} of {total_imgs} images missing alt text. Quick fix from the WordPress media library."})

    if word_count >= 500:
        checks.append({"label": "Homepage depth", "status": "pass",
                       "detail": f"{word_count} words of homepage content. Strong depth for SEO."})
    else:
        checks.append({"label": "Homepage depth", "status": "warn",
                       "detail": (
                           f"Approximately {word_count} words on the homepage. Competitive {spec_lc} "
                           "keywords typically rank pages with 600-1,000 words. Adding service summaries, "
                           "an FAQ, and location details strengthens keyword coverage with no design change."
                       )})

    if d.get("has_ssl", True):
        checks.append({"label": "SSL (HTTPS)", "status": "pass",
                       "detail": "Site is served over HTTPS."})
    else:
        checks.append({"label": "SSL (HTTPS)", "status": "fail",
                       "detail": "No HTTPS. Critical security and ranking issue. Contact the host today."})

    if d.get("has_sitemap", True):
        checks.append({"label": "XML sitemap", "status": "pass",
                       "detail": (
                           f"Sitemap covers {pages_indexed} pages. Keep service and location pages updated."
                           if pages_indexed else "Sitemap is in place."
                       )})
    else:
        checks.append({"label": "XML sitemap", "status": "fail",
                       "detail": (
                           "No sitemap detected. Most WordPress SEO plugins (Rank Math, Yoast) generate one "
                           "automatically. Submit via Google Search Console once enabled."
                       )})

    if is_multi:
        checks.append({"label": "Suburb landing pages", "status": "warn",
                       "detail": (
                           f"With clinics across {d.get('location', '')} there is a strong opportunity "
                           "to rank for suburb-level searches. Each location page needs 400+ words of "
                           "local content, the address, a team photo, directions and a booking CTA."
                       )})

    fails = sum(c["status"] == "fail" for c in checks)
    warns = sum(c["status"] == "warn" for c in checks)
    if fails >= 2:
        variant = "rose"
    elif fails == 1 or warns >= 2:
        variant = "amber"
    else:
        variant = "green"

    title = (
        f"SEO structure determines whether visitors searching '{spec_lc} {primary}' "
        f"find this clinic or a competitor. Each item below directly affects ranking."
        if primary else
        "SEO structure determines whether visitors searching for this specialty find this clinic or a competitor."
    )

    return {
        "variant": variant,
        "title": title,
        "checks": checks,
    }


def _ws_ux_card(d: dict) -> dict:
    spec = d.get("specialty", "") or ""
    audience, action = _ws_audience(spec.lower())
    issues: list[dict] = []

    if d.get("mobile_hero_overlap"):
        issues.append({
            "severity": "HIGH",
            "title": "Mobile hero needs a clean breakpoint",
            "detail": (
                f"On mobile viewports (390px wide, the most common screen size for local health "
                f"searches) the hero has layout issues that look unpolished. This is the first thing "
                f"a {audience} sees on a phone. A CSS breakpoint below 480px that stacks the hero "
                "elements cleanly resolves it."
            ),
        })
    if d.get("cta_label_mismatch"):
        issues.append({
            "severity": "HIGH",
            "title": "CTA label does not match what the button delivers",
            "detail": (
                f"The primary call-to-action says <em>Book Now</em> but leads to an enquiry or "
                f"waitlist form, not a booking. A {audience} clicking <em>Book Now</em> expecting "
                "to secure an appointment may not follow through when they hit a callback form. "
                "Either set up direct online booking, or rename the button to match the actual step "
                "(<em>Submit an Enquiry</em>, <em>Join the Waitlist</em>, or <em>Request a Callback</em>)."
            ),
        })
    booking_steps = d.get("booking_steps", 0) or 0
    if booking_steps >= 4:
        issues.append({
            "severity": "MEDIUM",
            "title": f"Booking flow is {booking_steps} steps",
            "detail": (
                f"{audience.capitalize()} on mobile, often mid-commute or mid-school-run, may "
                f"abandon a long form before completing it. Test a 2 or 3 step version capturing "
                "name, phone and preferred time first; collect clinical detail on a follow-up call."
            ),
        })
    if not d.get("social_proof_above_fold", True):
        issues.append({
            "severity": "HIGH",
            "title": "No trust signals above the fold",
            "detail": (
                "The hero shows the clinic name and headline, but no professional credibility signals "
                "appear without scrolling. Add a credential bar below the hero: professional body logo, "
                "NDIS registration if applicable, years established and Google review count. "
                "AHPRA-compliant: patient testimonials are restricted, but professional logos, "
                "credentials and years established are fully permitted."
            ),
        })
    if d.get("external_links_dilute"):
        issues.append({
            "severity": "MEDIUM",
            "title": "External links dilute the conversion funnel",
            "detail": (
                f"Several pages link to external resources before the {audience} has booked. "
                "Move these to a dedicated <em>Resources</em> page; keep service and location pages "
                "focused on the booking CTA."
            ),
        })
    if d.get("no_pricing_on_service_pages"):
        issues.append({
            "severity": "MEDIUM",
            "title": "Pricing not visible on service pages",
            "detail": (
                f"Service pages carry no pricing or fees link. A {audience} researching "
                "affordability has to navigate to a separate fees page. A <em>From $X per session, "
                "see full fees</em> callout on each service page removes the barrier."
            ),
        })

    if not issues:
        issues.append({
            "severity": "LOW",
            "title": "UX fundamentals are in good shape",
            "detail": (
                "No critical UX issues stood out. The site presents clearly and the conversion "
                "flow is logical. Continue monitoring via Google Analytics and Search Console."
            ),
        })

    fails = sum(i["severity"] == "HIGH" for i in issues)
    warns = sum(i["severity"] == "MEDIUM" for i in issues)
    if fails >= 2:
        variant = "rose"
    elif fails == 1 or warns >= 2:
        variant = "amber"
    else:
        variant = "green"

    return {
        "variant": variant,
        "title": (
            f"The job of this site is to reduce hesitation, build trust quickly, and get the "
            f"{audience} to one action: {action}. Every friction point below is a reason a "
            "visitor might click away instead."
        ),
        "issues": issues,
    }


def _ws_content_card(d: dict) -> dict:
    spec = d.get("specialty", "") or ""
    spec_lc = spec.lower()
    blog_posts = d.get("blog_posts", 0) or 0
    has_blog = bool(d.get("has_blog"))
    locs, primary = _ws_locations(d)
    is_multi = len(locs) > 1

    if "psychol" in spec_lc or "counsel" in spec_lc:
        topics = "what to expect from your first session, anxiety vs depression, ADHD assessment for adults"
        ndis_label = f"NDIS Psychology page targeting NDIS psychologist {primary or '[suburb]'}"
    elif "speech" in spec_lc:
        topics = "when should my child see a speech pathologist, speech delay vs disorder, NDIS speech therapy"
        ndis_label = "NDIS Speech Pathology page"
    elif "physio" in spec_lc:
        topics = "how long does physio take, physio vs GP, sports injury recovery, does Medicare cover physio"
        ndis_label = "NDIS Physiotherapy page"
    else:
        topics = (
            f"what to expect at your first {spec_lc} appointment, does Medicare cover {spec_lc}, "
            f"how to find a {spec_lc} near me"
        )
        ndis_label = f"NDIS {spec} page"

    if not has_blog or blog_posts == 0:
        blog_now = "No blog detected on the site."
        blog_next = f"Start with one post per month targeting questions clients actually search: {topics}."
    elif blog_posts < 10:
        blog_now = f"{blog_posts} posts published."
        blog_next = f"Aim for one post per month. High-value topics: {topics}."
    else:
        blog_now = f"{blog_posts} posts published; strong content library."
        blog_next = (
            "Maintain at least one post per month. Prioritise suburb-specific and condition-specific "
            "content. Update older posts annually to keep them ranking."
        )

    if is_multi:
        loc_now = f"Operates across {d.get('location', '')}."
        loc_next = (
            f"Each location page needs 400+ words of local content: suburb context, team photo, "
            f"nearby areas served, directions and a booking CTA. Target '{spec_lc} [suburb]' as the H1."
        )
    else:
        loc_now = f"Single location in {primary or 'one suburb'}."
        loc_next = (
            f"Suburb-radius content: blog posts targeting '{spec_lc} near [adjacent suburb]' extend "
            "reach without new premises."
        )

    rows = [
        {"area": "Blog / Articles", "now": blog_now, "next": blog_next},
        {"area": "FAQ content", "now": "Check whether common pre-booking questions are answered on service pages or a dedicated FAQ.",
         "next": "A 15-20 question FAQ targeting questions clients Google ranks in featured snippets and reduces pre-booking uncertainty."},
        {"area": "NDIS content", "now": "NDIS mentioned across the site.",
         "next": (
            f"A dedicated {ndis_label} attracts plan managers, support coordinators, and self-managed "
            "NDIS participants. High-intent referrers."
         )},
        {"area": "Location pages", "now": loc_now, "next": loc_next},
        {"area": "Service depth", "now": "Service pages describe core offerings.",
         "next": (
            "Expand each service page to 400+ words with a 'what to expect' section, who it helps, "
            "and a clear booking CTA. Lifts both rankings and pre-booking confidence."
         )},
        {"area": "Team profiles", "now": "About page lists team credentials.",
         "next": (
            "Short practitioner profiles with photo, credentials, and specialty areas build trust. "
            "A short video introduction from one or two practitioners increases time-on-page noticeably."
         )},
    ]
    return {
        "variant": "blue",
        "title": (
            f"Content is how Google decides which clinic is the authority on {spec_lc} in a given "
            "suburb. The more relevant, helpful content on the site, the more often it appears."
        ),
        "rows": rows,
    }


def _ws_priority_counts(priorities: list[dict]) -> list[dict]:
    """At-a-glance count of each priority level for the section header."""
    levels = ["CRITICAL", "HIGH", "MEDIUM", "QUICK WIN"]
    counts = {lvl: sum(1 for p in priorities if p.get("level") == lvl) for lvl in levels}
    return [
        {"label": lvl, "count": counts[lvl], "class": lvl.replace(" ", "_")}
        for lvl in levels if counts[lvl] > 0
    ]


def _ws_capture_screenshots(url: str, audit_data: dict) -> list[dict]:
    """Capture homepage desktop, homepage mobile, and a contact/booking page if
    auto-discoverable. Returns a list of {b64, caption, viewport} dicts.

    Silent-fail by design. If Playwright is not installed, the site is
    unreachable, or any single shot fails, we log and skip rather than block
    the audit. Captions are data-driven from audit_data so they comment
    specifically on findings already in the report.
    """
    if not url:
        return []
    try:
        from playwright.sync_api import sync_playwright
        from PIL import Image
        import base64, io
    except Exception as exc:
        log.warning("Website audit screenshots skipped: %s", exc)
        return []

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    def _to_jpeg_b64(png_bytes: bytes, target_w: int) -> str:
        img = Image.open(io.BytesIO(png_bytes))
        if img.width > target_w:
            scale = target_w / img.width
            img = img.resize((target_w, int(img.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=82, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    shots: list[dict] = []

    # Caption helpers driven by audit findings.
    cta_mismatch = bool(audit_data.get("cta_label_mismatch"))
    no_social    = not audit_data.get("social_proof_above_fold", True)
    booking_steps = audit_data.get("booking_steps", 0) or 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                # ── Desktop homepage ────────────────────────────────────────
                desk_ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                desk_page = desk_ctx.new_page()
                try:
                    desk_page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    desk_page.wait_for_timeout(1500)
                    png = desk_page.screenshot(full_page=False)
                    desk_caption_parts = []
                    if cta_mismatch:
                        desk_caption_parts.append(
                            "The primary CTA visible above the fold says <em>Book Now</em> "
                            "but the click leads to an enquiry or waitlist form, not a booking."
                        )
                    if no_social:
                        desk_caption_parts.append(
                            "No professional credentials or trust signals are visible without scrolling."
                        )
                    desk_caption = (
                        " ".join(desk_caption_parts)
                        if desk_caption_parts
                        else "Desktop homepage above the fold at 1,440 pixels."
                    )
                    shots.append({
                        "b64": _to_jpeg_b64(png, 760),
                        "caption": desk_caption,
                        "viewport": "DESKTOP · 1440 × 900",
                    })
                except Exception as exc:
                    log.warning("Desktop screenshot failed: %s", exc)
                desk_ctx.close()

                # ── Mobile homepage ─────────────────────────────────────────
                mob_ctx = browser.new_context(
                    viewport={"width": 390, "height": 844},
                    device_scale_factor=2,
                    is_mobile=True,
                    has_touch=True,
                )
                mob_page = mob_ctx.new_page()
                try:
                    mob_page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    mob_page.wait_for_timeout(1500)
                    body_w = mob_page.evaluate("() => document.body.scrollWidth")
                    has_hscroll = body_w > 390
                    png = mob_page.screenshot(full_page=False)
                    if has_hscroll:
                        mob_caption = (
                            f"Mobile homepage on a 390 pixel viewport. The page renders at "
                            f"{body_w} pixels wide, producing horizontal scroll. The site is "
                            "not responsive, which is the single largest conversion blocker on "
                            "any phone-driven traffic."
                        )
                    elif audit_data.get("mobile_hero_overlap"):
                        mob_caption = (
                            "Mobile homepage at 390 pixels. The hero has layout issues that "
                            "break the first impression on the most common screen size for "
                            "local clinic searches."
                        )
                    else:
                        mob_caption = "Mobile homepage above the fold at a 390 pixel viewport."
                    shots.append({
                        "b64": _to_jpeg_b64(png, 760),
                        "caption": mob_caption,
                        "viewport": "MOBILE · 390 × 844",
                    })
                except Exception as exc:
                    log.warning("Mobile screenshot failed: %s", exc)
                mob_ctx.close()

                # ── Contact / booking page (auto-discover) ──────────────────
                base = url.rstrip("/")
                for path in ("/contact", "/contact-us", "/book", "/booking", "/book-online", "/appointments", "/make-a-booking"):
                    try:
                        cctx = browser.new_context(viewport={"width": 1440, "height": 900})
                        cpage = cctx.new_page()
                        resp = cpage.goto(base + path, wait_until="domcontentloaded", timeout=10000)
                        if resp and 200 <= resp.status < 400:
                            cpage.wait_for_timeout(1000)
                            png = cpage.screenshot(full_page=False)
                            booking_caption_parts = []
                            if cta_mismatch:
                                booking_caption_parts.append(
                                    "The path most ad clicks take. The booking flow on this page "
                                    "leads to a callback form rather than direct online scheduling."
                                )
                            if booking_steps >= 4:
                                booking_caption_parts.append(
                                    f"The current process is {booking_steps} steps before any "
                                    "confirmation, which adds drop-off on mobile."
                                )
                            booking_caption = (
                                " ".join(booking_caption_parts)
                                if booking_caption_parts
                                else f"Contact page ({path}). The path most ad clicks take after the homepage."
                            )
                            shots.append({
                                "b64": _to_jpeg_b64(png, 760),
                                "caption": booking_caption,
                                "viewport": f"DESKTOP · {path}",
                            })
                            cctx.close()
                            break
                        cctx.close()
                    except Exception:
                        try: cctx.close()
                        except Exception: pass
                        continue
            finally:
                browser.close()
    except Exception as exc:
        log.warning("Website audit screenshot capture aborted: %s", exc)
        return shots  # return whatever we got before the failure

    log.info("Captured %d website screenshots for %s", len(shots), url)
    return shots


def _ws_priorities(d: dict) -> list[dict]:
    spec = d.get("specialty", "") or ""
    spec_lc = spec.lower()
    locs, primary = _ws_locations(d)
    is_multi = len(locs) > 1
    schema_type = _ws_schema_type(spec_lc)
    h1_example = f"{spec} in {primary}" if primary else spec
    h1_count = d.get("h1_count", 1) or 0
    imgs_no_alt = d.get("images_missing_alt", 0) or 0
    total_imgs = d.get("total_images", 1) or 1
    word_count = d.get("homepage_word_count", 500) or 500
    js = d.get("js_files", 0) or 0
    css = d.get("css_files", 0) or 0

    out: list[dict] = []

    # ── CRITICAL ──
    if h1_count != 1:
        out.append({
            "level": "CRITICAL",
            "title": "Fix duplicate H1 tags across the site",
            "body": (
                f"There are {h1_count} H1 headings on the homepage, and other pages may carry "
                "additional H1s on every practitioner name. Google uses the H1 as the primary topic "
                f"signal per page. Set one H1 per page targeting the main keyword, for example "
                f"<em>{h1_example}</em>. All practitioner names and sub-headings should be H2 or H3."
            ),
        })
    if not d.get("schema_ok"):
        out.append({
            "level": "CRITICAL",
            "title": "Add LocalBusiness schema markup to every page",
            "body": (
                f"No valid structured data is set. Google uses {schema_type} schema to power "
                "rich results: star ratings, opening hours, address and phone in search listings. "
                "Configure via the SEO plugin (Rank Math or Yoast) in 30 to 45 minutes. No design change."
            ),
        })
    if not d.get("og_image_ok"):
        out.append({
            "level": "CRITICAL",
            "title": "Replace the Open Graph image with a real clinic photo",
            "body": (
                "Every share on Facebook, WhatsApp or LinkedIn shows a small icon rather than a real "
                "clinic image. This undermines credibility at the moment of referral. Upload a "
                "1200x630 clinic or team photo to the SEO plugin's social settings."
            ),
        })
    if imgs_no_alt > 0:
        pct = round(imgs_no_alt / total_imgs * 100)
        out.append({
            "level": "CRITICAL",
            "title": f"Add alt text to {imgs_no_alt} images ({pct}% of total)",
            "body": (
                f"{imgs_no_alt} of {total_imgs} images carry no alt text. This blocks screen readers "
                "and stops Google understanding the images. Add descriptive alt text in the WordPress "
                "media library. Around 30 minutes of work."
            ),
        })
    if d.get("cta_label_mismatch"):
        out.append({
            "level": "CRITICAL",
            "title": "Fix the CTA: 'Book Now' must deliver what it promises",
            "body": (
                "The primary CTA says <em>Book Now</em> but leads to an enquiry or waitlist form. "
                "This creates a trust gap at the highest-intent moment. Either set up direct online "
                "booking, or rename the CTA to describe the actual next step (<em>Submit an "
                "Enquiry</em>, <em>Join the Waitlist</em>, <em>Request a Callback</em>)."
            ),
        })

    # ── HIGH ──
    if js > 20 or css > 15:
        out.append({
            "level": "HIGH",
            "title": "Reduce JavaScript and CSS file bloat",
            "body": (
                f"The site loads {js} JavaScript files and {css} CSS stylesheets on every page. "
                "Healthy range is under 10 JS and 8 CSS. WP Rocket (~$59/yr) with asset minification "
                "and bundling reduces these to 2-4 files each, cutting load time by 50-70% and "
                "directly improving the mobile experience."
            ),
        })
    if d.get("mobile_hero_overlap"):
        out.append({
            "level": "HIGH",
            "title": "Fix the mobile hero layout",
            "body": (
                "On mobile viewports the homepage hero has layout issues. Most local clinic searches "
                "happen on a phone, so this is the first impression for the majority of visitors. "
                "A CSS fix at the 480px breakpoint resolves it. Test on iPhone and a mid-range Android "
                "before publishing."
            ),
        })
    if not d.get("social_proof_above_fold", True):
        out.append({
            "level": "HIGH",
            "title": "Add trust signals above the fold",
            "body": (
                "No professional credentials are visible without scrolling. Add a credential bar "
                "below the hero: professional body logo, NDIS registration if applicable, years "
                "established, Google review count. All AHPRA-compliant; no patient testimonials needed."
            ),
        })
    if not d.get("has_lazy_load"):
        out.append({
            "level": "HIGH",
            "title": "Enable lazy loading on images",
            "body": (
                "Images load on first page load whether or not the visitor has scrolled to them. "
                "Adding loading='lazy' to below-the-fold images cuts initial page weight and "
                "improves mobile load. Enable via WP Rocket or set the attribute in the theme."
            ),
        })

    # ── MEDIUM ──
    if d.get("no_pricing_on_service_pages"):
        out.append({
            "level": "MEDIUM",
            "title": "Add pricing visibility on service pages",
            "body": (
                "Service pages carry no pricing or link to a fees page. Someone researching "
                "affordability has to find the fees page independently. A <em>From $X per session, "
                "see full fees</em> callout with a link removes the barrier on every service page."
            ),
        })
    if is_multi:
        loc_list = " and ".join(locs[:2]) if len(locs) >= 2 else primary
        out.append({
            "level": "MEDIUM",
            "title": f"Optimise location landing pages for {loc_list}",
            "body": (
                f"Location pages exist but should be expanded with local content: 400+ words per "
                f"page, suburb-specific intro, team members at that location, nearby areas served, "
                f"directions and a booking CTA. Each page should target '{spec_lc} [suburb]' as its H1."
            ),
        })
    if word_count < 500:
        out.append({
            "level": "MEDIUM",
            "title": "Expand homepage content depth",
            "body": (
                f"The homepage is under 500 words. For competitive {spec_lc} keywords, Google "
                "typically ranks pages with 600 to 1,000 words above thin pages. Adding service "
                "summaries, location details and an FAQ strengthens keyword coverage with no "
                "design change."
            ),
        })

    # ── QUICK WINS ──
    if not d.get("has_sitemap", True):
        out.append({
            "level": "QUICK WIN",
            "title": "Create and submit an XML sitemap",
            "body": (
                "No sitemap detected. Enable the sitemap feature in Rank Math or Yoast SEO (both free). "
                "Submit the sitemap URL in Google Search Console. 15 minute fix."
            ),
        })
    if not d.get("has_webp"):
        out.append({
            "level": "QUICK WIN",
            "title": "Convert images to WebP format",
            "body": (
                "No WebP images detected. WebP is 25-35% smaller than PNG/JPG at equivalent quality. "
                "Smush or ShortPixel converts images automatically on upload. Enable in the plugin "
                "dashboard."
            ),
        })
    out.append({
        "level": "QUICK WIN",
        "title": "Add a Google review count near the hero CTA",
        "body": (
            "A single line showing the Google rating and review count near the booking button "
            "(<em>4.9 stars, 120+ Google Reviews</em>) lifts click-through by reducing uncertainty "
            "at the decision moment. AHPRA-compliant: it references a third-party platform."
        ),
    })

    return out


# ── Template ──────────────────────────────────────────────────────────────────

TEMPLATE_WS_SRC = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{{ clinic_name }} · Website Audit · {{ audit_date }}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Lexend:wght@400;500;700&family=Work+Sans:wght@400;500;700&display=swap');

  :root {
    --cm-purple:       #2E0A78;
    --cm-yellow:       #F0D140;
    --cm-charcoal:     #2A2B2B;
    --cm-off-white:    #FEFEFE;
    --cm-body-grey:    #6E6E6E;
    --cm-orange:       #FF8E21;
    --cm-blue:         #24A3FF;
    --cm-magenta:      #A1129E;
    --cm-warm-red:     #FF7777;
    --cm-coral-red:    #FF707D;
    --cm-silver-grey:  #ABB1BA;
    --cm-light-grey-1: #F5F5F7;
    --cm-light-grey-2: #E3E5E8;
    --cm-light-grey-3: #F9F9F9;
    --cm-divider:      #EDEDED;
    --cm-lavender:     #E2D4FF;
    --cm-rose-bg:      #FFE3E6;
    --cm-green:        #2E8B4A;
    --cm-green-bg:     #E5F4EA;
    --cm-amber-bg:     #FFE6CC;
    --cm-blue-bg:      #DEF1FF;
  }

  @page { size: A4; margin: 14mm 14mm; }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Work Sans', -apple-system, sans-serif;
    background: var(--cm-light-grey-1);
    color: var(--cm-charcoal);
    padding: 40px 24px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .page { max-width: 760px; margin: 0 auto; }
  .page > * + * { margin-top: 12px; }

  /* HEADER */
  .header {
    background: var(--cm-purple); border-radius: 14px;
    padding: 28px 32px; color: var(--cm-off-white);
    position: relative; overflow: hidden;
    display: flex; align-items: center; gap: 26px;
  }
  .header::after {
    content: ""; position: absolute; top: -40px; right: -40px;
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(240, 209, 64, 0.18) 0%, rgba(240, 209, 64, 0) 70%);
    pointer-events: none;
  }
  .header-logo { height: 68px; width: auto; flex-shrink: 0; position: relative; z-index: 1; }
  .header-content { flex: 1; min-width: 0; position: relative; z-index: 1; }
  .header-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--cm-yellow); margin-bottom: 10px;
  }
  .header-title {
    font-family: 'Lexend', sans-serif; font-size: 26px; font-weight: 500;
    color: var(--cm-off-white); margin-bottom: 6px; letter-spacing: -0.01em; line-height: 1.2;
  }
  .header-sub { font-size: 14px; color: var(--cm-lavender); }
  .header-meta {
    font-size: 11px; color: var(--cm-yellow); margin-top: 14px;
    letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700;
  }

  /* SECTION LABEL */
  .section-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--cm-orange);
    margin-bottom: 4px; margin-top: 6px;
    break-after: avoid; page-break-after: avoid;
  }

  /* HERO */
  .stat-hero { background: var(--cm-lavender); border-radius: 12px; padding: 24px 28px; }
  .stat-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--cm-magenta); margin-bottom: 10px;
  }
  .stat-headline {
    font-family: 'Lexend', sans-serif; font-size: 19px; font-weight: 500;
    color: var(--cm-purple); margin-bottom: 12px; line-height: 1.4; letter-spacing: -0.01em;
  }
  .stat-body { font-size: 13px; color: var(--cm-charcoal); line-height: 1.65; }
  .stat-body strong, .stat-headline strong { color: var(--cm-purple); font-weight: 600; }

  /* SCORECARD KPI GRID */
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  .score-tile {
    background: var(--cm-off-white);
    border: 1px solid var(--cm-light-grey-2);
    border-radius: 12px;
    padding: 22px 18px 18px;
    text-align: center;
  }
  .score-tile.pass { border-color: var(--cm-green); background: var(--cm-green-bg); }
  .score-tile.warn { border-color: var(--cm-orange); background: var(--cm-amber-bg); }
  .score-tile.fail { border-color: var(--cm-coral-red); background: var(--cm-rose-bg); }
  .score-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--cm-charcoal); margin-bottom: 12px;
  }
  .score-tag {
    display: inline-block;
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 18px;
    letter-spacing: 0.04em;
    padding: 6px 14px; border-radius: 999px;
  }
  .score-tile.pass .score-tag { color: var(--cm-off-white); background: var(--cm-green); }
  .score-tile.warn .score-tag { color: var(--cm-off-white); background: var(--cm-orange); }
  .score-tile.fail .score-tag { color: var(--cm-off-white); background: var(--cm-coral-red); }

  /* INSIGHT CARDS */
  .insight {
    border-radius: 12px;
    padding: 20px 22px;
    border-left: 4px solid;
  }
  .insight.green { background: var(--cm-green-bg); border-color: var(--cm-green); }
  .insight.amber { background: var(--cm-amber-bg); border-color: var(--cm-orange); }
  .insight.rose  { background: var(--cm-rose-bg); border-color: var(--cm-coral-red); }
  .insight.blue  { background: var(--cm-blue-bg); border-color: var(--cm-blue); }
  .insight h3 {
    font-family: 'Lexend', sans-serif; font-size: 14.5px; font-weight: 500;
    margin-bottom: 8px; line-height: 1.4;
  }
  .insight.green h3 { color: var(--cm-green); }
  .insight.amber h3 { color: var(--cm-orange); }
  .insight.rose  h3 { color: var(--cm-coral-red); }
  .insight.blue  h3 { color: var(--cm-blue); }
  .insight p { font-size: 13px; color: var(--cm-charcoal); line-height: 1.6; }
  .insight p + p { margin-top: 8px; }
  .insight ul { margin-top: 8px; padding-left: 18px; }
  .insight li { font-size: 13px; color: var(--cm-charcoal); line-height: 1.6; margin-bottom: 5px; }
  .insight strong { font-weight: 600; }
  .insight em { font-style: italic; color: var(--cm-purple); }

  /* SPEED METRIC GRID INSIDE INSIGHT */
  .metric-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
    margin-top: 12px;
  }
  .metric-cell {
    background: var(--cm-off-white);
    border: 1px solid var(--cm-light-grey-2);
    border-radius: 8px;
    padding: 10px 8px;
    text-align: center;
  }
  .metric-v {
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 15px;
    color: var(--cm-purple); line-height: 1.1; margin-bottom: 4px;
  }
  .metric-l {
    font-size: 9.5px; color: var(--cm-body-grey);
    text-transform: uppercase; letter-spacing: 0.08em; line-height: 1.3;
  }

  /* CHECKLIST INSIDE INSIGHT */
  .check-list { margin-top: 10px; }
  .check-row {
    display: grid; grid-template-columns: 1fr auto;
    gap: 12px; padding: 10px 0;
    border-bottom: 1px solid rgba(0,0,0,0.07);
  }
  .check-row:last-child { border-bottom: none; }
  .check-row .ck-detail { font-size: 12.5px; color: var(--cm-charcoal); line-height: 1.55; }
  .check-row .ck-detail strong { font-weight: 600; color: var(--cm-purple); }
  .check-row .ck-detail .ck-label {
    display: block;
    font-family: 'Lexend', sans-serif; font-weight: 500; font-size: 13px;
    color: var(--cm-charcoal); margin-bottom: 2px;
  }
  .ck-pill {
    align-self: start;
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 9.5px;
    letter-spacing: 0.1em; text-transform: uppercase;
    padding: 4px 10px; border-radius: 999px; white-space: nowrap;
  }
  .ck-pill.pass { background: var(--cm-green); color: var(--cm-off-white); }
  .ck-pill.warn { background: var(--cm-orange); color: var(--cm-off-white); }
  .ck-pill.fail { background: var(--cm-coral-red); color: var(--cm-off-white); }

  /* UX ISSUE ROWS */
  .issue-row {
    display: grid; grid-template-columns: 1fr auto;
    gap: 12px; padding: 12px 0;
    border-bottom: 1px solid rgba(0,0,0,0.07);
  }
  .issue-row:last-child { border-bottom: none; }
  .issue-row .iss-title {
    font-family: 'Lexend', sans-serif; font-weight: 500; font-size: 13.5px;
    color: var(--cm-charcoal); margin-bottom: 4px; line-height: 1.35;
  }
  .issue-row .iss-detail { font-size: 12.5px; color: var(--cm-charcoal); line-height: 1.55; }
  .iss-pill {
    align-self: start;
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 9.5px;
    letter-spacing: 0.1em; text-transform: uppercase;
    padding: 4px 10px; border-radius: 999px; white-space: nowrap;
  }
  .iss-pill.HIGH   { background: var(--cm-coral-red); color: var(--cm-off-white); }
  .iss-pill.MEDIUM { background: var(--cm-orange);    color: var(--cm-off-white); }
  .iss-pill.LOW    { background: var(--cm-green);     color: var(--cm-off-white); }

  /* CONTENT TABLE */
  .content-table {
    width: 100%; border-collapse: collapse; margin-top: 10px;
    font-size: 12.5px; color: var(--cm-charcoal);
  }
  .content-table th {
    background: var(--cm-purple); color: var(--cm-off-white);
    font-family: 'Lexend', sans-serif; font-weight: 500; font-size: 11px;
    letter-spacing: 0.06em; text-transform: uppercase;
    padding: 10px 12px; text-align: left;
  }
  .content-table td {
    padding: 10px 12px; vertical-align: top; line-height: 1.55;
    border-bottom: 1px solid rgba(0,0,0,0.07);
  }
  .content-table .area { font-weight: 600; color: var(--cm-purple); width: 22%; }
  .content-table .now { width: 36%; }

  /* ACTION ROW */
  .action-row {
    display: flex; gap: 16px;
    background: var(--cm-off-white);
    border: 1px solid var(--cm-light-grey-2);
    border-radius: 12px;
    padding: 16px 20px;
    align-items: flex-start;
    break-inside: avoid; page-break-inside: avoid;
  }
  .action-num {
    background: var(--cm-purple); color: var(--cm-yellow);
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 17px;
    width: 36px; height: 36px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .action-content { flex: 1; break-inside: avoid; page-break-inside: avoid; }
  .action-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; flex-wrap: wrap; }
  .action-title {
    font-family: 'Lexend', sans-serif; font-size: 14px; font-weight: 500;
    color: var(--cm-purple); line-height: 1.3;
  }
  .pri-pill {
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 9px;
    letter-spacing: 0.1em; text-transform: uppercase;
    padding: 3px 9px; border-radius: 999px;
  }
  .pri-pill.CRITICAL  { background: var(--cm-coral-red); color: var(--cm-off-white); }
  .pri-pill.HIGH      { background: var(--cm-orange);    color: var(--cm-off-white); }
  .pri-pill.MEDIUM    { background: var(--cm-lavender);  color: var(--cm-purple); }
  .pri-pill.QUICK_WIN { background: var(--cm-green);     color: var(--cm-off-white); }
  .action-body { font-size: 12.5px; color: var(--cm-charcoal); line-height: 1.6; }
  .action-body strong { color: var(--cm-purple); font-weight: 600; }
  .action-body em { font-style: italic; color: var(--cm-purple); }

  /* PRIORITY-COUNT BADGES (above the priority list) */
  .pri-counts {
    display: flex; flex-wrap: wrap; gap: 6px;
    margin-top: 4px; margin-bottom: 4px;
  }
  .count-pill {
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 9.5px;
    letter-spacing: 0.1em; text-transform: uppercase;
    padding: 4px 10px; border-radius: 999px;
  }
  .count-pill.CRITICAL  { background: var(--cm-coral-red); color: var(--cm-off-white); }
  .count-pill.HIGH      { background: var(--cm-orange);    color: var(--cm-off-white); }
  .count-pill.MEDIUM    { background: var(--cm-lavender);  color: var(--cm-purple); }
  .count-pill.QUICK_WIN { background: var(--cm-green);     color: var(--cm-off-white); }

  /* WEBSITE EVIDENCE (auto-captured screenshots) */
  .evidence-block {
    background: var(--cm-off-white);
    border: 1px solid var(--cm-light-grey-2);
    border-radius: 12px;
    padding: 18px 20px;
    page-break-inside: avoid; break-inside: avoid;
  }
  .evidence-block + .evidence-block { margin-top: 10px; }
  .evidence-tag {
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 9.5px;
    letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--cm-purple); margin-bottom: 8px;
  }
  .evidence-img {
    width: 100%; height: auto; border-radius: 8px;
    border: 1px solid var(--cm-light-grey-2); display: block;
  }
  .evidence-caption {
    font-size: 12px; color: var(--cm-body-grey);
    line-height: 1.55; margin-top: 8px;
  }
  .evidence-caption em { font-style: italic; color: var(--cm-purple); }

  /* BOOK-A-CALL CTA */
  .book-cta {
    background: var(--cm-purple); color: var(--cm-off-white);
    border-radius: 12px; padding: 26px 30px; text-align: center;
    page-break-inside: avoid; break-inside: avoid; margin-top: 4px;
  }
  .book-cta-headline {
    font-family: 'Lexend', sans-serif; font-size: 18px; font-weight: 500;
    color: var(--cm-off-white); margin-bottom: 8px; line-height: 1.3;
  }
  .book-cta-body { font-size: 13px; color: var(--cm-lavender); line-height: 1.6; margin-bottom: 16px; }
  .book-cta-btn {
    display: inline-block; background: var(--cm-yellow); color: var(--cm-purple);
    font-family: 'Lexend', sans-serif; font-weight: 700; font-size: 13px;
    padding: 12px 26px; border-radius: 999px; text-decoration: none;
    letter-spacing: 0.04em;
  }

  .footer {
    text-align: center; color: var(--cm-body-grey); font-size: 11px;
    line-height: 1.6; margin-top: 18px;
  }
  .footer strong { color: var(--cm-purple); font-weight: 600; }
</style>
</head>
<body>
<div class="page">

  <header class="header">
    {% if logo_b64 %}<img class="header-logo" src="data:image/png;base64,{{ logo_b64 }}" alt="Clinic Mastery" />{% endif %}
    <div class="header-content">
      <div class="header-eyebrow">WEBSITE AUDIT</div>
      <h1 class="header-title">{{ clinic_name }}</h1>
      <div class="header-sub">{{ website_url }}{% if specialty %} · {{ specialty }}{% endif %}{% if location %} · {{ location }}{% endif %}</div>
      <div class="header-meta">AUDITED {{ audit_date }} · CLINIC MASTERY</div>
    </div>
  </header>

  <section class="stat-hero">
    <div class="stat-eyebrow">{{ hero.eyebrow }}</div>
    <div class="stat-headline">{{ hero.headline | safe }}</div>
    <p class="stat-body">{{ hero.body | safe }}</p>
  </section>

  <div class="section-label">SCORECARD</div>
  <div class="grid-3">
    {% for tile in scorecard %}
    <div class="score-tile {{ tile.status }}">
      <div class="score-label">{{ tile.label }}</div>
      <div class="score-tag">{{ tile.text }}</div>
    </div>
    {% endfor %}
  </div>

  <div class="section-label">SITE SPEED</div>
  <div class="insight {{ speed.variant }}">
    <h3>{{ speed.title }}</h3>
    <ul>
      {% for b in speed.bullets %}<li>{{ b | safe }}</li>{% endfor %}
    </ul>
    <div class="metric-grid">
      {% for m in speed.metrics %}
      <div class="metric-cell">
        <div class="metric-v">{{ m.v }}</div>
        <div class="metric-l">{{ m.l }}</div>
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="section-label">SEO STRUCTURE</div>
  <div class="insight {{ seo.variant }}">
    <h3>{{ seo.title }}</h3>
    <div class="check-list">
      {% for c in seo.checks %}
      <div class="check-row">
        <div class="ck-detail">
          <span class="ck-label">{{ c.label }}</span>
          {{ c.detail | safe }}
        </div>
        <span class="ck-pill {{ c.status }}">{{ c.status_text }}</span>
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="section-label">UX &amp; CONVERSION FLOW</div>
  <div class="insight {{ ux.variant }}">
    <h3>{{ ux.title }}</h3>
    <div class="check-list">
      {% for i in ux.issues %}
      <div class="issue-row">
        <div>
          <div class="iss-title">{{ i.title }}</div>
          <div class="iss-detail">{{ i.detail | safe }}</div>
        </div>
        <span class="iss-pill {{ i.severity }}">{{ i.severity }}</span>
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="section-label">CONTENT &amp; LOCAL AUTHORITY</div>
  <div class="insight {{ content.variant }}">
    <h3>{{ content.title }}</h3>
    <table class="content-table">
      <thead>
        <tr><th class="area">Area</th><th class="now">Current state</th><th>Opportunity</th></tr>
      </thead>
      <tbody>
        {% for r in content.rows %}
        <tr>
          <td class="area">{{ r.area }}</td>
          <td class="now">{{ r.now | safe }}</td>
          <td>{{ r.next | safe }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% if screenshots %}
  <div class="section-label">WEBSITE EVIDENCE</div>
  {% for s in screenshots %}
  <div class="evidence-block">
    <div class="evidence-tag">{{ s.viewport }}</div>
    <img class="evidence-img" src="data:image/jpeg;base64,{{ s.b64 }}" alt="{{ s.viewport }}" />
    <p class="evidence-caption">{{ s.caption | safe }}</p>
  </div>
  {% endfor %}
  {% endif %}

  <div class="section-label">PRIORITY FIX LIST</div>
  {% if priority_counts %}
  <div class="pri-counts">
    {% for c in priority_counts %}
    <span class="count-pill {{ c.class }}">{{ c.count }} {{ c.label }}</span>
    {% endfor %}
  </div>
  {% endif %}
  {% for a in priorities %}
  <div class="action-row">
    <div class="action-num">{{ loop.index }}</div>
    <div class="action-content">
      <div class="action-head">
        <div class="action-title">{{ a.title }}</div>
        <span class="pri-pill {{ a.level | replace(' ', '_') }}">{{ a.level }}</span>
      </div>
      <div class="action-body">{{ a.body | safe }}</div>
    </div>
  </div>
  {% endfor %}

  <div class="book-cta">
    <div class="book-cta-headline">Want to walk through this together?</div>
    <p class="book-cta-body">Twenty minutes with Pete to walk through this website audit, prioritise the fixes that matter most, and decide what to tackle first.</p>
    <a class="book-cta-btn" href="https://bookings.clinicmastery.com/pete-flynn-google-ads">Book a 20-minute call</a>
  </div>

  <div class="footer">
    <strong>{{ clinic_name }} · Website Audit · {{ audit_date }}</strong><br>
    Prepared by Clinic Mastery from a manual audit of {{ website_url }}.<br>
    All recommendations are prioritised by patient acquisition impact. clinicmastery.com
  </div>

</div>
</body>
</html>
"""

assert "—" not in TEMPLATE_WS_SRC, (
    "Em dash found in CM website audit template. Brand voice rule: no em dashes."
)

_TEMPLATE_WS = _jinja_env.from_string(TEMPLATE_WS_SRC)


def generate_website_audit(audit_data: dict) -> bytes:
    """Render the v2 website audit PDF.

    Same input contract as the legacy pdf_report.generate_website_audit:
    a single dict with the keys documented in run_raisethebar_audit.py.
    """
    d = audit_data or {}
    clinic_name = d.get("clinic_name") or "Your Clinic"
    audit_date = d.get("audit_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    website_url = d.get("website_url") or ""

    # Augment status text on each SEO check for the template.
    seo = _ws_seo_card(d)
    for c in seo["checks"]:
        c["status_text"] = _ws_status_text(c["status"])

    priorities = _ws_priorities(d)

    # Auto-capture screenshots from website_url. Silently fails if Playwright
    # is missing or the site is unreachable.
    screenshots = _ws_capture_screenshots(website_url, d)

    ctx = {
        "logo_b64": _LOGO_B64,
        "clinic_name": clinic_name,
        "website_url": website_url,
        "specialty": d.get("specialty", ""),
        "location": d.get("location", ""),
        "audit_date": audit_date,
        "hero": _ws_hero(d),
        "scorecard": _ws_scorecard(d),
        "speed": _ws_speed_card(d),
        "seo": seo,
        "ux": _ws_ux_card(d),
        "content": _ws_content_card(d),
        "screenshots": screenshots,
        "priorities": priorities,
        "priority_counts": _ws_priority_counts(priorities),
    }

    html_text = _TEMPLATE_WS.render(**ctx)
    pdf_bytes = HTML(string=html_text).write_pdf()
    log.info(
        "Generated v2 website audit PDF: clinic=%s, %d bytes, %d priorities, %d screenshots",
        clinic_name, len(pdf_bytes), len(priorities), len(screenshots),
    )
    return pdf_bytes
