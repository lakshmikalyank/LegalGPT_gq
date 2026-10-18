"""
app/services/email_service.py

Sends emails with PDF attachments via SMTP.
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from flask import current_app

logger = logging.getLogger(__name__)


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

    msg = MIMEMultipart()
    msg["From"] = config["MAIL_DEFAULT_SENDER"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path:
        try:
            with open(attachment_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=attachment_name or "document.pdf")
            part["Content-Disposition"] = f'attachment; filename="{attachment_name or "document.pdf"}"'
            msg.attach(part)
        except OSError:
            logger.exception("Failed to read attachment at %s", attachment_path)
            return False, "Could not read the attachment file."

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