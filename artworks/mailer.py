import smtplib
from email.message import EmailMessage

from flask import current_app


def mail_configured() -> bool:
    return bool(current_app.config.get("MAIL_SERVER"))


def _from_header() -> str:
    return current_app.config.get("MAIL_FROM") or "Artworksdigital <hello@artworksdigital.fr>"


def send_email(to_email: str, subject: str, body: str, reply_to: str = "") -> tuple[bool, str]:
    if not to_email:
        return False, "Destinataire manquant."
    if not mail_configured():
        return False, "SMTP non configuré — le message est conservé dans l’admin."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _from_header()
    message["To"] = to_email
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)

    try:
        with smtplib.SMTP(
            current_app.config["MAIL_SERVER"],
            int(current_app.config.get("MAIL_PORT") or 587),
            timeout=12,
        ) as smtp:
            if current_app.config.get("MAIL_USE_TLS", True):
                smtp.starttls()
            username = current_app.config.get("MAIL_USERNAME")
            password = current_app.config.get("MAIL_PASSWORD")
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        return True, ""
    except Exception as exc:
        return False, str(exc)
