"""
Sends emails for the clinic intake system via Gmail SMTP.

Two email types:
  1. Google Ads audit - full PDF report + prospect draft email to pete
  2. Intake brief     - standard brief PDF for clinics without Google Ads access

Uses Gmail SMTP (not Resend) because the Resend test-mode sender
(onboarding@resend.dev) had deliverability issues with Google Workspace
inboxes and a 6-per-day quota cap. Gmail SMTP sends from pete@clinicmastery.com
directly, with the existing SPF/DKIM/DMARC for the domain.

Requires in .env / Render env vars:
  GMAIL_ADDRESS      - the Google Workspace address to send from
  GMAIL_APP_PASSWORD - app password from myaccount.google.com/apppasswords
"""
import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "").strip()
# App passwords are typically displayed with spaces in the Google UI but the
# actual auth value is the spaceless form. Strip them so either copy works.
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
NOTIFY_EMAIL       = "pete@clinicmastery.com"
FROM_NAME          = "Clinic Mastery"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT = 30


def _send(
    subject: str,
    html: str,
    text: str = "",
    pdf_bytes: bytes = None,
    filename: str = None,
) -> bool:
    """Core send helper. Sends via Gmail SMTP over SSL.

    pdf_bytes + filename are optional. Omit for messages without attachments
    (e.g. submission notifications).
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.error("GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set, cannot send email")
        return False

    # Top level is "mixed" so the PDF attaches alongside the body. The body
    # itself is "alternative" wrapping the plain-text and HTML parts.
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = formataddr((FROM_NAME, GMAIL_ADDRESS))
    msg["To"]      = NOTIFY_EMAIL
    msg["Message-ID"] = make_msgid(domain=GMAIL_ADDRESS.split("@", 1)[-1] or "clinicmastery.com")

    body = MIMEMultipart("alternative")
    if text:
        body.attach(MIMEText(text, "plain", "utf-8"))
    body.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(body)

    if pdf_bytes:
        part = MIMEApplication(pdf_bytes, _subtype="pdf")
        part.add_header(
            "Content-Disposition", "attachment",
            filename=(filename or "attachment.pdf"),
        )
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Email sent via Gmail SMTP: {subject}")
        return True
    except Exception as exc:
        logger.error(f"Gmail SMTP send failed: {exc}")
        return False


def send_submission_notification(submission: dict, collision: dict | None = None) -> bool:
    """
    Fires immediately when the intake form is received. Sends a quick
    heads-up email so pete knows a new clinic has come through, no PDF.

    `collision` is set when the phone-based GHL match landed on a contact
    whose existing clinic name or specialty differs from the incoming
    submission. We render a red banner at the top of the email so Pete
    can spot phone-number reuse before it silently corrupts a real
    client's record (CWC ← Hfg incident on 2026-05-03).
    """
    clinic_name = submission.get("clinic_name", "Unknown")
    has_ads     = submission.get("has_google_ads") or "Not provided"
    invite      = submission.get("invite_sent") or "Not provided"

    if "Yes" in has_ads and invite not in ("skipped", "Not provided", "Not sent"):
        ads_status = "Running Google Ads, invite sent, audit will follow"
    elif "Yes" in has_ads:
        ads_status = "Running Google Ads, invite not yet sent"
    else:
        ads_status = "Not running Google Ads"

    subject = f"New Intake Submission - {clinic_name}"

    rows = [
        ("Email",             submission.get("email", "-")),
        ("Phone",             submission.get("phone") or "-"),
        ("Specialty",         submission.get("primary_specialty", "-")),
        ("Location",          f"{submission.get('suburb', '-')}, {submission.get('state', '-')}"),
        ("Practitioners",     submission.get("num_practitioners", "-")),
        ("Website",           submission.get("website_url", "-")),
        ("Avg appt fee",      f"${float(submission.get('avg_appointment_fee', 0) or 0):,.0f}"),
        ("Avg visits/patient",submission.get("avg_visits_per_patient", "-")),
        ("New patients/mo",   submission.get("new_patients_per_month", "-")),
        ("Monthly ad spend",  f"${float(submission.get('monthly_ad_spend', 0) or 0):,.0f}"),
        ("Goal",              submission.get("main_goal", "-")),
        ("Appt types to grow",submission.get("appointment_types_to_grow", "-")),
        ("Google Ads",        ads_status),
        ("Additional context",submission.get("additional_context") or "-"),
    ]

    row_html = ""
    for i, (label, value) in enumerate(rows):
        bg = 'style="background:#eeecfb;"' if i % 2 == 0 else ""
        row_html += (
            f'<tr {bg}>'
            f'<td style="padding:8px 12px;font-weight:600;color:#534AB7;width:38%;">{label}</td>'
            f'<td style="padding:8px 12px;color:#374151;">{value}</td>'
            f"</tr>\n"
        )

    collision_banner = ""
    if collision:
        diff_rows = ""
        if collision.get("clinic_changed"):
            diff_rows += (
                f'<tr><td style="padding:6px 10px;color:#991B1B;width:38%;">Existing clinic name</td>'
                f'<td style="padding:6px 10px;color:#1f2937;">{collision.get("existing_clinic", "-")}</td></tr>'
                f'<tr><td style="padding:6px 10px;color:#991B1B;">New clinic name</td>'
                f'<td style="padding:6px 10px;color:#1f2937;font-weight:600;">{collision.get("incoming_clinic", "-")}</td></tr>'
            )
        if collision.get("spec_changed"):
            diff_rows += (
                f'<tr><td style="padding:6px 10px;color:#991B1B;">Existing specialty</td>'
                f'<td style="padding:6px 10px;color:#1f2937;">{collision.get("existing_specialty", "-")}</td></tr>'
                f'<tr><td style="padding:6px 10px;color:#991B1B;">New specialty</td>'
                f'<td style="padding:6px 10px;color:#1f2937;font-weight:600;">{collision.get("incoming_specialty", "-")}</td></tr>'
            )
        diff_rows += (
            f'<tr><td style="padding:6px 10px;color:#991B1B;">Existing email</td>'
            f'<td style="padding:6px 10px;color:#1f2937;">{collision.get("existing_email", "-")}</td></tr>'
            f'<tr><td style="padding:6px 10px;color:#991B1B;">New email</td>'
            f'<td style="padding:6px 10px;color:#1f2937;">{collision.get("incoming_email", "-")}</td></tr>'
        )
        collision_banner = f"""
    <div style="background:#FEE2E2;border:2px solid #DC2626;border-radius:8px;padding:14px 16px;margin-bottom:16px;">
      <h2 style="color:#991B1B;margin:0 0 8px;font-size:15px;">Possible phone collision detected</h2>
      <p style="color:#1f2937;margin:0 0 10px;font-size:13px;line-height:1.5;">
        This submission's <strong>{collision.get("matched_via", "phone")}</strong> matched an existing GHL contact
        (<code>{collision.get("contact_id", "-")}</code>) whose stored data looks like a different clinic.
        The submission has been written through, but check whether the wrong phone or email was entered before
        sending anything to the clinic.
      </p>
      <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:6px;font-size:12px;">
{diff_rows}      </table>
    </div>"""

    html = f"""
<div style="font-family:-apple-system,sans-serif;max-width:640px;margin:0 auto;padding:24px;">
  <div style="background:#534AB7;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:18px;">New Intake Submission</h1>
    <p style="color:#c4b9f5;margin:4px 0 0;font-size:13px;">{clinic_name}</p>
  </div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-top:none;
              padding:24px;border-radius:0 0 8px 8px;">
{collision_banner}
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
{row_html}
    </table>
    <p style="color:#6b7280;font-size:12px;margin:16px 0 0;">
      Full details saved to GHL. PDF brief or audit report to follow.
    </p>
  </div>
</div>
"""

    return _send(subject, html, text="")


def send_ads_report(
    clinic_name: str,
    pdf_bytes: bytes,
    ads_data: dict,
    contact_name: str = "",
    contact_email: str = "",
) -> bool:
    """
    Emails the Google Ads audit PDF to pete, with a copy-paste prospect
    email draft included in the email body.
    """
    from pdf_report import generate_prospect_email_draft
    draft = generate_prospect_email_draft(clinic_name, ads_data, contact_name=contact_name)
    draft_html = draft.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br/>")

    subject = f"Google Ads Audit Ready - {clinic_name}"

    # Contact info banner shown prominently so pete can forward immediately.
    contact_rows = ""
    if contact_name or contact_email:
        if contact_name:
            contact_rows += (
                f'<tr><td style="padding:8px 12px;font-weight:600;color:#534AB7;width:30%;">Send to</td>'
                f'<td style="padding:8px 12px;color:#374151;">{contact_name}</td></tr>\n'
            )
        if contact_email:
            contact_rows += (
                f'<tr style="background:#eeecfb;"><td style="padding:8px 12px;font-weight:600;color:#534AB7;">Email</td>'
                f'<td style="padding:8px 12px;color:#374151;"><a href="mailto:{contact_email}" style="color:#534AB7;">{contact_email}</a></td></tr>\n'
            )
        contact_banner = f"""
    <div style="background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;padding:4px 0;margin-bottom:20px;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
{contact_rows}      </table>
    </div>"""
    else:
        contact_banner = ""

    html = f"""
<div style="font-family:-apple-system,sans-serif;max-width:640px;margin:0 auto;padding:24px;">
  <div style="background:#534AB7;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:18px;">Google Ads Audit Ready</h1>
    <p style="color:#c4b9f5;margin:4px 0 0;font-size:13px;">{clinic_name}</p>
  </div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-top:none;
              padding:24px;border-radius:0 0 8px 8px;">
    {contact_banner}
    <p style="color:#374151;margin:0 0 16px;">
      The full audit PDF is attached. Key findings are also saved to the
      GHL contact under <strong>Google Ads Intake Form, google_ads_summary</strong>.
    </p>
    <hr style="border:none;border-top:2px solid #D4B22F;margin:20px 0;" />
    <h2 style="font-size:15px;color:#534AB7;margin:0 0 8px;">Draft email to send to the clinic</h2>
    <p style="color:#6b7280;font-size:12px;margin:0 0 12px;">
      Copy and send with the PDF attached.
    </p>
    <div style="background:#fff;border:1px solid #d1d5db;border-radius:6px;
                padding:16px 20px;font-family:monospace;font-size:13px;
                color:#1a1a2e;line-height:1.6;white-space:pre-wrap;">
{draft_html}
    </div>
  </div>
</div>
"""

    text = (
        f"Google Ads audit for {clinic_name}. PDF attached.\n\n"
        f"Send to: {contact_name} <{contact_email}>\n\n"
        f"--- DRAFT EMAIL ---\n\n{draft}"
    )
    safe = clinic_name.lower().replace(" ", "_").replace("/", "-")
    return _send(subject, html, text, pdf_bytes, f"google_ads_audit_{safe}.pdf")


def send_intake_brief(clinic_name: str, pdf_bytes: bytes, submission: dict) -> bool:
    """
    Emails the standard intake brief PDF to pete for clinics that didn't
    provide Google Ads access. Includes a copy-paste draft email in the body.
    """
    from pdf_report import generate_intake_email_draft
    draft = generate_intake_email_draft(clinic_name, submission)
    draft_html = draft.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

    has_ads = submission.get("has_google_ads") or "Not provided"
    skipped = submission.get("invite_sent") == "skipped"
    reason  = "skipped Google Ads access" if skipped else (
              "doesn't run Google Ads" if "No" in has_ads else "did not provide access")

    subject = f"New Intake Brief - {clinic_name}"

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
        <td style="padding:8px 12px;color:#374151;">{submission.get('primary_specialty', '-')}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;">Location</td>
        <td style="padding:8px 12px;color:#374151;">{submission.get('suburb', '-')}, {submission.get('state', '-')}</td>
      </tr>
      <tr style="background:#eeecfb;">
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;">Goal</td>
        <td style="padding:8px 12px;color:#374151;">{submission.get('main_goal', '-')}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;">Monthly ad spend</td>
        <td style="padding:8px 12px;color:#374151;">${float(submission.get('monthly_ad_spend', 0) or 0):,.0f}</td>
      </tr>
      <tr style="background:#eeecfb;">
        <td style="padding:8px 12px;font-weight:600;color:#534AB7;">New patients/month</td>
        <td style="padding:8px 12px;color:#374151;">{submission.get('new_patients_per_month', '-')}</td>
      </tr>
    </table>
    <hr style="border:none;border-top:2px solid #D4B22F;margin:20px 0;" />
    <h2 style="font-size:15px;color:#534AB7;margin:0 0 8px;">Draft email to send to the clinic</h2>
    <p style="color:#6b7280;font-size:12px;margin:0 0 12px;">
      Copy, personalise the bracketed sections, and send with the PDF attached.
    </p>
    <div style="background:#fff;border:1px solid #d1d5db;border-radius:6px;
                padding:16px 20px;font-family:monospace;font-size:13px;
                color:#1a1a2e;line-height:1.6;white-space:pre-wrap;">
{draft_html}
    </div>
    <p style="color:#6b7280;font-size:12px;margin:16px 0 0;">
      Full details are saved on the GHL contact.
    </p>
  </div>
</div>
"""

    text = (
        f"New intake from {clinic_name} ({reason}).\n"
        f"Specialty: {submission.get('primary_specialty')}\n"
        f"Location: {submission.get('suburb')}, {submission.get('state')}\n"
        f"Goal: {submission.get('main_goal')}\n\n"
        f"--- DRAFT EMAIL ---\n\n{draft}"
    )

    safe = clinic_name.lower().replace(" ", "_").replace("/", "-")
    return _send(subject, html, text, pdf_bytes, f"intake_brief_{safe}.pdf")


def send_pending_summary(pending: list[dict]) -> bool:
    """
    Daily digest email of clinics still in google_ads_data_status = Pending.
    Each entry should contain: clinic_name, ghl_contact_id, intake_date, email.

    Sends nothing if the list is empty (no point pestering Pete with a "0 pending"
    email every day).
    """
    if not pending:
        logger.info("send_pending_summary: 0 pending, skipping send")
        return True

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    rows: list[str] = []
    for i, entry in enumerate(pending):
        clinic = entry.get("clinic_name") or "Unknown"
        contact_id = entry.get("ghl_contact_id") or "-"
        contact_email = entry.get("email") or "-"
        intake_raw = entry.get("intake_date") or ""
        try:
            started = datetime.fromisoformat(intake_raw)
            elapsed_h = (now - started).total_seconds() / 3600
            remaining_h = max(0.0, 72 - elapsed_h)
            elapsed_str = f"{elapsed_h:.1f}h"
            remaining_str = f"{remaining_h:.1f}h" if remaining_h > 0 else "expired"
        except (ValueError, TypeError):
            elapsed_str = "unknown"
            remaining_str = "unknown"

        bg = 'style="background:#eeecfb;"' if i % 2 == 0 else ""
        rows.append(
            f'<tr {bg}>'
            f'<td style="padding:10px 12px;font-weight:600;color:#1a1a2e;">{clinic}</td>'
            f'<td style="padding:10px 12px;color:#374151;font-family:monospace;font-size:12px;">{contact_id}</td>'
            f'<td style="padding:10px 12px;color:#374151;">{contact_email}</td>'
            f'<td style="padding:10px 12px;color:#6b7280;text-align:right;">{elapsed_str}</td>'
            f'<td style="padding:10px 12px;color:#6b7280;text-align:right;">{remaining_str}</td>'
            f"</tr>\n"
        )

    table_html = "".join(rows)
    count = len(pending)
    word = "clinic" if count == 1 else "clinics"
    subject = f"Google Ads pending digest - {count} {word}"

    html = f"""
<div style="font-family:-apple-system,sans-serif;max-width:760px;margin:0 auto;padding:24px;">
  <div style="background:#534AB7;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:18px;">Google Ads pending digest</h1>
    <p style="color:#c4b9f5;margin:4px 0 0;font-size:13px;">
      {count} {word} still waiting for ad-account access to come through
    </p>
  </div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-top:none;
              padding:20px;border-radius:0 0 8px 8px;">
    <p style="color:#374151;margin:0 0 12px;font-size:13px;">
      These clinics submitted the intake form, were tagged Pending, and the cron
      worker has been polling for their Google Ads account but hasn't found a match yet.
      Once the 72-hour window expires they're auto-skipped.
    </p>
    <table style="width:100%;border-collapse:collapse;font-size:13px;
                  border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;">
      <thead>
        <tr style="background:#1a1a2e;color:#fff;">
          <th style="padding:10px 12px;text-align:left;font-weight:600;">Clinic</th>
          <th style="padding:10px 12px;text-align:left;font-weight:600;">Contact ID</th>
          <th style="padding:10px 12px;text-align:left;font-weight:600;">Email</th>
          <th style="padding:10px 12px;text-align:right;font-weight:600;">Elapsed</th>
          <th style="padding:10px 12px;text-align:right;font-weight:600;">Remaining</th>
        </tr>
      </thead>
      <tbody>
{table_html}      </tbody>
    </table>
    <p style="color:#6b7280;font-size:12px;margin:16px 0 0;">
      Sent by the clinic-intake cron worker. To investigate a stuck clinic,
      check the GHL contact and confirm their Google Ads account name matches.
    </p>
  </div>
</div>
"""

    text_lines = [f"{count} clinic(s) still pending Google Ads access:\n"]
    for entry in pending:
        text_lines.append(
            f"  - {entry.get('clinic_name')} ({entry.get('ghl_contact_id')}) {entry.get('email') or ''}"
        )
    text = "\n".join(text_lines)

    return _send(subject, html, text)
