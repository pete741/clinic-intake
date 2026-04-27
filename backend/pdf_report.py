"""
Generates a branded Clinic Mastery Google Ads audit PDF.

Sections:
  1. Cover / headline metrics snapshot
  2. Campaign performance (last 90 days)
  3. Wasted spend - high cost, zero conversions
  4. Irrelevant search terms (from search term report)
  5. Brand vs non-brand spend split
  6. Conversion tracking health check
  7. Quality score breakdown
  8. Priority fix list

Colours:
  Purple  #534AB7  - headings, accents
  Gold    #D4B22F  - logo, rules
  Dark    #1a1a2e  - body text
  Light   #f5f3ff  - shaded rows / panels
"""

import io
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Image, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
    KeepTogether,
)

# ── Brand colours ─────────────────────────────────────────────────────────────
PURPLE      = colors.HexColor("#534AB7")
PURPLE_DARK = colors.HexColor("#3d3589")
GOLD        = colors.HexColor("#D4B22F")
DARK        = colors.HexColor("#1a1a2e")
LIGHT_BG    = colors.HexColor("#f5f3ff")
MID_GREY    = colors.HexColor("#6b7280")
LIGHT_GREY  = colors.HexColor("#f9fafb")
RED_WARN    = colors.HexColor("#dc2626")
RED_LIGHT   = colors.HexColor("#fff5f5")
AMBER       = colors.HexColor("#d97706")
AMBER_LIGHT = colors.HexColor("#fffbeb")
GREEN_OK    = colors.HexColor("#16a34a")
GREEN_LIGHT = colors.HexColor("#f0fdf4")
WHITE       = colors.white

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


# ── Styles ────────────────────────────────────────────────────────────────────

def _styles() -> dict:
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=24,
                                textColor=PURPLE, leading=30, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11,
                                   textColor=MID_GREY, leading=16, spaceAfter=6),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13,
                                  textColor=PURPLE, leading=18, spaceBefore=12, spaceAfter=0),
        "subsection": ParagraphStyle("subsection", fontName="Helvetica-Bold", fontSize=10,
                                     textColor=DARK, leading=14, spaceBefore=4, spaceAfter=0),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9,
                               textColor=DARK, leading=14),
        "body_bold": ParagraphStyle("body_bold", fontName="Helvetica-Bold", fontSize=9,
                                    textColor=DARK, leading=14),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8,
                                textColor=MID_GREY, leading=12),
        "warn": ParagraphStyle("warn", fontName="Helvetica-Bold", fontSize=9,
                               textColor=RED_WARN, leading=13),
        "amber": ParagraphStyle("amber", fontName="Helvetica-Bold", fontSize=9,
                                textColor=AMBER, leading=13),
        "ok": ParagraphStyle("ok", fontName="Helvetica-Bold", fontSize=9,
                             textColor=GREEN_OK, leading=13),
        "metric_val": ParagraphStyle("metric_val", fontName="Helvetica-Bold", fontSize=13,
                                     textColor=PURPLE, leading=17, alignment=TA_CENTER),
        "metric_lbl": ParagraphStyle("metric_lbl", fontName="Helvetica", fontSize=7,
                                     textColor=MID_GREY, leading=10, alignment=TA_CENTER),
        "tag_red": ParagraphStyle("tag_red", fontName="Helvetica-Bold", fontSize=8,
                                  textColor=RED_WARN, leading=11, alignment=TA_CENTER),
        "tag_amber": ParagraphStyle("tag_amber", fontName="Helvetica-Bold", fontSize=8,
                                    textColor=AMBER, leading=11, alignment=TA_CENTER),
        "tag_green": ParagraphStyle("tag_green", fontName="Helvetica-Bold", fontSize=8,
                                    textColor=GREEN_OK, leading=11, alignment=TA_CENTER),
        "footer": ParagraphStyle("footer", fontName="Helvetica", fontSize=8,
                                 textColor=MID_GREY, alignment=TA_CENTER),
        "cover_clinic": ParagraphStyle("cover_clinic", fontName="Helvetica-Bold", fontSize=16,
                                       textColor=WHITE, leading=22, alignment=TA_CENTER),
        "cover_date": ParagraphStyle("cover_date", fontName="Helvetica", fontSize=10,
                                     textColor=colors.HexColor("#c4b9f5"), leading=14,
                                     alignment=TA_CENTER),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rule(story):
    story.append(HRFlowable(width="100%", thickness=1, color=PURPLE, spaceBefore=2, spaceAfter=3))

def _gold_rule(story):
    story.append(HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=2, spaceAfter=4))

def _spacer(story, h=8):
    story.append(Spacer(1, h))

def _fmt_d(v) -> str:
    try: return f"${float(v):,.2f}"
    except: return str(v)

def _fmt_i(v) -> str:
    try: return f"{int(float(v)):,}"
    except: return str(v)

def _pct(part, whole) -> str:
    try: return f"{part/whole*100:.1f}%"
    except: return "-"

def _tbl_style(header_bg=PURPLE, stripe=LIGHT_BG):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, stripe]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])

def _info_box(story, styles, text, bg=LIGHT_BG, border=PURPLE):
    tbl = Table([[Paragraph(text, styles["body"])]], colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEAFTER", (0, 0), (0, -1), 3, border),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(tbl)
    _spacer(story, 2)


# ── Page header & footer ──────────────────────────────────────────────────────

def _page_header(story, styles, clinic_name: str, pulled_at: str):
    logo_cell = ""
    if LOGO_PATH.exists():
        logo_cell = Image(str(LOGO_PATH), width=14*mm, height=18*mm, kind="proportional")

    title = Paragraph(
        f"Google Ads Audit Report<br/>"
        f"<font size='11' color='#6b7280'>{clinic_name}</font>",
        styles["title"],
    )
    date = Paragraph(f"Data pulled {pulled_at[:10]}", ParagraphStyle(
        "dr", fontName="Helvetica", fontSize=9, textColor=MID_GREY, alignment=TA_RIGHT))

    hdr = Table([[logo_cell, title, date]],
                colWidths=[22*mm, 115*mm, 38*mm])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
    ]))
    story.append(hdr)
    _gold_rule(story)


def _make_page_cb(clinic_name: str, pulled_at: str, report_title: str = "Google Ads Audit Report"):
    """Returns a canvas callback that draws header (pages 2+) and footer (all pages)."""
    def cb(canvas, doc):
        canvas.saveState()
        # ── Footer (every page) ───────────────────────────────────────────────
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MID_GREY)
        canvas.drawCentredString(PAGE_W / 2, 12 * mm,
            f"Clinic Mastery - Confidential  |  clinicmastery.com  |  Page {doc.page}")
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(1.5)
        canvas.line(MARGIN, 16 * mm, PAGE_W - MARGIN, 16 * mm)
        # ── Mini header (pages 2+) ────────────────────────────────────────────
        if doc.page > 1:
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(PURPLE)
            canvas.drawString(MARGIN, PAGE_H - 10 * mm, report_title)
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(MID_GREY)
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 10 * mm,
                f"{clinic_name}  |  {pulled_at[:10]}")
            canvas.setStrokeColor(GOLD)
            canvas.setLineWidth(1)
            canvas.line(MARGIN, PAGE_H - 13 * mm, PAGE_W - MARGIN, PAGE_H - 13 * mm)
        canvas.restoreState()
    return cb


# ── Section builders ──────────────────────────────────────────────────────────

def _section_snapshot(story, styles, data: dict):
    """6 headline metrics in a coloured band."""
    wasted_total = sum(k.get("spend", 0) for k in data.get("wasted_keywords", []))
    irrel_total  = sum(k.get("spend", 0) for k in data.get("irrelevant_terms", []))
    total_waste  = wasted_total + irrel_total

    metrics = [
        (_fmt_d(data.get("total_spend_90d", 0)),            "Total spend (90 days)"),
        (_fmt_i(data.get("total_conversions_90d", 0)),       "Conversions"),
        (_fmt_d(data.get("cost_per_conversion", 0)),         "Cost per conversion"),
        (str(data.get("num_active_campaigns", 0)),           "Active campaigns"),
        (_fmt_d(total_waste),                                "Est. wasted spend"),
        (str(data.get("avg_quality_score", "-")),            "Avg quality score /10"),
    ]
    cells = [[
        [Paragraph(v, styles["metric_val"]), Paragraph(l, styles["metric_lbl"])]
        for v, l in metrics
    ]]
    tbl = Table(cells, colWidths=[CONTENT_W/6]*6)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 1, PURPLE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    _spacer(story, 2)


def _section_campaigns(story, styles, data: dict):
    story.append(Paragraph("1. Campaign Performance - Last 90 Days", styles["section"]))
    _rule(story)

    campaigns = data.get("top_campaigns", [])
    if not campaigns:
        story.append(Paragraph("No campaign data found.", styles["body"]))
        return

    total_spend = data.get("total_spend_90d", 1) or 1
    rows = [["Campaign", "Status", "Spend", "% Budget", "Conv.", "Cost/Conv.", "CTR"]]
    for c in campaigns:
        spend = c.get("spend", 0)
        conv  = c.get("conversions", 0)
        rows.append([
            Paragraph(c.get("name", ""), styles["body"]),
            c.get("status", "").replace("_", " ").title(),
            _fmt_d(spend),
            _pct(spend, total_spend),
            str(int(conv)) if conv else "0",
            _fmt_d(spend / conv) if conv else "-",
            f"{c.get('ctr', 0):.1f}%",
        ])

    col_w = [68*mm, 18*mm, 20*mm, 18*mm, 14*mm, 22*mm, 14*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    story.append(tbl)
    _info_box(story, styles,
        "💡 <b>What to look for:</b> Campaigns with high spend and low (or zero) conversions "
        "are your biggest optimisation opportunity. A cost per conversion more than 3× your "
        "average appointment fee is a red flag.")


def _section_visibility(story, styles, data: dict):
    _spacer(story, 10)
    story.append(Paragraph("2. Visibility & Impression Share", styles["section"]))
    _rule(story)

    campaigns = [c for c in data.get("top_campaigns", []) if c.get("spend", 0) > 0]
    all_paused = data.get("all_campaigns_paused", False)

    if all_paused:
        story.append(Paragraph(
            "⚠ ALL CAMPAIGNS ARE CURRENTLY PAUSED. Your ads are not running. "
            "The data below reflects historical performance before pausing.",
            styles["warn"]))
        _spacer(story, 4)

    story.append(Paragraph(
        "Impression Share (IS) shows what percentage of eligible searches your ads actually appeared in. "
        "Lost IS reveals exactly where budget is being left on the table - "
        "either from insufficient budget or from ads not being competitive enough to win the auction.",
        styles["body"]))
    _spacer(story, 2)

    has_is_data = any(c.get("impression_share") is not None for c in campaigns)
    if not has_is_data or not campaigns:
        story.append(Paragraph(
            "Impression share data is not available for this account - "
            "this typically means all campaigns are Display-only or have insufficient search volume.",
            styles["small"]))
        return

    rows = [["Campaign", "Status", "Imp. Share", "Lost to Budget", "Lost to Rank", "Opportunity"]]
    for c in campaigns:
        is_val  = c.get("impression_share")
        budget  = c.get("lost_to_budget")
        rank    = c.get("lost_to_rank")

        if is_val is None:
            continue

        # Opportunity callout
        if rank is not None and rank > 20:
            opp = Paragraph("Low ad quality / bids", styles["warn"])
        elif budget is not None and budget > 20:
            opp = Paragraph("Underfunded", styles["amber"])
        else:
            opp = Paragraph("Healthy", styles["ok"])

        rows.append([
            Paragraph(c.get("name", ""), styles["body"]),
            c.get("status", "").replace("_", " ").title(),
            f"{is_val:.0f}%" if is_val is not None else "-",
            f"{budget:.0f}%" if budget is not None else "-",
            f"{rank:.0f}%"  if rank is not None else "-",
            opp,
        ])

    if len(rows) > 1:
        col_w = [65*mm, 17*mm, 22*mm, 26*mm, 22*mm, 22*mm]
        tbl = Table(rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(_tbl_style())
        story.append(tbl)

    _info_box(story, styles,
        "💡 <b>Lost to rank</b> means your Quality Score or bids are too low to win auctions - "
        "Google is choosing competitors over you even when you're targeting the right searches. "
        "<b>Lost to budget</b> means your ads ran out of money before the day ended. "
        "Both are recoverable: rank with better ad/landing page alignment, budget with spend increases.")


def _section_wasted(story, styles, data: dict):
    _spacer(story, 10)
    conversions_invalid = data.get("conversions_invalid", False)
    story.append(Paragraph("3. Wasted Spend - High Cost, Zero Conversions", styles["section"]))
    _rule(story)

    keywords = data.get("wasted_keywords", [])
    if not keywords:
        if conversions_invalid:
            _info_box(story, styles,
                "⚠ <b>Wasted spend analysis is not available for this account.</b> The recorded "
                "cost per conversion is under $20, which is not achievable for real patient bookings. "
                "This means conversion tracking is misconfigured — see Section 6 for details. "
                "Once tracking is fixed, this section will accurately identify keywords burning "
                "budget without producing patient enquiries.",
                bg=AMBER_LIGHT, border=AMBER)
        else:
            story.append(Paragraph("✓ No significant wasted keywords found in this period.", styles["ok"]))
        _spacer(story, 2)
        return

    total = sum(k.get("spend", 0) for k in keywords)
    story.append(Paragraph(
        f"<b>Total wasted spend: {_fmt_d(total)}</b> across {len(keywords)} "
        f"keyword{'s' if len(keywords)!=1 else ''} with spend over $20 and zero conversions.",
        styles["warn"]))
    _spacer(story, 2)

    rows = [["Keyword", "Match Type", "Spend", "Clicks", "Impressions", "Quality Score", "Action"]]
    for k in keywords:
        qs = k.get("quality_score", 0)
        action = "Pause + add as negative" if k.get("spend", 0) > 200 else "Review & consider pausing"
        rows.append([
            Paragraph(k.get("keyword", ""), styles["body"]),
            k.get("match_type", "").replace("_"," ").title(),
            _fmt_d(k.get("spend", 0)),
            _fmt_i(k.get("clicks", 0)),
            _fmt_i(k.get("impressions", 0)),
            str(qs) if qs else "-",
            Paragraph(action, styles["small"]),
        ])

    col_w = [55*mm, 20*mm, 18*mm, 14*mm, 22*mm, 20*mm, 25*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style(header_bg=RED_WARN, stripe=RED_LIGHT))
    story.append(tbl)
    _info_box(story, styles,
        "💡 <b>Recommended action:</b> Pause these keywords immediately and add the "
        "high-spend ones as exact-match negatives at the campaign level. This alone "
        f"could recover up to {_fmt_d(total)} per 90-day period.",
        bg=RED_LIGHT, border=RED_WARN)


def _section_irrelevant(story, styles, data: dict):
    _spacer(story, 10)
    story.append(Paragraph("4. Irrelevant Search Terms", styles["section"]))
    _rule(story)

    terms = data.get("irrelevant_terms", [])

    story.append(Paragraph(
        "These are actual search queries that triggered your ads. They are clearly "
        "unrelated to your clinic's services - people who would never become patients. "
        "Each click costs money with zero chance of conversion.",
        styles["body"]))
    _spacer(story, 2)

    if not terms:
        story.append(Paragraph(
            "✓ No clearly irrelevant search terms identified in this period. "
            "Consider running a manual search term report in Google Ads for further review.",
            styles["ok"]))
        _spacer(story, 2)
        return

    total = sum(t.get("spend", 0) for t in terms)
    story.append(Paragraph(
        f"<b>{_fmt_d(total)} spent on irrelevant searches</b> across {len(terms)} terms.",
        styles["warn"]))
    _spacer(story, 2)

    rows = [["Search Term", "Spend", "Clicks", "Why Irrelevant", "Fix"]]
    for t in terms:
        rows.append([
            Paragraph(t.get("term", ""), styles["body"]),
            _fmt_d(t.get("spend", 0)),
            _fmt_i(t.get("clicks", 0)),
            Paragraph(t.get("reason", "Unrelated to clinic services"), styles["small"]),
            Paragraph("Add as negative keyword", styles["small"]),
        ])

    col_w = [55*mm, 18*mm, 14*mm, 55*mm, 32*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style(header_bg=AMBER, stripe=AMBER_LIGHT))
    story.append(tbl)
    _info_box(story, styles,
        "💡 <b>Fix:</b> Add all of these as exact-match negative keywords at the account level. "
        "Review your search terms report monthly - broad match and phrase match campaigns "
        "generate irrelevant traffic over time as Google's matching expands.",
        bg=AMBER_LIGHT, border=AMBER)


def _section_brand(story, styles, data: dict):
    _spacer(story, 10)
    story.append(Paragraph("5. Brand Keyword Spend - A Healthcare-Specific Problem", styles["section"]))
    _rule(story)

    # Derive brand/non-brand spend: use explicit keys if present,
    # otherwise compute from brand_keywords list + total spend
    brand_kws = data.get("brand_keywords", [])
    brand     = data.get("brand_spend") or sum(k.get("spend", 0) for k in brand_kws)
    non_brand = data.get("non_brand_spend") or max(data.get("total_spend_90d", 0) - brand, 0)
    total     = brand + non_brand or 1
    brand_pct = brand / total * 100

    # In healthcare, brand spend is ALWAYS flagged as a problem.
    # People searching a clinic name already know it - they are not new patients.
    # Brand ads intercept existing demand and inflate conversion rates without
    # generating growth. This is fundamentally different from e-commerce.
    story.append(Paragraph(
        "<b>In healthcare, brand keyword spend is almost always wasted money.</b> "
        "Unlike e-commerce, people searching your clinic name are <i>existing patients, "
        "referrals, or people who already decided to book</i> - they were going to find "
        "you regardless. Paying Google to intercept them inflates your conversion rate "
        "and makes your account look better than it is, while doing nothing to grow "
        "your actual patient base.",
        styles["warn"]))
    _spacer(story, 2)

    rows = [
        ["", "Spend", "% of Budget", "Who's Searching", "Verdict"],
        [
            Paragraph("Brand keywords", styles["body_bold"]),
            _fmt_d(brand),
            f"{brand_pct:.1f}%",
            Paragraph("Existing patients, referrals, people who already chose you", styles["body"]),
            Paragraph("✗ Wasted on existing demand", styles["tag_red"]),
        ],
        [
            Paragraph("Non-brand keywords", styles["body_bold"]),
            _fmt_d(non_brand),
            f"{100-brand_pct:.1f}%",
            Paragraph("New patients actively searching for a clinic", styles["body"]),
            Paragraph("✓ This is real growth spend", styles["tag_green"]),
        ],
    ]

    col_w = [35*mm, 22*mm, 22*mm, 62*mm, 33*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    story.append(tbl)
    if brand_pct > 0:
        _info_box(story, styles,
            f"⚠ <b>{_fmt_d(brand)} ({brand_pct:.0f}% of budget) is being spent on brand searches.</b> "
            "These are not new patients. Removing brand keywords from your non-brand campaigns "
            "and either eliminating them entirely - or capping them in a separate low-budget "
            "brand campaign - would redirect this spend toward genuine patient acquisition. "
            "Your conversion rate will drop, but your <i>real</i> cost per new patient will improve.",
            bg=RED_LIGHT, border=RED_WARN)


def _section_conversion(story, styles, data: dict):
    _spacer(story, 10)
    story.append(Paragraph("6. Conversion Tracking Health Check", styles["section"]))
    _rule(story)

    story.append(Paragraph(
        "Conversion tracking tells Google which clicks led to a patient booking or enquiry. "
        "Without accurate tracking, Google's algorithm is optimising blind - spending more "
        "on clicks that <i>look</i> similar to converting clicks but aren't.",
        styles["body"]))
    _spacer(story, 2)

    _ltv = (
        float(data.get("avg_appointment_fee", 0) or 0) *
        float(data.get("avg_visits_per_patient", 0) or 0)
    ) or 0  # 0 means not provided

    total_conv  = data.get("total_conversions_90d", 0)
    cost_per_conv = data.get("cost_per_conversion", 0)
    total_clicks = max(sum(c.get("clicks", 0) for c in data.get("top_campaigns", [])), 1)
    conv_rate   = round(total_conv / total_clicks * 100, 1)

    # Snapshot metrics row
    snapshot_metrics = [
        (_fmt_i(total_conv),       "Conversions (90d)"),
        (f"{conv_rate}%",          "Conversion rate"),
        (_fmt_d(cost_per_conv),    "Cost per conversion"),
    ]
    cells = [[
        [Paragraph(v, styles["metric_val"]), Paragraph(l, styles["metric_lbl"])]
        for v, l in snapshot_metrics
    ]]
    snap_tbl = Table(cells, colWidths=[CONTENT_W/3]*3)
    snap_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 1, PURPLE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(snap_tbl)
    _spacer(story, 4)

    # Cost per conversion under $20 almost certainly means micro-conversions
    # (button clicks, page views, phone reveals) not actual patient bookings.
    suspicious_cpc = 0 < cost_per_conv < 20

    issues = data.get("conversion_issues", [])
    checks = [
        {
            "check": "Conversions being recorded",
            "status": "ok" if total_conv > 0 else "fail",
            "detail": (
                f"{total_conv} conversions recorded over 90 days."
                if total_conv > 0
                else "Zero conversions recorded. Tracking may be broken or not set up."
            ),
        },
        {
            "check": "Conversion value is realistic for healthcare",
            "status": "fail" if suspicious_cpc else "ok",
            "detail": (
                f"Cost per conversion is {_fmt_d(cost_per_conv)}, which is below $50. "
                "In healthcare, a genuine patient booking costs far more to acquire. "
                "This strongly suggests the account is recording a micro-conversion - "
                "such as a button click, phone number reveal, or page scroll - "
                "rather than an actual enquiry or booking. "
                "Google is optimising for these cheap actions, not real patients."
                if suspicious_cpc else
                f"Cost per conversion is {_fmt_d(cost_per_conv)}, which is within a plausible "
                "range for a healthcare patient acquisition."
            ),
        },
        {
            "check": "Conversion rate is plausible",
            "status": (
                "warn" if conv_rate < 1 or conv_rate > 30 else
                "fail" if conv_rate > 50 else
                "ok"
            ),
            "detail": (
                f"Conversion rate is {conv_rate}%. "
                + (
                    "Below 1% usually means tracking is not capturing all converting sessions."
                    if conv_rate < 1 else
                    "Above 30% is implausibly high for real patient bookings and confirms "
                    "a micro-conversion is being tracked instead of genuine enquiries."
                    if conv_rate > 30 else
                    "Within a normal range for a healthcare practice."
                )
            ),
        },
    ]

    # Only show the LTV check if we have LTV data and CPC is not suspicious
    if _ltv > 0 and not suspicious_cpc:
        checks.append({
            "check": "Cost per conversion vs lifetime value",
            "status": (
                "ok"   if cost_per_conv < _ltv * 0.20 else
                "warn" if cost_per_conv < _ltv * 0.40 else
                "fail"
            ),
            "detail": (
                f"Cost per conversion is {_fmt_d(cost_per_conv)} vs "
                f"patient LTV of {_fmt_d(_ltv)} "
                f"({_fmt_d(data.get('avg_appointment_fee', 0))} x {data.get('avg_visits_per_patient', 0)} visits). "
                f"Target is under 20% of LTV ({_fmt_d(_ltv * 0.20)}). "
                + ("Healthy - acquisition cost is within target."
                   if cost_per_conv < _ltv * 0.20 else
                   "Needs attention - acquisition cost exceeds 20% of patient lifetime value.")
            ),
        })
    elif _ltv > 0 and suspicious_cpc:
        checks.append({
            "check": "Cost per conversion vs lifetime value",
            "status": "fail",
            "detail": (
                f"Cannot assess accurately - the {_fmt_d(cost_per_conv)} cost per conversion "
                "is almost certainly a micro-conversion, not a real patient booking. "
                "Fix conversion tracking first, then re-evaluate against LTV."
            ),
        })

    for issue in issues:
        checks.append({"check": issue.get("check", ""), "status": issue.get("status", "warn"),
                       "detail": issue.get("detail", "")})

    status_map = {
        "ok":   lambda: Paragraph("✓ Pass", styles["tag_green"]),
        "warn": lambda: Paragraph("⚠ Review", styles["tag_amber"]),
        "fail": lambda: Paragraph("✗ Issue", styles["tag_red"]),
    }

    rows = [["Check", "Status", "Detail"]]
    for c in checks:
        rows.append([
            Paragraph(c["check"], styles["body_bold"]),
            status_map.get(c["status"], status_map["warn"])(),
            Paragraph(c["detail"], styles["body"]),
        ])

    col_w = [55*mm, 22*mm, 97*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    story.append(tbl)

    if suspicious_cpc:
        _info_box(story, styles,
            f"💡 <b>Action required:</b> Go to Google Ads → Tools → Measurement → Conversions "
            f"and check what action is being recorded. It should be a phone call, form submission, "
            f"or booking confirmation - not a click, scroll, or page visit. "
            f"Fixing this is the single highest-leverage change available in this account.",
            bg=RED_LIGHT, border=RED_WARN)
    else:
        _info_box(story, styles,
            "💡 <b>To verify conversion tracking:</b> In Google Ads → Tools → Measurement → "
            "Conversions. Each conversion action should show 'Recording conversions' in green. "
            "If any show 'No recent conversions' or 'Inactive', tracking needs fixing before "
            "increasing spend.")


def _section_quality(story, styles, data: dict):
    _spacer(story, 10)
    story.append(Paragraph("7. Quality Score Breakdown", styles["section"]))
    _rule(story)

    qs = data.get("avg_quality_score", 0)
    story.append(Paragraph(
        "Quality Score (1-10) measures how relevant your keywords, ads and landing pages "
        "are to each other. A low score means Google charges you <i>more per click</i> "
        "than competitors with better-structured accounts.",
        styles["body"]))
    _spacer(story, 2)

    # Use the dedicated low_qs_keywords list from the data pull for accurate counts
    all_kws = data.get("low_qs_keywords", []) + data.get("wasted_keywords", [])
    seen = set()
    deduped = []
    for k in all_kws:
        key = (k.get("keyword", ""), k.get("match_type", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(k)

    qs_scores = [k.get("quality_score", 0) for k in deduped if k.get("quality_score", 0) > 0]

    poor   = sum(1 for q in qs_scores if q <= 4)
    avg_qs = sum(1 for q in qs_scores if 5 <= q <= 6)
    good   = sum(1 for q in qs_scores if q >= 7)
    total  = len(qs_scores) or 1

    rows = [
        ["Quality Score Band", "Keywords", "% of Total", "Impact", "Priority"],
        ["Poor (1-4)",   str(poor),   _pct(poor, total),   "Paying premium CPC",    Paragraph("Fix first", styles["tag_red"])],
        ["Average (5-6)", str(avg_qs), _pct(avg_qs, total), "Slightly above market", Paragraph("Improve", styles["tag_amber"])],
        ["Good (7-10)",  str(good),   _pct(good, total),   "Competitive CPC",       Paragraph("Maintain", styles["tag_green"])],
    ]

    col_w = [45*mm, 25*mm, 25*mm, 50*mm, 29*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    story.append(tbl)

    # Show the worst offenders (QS 1-4 with spend)
    worst = [k for k in data.get("low_qs_keywords", []) if k.get("quality_score", 0) <= 4][:10]
    if worst:
        _spacer(story, 4)
        story.append(Paragraph("Worst performers (QS 1-4, ranked by spend):", styles["subsection"]))
        _spacer(story, 2)
        kw_rows = [["Keyword", "Match Type", "QS", "Spend", "Conversions"]]
        for k in worst:
            kw_rows.append([
                Paragraph(k.get("keyword", ""), styles["body"]),
                k.get("match_type", "").replace("_", " ").title(),
                str(k.get("quality_score", "-")),
                _fmt_d(k.get("spend", 0)),
                str(int(k.get("conversions", 0))),
            ])
        kw_tbl = Table(kw_rows, colWidths=[70*mm, 25*mm, 15*mm, 20*mm, 24*mm], repeatRows=1)
        kw_tbl.setStyle(_tbl_style(header_bg=AMBER, stripe=AMBER_LIGHT))
        story.append(kw_tbl)

    qs_comment = (
        f"Average quality score is <b>{qs}/10</b> - "
        + ("above average. Maintain by keeping ads and landing pages tightly aligned to keywords."
           if qs >= 7 else
           "below average. This is costing you money on every click. "
           "The fastest fix is to tighten keyword-to-ad copy alignment and ensure "
           "your landing page mentions the exact service the keyword targets."
           if qs < 5 else
           "average. There's meaningful room to reduce CPC by improving ad relevance.")
    )
    _info_box(story, styles, f"💡 {qs_comment}")


def _section_priorities(story, styles, data: dict):
    story.append(PageBreak())
    story.append(Paragraph("8. Priority Fix List", styles["section"]))
    _rule(story)

    story.append(Paragraph(
        "Ranked by estimated impact.",
        styles["body"]))
    _spacer(story, 2)

    wasted       = data.get("wasted_keywords", [])
    irrelevant   = data.get("irrelevant_terms", [])
    qs           = data.get("avg_quality_score", 0)
    conv_issues      = data.get("total_conversions_90d", 1) == 0
    _cost_per_conv   = data.get("cost_per_conversion", 0)
    micro_conversion = 0 < _cost_per_conv < 20
    all_paused       = data.get("all_campaigns_paused", False)
    _brand_kws   = data.get("brand_keywords", [])
    _brand_spend = data.get("brand_spend") or sum(k.get("spend",0) for k in _brand_kws)
    _non_brand   = data.get("non_brand_spend") or max(data.get("total_spend_90d",0) - _brand_spend, 0)
    brand_pct    = _brand_spend / (_brand_spend + _non_brand + 0.01) * 100

    # Check for impression share issues
    campaigns = data.get("top_campaigns", [])
    rank_losers = [c for c in campaigns if (c.get("lost_to_rank") or 0) > 20 and c.get("spend", 0) > 0]
    budget_losers = [c for c in campaigns if (c.get("lost_to_budget") or 0) > 20 and c.get("spend", 0) > 0]
    low_qs_kws = data.get("low_qs_keywords", [])

    priorities = []

    if all_paused:
        priorities.append(("🔴", "Reactivate campaigns - all ads are currently paused",
            "Every campaign with historical spend is paused. No ads are running. "
            "Review why campaigns were paused and re-enable with a clear daily budget cap.",
            "Critical"))

    if conv_issues:
        priorities.append(("🔴", "Fix conversion tracking",
            "Zero conversions recorded - Google is optimising blind. "
            "Check Tools -> Conversions in Google Ads and fix before increasing budget.",
            "Critical"))

    if micro_conversion:
        priorities.append(("🔴", f"Fix conversion tracking - micro-conversion detected ({_fmt_d(_cost_per_conv)}/conv)",
            f"A cost per conversion of {_fmt_d(_cost_per_conv)} is not achievable for real patient bookings. "
            "The account is recording a low-value action (click, scroll, phone reveal) as a conversion. "
            "Google is optimising for these cheap events instead of actual patient enquiries. "
            "Go to Tools -> Conversions, identify the action being tracked, and replace it with "
            "a booking confirmation or genuine form submission.",
            "Critical"))

    if rank_losers:
        names = ", ".join(c["name"][:30] for c in rank_losers[:2])
        priorities.append(("🔴", f"Improve ad quality to win more auctions ({len(rank_losers)} campaign{'s' if len(rank_losers)>1 else ''})",
            f"Losing significant impression share to poor ad rank in: {names}. "
            "Higher quality scores lower your cost-per-click AND increase how often your ads show.",
            "High"))

    if wasted:
        total_waste = sum(k.get("spend",0) for k in wasted)
        priorities.append(("🔴", f"Pause {len(wasted)} wasted keywords",
            f"Estimated {_fmt_d(total_waste)} recoverable per 90 days. "
            "Pause these immediately and add as exact-match negatives.",
            "High"))

    if budget_losers:
        names = ", ".join(c["name"][:30] for c in budget_losers[:2])
        priorities.append(("🟠", f"Increase budget for underfunded campaigns ({len(budget_losers)} campaign{'s' if len(budget_losers)>1 else ''})",
            f"Ads running out of budget before end of day in: {names}. "
            "Losing patients to competitors who are still showing. Increase daily budget or tighten targeting.",
            "Medium"))

    if irrelevant:
        irrel_waste = sum(t.get("spend",0) for t in irrelevant)
        priorities.append(("🟠", f"Add {len(irrelevant)} irrelevant search terms as negatives",
            f"{_fmt_d(irrel_waste)} spent on searches with zero patient intent. "
            "Add as exact-match negatives at account level.",
            "High"))

    if low_qs_kws and qs < 6:
        priorities.append(("🟠", f"Rewrite ad copy for {len(low_qs_kws)} low quality score keywords",
            f"Average QS {qs}/10. Keywords rated 1-5 cost more per click than competitors. "
            "Tighten keyword -> ad copy -> landing page alignment for each ad group.",
            "Medium"))

    if brand_pct > 0:
        priorities.append(("🔴", f"Remove brand keywords from growth campaigns ({_fmt_d(_brand_spend)} at risk)",
            f"{brand_pct:.0f}% of budget on brand terms. In healthcare these intercept "
            "existing patients, not new ones. Eliminate or cap in a separate low-budget campaign.",
            "High"))

    priorities.append(("🟢", "Schedule a monthly search term review",
        "Irrelevant terms accumulate over time with broad/phrase match. "
        "A 20-minute monthly review prevents budget leakage.",
        "Ongoing"))

    priorities.append(("🟢", "Check ad scheduling matches clinic hours",
        "Ads running outside opening hours waste budget on calls that go unanswered.",
        "Quick win"))

    rows = [["", "Action", "Detail", "Priority"]]
    for icon, action, detail, pri in priorities:
        pri_style = {
            "Critical": styles["tag_red"],
            "High": styles["tag_red"],
            "Medium": styles["tag_amber"],
            "Quick win": styles["tag_green"],
            "Ongoing": styles["tag_green"],
        }.get(pri, styles["body"])
        rows.append([
            icon,
            Paragraph(f"<b>{action}</b>", styles["body_bold"]),
            Paragraph(detail, styles["body"]),
            Paragraph(pri, pri_style),
        ])

    col_w = [8*mm, 50*mm, 98*mm, 18*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PURPLE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (-1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 1), (0, -1), 12),
    ]))
    story.append(tbl)
    _spacer(story, 2)

    _gold_rule(story)
    story.append(Paragraph(
        "This report was generated automatically by Clinic Mastery's intake system. "
        "Read-only access can be revoked at any time via Google Ads → Admin → Access and security. "
        "All data covers the 90-day period ending on the date shown above.",
        styles["small"]))


# ── Prospect email draft ──────────────────────────────────────────────────────

def generate_prospect_email_draft(clinic_name: str, ads_data: dict) -> str:
    """
    Generates a plain-text draft email pete can copy, personalise, and send
    to the clinic prospect along with the PDF report.
    """
    wasted       = ads_data.get("wasted_keywords", [])
    irrelevant   = ads_data.get("irrelevant_terms", [])
    brand_kws    = ads_data.get("brand_keywords", [])
    brand        = ads_data.get("brand_spend") or sum(k.get("spend",0) for k in brand_kws)
    non_brand    = ads_data.get("non_brand_spend") or max(ads_data.get("total_spend_90d",0) - brand, 0)
    brand_pct    = brand / (brand + non_brand + 0.01) * 100
    total_waste  = sum(k.get("spend",0) for k in wasted) + sum(t.get("spend",0) for t in irrelevant)
    spend_90d    = ads_data.get("total_spend_90d", 0)
    cost_per_conv = ads_data.get("cost_per_conversion", 0)
    qs           = ads_data.get("avg_quality_score", 0)

    # Build 2-3 punchy findings
    findings = []
    if total_waste > 0:
        findings.append(
            f"- We identified ${total_waste:,.0f} in wasted spend over the last 90 days - "
            f"keywords and search terms eating budget with zero patient bookings."
        )
    if brand_pct > 5:
        findings.append(
            f"- {brand_pct:.0f}% of your budget ({_fmt_d(brand)}) is going to brand keyword searches. "
            f"In healthcare, these are existing patients and referrals - not new ones. "
            f"That money can be redirected to genuine patient acquisition."
        )
    if qs < 6:
        findings.append(
            f"- Your average quality score is {qs}/10, which means Google is charging you "
            f"a premium on every click. Better ad structure would reduce your cost per click "
            f"without increasing spend."
        )
    if cost_per_conv > 0:
        findings.append(
            f"- Current cost per new patient enquiry is {_fmt_d(cost_per_conv)}. "
            f"There's a clear path to improving this."
        )

    findings_text = "\n".join(findings) if findings else \
        "- Your account data is attached in full - there are several clear optimisation opportunities."

    draft = f"""Subject: Your Google Ads analysis is ready - {clinic_name}

Hi [First name],

I've had a look through your Google Ads account and put together a full analysis - attached as a PDF.

Here are the main things that stood out:

{findings_text}

I've outlined the specific fixes and what I'd prioritise first in the report.

Happy to walk through it with you on a quick call - usually takes about 20 minutes and by the end you'll have a clear picture of exactly what to change and what it's worth.

Are you free [suggest a time]?

Pete
Clinic Mastery
pete@clinicmastery.com"""

    return draft


def generate_intake_email_draft(clinic_name: str, submission: dict) -> str:
    """
    Generates a plain-text draft email pete can send to a clinic that completed
    the intake form but did not provide Google Ads access.
    """
    spec      = submission.get("primary_specialty", "clinic")
    suburb    = submission.get("suburb", "")
    state     = submission.get("state", "")
    goal      = submission.get("main_goal", "")
    avg_fee   = float(submission.get("avg_appointment_fee", 0) or 0)
    avg_visits= float(submission.get("avg_visits_per_patient", 0) or 0)
    ltv       = avg_fee * avg_visits
    new_pts   = int(submission.get("new_patients_per_month", 0) or 0)
    ad_spend  = float(submission.get("monthly_ad_spend", 0) or 0)
    appt      = submission.get("appointment_types_to_grow", "")

    findings = []

    if ltv > 0 and new_pts > 0:
        findings.append(
            f"- Based on your numbers, each new patient is worth around ${ltv:,.0f} in lifetime value. "
            f"With {new_pts} new patients per month, there's a clear lever here worth pulling."
        )

    if ad_spend > 0:
        cost_per_new = ad_spend / new_pts if new_pts else 0
        if cost_per_new > ltv * 0.20 and ltv > 0:
            findings.append(
                f"- Your current spend of ${ad_spend:,.0f}/month is producing new patients at around "
                f"${cost_per_new:,.0f} each - higher than the 20% of LTV benchmark we target. "
                f"There's likely room to either reduce that cost or increase volume for the same spend."
            )
        else:
            findings.append(
                f"- You're currently spending ${ad_spend:,.0f}/month on advertising. "
                f"I've outlined in the brief how we'd structure a Google Ads campaign "
                f"to make that spend work harder."
            )

    if goal:
        findings.append(
            f"- Your main goal is: \"{goal}\". I've put together some specific suggestions "
            f"in the brief on how to get there."
        )

    if appt:
        findings.append(
            f"- You're looking to grow: {appt}. The keyword and campaign structure "
            f"in the brief is built around exactly that."
        )

    findings_text = "\n".join(findings[:3]) if findings else \
        "- I've put together a brief with some specific recommendations based on your answers."

    draft = f"""Subject: Your clinic growth brief - {clinic_name}

Hi [First name],

Thanks for filling out the form - I've put together a short brief for {clinic_name} based on what you shared, attached as a PDF.

A few things that stood out:

{findings_text}

I'd love to walk through it with you on a quick call - usually about 20 minutes and you'll leave with a clear picture of what's worth doing first.

Are you free [suggest a time]?

Pete
Clinic Mastery
pete@clinicmastery.com"""

    return draft


# ── Standard intake brief (no Google Ads data) ───────────────────────────────

def _condition_keywords(spec_lc: str, suburb: str, appt: str) -> list[str]:
    """Returns condition/symptom-based keywords tailored to the specialty."""
    suburb_lc = suburb.lower()
    base = {
        "physio": [
            f"back pain {suburb_lc}", f"knee pain treatment {suburb_lc}",
            f"sports injury {suburb_lc}", f"neck pain {suburb_lc}",
            "shoulder physio", "sciatica treatment",
        ],
        "chiropractor": [
            f"back pain relief {suburb_lc}", f"neck pain chiropractor {suburb_lc}",
            f"headache treatment {suburb_lc}", "sciatica chiropractor",
            "lower back pain", "whiplash treatment",
        ],
        "psychologist": [
            f"anxiety treatment {suburb_lc}", f"depression help {suburb_lc}",
            "counselling near me", "stress management",
            "PTSD therapist", "relationship counselling",
        ],
        "osteopath": [
            f"back pain osteopath {suburb_lc}", "joint pain treatment",
            f"osteopathy {suburb_lc}", "muscle pain relief",
            "posture treatment", "hip pain osteopath",
        ],
        "podiatrist": [
            f"heel pain {suburb_lc}", "plantar fasciitis treatment",
            f"foot pain podiatrist {suburb_lc}", "ingrown toenail",
            "diabetic foot care", "orthotics near me",
        ],
        "dentist": [
            f"tooth pain {suburb_lc}", "emergency dentist near me",
            f"teeth whitening {suburb_lc}", "dental implants",
            "broken tooth", "dental check up",
        ],
    }
    for key, kws in base.items():
        if key in spec_lc:
            return kws[:5]
    # Generic fallback
    return [
        f"{spec_lc} {suburb_lc}", f"pain relief {suburb_lc}",
        f"treatment near me", f"clinic {suburb_lc}", "specialist near me",
    ]


def _service_keywords(spec_lc: str, suburb: str, appt: str) -> list[str]:
    """Returns service-specific keywords derived from appointment types to grow."""
    suburb_lc = suburb.lower()
    appt_lc = appt.lower() if appt else ""
    keywords = []
    # Pull service hints from appointment types field
    service_map = {
        "initial": [f"initial {spec_lc.split()[0]} appointment {suburb_lc}", "first physio appointment"],
        "sports": [f"sports {spec_lc.split()[0]} {suburb_lc}", "sports injury clinic"],
        "pregnancy": ["pregnancy physio", "prenatal physiotherapy", "pelvic floor physio"],
        "paediatric": ["children's physio", "paediatric physiotherapy", "kids chiropractor"],
        "family": [f"family {spec_lc.split()[0]} {suburb_lc}", "family chiropractic"],
        "dry needling": [f"dry needling {suburb_lc}", "acupuncture physio"],
        "massage": [f"remedial massage {suburb_lc}", "sports massage near me"],
        "hydrotherapy": [f"hydrotherapy {suburb_lc}", "pool physio"],
        "pilates": [f"clinical pilates {suburb_lc}", "physio pilates"],
        "mental health": ["mental health therapy", "NDIS psychology"],
        "anxiety": ["anxiety specialist", "CBT therapy near me"],
        "depression": ["depression counselling", "mindfulness therapy"],
    }
    for trigger, kws in service_map.items():
        if trigger in appt_lc:
            keywords.extend(kws)
        if len(keywords) >= 5:
            break
    if not keywords:
        keywords = [
            f"{spec_lc.split()[0]} appointment {suburb_lc}",
            f"book {spec_lc.split()[0]}",
            f"{spec_lc.split()[0]} consultation",
            f"new patient {spec_lc.split()[0]}",
            f"online booking {spec_lc.split()[0]}",
        ]
    return keywords[:5]


def _negative_keywords(spec_lc: str) -> list[str]:
    """Returns standard negative keywords relevant to healthcare clinics."""
    base = [
        "free", "jobs", "salary", "courses", "study", "degree",
        "become a", "training", "volunteer", "DIY", "youtube",
        "massage" if "physio" in spec_lc else "physio",
        "veterinary", "animal", "horse",
    ]
    return base[:8]


def generate_intake_brief(submission: dict) -> bytes:
    """
    Generates a short 1–2 page brief from intake form data alone.
    Used when a clinic skips Google Ads access or doesn't run Google Ads.

    Args:
        submission: The raw intake form data dict (matches IntakeSubmission fields)

    Returns:
        PDF as bytes.
    """
    buffer = io.BytesIO()
    clinic_name = submission.get("clinic_name", "Unknown Clinic")
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=22*mm,
        title=f"Intake Brief - {clinic_name}",
        author="Clinic Mastery",
    )

    styles = _styles()
    story  = []

    # Header
    logo_cell = ""
    if LOGO_PATH.exists():
        logo_cell = Image(str(LOGO_PATH), width=14*mm, height=18*mm, kind="proportional")

    title = Paragraph(
        f"Clinic Growth Brief<br/>"
        f"<font size='11' color='#6b7280'>{clinic_name}</font>",
        styles["title"],
    )
    date = Paragraph(datetime.utcnow().strftime("Received %d %b %Y"),
                     ParagraphStyle("dr", fontName="Helvetica", fontSize=9,
                                    textColor=MID_GREY, alignment=TA_RIGHT))
    hdr = Table([[logo_cell, title, date]], colWidths=[22*mm, 115*mm, 38*mm])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(0,0),0),
        ("RIGHTPADDING",(-1,0),(-1,0),0),
    ]))
    story.append(hdr)
    _gold_rule(story)

    # Intro
    story.append(Paragraph(
        f"<b>{clinic_name}</b> completed the Clinic Mastery intake form. "
        f"Google Ads account access was not provided - this brief is based on "
        f"the information submitted in the form.",
        styles["body"]))
    _spacer(story, 2)

    # ── Clinic snapshot ───────────────────────────────────────────────────────
    story.append(Paragraph("Clinic Snapshot", styles["section"]))
    _rule(story)

    snap_rows = [
        ["Clinic name",     clinic_name],
        ["Specialty",       submission.get("primary_specialty", "-")],
        ["Location",        f"{submission.get('suburb','-')}, {submission.get('state','-')}"],
        ["Practitioners",   str(submission.get("num_practitioners", "-"))],
        ["Website",         submission.get("website_url", "-")],
        ["Email",           submission.get("email", "-")],
    ]
    snap_tbl = Table(snap_rows, colWidths=[50*mm, 124*mm])
    snap_tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0),(0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0),(-1,-1), 9),
        ("TOPPADDING", (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("ROWBACKGROUNDS", (0,0),(-1,-1), [WHITE, LIGHT_BG]),
        ("GRID", (0,0),(-1,-1), 0.5, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0,0),(-1,-1), "MIDDLE"),
    ]))
    story.append(snap_tbl)
    _spacer(story, 2)

    # ── Revenue context ───────────────────────────────────────────────────────
    _spacer(story, 10)
    story.append(Paragraph("Revenue Context", styles["section"]))
    _rule(story)

    avg_fee    = float(submission.get("avg_appointment_fee", 0) or 0)
    avg_visits = float(submission.get("avg_visits_per_patient", 0) or 0)
    ltv        = avg_fee * avg_visits
    new_pts    = int(submission.get("new_patients_per_month", 0) or 0)
    ad_spend   = float(submission.get("monthly_ad_spend", 0) or 0)
    monthly_rev_from_new = ltv * new_pts

    rev_rows = [
        ["Avg appointment fee",       _fmt_d(avg_fee)],
        ["Avg visits per patient",    str(avg_visits)],
        ["Estimated patient LTV",     _fmt_d(ltv)],
        ["New patients per month",    str(new_pts)],
        ["Monthly revenue from new pts (est.)", _fmt_d(monthly_rev_from_new)],
        ["Monthly Google Ads spend",  _fmt_d(ad_spend)],
        ["Appointment types to grow", submission.get("appointment_types_to_grow", "-")],
    ]
    rev_tbl = Table(rev_rows, colWidths=[80*mm, 94*mm])
    rev_tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0),(0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0),(-1,-1), 9),
        ("TOPPADDING", (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("ROWBACKGROUNDS", (0,0),(-1,-1), [WHITE, LIGHT_BG]),
        ("GRID", (0,0),(-1,-1), 0.5, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0,2),(1,2), colors.HexColor("#eeecfb")),
        ("FONTNAME", (0,2),(1,2), "Helvetica-Bold"),
        ("VALIGN", (0,0),(-1,-1), "MIDDLE"),
    ]))
    story.append(rev_tbl)
    _info_box(story, styles,
        f"💡 At an estimated LTV of {_fmt_d(ltv)} per patient, each additional new patient "
        f"per month is worth approximately {_fmt_d(ltv * 12)} in annual revenue. "
        f"With {new_pts} new patients currently per month, there's a clear growth lever here.")

    # ── Goals ─────────────────────────────────────────────────────────────────
    _spacer(story, 10)
    story.append(Paragraph("Goals & Context", styles["section"]))
    _rule(story)

    goal_rows = [
        ["Main goal",          submission.get("main_goal", "-")],
        ["Additional context", submission.get("additional_context") or "None provided"],
        ["Google Ads status",  submission.get("has_google_ads") or "Not provided"],
    ]
    goal_tbl = Table(goal_rows, colWidths=[50*mm, 124*mm])
    goal_tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0),(0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0),(-1,-1), 9),
        ("TOPPADDING", (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("ROWBACKGROUNDS", (0,0),(-1,-1), [WHITE, LIGHT_BG]),
        ("GRID", (0,0),(-1,-1), 0.5, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0,0),(-1,-1), "TOP"),
    ]))
    story.append(goal_tbl)
    _spacer(story, 2)

    # ── Keyword targets ───────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Keyword Targets", styles["section"]))
    _rule(story)

    story.append(Paragraph(
        "Based on this clinic's specialty, location, and growth goals, these are the "
        "keyword categories we'd target. Terms are grouped by intent - from highest "
        "to lowest conversion likelihood.",
        styles["body"]))
    _spacer(story, 2)

    suburb  = submission.get("suburb", "")
    state   = submission.get("state", "")
    spec    = submission.get("primary_specialty", "clinic")
    spec_lc = spec.lower()
    appt    = submission.get("appointment_types_to_grow", "")

    # Derive short specialty label (e.g. "Physiotherapy" → "physio")
    _abbrev_map = {
        "physiotherapy": "physio", "chiropractic": "chiropractor", "chiro": "chiropractor",
        "psychology": "psychologist", "osteopathy": "osteopath", "osteo": "osteopath",
        "podiatry": "podiatrist", "naturopathy": "naturopath", "dentistry": "dentist",
        "dental": "dentist", "optometry": "optometrist", "dietitian": "dietitian",
        "speech pathology": "speech pathologist", "occupational therapy": "occupational therapist",
    }
    abbrev = next((v for k, v in _abbrev_map.items() if k in spec_lc), spec_lc.split()[0])

    kw_groups = [
        {
            "group": "Location - highest intent",
            "match": "Exact / Phrase",
            "color": GREEN_OK,
            "keywords": [
                f"{abbrev} {suburb.lower()}",
                f"{abbrev} near me",
                f"best {abbrev} {suburb.lower()}",
                f"{abbrev} {state.lower()}",
                f"{spec_lc} clinic {suburb.lower()}",
            ],
            "note": "Searchers with strong local intent. Highest conversion rate.",
        },
        {
            "group": "Condition / Symptom",
            "match": "Phrase / Broad Match Modified",
            "color": PURPLE,
            "keywords": _condition_keywords(spec_lc, suburb, appt),
            "note": "Patients describing their problem, not the solution. High volume, slightly lower intent.",
        },
        {
            "group": "Service-specific",
            "match": "Exact / Phrase",
            "color": AMBER,
            "keywords": _service_keywords(spec_lc, suburb, appt),
            "note": "Based on appointment types to grow. Targets patients already knowing what they need.",
        },
        {
            "group": "Negative keywords (add immediately)",
            "match": "Exact negative",
            "color": RED_WARN,
            "keywords": _negative_keywords(spec_lc),
            "note": "Add these before launch to block irrelevant traffic - jobs, courses, free services.",
        },
    ]

    for grp in kw_groups:
        hdr_style = ParagraphStyle("kh", fontName="Helvetica-Bold", fontSize=9,
                                   textColor=WHITE, leading=13)
        sub_style = ParagraphStyle("ks", fontName="Helvetica", fontSize=8,
                                   textColor=WHITE, leading=11)
        kw_text   = "  |  ".join(grp["keywords"])

        rows = [
            [Paragraph(grp["group"], hdr_style),
             Paragraph(f"Match type: {grp['match']}", sub_style)],
            [Paragraph(kw_text, styles["body"]), ""],
            [Paragraph(f"💡 {grp['note']}", styles["small"]), ""],
        ]
        kw_tbl = Table(rows, colWidths=[CONTENT_W * 0.70, CONTENT_W * 0.30])
        kw_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), grp["color"]),
            ("SPAN", (0, 1), (-1, 1)),
            ("SPAN", (0, 2), (-1, 2)),
            ("BACKGROUND", (0, 1), (-1, 1), WHITE),
            ("BACKGROUND", (0, 2), (-1, 2), LIGHT_BG),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ]))
        story.append(kw_tbl)
        _spacer(story, 2)

    _spacer(story, 2)

    # ── Campaign structure ─────────────────────────────────────────────────────
    _spacer(story, 10)
    story.append(Paragraph("Example Campaign Structure", styles["section"]))
    _rule(story)

    story.append(Paragraph(
        "A well-structured account separates intent types so Google can optimise each "
        "independently. Below is how we'd set up the first 90 days for this clinic.",
        styles["body"]))
    _spacer(story, 2)

    ad_spend   = float(submission.get("monthly_ad_spend", 0) or 0)
    # Budget split guidance: 70% location/core, 30% condition/symptom
    # Note: remarketing is excluded — Google restricts healthcare remarketing
    budget_core  = ad_spend * 0.70 if ad_spend else None
    budget_cond  = ad_spend * 0.30 if ad_spend else None

    campaigns = [
        {
            "name": f"Search - {spec} | {suburb} (Core)",
            "budget": _fmt_d(budget_core) + "/mo" if budget_core else "~70% of budget",
            "type": "Search",
            "bidding": "Maximise Conversions (switch to Target CPA after 30+ conversions)",
            "ad_groups": [
                f"{abbrev} {suburb} - [exact location terms]",
                f"{abbrev} near me - [proximity intent]",
                f"best {abbrev} - [quality seekers]",
            ],
            "notes": "Tightest control. Use exact and phrase match only. "
                     "Enable location extensions and call extensions from day one.",
        },
        {
            "name": f"Search - {spec} | Condition/Symptom",
            "budget": _fmt_d(budget_cond) + "/mo" if budget_cond else "~30% of budget",
            "type": "Search",
            "bidding": "Maximise Clicks initially, then Maximise Conversions",
            "ad_groups": [g for g in _condition_keywords(spec_lc, suburb, appt)[:3]],
            "notes": "Higher volume, lower intent. Monitor search term report weekly "
                     "and aggressively add negatives. Separate ad groups per condition.",
        },
    ]

    camp_rows = [["Campaign", "Type", "Budget", "Bidding Strategy"]]
    for c in campaigns:
        camp_rows.append([
            Paragraph(f"<b>{c['name']}</b>", styles["body_bold"]),
            Paragraph(c["type"], styles["small"]),
            Paragraph(c["budget"], styles["small"]),
            Paragraph(c["bidding"], styles["small"]),
        ])
    camp_tbl = Table(camp_rows, colWidths=[70*mm, 30*mm, 26*mm, 48*mm], repeatRows=1)
    camp_tbl.setStyle(_tbl_style())
    story.append(camp_tbl)
    _spacer(story, 2)

    # Ad group detail per campaign
    for c in campaigns:
        story.append(Paragraph(c["name"], styles["subsection"]))
        ag_rows = [["Ad Groups", "Notes"]]
        ag_rows.append([
            Paragraph("\n".join(f"• {ag}" for ag in c["ad_groups"]), styles["body"]),
            Paragraph(c["notes"], styles["small"]),
        ])
        ag_tbl = Table(ag_rows, colWidths=[90*mm, 84*mm], repeatRows=1)
        ag_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BG),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ag_tbl)
        _spacer(story, 2)

    _spacer(story, 2)

    # ── Next steps ─────────────────────────────────────────────────────────────
    _spacer(story, 10)
    story.append(Paragraph("Suggested Next Steps", styles["section"]))
    _rule(story)

    next_steps = [
        ("1", "Schedule strategy call",
         f"Review this brief with {clinic_name} and identify the biggest growth lever "
         f"based on their goal: \"{submission.get('main_goal','')}\"."),
        ("2", "Benchmark ad spend",
         f"Monthly spend of {_fmt_d(ad_spend)} for {new_pts} new patients/month. "
         f"Run a market-rate comparison for {submission.get('primary_specialty','')} "
         f"in {submission.get('suburb','')}, {submission.get('state','')}."),
        ("3", "Request Google Ads access",
         "Audit not possible without account access. Consider requesting this on the call "
         "to unlock the full analysis and wasted spend identification."),
    ]

    rows = [["", "Step", "Detail"]]
    for num, step, detail in next_steps:
        rows.append([
            Paragraph(f"<b>{num}</b>", ParagraphStyle("n", fontName="Helvetica-Bold",
                      fontSize=11, textColor=WHITE, alignment=TA_CENTER)),
            Paragraph(f"<b>{step}</b>", styles["body_bold"]),
            Paragraph(detail, styles["body"]),
        ])

    col_w = [10*mm, 45*mm, 119*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,0), PURPLE),
        ("TEXTCOLOR", (0,0),(-1,0), WHITE),
        ("FONTNAME", (0,0),(-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0),(-1,0), 8),
        ("BACKGROUND", (0,1),(0,-1), PURPLE),
        ("TOPPADDING", (0,0),(-1,-1), 7),
        ("BOTTOMPADDING", (0,0),(-1,-1), 7),
        ("FONTNAME", (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE", (0,1),(-1,-1), 8),
        ("ROWBACKGROUNDS", (1,1),(-1,-1), [WHITE, LIGHT_BG]),
        ("GRID", (0,0),(-1,-1), 0.5, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0,0),(-1,-1), "TOP"),
        ("ALIGN", (0,0),(0,-1), "CENTER"),
    ]))
    story.append(tbl)
    _spacer(story, 2)

    _gold_rule(story)
    story.append(Paragraph(
        "Generated automatically by Clinic Mastery's intake system - clinicmastery.com",
        styles["small"]))

    brief_cb = _make_page_cb(clinic_name, datetime.utcnow().isoformat(), "Clinic Growth Brief")
    doc.build(story, onFirstPage=brief_cb, onLaterPages=brief_cb)
    return buffer.getvalue()


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_pdf(ads_data: dict, clinic_name: str) -> bytes:
    """
    Generates the full branded audit PDF.

    Args:
        ads_data:    Summary dict from google_ads.pull_account_data()
        clinic_name: Clinic name for the header

    Returns:
        PDF as bytes, ready to attach to an email.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=16*mm, bottomMargin=22*mm,
        title=f"Google Ads Audit - {clinic_name}",
        author="Clinic Mastery",
    )

    styles = _styles()
    story  = []
    pulled_at = ads_data.get("pulled_at", datetime.utcnow().isoformat())

    _page_header(story, styles, clinic_name, pulled_at)
    _spacer(story, 2)

    story.append(Paragraph(
        f"This report covers the Google Ads account linked to <b>{clinic_name}</b> "
        f"for the 90-day period ending {pulled_at[:10]}. It identifies wasted spend, "
        f"impression share lost to budget and ad rank, irrelevant traffic, brand vs non-brand split, "
        f"conversion tracking health, and quality score issues - with a prioritised fix list at the end.",
        styles["body"]))
    _spacer(story, 2)

    _section_snapshot(story, styles, ads_data)
    _section_campaigns(story, styles, ads_data)
    _section_visibility(story, styles, ads_data)
    _section_wasted(story, styles, ads_data)
    _section_irrelevant(story, styles, ads_data)
    _section_brand(story, styles, ads_data)
    _section_conversion(story, styles, ads_data)
    _section_quality(story, styles, ads_data)
    _section_priorities(story, styles, ads_data)

    page_cb = _make_page_cb(clinic_name, pulled_at)
    doc.build(story, onFirstPage=page_cb, onLaterPages=page_cb)
    return buffer.getvalue()
