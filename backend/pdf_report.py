"""
Generates a branded Clinic Mastery Google Ads audit PDF.

Sections:
  1. Cover / headline metrics snapshot
  2. Campaign performance (last 90 days)
  3. Wasted spend — high cost, zero conversions
  4. Irrelevant search terms (from search term report)
  5. Brand vs non-brand spend split
  6. Conversion tracking health check
  7. Quality score breakdown
  8. Priority fix list

Colours:
  Purple  #534AB7  — headings, accents
  Gold    #D4B22F  — logo, rules
  Dark    #1a1a2e  — body text
  Light   #f5f3ff  — shaded rows / panels
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
                                  textColor=PURPLE, leading=18, spaceBefore=14, spaceAfter=6),
        "subsection": ParagraphStyle("subsection", fontName="Helvetica-Bold", fontSize=10,
                                     textColor=DARK, leading=14, spaceBefore=8, spaceAfter=4),
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
        "metric_val": ParagraphStyle("metric_val", fontName="Helvetica-Bold", fontSize=18,
                                     textColor=PURPLE, leading=22, alignment=TA_CENTER),
        "metric_lbl": ParagraphStyle("metric_lbl", fontName="Helvetica", fontSize=8,
                                     textColor=MID_GREY, leading=11, alignment=TA_CENTER),
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
    story.append(HRFlowable(width="100%", thickness=1, color=PURPLE, spaceAfter=8))

def _gold_rule(story):
    story.append(HRFlowable(width="100%", thickness=2, color=GOLD, spaceAfter=10))

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
    except: return "—"

def _tbl_style(header_bg=PURPLE, stripe=LIGHT_BG):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
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
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(tbl)
    _spacer(story, 6)


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


def _footer_cb(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(PAGE_W/2, 12*mm,
        f"Clinic Mastery — Confidential  |  clinicmastery.com  |  Page {doc.page}")
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.5)
    canvas.line(MARGIN, 16*mm, PAGE_W-MARGIN, 16*mm)
    canvas.restoreState()


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
        (str(data.get("avg_quality_score", "—")),            "Avg quality score /10"),
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
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    _spacer(story, 10)


def _section_campaigns(story, styles, data: dict):
    story.append(Paragraph("1. Campaign Performance — Last 90 Days", styles["section"]))
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
            _fmt_d(spend / conv) if conv else "—",
            f"{c.get('ctr', 0):.1f}%",
        ])

    col_w = [68*mm, 18*mm, 20*mm, 18*mm, 14*mm, 22*mm, 14*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    story.append(tbl)
    _spacer(story, 6)

    _info_box(story, styles,
        "💡 <b>What to look for:</b> Campaigns with high spend and low (or zero) conversions "
        "are your biggest optimisation opportunity. A cost per conversion more than 3× your "
        "average appointment fee is a red flag.")


def _section_wasted(story, styles, data: dict):
    story.append(Paragraph("2. Wasted Spend — High Cost, Zero Conversions", styles["section"]))
    _rule(story)

    keywords = data.get("wasted_keywords", [])
    if not keywords:
        story.append(Paragraph("✓ No significant wasted keywords found in this period.", styles["ok"]))
        _spacer(story, 6)
        return

    total = sum(k.get("spend", 0) for k in keywords)
    story.append(Paragraph(
        f"<b>Total wasted spend: {_fmt_d(total)}</b> across {len(keywords)} "
        f"keyword{'s' if len(keywords)!=1 else ''} with spend over $50 and zero conversions.",
        styles["warn"]))
    _spacer(story, 6)

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
            str(qs) if qs else "—",
            Paragraph(action, styles["small"]),
        ])

    col_w = [55*mm, 20*mm, 18*mm, 14*mm, 22*mm, 20*mm, 25*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style(header_bg=RED_WARN, stripe=RED_LIGHT))
    story.append(tbl)
    _spacer(story, 6)

    _info_box(story, styles,
        "💡 <b>Recommended action:</b> Pause these keywords immediately and add the "
        "high-spend ones as exact-match negatives at the campaign level. This alone "
        f"could recover up to {_fmt_d(total)} per 90-day period.",
        bg=RED_LIGHT, border=RED_WARN)


def _section_irrelevant(story, styles, data: dict):
    story.append(Paragraph("3. Irrelevant Search Terms", styles["section"]))
    _rule(story)

    terms = data.get("irrelevant_terms", [])

    story.append(Paragraph(
        "These are actual search queries that triggered your ads. They are clearly "
        "unrelated to your clinic's services — people who would never become patients. "
        "Each click costs money with zero chance of conversion.",
        styles["body"]))
    _spacer(story, 8)

    if not terms:
        story.append(Paragraph(
            "✓ No clearly irrelevant search terms identified in this period. "
            "Consider running a manual search term report in Google Ads for further review.",
            styles["ok"]))
        _spacer(story, 6)
        return

    total = sum(t.get("spend", 0) for t in terms)
    story.append(Paragraph(
        f"<b>{_fmt_d(total)} spent on irrelevant searches</b> across {len(terms)} terms.",
        styles["warn"]))
    _spacer(story, 6)

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
    _spacer(story, 6)

    _info_box(story, styles,
        "💡 <b>Fix:</b> Add all of these as exact-match negative keywords at the account level. "
        "Review your search terms report monthly — broad match and phrase match campaigns "
        "generate irrelevant traffic over time as Google's matching expands.",
        bg=AMBER_LIGHT, border=AMBER)


def _section_brand(story, styles, data: dict):
    story.append(Paragraph("4. Brand Keyword Spend — A Healthcare-Specific Problem", styles["section"]))
    _rule(story)

    brand     = data.get("brand_spend", 0)
    non_brand = data.get("non_brand_spend", 0)
    total     = brand + non_brand or 1
    brand_pct = brand / total * 100

    # In healthcare, brand spend is ALWAYS flagged as a problem.
    # People searching a clinic name already know it — they are not new patients.
    # Brand ads intercept existing demand and inflate conversion rates without
    # generating growth. This is fundamentally different from e-commerce.
    story.append(Paragraph(
        "<b>In healthcare, brand keyword spend is almost always wasted money.</b> "
        "Unlike e-commerce, people searching your clinic name are <i>existing patients, "
        "referrals, or people who already decided to book</i> — they were going to find "
        "you regardless. Paying Google to intercept them inflates your conversion rate "
        "and makes your account look better than it is, while doing nothing to grow "
        "your actual patient base.",
        styles["warn"]))
    _spacer(story, 8)

    rows = [
        ["", "Spend", "% of Budget", "Who's Searching", "Verdict"],
        [
            "Brand keywords",
            _fmt_d(brand),
            f"{brand_pct:.1f}%",
            "Existing patients, referrals, people who already chose you",
            Paragraph("✗ Wasted on existing demand", styles["tag_red"]),
        ],
        [
            "Non-brand keywords",
            _fmt_d(non_brand),
            f"{100-brand_pct:.1f}%",
            "New patients actively searching for a clinic",
            Paragraph("✓ This is real growth spend", styles["tag_green"]),
        ],
    ]

    col_w = [35*mm, 22*mm, 22*mm, 62*mm, 33*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    story.append(tbl)
    _spacer(story, 6)

    if brand_pct > 0:
        _info_box(story, styles,
            f"⚠ <b>{_fmt_d(brand)} ({brand_pct:.0f}% of budget) is being spent on brand searches.</b> "
            "These are not new patients. Removing brand keywords from your non-brand campaigns "
            "and either eliminating them entirely — or capping them in a separate low-budget "
            "brand campaign — would redirect this spend toward genuine patient acquisition. "
            "Your conversion rate will drop, but your <i>real</i> cost per new patient will improve.",
            bg=RED_LIGHT, border=RED_WARN)


def _section_conversion(story, styles, data: dict):
    story.append(Paragraph("5. Conversion Tracking Health Check", styles["section"]))
    _rule(story)

    story.append(Paragraph(
        "Conversion tracking tells Google which clicks led to a patient booking or enquiry. "
        "Without accurate tracking, Google's algorithm is optimising blind — spending more "
        "on clicks that <i>look</i> similar to converting clicks but aren't.",
        styles["body"]))
    _spacer(story, 8)

    issues = data.get("conversion_issues", [])
    checks = [
        {
            "check": "Conversions being recorded",
            "status": "ok" if data.get("total_conversions_90d", 0) > 0 else "fail",
            "detail": (
                f"{data.get('total_conversions_90d', 0)} conversions recorded in 90 days."
                if data.get("total_conversions_90d", 0) > 0
                else "Zero conversions recorded. Tracking may be broken or not set up."
            ),
        },
        {
            "check": "Conversion rate is plausible",
            "status": "ok" if 1 < (data.get("total_conversions_90d", 0) /
                                   max(sum(c.get("clicks",0) for c in data.get("top_campaigns",[])), 1) * 100) < 20
                     else "warn",
            "detail": "A conversion rate below 1% usually means tracking is missing clicks, "
                      "above 20% often means duplicate conversion events are firing.",
        },
        {
            "check": "Cost per conversion vs appointment fee",
            "status": (
                "ok"   if data.get("cost_per_conversion", 0) < data.get("avg_appointment_fee", 999) else
                "warn" if data.get("cost_per_conversion", 0) < data.get("avg_appointment_fee", 999) * 3 else
                "fail"
            ),
            "detail": (
                f"Cost per conversion is {_fmt_d(data.get('cost_per_conversion', 0))} vs "
                f"avg appointment fee of {_fmt_d(data.get('avg_appointment_fee', 0))}. "
                + ("This is healthy." if data.get("cost_per_conversion", 0) < data.get("avg_appointment_fee", 999)
                   else "This needs attention — acquisition cost exceeds appointment value.")
            ),
        },
    ]
    # Append any extra issues from the data
    for issue in issues:
        checks.append({"check": issue.get("check",""), "status": issue.get("status","warn"),
                       "detail": issue.get("detail","")})

    rows = [["Check", "Status", "Detail"]]
    for c in checks:
        status_map = {
            "ok":   Paragraph("✓ Pass", styles["tag_green"]),
            "warn": Paragraph("⚠ Review", styles["tag_amber"]),
            "fail": Paragraph("✗ Issue", styles["tag_red"]),
        }
        rows.append([
            Paragraph(c["check"], styles["body_bold"]),
            status_map.get(c["status"], status_map["warn"]),
            Paragraph(c["detail"], styles["body"]),
        ])

    col_w = [55*mm, 22*mm, 97*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    story.append(tbl)
    _spacer(story, 6)

    _info_box(story, styles,
        "💡 <b>To verify conversion tracking:</b> In Google Ads → Tools → Measurement → "
        "Conversions. Each conversion action should show 'Recording conversions' in green. "
        "If any show 'No recent conversions' or 'Inactive', tracking needs fixing before "
        "increasing spend.")


def _section_quality(story, styles, data: dict):
    story.append(Paragraph("6. Quality Score Breakdown", styles["section"]))
    _rule(story)

    qs = data.get("avg_quality_score", 0)
    story.append(Paragraph(
        "Quality Score (1–10) measures how relevant your keywords, ads and landing pages "
        "are to each other. A low score means Google charges you <i>more per click</i> "
        "than competitors with better-structured accounts.",
        styles["body"]))
    _spacer(story, 8)

    # QS bands breakdown
    keywords = data.get("wasted_keywords", []) + data.get("irrelevant_terms", [])
    qs_scores = [k.get("quality_score", 0) for k in keywords if k.get("quality_score", 0) > 0]

    poor   = sum(1 for q in qs_scores if q <= 4)
    avg_qs = sum(1 for q in qs_scores if 5 <= q <= 6)
    good   = sum(1 for q in qs_scores if q >= 7)
    total  = len(qs_scores) or 1

    rows = [
        ["Quality Score Band", "Keywords", "% of Total", "Impact", "Priority"],
        ["Poor (1–4)",   str(poor),   _pct(poor, total),   "Paying premium CPC",    Paragraph("Fix first", styles["tag_red"])],
        ["Average (5–6)", str(avg_qs), _pct(avg_qs, total), "Slightly above market", Paragraph("Improve", styles["tag_amber"])],
        ["Good (7–10)",  str(good),   _pct(good, total),   "Competitive CPC",       Paragraph("Maintain", styles["tag_green"])],
    ]

    col_w = [45*mm, 25*mm, 25*mm, 50*mm, 29*mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    story.append(tbl)
    _spacer(story, 6)

    qs_comment = (
        f"Average quality score is <b>{qs}/10</b> — "
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
    story.append(Paragraph("7. Priority Fix List", styles["section"]))
    _rule(story)

    story.append(Paragraph(
        "Ranked by estimated impact. Address these before your strategy call.",
        styles["body"]))
    _spacer(story, 8)

    wasted       = data.get("wasted_keywords", [])
    irrelevant   = data.get("irrelevant_terms", [])
    qs           = data.get("avg_quality_score", 0)
    conv_issues  = data.get("total_conversions_90d", 1) == 0
    brand_pct    = (data.get("brand_spend", 0) /
                   (data.get("brand_spend", 0) + data.get("non_brand_spend", 0) + 0.01) * 100)

    priorities = []

    if conv_issues:
        priorities.append(("🔴", "Fix conversion tracking",
            "Zero conversions recorded — Google is optimising blind. "
            "Check Tools → Conversions in Google Ads and fix before increasing budget.",
            "Critical"))

    if wasted:
        total_waste = sum(k.get("spend",0) for k in wasted)
        priorities.append(("🔴", f"Pause {len(wasted)} wasted keywords",
            f"Estimated {_fmt_d(total_waste)} recoverable per 90 days. "
            "Pause these immediately and add as exact-match negatives.",
            "High"))

    if irrelevant:
        irrel_waste = sum(t.get("spend",0) for t in irrelevant)
        priorities.append(("🟠", f"Add {len(irrelevant)} irrelevant search terms as negatives",
            f"{_fmt_d(irrel_waste)} spent on searches with zero patient intent. "
            "Add as exact-match negatives at account level.",
            "High"))

    if qs < 5:
        priorities.append(("🟠", "Rewrite ad copy to improve quality scores",
            f"Average QS of {qs}/10 means you're paying above-market CPC. "
            "Tighten keyword → ad copy → landing page alignment for each ad group.",
            "Medium"))

    if brand_pct > 0:
        priorities.append(("🔴", f"Remove brand keywords from growth campaigns ({_fmt_d(data.get('brand_spend',0))} at risk)",
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
    _spacer(story, 12)

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
    brand        = ads_data.get("brand_spend", 0)
    non_brand    = ads_data.get("non_brand_spend", 0)
    brand_pct    = brand / (brand + non_brand + 0.01) * 100
    total_waste  = sum(k.get("spend",0) for k in wasted) + sum(t.get("spend",0) for t in irrelevant)
    spend_90d    = ads_data.get("total_spend_90d", 0)
    cost_per_conv = ads_data.get("cost_per_conversion", 0)
    qs           = ads_data.get("avg_quality_score", 0)

    # Build 2-3 punchy findings
    findings = []
    if total_waste > 0:
        findings.append(
            f"- We identified ${total_waste:,.0f} in wasted spend over the last 90 days — "
            f"keywords and search terms eating budget with zero patient bookings."
        )
    if brand_pct > 5:
        findings.append(
            f"- {brand_pct:.0f}% of your budget ({_fmt_d(brand)}) is going to brand keyword searches. "
            f"In healthcare, these are existing patients and referrals — not new ones. "
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
        "- Your account data is attached in full — there are several clear optimisation opportunities."

    draft = f"""Subject: Your Google Ads analysis is ready — {clinic_name}

Hi [First name],

I've had a look through your Google Ads account and put together a full analysis — attached as a PDF.

Here are the main things that stood out:

{findings_text}

I've outlined the specific fixes and what I'd prioritise first in the report.

Happy to walk through it with you on a quick call — usually takes about 20 minutes and by the end you'll have a clear picture of exactly what to change and what it's worth.

Are you free [suggest a time]?

Pete
Clinic Mastery
pete@clinicmastery.com"""

    return draft


# ── Standard intake brief (no Google Ads data) ───────────────────────────────

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
        title=f"Intake Brief — {clinic_name}",
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
        f"Google Ads account access was not provided — this brief is based on "
        f"the information submitted in the form.",
        styles["body"]))
    _spacer(story, 12)

    # ── Clinic snapshot ───────────────────────────────────────────────────────
    story.append(Paragraph("Clinic Snapshot", styles["section"]))
    _rule(story)

    snap_rows = [
        ["Clinic name",     clinic_name],
        ["Specialty",       submission.get("primary_specialty", "—")],
        ["Location",        f"{submission.get('suburb','—')}, {submission.get('state','—')}"],
        ["Practitioners",   str(submission.get("num_practitioners", "—"))],
        ["Website",         submission.get("website_url", "—")],
        ["Email",           submission.get("email", "—")],
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
    _spacer(story, 10)

    # ── Revenue context ───────────────────────────────────────────────────────
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
        ["Appointment types to grow", submission.get("appointment_types_to_grow", "—")],
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
    _spacer(story, 6)

    _info_box(story, styles,
        f"💡 At an estimated LTV of {_fmt_d(ltv)} per patient, each additional new patient "
        f"per month is worth approximately {_fmt_d(ltv * 12)} in annual revenue. "
        f"With {new_pts} new patients currently per month, there's a clear growth lever here.")

    # ── Goals ─────────────────────────────────────────────────────────────────
    story.append(Paragraph("Goals & Context", styles["section"]))
    _rule(story)

    goal_rows = [
        ["Main goal",          submission.get("main_goal", "—")],
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
    _spacer(story, 10)

    # ── Next steps ─────────────────────────────────────────────────────────────
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
    _spacer(story, 12)

    _gold_rule(story)
    story.append(Paragraph(
        "Generated automatically by Clinic Mastery's intake system — clinicmastery.com",
        styles["small"]))

    doc.build(story, onFirstPage=_footer_cb, onLaterPages=_footer_cb)
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
        topMargin=MARGIN, bottomMargin=22*mm,
        title=f"Google Ads Audit — {clinic_name}",
        author="Clinic Mastery",
    )

    styles = _styles()
    story  = []
    pulled_at = ads_data.get("pulled_at", datetime.utcnow().isoformat())

    _page_header(story, styles, clinic_name, pulled_at)
    _spacer(story, 4)

    story.append(Paragraph(
        f"This report covers the Google Ads account linked to <b>{clinic_name}</b> "
        f"for the 90-day period ending {pulled_at[:10]}. It identifies wasted spend, "
        f"irrelevant traffic, brand vs non-brand split, conversion tracking health, "
        f"and quality score issues — with a prioritised fix list at the end.",
        styles["body"]))
    _spacer(story, 10)

    _section_snapshot(story, styles, ads_data)
    _section_campaigns(story, styles, ads_data)
    story.append(PageBreak())
    _page_header(story, styles, clinic_name, pulled_at)
    _section_wasted(story, styles, ads_data)
    _section_irrelevant(story, styles, ads_data)
    story.append(PageBreak())
    _page_header(story, styles, clinic_name, pulled_at)
    _section_brand(story, styles, ads_data)
    _section_conversion(story, styles, ads_data)
    _section_quality(story, styles, ads_data)
    _section_priorities(story, styles, ads_data)

    doc.build(story, onFirstPage=_footer_cb, onLaterPages=_footer_cb)
    return buffer.getvalue()
