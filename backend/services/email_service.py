"""
Optional SMTP email helper for customer portal disputes.
Email delivery is intentionally non-blocking for business actions: callers should
log the returned boolean but should not fail dispute creation/replies if email fails.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import settings

logger = logging.getLogger(__name__)


def send_optional_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email when SMTP is configured. Returns True on send."""
    if not to:
        return False

    if not settings.smtp_user or not settings.smtp_password:
        logger.info("SMTP not configured; email skipped: %s", subject)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.email_from
        msg["To"] = to
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_tls:
                server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.email_from, [to], msg.as_string())

        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        logger.warning("Email send failed to %s: %s", to, exc)
        return False
