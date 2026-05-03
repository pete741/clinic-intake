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
  .kpi-tile {
    background: var(--cm-off-white); border: 1px solid var(--cm-light-grey-2);
    border-radius: 10px; padding: 18px 20px;
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

  /* CARD */
  .card {
    background: var(--cm-off-white); border: 1px solid var(--cm-light-grey-2);
    border-radius: 12px; padding: 20px 24px;
  }
  .card-title {
    font-family: 'Lexend', sans-serif; font-size: 15px; font-weight: 500;
    color: var(--cm-charcoal); margin-bottom: 4px;
  }
  .card-sub { font-size: 12px; color: var(--cm-body-grey); margin-bottom: 16px; }

  /* CAMPAIGN / VISIBILITY ROWS */
  .row-block {
    display: grid; grid-template-columns: 1fr auto; gap: 16px;
    align-items: center; padding: 14px 0; border-bottom: 0.5px solid var(--cm-divider);
    page-break-inside: avoid; break-inside: avoid;
  }
  .row-block:last-child { border-bottom: none; padding-bottom: 4px; }
  .row-block:first-child { padding-top: 4px; }
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
  .row-stats { display: flex; gap: 18px; text-align: right; }
  .row-stat-num {
    font-family: 'Lexend', sans-serif; font-size: 16px; font-weight: 700;
    color: var(--cm-purple); line-height: 1.1;
  }
  .row-stat-label {
    font-size: 9px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--cm-body-grey); margin-top: 4px;
    white-space: nowrap;
  }

  /* INSIGHT CARDS */
  .insight-card { border-radius: 12px; padding: 20px 24px; }
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

  <div class="section-group">
    <div class="section-label">The headline numbers · 90 days to {{ data_pulled }}</div>
    <div class="grid-3">
      <div class="kpi-tile featured">
        <div class="kpi-label">Total spend</div>
        <div class="kpi-num">{{ total_spend | money_2dp }}</div>
        <div class="kpi-sub">Across {{ num_active_campaigns }} active campaigns over the last 90 days.</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">Conversions</div>
        <div class="kpi-num">{{ total_conv | pint }}</div>
        <div class="kpi-sub">At <strong>{{ cost_per_conv | money_2dp }}</strong> per conversion.</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">Active campaigns</div>
        <div class="kpi-num">{{ num_active_campaigns }}</div>
        <div class="kpi-sub">Search and Performance Max, ranked by spend.</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">Wasted spend</div>
        <div class="kpi-num">{{ wasted_total | money_2dp }}</div>
        <div class="kpi-sub">{% if wasted_total > 0 %}<span class="kpi-warn">Recoverable.</span> {% endif %}{{ wasted_count }} keywords with $20+ spend and zero conversions.</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">Avg quality score</div>
        <div class="kpi-num">{{ "%.1f"|format(avg_qs) }} / 10</div>
        <div class="kpi-sub">{% if avg_qs and avg_qs < 6 %}<span class="kpi-warn">Below average.</span> Premium CPC on most clicks.{% elif avg_qs >= 7 %}Above average. Maintaining well.{% else %}Room to improve.{% endif %}</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">Brand spend leak</div>
        <div class="kpi-num">{{ brand_spend | money_2dp }}</div>
        <div class="kpi-sub">{{ "%.1f"|format(brand_pct) }}% of budget intercepting people who already chose you.</div>
      </div>
    </div>
  </div>

  {% if top_campaigns %}
  <div class="section-group">
    <div class="section-label">Where the budget went · top {{ top_campaigns|length }} campaign{{ 's' if top_campaigns|length > 1 else '' }}</div>
    <div class="card">
      <div class="card-title">Spend, conversions, and cost per conversion by campaign.</div>
      <div class="card-sub">Bars scaled to the largest campaign by spend.</div>
      {% for c in top_campaigns %}
      <div class="row-block">
        <div>
          <div class="row-name">{{ c.name }}</div>
          <div class="row-meta">
            <strong>{{ "%.1f"|format(c.share_pct) }}%</strong> of spend · CTR <strong>{{ "%.1f"|format(c.ctr) }}%</strong>
          </div>
          <div class="row-bar"><div class="row-bar-fill" style="width: {{ "%.1f"|format(c.share_bar_pct) }}%; background: {% if c.is_first %}var(--cm-purple){% else %}var(--cm-orange){% endif %};"></div></div>
        </div>
        <div class="row-stats">
          <div><div class="row-stat-num">{{ c.spend | money_round }}</div><div class="row-stat-label">Spend</div></div>
          <div><div class="row-stat-num">{{ c.conv | pint }}</div><div class="row-stat-label">Conv</div></div>
          <div><div class="row-stat-num">{{ c.cost_per_conv | money_2dp }}</div><div class="row-stat-label">Cost/Conv</div></div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  {% if visibility_rows %}
  <div class="section-group">
    <div class="section-label">Visibility · which auctions you are winning</div>
    <div class="card">
      <div class="card-title">Impression share won, vs share lost to budget and to ad rank.</div>
      <div class="card-sub">Lost to rank means quality scores or bids are too low. Lost to budget means the campaign ran out of money before end of day.</div>
      {% for v in visibility_rows %}
      <div class="row-block">
        <div>
          <div class="row-name">{{ v.name }}</div>
          <div class="row-meta">
            Winning <strong>{{ v.is_pct | pct_int }}</strong> of eligible auctions · biggest loss: <strong>{{ v.bigger_loss }}</strong>
          </div>
          <div class="row-bar"><div class="row-bar-fill" style="width: {{ v.is_pct or 0 }}%; background: var(--cm-purple);"></div></div>
        </div>
        <div class="row-stats">
          <div><div class="row-stat-num">{{ v.is_pct | pct_int }}</div><div class="row-stat-label">Won</div></div>
          <div><div class="row-stat-num">{{ v.lost_budget | pct_int }}</div><div class="row-stat-label">Lost: Budget</div></div>
          <div><div class="row-stat-num">{{ v.lost_rank | pct_int }}</div><div class="row-stat-label">Lost: Rank</div></div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  {% if wasted_keywords %}
  <div class="insight-card amber">
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
  <div class="insight-card amber">
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
  <div class="insight-card blue">
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

  <div class="insight-card {{ tracking_card.variant }}">
    <div class="insight-eyebrow">{{ tracking_card.eyebrow }}</div>
    <div class="insight-title">{{ tracking_card.title | safe }}</div>
    <div class="insight-body">{{ tracking_card.body | safe }}</div>
  </div>

  {% if qs.has_data %}
  <div class="card">
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

  <div class="section-group">
    <div class="section-label">What we would fix first · ranked by impact</div>
    <div class="card">
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
