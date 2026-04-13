"""
Sends the Google Ads audit PDF to pete@clinicmastery.com via Gmail SMTP.

Requires in .env:
  GMAIL_ADDRESS      — the Gmail address to send FROM (e.g. pete@gmail.com)
  GMAIL_APP_PASSWORD — Gmail App Password (not your regular password)
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
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAIL       = "pete@clinicmastery.com.au"


def send_ads_report(clinic_name: str, pdf_bytes: bytes) -> bool:
    """
    Emails the Google Ads PDF report to pete@clinicmastery.com.au.

    Args:
        clinic_name: Used in the subject line and email body.
        pdf_bytes:   The PDF file contents returned by pdf_report.generate_pdf().

    Returns:
        True on success, False on failure.
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.error(
            "GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set in .env — cannot send email"
        )
        return False

    subject = f"Google Ads Audit Ready — {clinic_name}"

    # Plain-text fallback
    text_body = f"""Hi Pete,

The Google Ads audit for {clinic_name} is ready.

The full report is attached as a PDF. Key findings are also saved on the
contact's GHL record under Google Ads Intake Form → google_ads_data_status.

— Clinic Mastery Intake System
"""

    # HTML email body
    html_body = f"""
<div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
  <div style="background:#534AB7;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:18px;">Google Ads Audit Ready</h1>
  </div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
    <p style="color:#374151;margin:0 0 12px;">Hi Pete,</p>
    <p style="color:#374151;margin:0 0 12px;">
      The Google Ads audit for <strong>{clinic_name}</strong> has been pulled and is attached.
    </p>
    <div style="background:#eeecfb;border-left:4px solid #534AB7;padding:12px 16px;border-radius:4px;margin:16px 0;">
      <p style="margin:0;color:#374151;font-size:14px;">
        The full report is in the attached PDF. A 6-line snapshot has also been
        saved to the contact's GHL record under <strong>Google Ads Intake Form</strong>.
      </p>
    </div>
    <p style="color:#6b7280;font-size:13px;margin:16px 0 0;">
      — Clinic Mastery Intake System
    </p>
  </div>
</div>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = NOTIFY_EMAIL

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    # Attach the PDF
    safe_name = clinic_name.lower().replace(" ", "_").replace("/", "-")
    pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
    pdf_part.add_header(
        "Content-Disposition",
        "attachment",
        filename=f"google_ads_audit_{safe_name}.pdf",
    )
    msg.attach(pdf_part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.sendmail(GMAIL_ADDRESS, NOTIFY_EMAIL, msg.as_string())
        logger.info(f"Ads audit email sent to {NOTIFY_EMAIL} for {clinic_name}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env. "
            "Make sure you're using an App Password, not your regular Gmail password."
        )
        return False
    except Exception as exc:
        logger.error(f"Failed to send ads audit email: {exc}")
        return False
