"""
Sends emails for the clinic intake system via Gmail SMTP.

Two email types:
  1. Google Ads audit — full PDF report + prospect draft email to pete
  2. Intake brief     — standard brief PDF for clinics without Google Ads access

Requires in .env:
  GMAIL_ADDRESS      — sending Gmail address (e.g. pete@clinicmastery.com)
  GMAIL_APP_PASSWORD — Gmail App Password (spaces are stripped automatically)
                       Generate at: myaccount.google.com/apppasswords
"""

import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
NOTIFY_EMAIL       = "pete@clinicmastery.com"


def _send(subject: str, html: str, text: str, pdf_bytes: bytes, filename: str) -> bool:
    """Core send helper — builds the MIME message and sends via Gmail SMTP."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.error("GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set — cannot send email")
        return False

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = NOTIFY_EMAIL

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain"))
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)

    pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
    pdf_part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(pdf_part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.sendmail(GMAIL_ADDRESS, NOTIFY_EMAIL, msg.as_string())
        logger.info(f"Email sent: {subject}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail auth failed. Use an App Password (not your regular password). "
            "Generate at myaccount.google.com/apppasswords"
        )
        return False
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")
        return False


def send_ads_report(clinic_name: str, pdf_bytes: bytes, ads_data: dict) -> bool:
    """
    Emails the Google Ads audit PDF to pete, with a copy-paste prospect
    email draft included in the email body.
    """
    from pdf_report import generate_prospect_email_draft
    draft = generate_prospect_email_draft(clinic_name, ads_data)

    # Escape the draft for HTML display
    draft_html = draft.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br/>")

    subject = f"Google Ads Audit Ready — {clinic_name}"

    html = f"""
<div style="font-family:-apple-system,sans-serif;max-width:640px;margin:0 auto;padding:24px;">

  <div style="background:#534AB7;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:18px;">Google Ads Audit Ready</h1>
    <p style="color:#c4b9f5;margin:4px 0 0;font-size:13px;">{clinic_name}</p>
  </div>

  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-top:none;
              padding:24px;border-radius:0 0 8px 8px;">

    <p style="color:#374151;margin:0 0 16px;">
      The full audit PDF is attached. Key findings are also saved to the
      GHL contact under <strong>Google Ads Intake Form → google_ads_summary</strong>.
    </p>

    <hr style="border:none;border-top:2px solid #D4B22F;margin:20px 0;" />

    <h2 style="font-size:15px;color:#534AB7;margin:0 0 8px;">
      Draft email to send to the clinic
    </h2>
    <p style="color:#6b7280;font-size:12px;margin:0 0 12px;">
      Copy, personalise the bracketed sections, and send with the PDF attached.
    </p>

    <div style="background:#fff;border:1px solid #d1d5db;border-radius:6px;
                padding:16px 20px;font-family:monospace;font-size:13px;
                color:#1a1a2e;line-height:1.6;white-space:pre-wrap;">
{draft_html}
    </div>

  </div>
</div>
"""

    text = f"Google Ads audit for {clinic_name} — PDF attached.\n\n--- DRAFT EMAIL ---\n\n{draft}"

    safe = clinic_name.lower().replace(" ","_").replace("/","-")
    return _send(subject, html, text, pdf_bytes, f"google_ads_audit_{safe}.pdf")


def send_intake_brief(clinic_name: str, pdf_bytes: bytes, submission: dict) -> bool:
    """
    Emails the standard intake brief PDF to pete for clinics that didn't
    provide Google Ads access.
    """
    has_ads = submission.get("has_google_ads") or "Not provided"
    skipped = submission.get("invite_sent") == "skipped"
    reason  = "skipped Google Ads access" if skipped else (
              "doesn't run Google Ads" if "No" in has_ads else "did not provide access")

    subject = f"New Intake Brief — {clinic_name}"

    html = f"""
<div style="font-family:-apple-system,sans-serif;max-width:640px;margin:0 auto;padding:24px;">

  <div style="background:#534AB7;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:18px;">New Clinic Intake</h1>
    <p style="color:#c4b9f5;margin:4px 0 0;font-size:13px;">{clinic_name}</p>
  </div>

  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-top:none;
              padding:24px;border-radius:0 0 8px 8px;">

    <p style="color:#374151;margin:0 0 12px;">
      <strong>{clinic_name}</strong> completed the intake form and {reason}.
      Their intake brief is attached.
    </p>

    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:8px;">
      <tr style="background:#eeecfb;">
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;width:40%;">Specialty</td>
        <td style="padding:8px 12px;color:#374151;">{submission.get('primary_specialty','—')}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;">Location</td>
        <td style="padding:8px 12px;color:#374151;">{submission.get('suburb','—')}, {submission.get('state','—')}</td>
      </tr>
      <tr style="background:#eeecfb;">
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;">Goal</td>
        <td style="padding:8px 12px;color:#374151;">{submission.get('main_goal','—')}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;">Monthly ad spend</td>
        <td style="padding:8px 12px;color:#374151;">${float(submission.get('monthly_ad_spend',0) or 0):,.0f}</td>
      </tr>
      <tr style="background:#eeecfb;">
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;">New patients/month</td>
        <td style="padding:8px 12px;color:#374151;">{submission.get('new_patients_per_month','—')}</td>
      </tr>
    </table>

    <p style="color:#6b7280;font-size:12px;margin:16px 0 0;">
      Full details are saved on the GHL contact. Brief attached as PDF.
    </p>

  </div>
</div>
"""

    text = (
        f"New intake from {clinic_name} ({reason}).\n"
        f"Specialty: {submission.get('primary_specialty')}\n"
        f"Location: {submission.get('suburb')}, {submission.get('state')}\n"
        f"Goal: {submission.get('main_goal')}\n"
        f"Brief attached."
    )

    safe = clinic_name.lower().replace(" ","_").replace("/","-")
    return _send(subject, html, text, pdf_bytes, f"intake_brief_{safe}.pdf")
