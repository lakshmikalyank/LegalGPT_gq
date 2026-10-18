"""
app/services/email_service.py

Sends emails with an optional PDF attachment.

Two delivery methods:
  1. Brevo HTTPS API  - used when the BREVO_API_KEY environment variable is
     set. Required on Render's free plan, which blocks SMTP ports
     25/465/587.
  2. SMTP (Gmail etc.) - used when BREVO_API_KEY is not set (fine locally).
"""

import base64
import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _read_attachment(attachment_path):
    with open(attachment_path, "rb") as f:
        return f.read()


def _send_via_brevo(api_key, sender, to_email, subject, body, attachment_bytes, attachment_name):
    payload = {
        "sender": {"email": sender},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body,
    }
    if attachment_bytes is not None:
        payload["attachment"] = [
            {
                "name": attachment_name or "document.pdf",
                "content": base64.b64encode(attachment_bytes).decode("ascii"),
            }
        ]
    request = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": api_key,
            "accept": "application/json",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def send_email_with_attachment(to_email, subject, body, attachment_path=None, attachment_name=None):
    """
    Send an email, optionally with a single file attachment.

    Args:
        to_email (str): Recipient email address.
        subject (str): Email subject line.
        body (str): Plain-text email body.
        attachment_path (str, optional): Path to a file to attach.
        attachment_name (str, optional): Filename to use for the attachment.

    Returns:
        tuple[bool, str]: (success, message)
    """
    config = current_app.config

    attachment_bytes = None
    if attachment_path:
        try:
            attachment_bytes = _read_attachment(attachment_path)
        except OSError:
            logger.exception("Failed to read attachment at %s", attachment_path)
            return False, "Could not read the attachment file."

    api_key = os.environ.get("BREVO_API_KEY")
    if api_key:
        try:
            _send_via_brevo(
                api_key, config["MAIL_DEFAULT_SENDER"], to_email, subject,
                body, attachment_bytes, attachment_name,
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            logger.error("Brevo API error %s: %s", exc.code, detail)
            if exc.code in (401, 403):
                return False, "Email service rejected the API key or the sender address."
            return False, "Failed to send email. Check the Brevo API key and verified sender."
        except Exception:
            logger.exception("Failed to send email via Brevo to %s", to_email)
            return False, "Failed to send email. Could not reach the email service."
        logger.info("Email sent via Brevo to %s", to_email)
        return True, "Email sent successfully."

    msg = MIMEMultipart()
    msg["From"] = config["MAIL_DEFAULT_SENDER"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    if attachment_bytes is not None:
        name = attachment_name or "document.pdf"
        part = MIMEApplication(attachment_bytes, Name=name)
        part["Content-Disposition"] = f'attachment; filename="{name}"'
        msg.attach(part)

    try:
        with smtplib.SMTP(config["MAIL_SERVER"], config["MAIL_PORT"]) as server:
            if config["MAIL_USE_TLS"]:
                server.starttls()
            server.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
            server.sendmail(config["MAIL_DEFAULT_SENDER"], to_email, msg.as_string())
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False, "Failed to send email. Please check SMTP configuration."

    logger.info("Email sent to %s", to_email)
    return True, "Email sent successfully."