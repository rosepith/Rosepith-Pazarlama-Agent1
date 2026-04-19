# Rosepith Pazarlama Agent - E-posta Entegrasyonu
# SMTP üzerinden e-posta gönderme ve IMAP ile okuma

import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from core.config import MAIL_USER, MAIL_PASS
from core.database import log_event

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
IMAP_HOST = "imap.gmail.com"


def send_email(to: str, subject: str, body: str, html: bool = False) -> bool:
    """SMTP üzerinden e-posta gönderir."""
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = MAIL_USER
        msg["To"] = to
        msg["Subject"] = subject
        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(MAIL_USER, MAIL_PASS)
            server.sendmail(MAIL_USER, to, msg.as_string())

        log_event("mail", f"E-posta gönderildi: {to} - {subject}")
        return True
    except Exception as e:
        log_event("mail", f"E-posta gönderilemedi: {e}", level="ERROR")
        return False


def fetch_unread(limit: int = 10) -> list:
    """IMAP üzerinden okunmamış e-postaları çeker."""
    messages = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(MAIL_USER, MAIL_PASS)
        mail.select("inbox")
        _, data = mail.search(None, "UNSEEN")
        ids = data[0].split()[-limit:]
        for uid in ids:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            messages.append({
                "from": msg["From"],
                "subject": msg["Subject"],
                "date": msg["Date"]
            })
        mail.logout()
    except Exception as e:
        log_event("mail", f"E-posta okunamadı: {e}", level="ERROR")
    return messages
