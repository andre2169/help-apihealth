import logging
import smtplib
from email.utils import formataddr, formatdate
from email.message import EmailMessage

from app.core.config import settings


logger = logging.getLogger(__name__)


def _html_body(body: str) -> str:
    escaped = (
        body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
    return (
        "<!doctype html>"
        "<html><body style=\"font-family:Arial,sans-serif;color:#1b2a1f;line-height:1.5\">"
        f"<p>{escaped}</p>"
        "</body></html>"
    )


def send_email(*, to_email: str, subject: str, body: str) -> bool:
    """
    Envia emails transacionais simples.

    Se SMTP não estiver configurado, a função retorna False para a API poder
    registrar o código no log durante desenvolvimento sem quebrar o fluxo.
    """
    if not settings.smtp_configured:
        logger.warning(
            "SMTP nao configurado; email nao enviado | to=%s | subject=%s",
            to_email,
            subject,
        )
        return False

    message = EmailMessage()
    from_name = settings.MAIL_FROM_NAME or "HelpWeb Health"
    message["From"] = formataddr((from_name, settings.MAIL_FROM))
    message["To"] = to_email
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    if settings.REPLY_TO_EMAIL:
        message["Reply-To"] = settings.REPLY_TO_EMAIL
    message.set_content(body)
    message.add_alternative(_html_body(body), subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)

    logger.info("Email aceito pelo SMTP | to=%s | subject=%s", to_email, subject)
    return True
