"""
Generates a branded Clinic Mastery PDF report from Google Ads account data.

Colours:
  Purple  #534AB7  — headings, accents
  Gold    #D4B22F  — logo accent, section rules
  Dark    #1a1a2e  — body text
  Light   #f8f7ff  — shaded rows / background panels
"""

import io
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Brand colours ─────────────────────────────────────────────────────────────
PURPLE      = colors.HexColor("#534AB7")
PURPLE_DARK = colors.HexColor("#3d3589")
GOLD        = colors.HexColor("#D4B22F")
DARK        = colors.HexColor("#1a1a2e")
LIGHT_BG    = colors.HexColor("#f5f3ff")
MID_GREY    = colors.HexColor("#6b7280")
RED_WARN    = colors.HexColor("#dc2626")
GREEN_OK    = colors.HexColor("#16a34a")
WHITE       = colors.white

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=PURPLE,
            leading=28,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="Helvetica",
            fontSize=11,
            textColor=MID_GREY,
            leading=16,
            spaceAfter=6,
        ),
        "section": ParagraphStyle(
            "section",
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=PURPLE,
            leading=18,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=9,
            textColor=DARK,
            leading=14,
        ),
        "body_bold": ParagraphStyle(
            "body_bold",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=DARK,
            leading=14,
        ),
        "small": ParagraphStyle(
            "small",
            fontName="Helvetica",
            fontSize=8,
            textColor=MID_GREY,
            leading=12,
        ),
        "metric_val": ParagraphStyle(
            "metric_val",
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=PURPLE,
            leading=22,
            alignment=TA_CENTER,
        ),
        "metric_lbl": ParagraphStyle(
            "metric_lbl",
            fontName="Helvetica",
            fontSize=8,
            textColor=MID_GREY,
            leading=11,
            alignment=TA_CENTER,
        ),
        "warn": ParagraphStyle(
            "warn",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=RED_WARN,
            leading=13,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName="Helvetica",
            fontSize=8,
            textColor=MID_GREY,
            alignment=TA_CENTER,
        ),
    }


def _rule():
    return HRFlowable(width="100%", thickness=1, color=PURPLE, spaceAfter=8)


def _gold_rule():
    return HRFlowable(width="100%", thickness=2, color=GOLD, spaceAfter=10)


def _fmt_dollars(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_int(value) -> str:
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return str(value)


def _header(story, styles, clinic_name: str, pulled_at: str):
    """Page header: logo left, clinic name + date right."""
    logo_cell = ""
    if LOGO_PATH.exists():
        # Keep logo proportional, max height 18mm
        img = Image(str(LOGO_PATH), width=14 * mm, height=18 * mm, kind="proportional")
        logo_cell = img

    title_para = Paragraph(
        f"Google Ads Audit Report<br/>"
        f"<font size='11' color='#6b7280'>{clinic_name}</font>",
        styles["title"],
    )
    date_para = Paragraph(
        f"Generated {pulled_at[:10]}",
        ParagraphStyle("dr", fontName="Helvetica", fontSize=9,
                       textColor=MID_GREY, alignment=TA_RIGHT),
    )

    header_table = Table(
        [[logo_cell, title_para, date_para]],
        colWidths=[22 * mm, 115 * mm, 38 * mm],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
    ]))
    story.append(header_table)
    story.append(_gold_rule())


def _snapshot_row(story, styles, data: dict):
    """6 key metrics in a coloured band across the page."""
    metrics = [
        (_fmt_dollars(data.get("total_spend_90d", 0)), "Total spend (90 days)"),
        (_fmt_int(data.get("total_conversions_90d", 0)), "Conversions"),
        (_fmt_dollars(data.get("cost_per_conversion", 0)), "Cost per conversion"),
        (str(data.get("num_active_campaigns", 0)), "Active campaigns"),
        (str(len(data.get("wasted_keywords", []))), "Wasted keywords found"),
        (str(data.get("avg_quality_score", "—")), "Avg quality score"),
    ]

    cells = []
    for val, lbl in metrics:
        cells.append([
            Paragraph(val, styles["metric_val"]),
            Paragraph(lbl, styles["metric_lbl"]),
        ])

    tbl = Table([cells], colWidths=[(PAGE_W - 2 * MARGIN) / 6] * 6)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 1, PURPLE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ROUNDEDCORNERS", [4]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))


def _campaigns_table(story, styles, campaigns: list):
    story.append(Paragraph("Campaign Performance — Last 90 Days", styles["section"]))
    story.append(_rule())

    if not campaigns:
        story.append(Paragraph("No campaign data found.", styles["body"]))
        return

    headers = ["Campaign", "Status", "Spend", "Conversions", "Conv. Cost", "CTR"]
    rows = [headers]
    for c in campaigns:
        rows.append([
            Paragraph(c.get("name", ""), styles["body"]),
            c.get("status", ""),
            _fmt_dollars(c.get("spend", 0)),
            str(c.get("conversions", 0)),
            _fmt_dollars(c.get("spend", 0) / c["conversions"] if c.get("conversions") else 0)
            if c.get("conversions") else "—",
            f"{c.get('ctr', 0):.1f}%",
        ])

    col_w = [75 * mm, 20 * mm, 22 * mm, 22 * mm, 22 * mm, 14 * mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), PURPLE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        # Data rows
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6))


def _wasted_table(story, styles, keywords: list):
    story.append(Paragraph("Wasted Spend — Keywords With Spend > $50 & Zero Conversions", styles["section"]))
    story.append(_rule())

    if not keywords:
        story.append(Paragraph(
            "✓ No significant wasted keywords identified in this period.",
            ParagraphStyle("ok", fontName="Helvetica-Bold", fontSize=9,
                           textColor=GREEN_OK, leading=13)
        ))
        story.append(Spacer(1, 6))
        return

    total_wasted = sum(k.get("spend", 0) for k in keywords)
    story.append(Paragraph(
        f"<b>Total wasted spend identified: {_fmt_dollars(total_wasted)}</b> "
        f"across {len(keywords)} keyword{'s' if len(keywords) != 1 else ''}.",
        styles["warn"],
    ))
    story.append(Spacer(1, 6))

    headers = ["Keyword", "Match Type", "Spend", "Clicks", "Impressions", "Quality Score"]
    rows = [headers]
    for k in keywords:
        rows.append([
            Paragraph(k.get("keyword", ""), styles["body"]),
            k.get("match_type", "").replace("_", " ").title(),
            _fmt_dollars(k.get("spend", 0)),
            _fmt_int(k.get("clicks", 0)),
            _fmt_int(k.get("impressions", 0)),
            str(k.get("quality_score", "—")),
        ])

    col_w = [72 * mm, 22 * mm, 20 * mm, 16 * mm, 22 * mm, 23 * mm]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), RED_WARN),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#fff5f5")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6))


def _footer(canvas, doc):
    """Draws page number and branding at the bottom of every page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(
        PAGE_W / 2,
        12 * mm,
        f"Clinic Mastery — Confidential  |  clinicmastery.com  |  Page {doc.page}",
    )
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.5)
    canvas.line(MARGIN, 16 * mm, PAGE_W - MARGIN, 16 * mm)
    canvas.restoreState()


def generate_pdf(ads_data: dict, clinic_name: str) -> bytes:
    """
    Generates the branded PDF report and returns it as bytes.

    Args:
        ads_data:    The summary dict returned by google_ads.pull_account_data()
        clinic_name: The clinic's name (used in the header)

    Returns:
        PDF file contents as bytes, ready to attach to an email.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=22 * mm,  # room for footer
        title=f"Google Ads Audit — {clinic_name}",
        author="Clinic Mastery",
    )

    styles = _styles()
    story = []

    pulled_at = ads_data.get("pulled_at", datetime.utcnow().isoformat())

    # Header
    _header(story, styles, clinic_name, pulled_at)
    story.append(Spacer(1, 6))

    # Intro blurb
    story.append(Paragraph(
        f"This report contains a full analysis of the Google Ads account linked to "
        f"<b>{clinic_name}</b>, based on the last 90 days of data pulled on "
        f"{pulled_at[:10]}. Use this to identify wasted spend and prioritise fixes "
        f"before your strategy call.",
        styles["body"],
    ))
    story.append(Spacer(1, 10))

    # Snapshot metrics band
    _snapshot_row(story, styles, ads_data)

    # Campaign table
    _campaigns_table(story, styles, ads_data.get("top_campaigns", []))

    # Wasted spend table
    _wasted_table(story, styles, ads_data.get("wasted_keywords", []))

    # Quality score note
    qs = ads_data.get("avg_quality_score", 0)
    story.append(Paragraph("Quality Score Summary", styles["section"]))
    story.append(_rule())
    qs_colour = GREEN_OK if qs >= 7 else (GOLD if qs >= 5 else RED_WARN)
    qs_comment = (
        "Above average — good relevance between keywords, ads and landing pages."
        if qs >= 7
        else "Below average — keyword/ad/landing page alignment needs attention."
        if qs < 5
        else "Average — some optimisation opportunity exists."
    )
    story.append(Paragraph(
        f"Average quality score across all keywords: <b>{qs}/10</b>. {qs_comment}",
        styles["body"],
    ))
    story.append(Spacer(1, 16))

    # Closing note
    story.append(_gold_rule())
    story.append(Paragraph(
        "This report was generated automatically by Clinic Mastery's intake system. "
        "Full account access is read-only and can be revoked at any time via "
        "Google Ads → Admin → Access and security.",
        styles["small"],
    ))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
