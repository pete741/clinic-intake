"""
Public API for Clinic Mastery PDFs.

The Google Ads audit and intake brief generators delegate to pdf_report_v2
(HTML + WeasyPrint, new brand design). The legacy ReportLab implementations
have been removed. v2 is the only path. Do not reintroduce a fallback.

Still ReportLab in this module:
  * generate_website_audit  (separate report, different brand template)
  * shared keyword helpers used by pdf_report_v2 (_condition_keywords,
    _service_keywords, _negative_keywords)
  * the prospect/intake email-draft builders
"""

import io
import os
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


# ── Prospect email draft ──────────────────────────────────────────────────────

def generate_prospect_email_draft(clinic_name: str, ads_data: dict, contact_name: str = "") -> str:
    """
    Generates a plain-text draft email pete can copy and send
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

    greeting = f"Hi {contact_name}," if contact_name else "Hi,"

    draft = f"""Subject: Your Google Ads analysis is ready - {clinic_name}

{greeting}

I've had a look through your Google Ads account and put together a full analysis - attached as a PDF.

Here are the main things that stood out:

{findings_text}

I've outlined the specific fixes and what I'd prioritise first in the report.

I'd love to walk you through it on a call - usually takes about 20 minutes and by the end you'll have a clear picture of exactly what to change, what it's costing you right now, and how we can drive a higher ROI from your ad spend.

Find a time that suits you here: https://bookings.clinicmastery.com/pete-flynn-google-ads

Pete Flynn
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

Find a time that suits you here: https://bookings.clinicmastery.com/pete-flynn-google-ads

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
        "naturopath": [
            f"naturopath {suburb_lc}", "gut health specialist",
            "hormone imbalance treatment", "chronic fatigue help",
            "ibs treatment naturopath", "womens health naturopath",
        ],
        "nutrition": [
            f"nutritionist {suburb_lc}", "weight loss program",
            "gut health nutritionist", "fatigue nutrition",
            "fertility nutritionist", "ibs nutritionist",
        ],
        "dietitian": [
            f"dietitian {suburb_lc}", "weight management dietitian",
            "diabetes dietitian", "ibs dietitian",
            "ndis dietitian", "paediatric dietitian",
        ],
        "speech": [
            f"speech pathologist {suburb_lc}", "speech therapy for kids",
            "stuttering therapy", "swallowing therapy",
            "ndis speech pathology", "adult speech therapy",
        ],
        "occupational": [
            f"occupational therapist {suburb_lc}", "ndis occupational therapy",
            "paediatric occupational therapy", "sensory processing therapy",
            "hand therapy", "adult occupational therapy",
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
        "naturopath": [f"naturopath consultation {suburb_lc}", "gut health consultation",
                       "hormone testing naturopath", "fertility naturopath",
                       "thyroid naturopath", "perimenopause naturopath"],
        "herbal": ["herbal medicine consultation", "herbal medicine naturopath"],
        "iridology": ["iridology consultation", f"iridologist {suburb_lc}"],
        "nutrition": [f"nutritionist consultation {suburb_lc}", "meal planning nutritionist",
                      "weight loss nutritionist"],
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
    """Generate the Clinic Growth Brief PDF (v2 design only)."""
    from pdf_report_v2 import generate_intake_brief as _v2
    return _v2(submission)


def generate_pdf(ads_data: dict, clinic_name: str) -> bytes:
    """Generate the Google Ads audit PDF (v2 design only)."""
    from pdf_report_v2 import generate_pdf as _v2
    return _v2(ads_data, clinic_name)



def generate_website_audit(audit_data: dict) -> bytes:
    """Generate the Clinic Mastery website audit PDF (v2 design only)."""
    from pdf_report_v2 import generate_website_audit as _v2
    return _v2(audit_data)
