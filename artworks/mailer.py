import imaplib
import smtplib
from email import message_from_bytes
from email.message import EmailMessage
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from flask import current_app

from artworks.extensions import db
from artworks.models import MailMessage


def mail_configured() -> bool:
    cfg = current_app.config
    return bool(cfg.get("MAIL_SERVER") and cfg.get("MAIL_USERNAME") and cfg.get("MAIL_PASSWORD"))


def inbox_configured() -> bool:
    cfg = current_app.config
    return bool((cfg.get("MAIL_IMAP_HOST") or cfg.get("MAIL_SERVER")) and cfg.get("MAIL_USERNAME") and cfg.get("MAIL_PASSWORD"))


def _from_header() -> str:
    return current_app.config.get("MAIL_FROM") or "Artworksdigital <contact@artworksdigital.fr>"


def contact_inbox() -> str:
    return current_app.config.get("SITE_CONTACT_EMAIL") or "contact@artworksdigital.fr"


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

    cfg = current_app.config
    host = cfg["MAIL_SERVER"]
    port = int(cfg.get("MAIL_PORT") or 465)
    try:
        if cfg.get("MAIL_USE_SSL", True) or port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=16)
        else:
            smtp = smtplib.SMTP(host, port, timeout=16)
            if cfg.get("MAIL_USE_TLS", False):
                smtp.starttls()
        with smtp:
            username = cfg.get("MAIL_USERNAME")
            password = cfg.get("MAIL_PASSWORD")
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _decode_header(value: str) -> str:
    if not value:
        return ""
    chunks = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            chunks.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            chunks.append(part)
    return " ".join(chunks).strip()


def _plain_body(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in (part.get("Content-Disposition") or ""):
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = message.get_payload(decode=True) or b""
    return payload.decode(message.get_content_charset() or "utf-8", errors="replace")


def fetch_inbox(limit: int = 40) -> int:
    if not inbox_configured():
        return 0
    cfg = current_app.config
    host = cfg.get("MAIL_IMAP_HOST") or cfg.get("MAIL_SERVER")
    added = 0
    try:
        mailbox = imaplib.IMAP4_SSL(host, int(cfg.get("MAIL_IMAP_PORT") or 993), timeout=20)
        mailbox.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
        mailbox.select("INBOX")
        _, data = mailbox.search(None, "ALL")
        ids = (data[0] or b"").split()[-limit:]
        for raw_id in reversed(ids):
            _, payload = mailbox.fetch(raw_id, "(RFC822)")
            if not payload or not payload[0]:
                continue
            blob = payload[0][1]
            parsed = message_from_bytes(blob)
            external = (parsed.get("Message-ID") or "").strip()[:200]
            if not external:
                external = f"imap:{parsed.get('Date','')}:{parsed.get('From','')}:{parsed.get('Subject','')}"[:200]
            if external and MailMessage.query.filter_by(external_id=external).first():
                continue
            name, addr = parseaddr(parsed.get("From") or "")
            subject = _decode_header(parsed.get("Subject") or "(sans objet)")[:200]
            body = _plain_body(parsed).strip()[:8000]
            created = None
            try:
                created = parsedate_to_datetime(parsed.get("Date"))
            except Exception:
                created = None
            row = MailMessage(
                direction="in",
                kind="imap",
                status="inbox",
                from_name=_decode_header(name)[:120],
                from_email=(addr or "").lower()[:180],
                to_email=contact_inbox(),
                subject=subject or "(sans objet)",
                body=body,
                is_read=False,
                external_id=external,
            )
            if created:
                row.created_at = created
            db.session.add(row)
            added += 1
        if added:
            db.session.commit()
        mailbox.logout()
    except Exception:
        db.session.rollback()
        return 0
    return added
