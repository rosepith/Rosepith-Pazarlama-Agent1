# Rosepith — Yandex Mail Handler
# IMAP: imap.yandex.com:993 (SSL)
# SMTP: smtp.yandex.com:465 (SSL)
# Thread takibi: mail_threads tablosu
# PARÇA 3: process_incoming_mail, MailPollingAgent

import imaplib
import smtplib
import email
import logging
import threading
import time
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header

logger = logging.getLogger(__name__)


def _init_table():
    from core.database import get_connection
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mail_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            in_reply_to TEXT,
            from_addr TEXT,
            to_addr TEXT,
            subject TEXT,
            body TEXT,
            direction TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _upgrade_table():
    """PARÇA 3 için mail_threads tablosuna yeni sütunlar ekle."""
    _init_table()
    from core.database import get_connection
    conn = get_connection()
    existing = {row[1] for row in conn.execute("PRAGMA table_info(mail_threads)").fetchall()}
    additions = {
        "mail_type":    "TEXT DEFAULT 'unknown'",
        "personel":     "TEXT DEFAULT ''",
        "is_urgent":    "INTEGER DEFAULT 0",
        "work_item_id": "INTEGER",
        "processed":    "INTEGER DEFAULT 0",
    }
    for col, defn in additions.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE mail_threads ADD COLUMN {col} {defn}")
            logger.info(f"mail_threads: '{col}' eklendi")
    conn.commit()
    conn.close()


def _get_creds():
    from core.config import YANDEX_MAIL, YANDEX_APP_PASSWORD
    return YANDEX_MAIL, YANDEX_APP_PASSWORD


def _decode_str(s) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    result = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="replace")
        else:
            result += str(part)
    return result.strip()


def _get_body(msg) -> str:
    """Mail içeriğini düz metin olarak çek."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def poll_new_mails(limit: int = 20) -> list[dict]:
    """INBOX'taki okunmamış mailleri çek, DB'ye kaydet, liste döndür."""
    mail_addr, app_pass = _get_creds()
    if not mail_addr or not app_pass:
        logger.warning("Yandex credentials eksik — mail polling atlandı")
        return []

    _init_table()
    results = []
    try:
        imap = imaplib.IMAP4_SSL("imap.yandex.com", 993)
        imap.login(mail_addr, app_pass)
        imap.select("INBOX")

        _, data = imap.search(None, "UNSEEN")
        ids = data[0].split() if data[0] else []
        ids = ids[-limit:]  # Son N tane

        for uid in ids:
            try:
                _, msg_data = imap.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                m = {
                    "message_id":  msg.get("Message-ID", f"<uid-{uid.decode()}>").strip(),
                    "in_reply_to": msg.get("In-Reply-To", "").strip(),
                    "from_addr":   _decode_str(msg.get("From", "")),
                    "subject":     _decode_str(msg.get("Subject", "")),
                    "body":        _get_body(msg).strip()[:3000],
                }
                results.append(m)

                # DB'ye kaydet (tekrar gelirse ignore)
                from core.database import get_connection
                conn = get_connection()
                conn.execute(
                    """INSERT OR IGNORE INTO mail_threads
                       (message_id, in_reply_to, from_addr, to_addr, subject, body, direction)
                       VALUES (?, ?, ?, ?, ?, ?, 'in')""",
                    (m["message_id"], m["in_reply_to"], m["from_addr"],
                     mail_addr, m["subject"], m["body"])
                )
                conn.commit()
                conn.close()

                # Okundu işaretle
                imap.store(uid, "+FLAGS", "\\Seen")

            except Exception as e:
                logger.error(f"Mail parse hatası (uid={uid}): {e}")

        imap.logout()
        logger.info(f"Mail polling: {len(results)} yeni mail")

    except Exception as e:
        logger.error(f"IMAP bağlantı hatası: {e}")

    return results


def send_mail(to: str, subject: str, body: str,
              reply_to_id: str = None) -> bool:
    """Mail gönder. reply_to_id varsa thread'e bağla."""
    mail_addr, app_pass = _get_creds()
    if not mail_addr or not app_pass:
        logger.warning("Yandex credentials eksik — mail gönderilemedi")
        return False

    _init_table()
    try:
        msg = MIMEMultipart()
        msg["From"]       = mail_addr
        msg["To"]         = to
        msg["Subject"]    = subject
        msg["Message-ID"] = f"<{uuid.uuid4()}@rosepith.net>"
        if reply_to_id:
            msg["In-Reply-To"] = reply_to_id
            msg["References"]  = reply_to_id

        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.yandex.com", 465, timeout=15) as smtp:
            smtp.login(mail_addr, app_pass)
            smtp.send_message(msg)

        # DB kaydet
        from core.database import get_connection
        conn = get_connection()
        conn.execute(
            """INSERT INTO mail_threads
               (message_id, in_reply_to, from_addr, to_addr, subject, body, direction, status)
               VALUES (?, ?, ?, ?, ?, ?, 'out', 'sent')""",
            (msg.get("Message-ID", ""), reply_to_id or "",
             mail_addr, to, subject, body[:3000])
        )
        conn.commit()
        conn.close()

        logger.info(f"Mail gönderildi → {to} | {subject}")
        return True

    except Exception as e:
        logger.error(f"SMTP hatası: {e}")
        return False


# ─── Poll zaman takibi ───────────────────────────────────────────────────────

_last_poll_time: str = ""   # In-memory, process ömrü boyunca


def _record_poll_time():
    """Son polling zamanını kaydet (in-memory + DB)."""
    global _last_poll_time
    import datetime
    _last_poll_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        from core.database import get_connection
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_meta (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO system_meta (key, value) VALUES ('last_mail_poll', ?)",
            (_last_poll_time,)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_last_poll_time() -> str:
    """Son mail poll zamanını döndür."""
    if _last_poll_time:
        return _last_poll_time
    try:
        from core.database import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT value FROM system_meta WHERE key='last_mail_poll'"
        ).fetchone()
        conn.close()
        return row[0] if row else "henüz poll yapılmadı"
    except Exception:
        return "henüz poll yapılmadı"


# ─── PARÇA 3: Yardımcı sorgular ──────────────────────────────────────────────

def get_thread_body(message_id: str) -> str:
    """Verilen Message-ID'ye ait önceki mail body'sini döndür."""
    if not message_id:
        return ""
    from core.database import get_connection
    conn = get_connection()
    row = conn.execute(
        "SELECT body FROM mail_threads WHERE message_id=? LIMIT 1",
        (message_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def get_last_sent_mail_id(personel_hitap: str) -> str:
    """Belirtilen personele son gönderilen mailin Message-ID'sini döndür."""
    from core.database import get_connection
    from core.config import PERSONEL_MAIL
    # personel_hitap → mail adresini bul
    to_mail = ""
    for isim_key, mail_val in PERSONEL_MAIL.items():
        if isim_key in personel_hitap.lower() and mail_val:
            to_mail = mail_val
            break
    if not to_mail:
        return ""
    conn = get_connection()
    row = conn.execute(
        """SELECT message_id FROM mail_threads
           WHERE direction='out' AND to_addr=?
           ORDER BY created_at DESC LIMIT 1""",
        (to_mail,)
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def _find_personel_by_mail(from_addr: str) -> str:
    """
    from_addr ile PERSONEL_MAIL eşleştir.
    Döndürür: personel_hitap ("Kağan", "Eda Hanım" vb.) veya boş string.
    """
    from core.config import PERSONEL_MAIL
    from_clean = from_addr.lower().strip()
    # from_addr "Ad Soyad <mail@x.com>" formatında gelebilir
    if "<" in from_clean:
        from_clean = from_clean.split("<")[-1].rstrip(">").strip()
    for isim_key, mail_val in PERSONEL_MAIL.items():
        if mail_val and mail_val.lower().strip() == from_clean:
            from agents.personnel_support import ISIM_TO_PROFIL
            for key in ISIM_TO_PROFIL:
                if key in isim_key.lower():
                    return ISIM_TO_PROFIL[key]["hitap"]
            return isim_key.title()
    return ""


def _is_urgent_mail(subject: str, body: str) -> bool:
    """Konu veya body'de ACİL geçiyor mu?"""
    combined = (subject + " " + body).upper()
    return "ACİL" in combined or "URGENT" in combined


def _update_mail_meta(message_id: str, mail_type: str,
                       personel: str, is_urgent: bool):
    """mail_threads satırını tip/personel/acil ile güncelle."""
    from core.database import get_connection
    conn = get_connection()
    conn.execute(
        """UPDATE mail_threads
           SET mail_type=?, personel=?, is_urgent=?
           WHERE message_id=?""",
        (mail_type, personel, int(is_urgent), message_id)
    )
    conn.commit()
    conn.close()


def _mark_processed(message_id: str, status: str = "islendi"):
    """Mail işlendi olarak işaretle."""
    from core.database import get_connection
    conn = get_connection()
    conn.execute(
        "UPDATE mail_threads SET processed=1, status=? WHERE message_id=?",
        (status, message_id)
    )
    conn.commit()
    conn.close()


# ─── PARÇA 3: Ana işleyici ────────────────────────────────────────────────────

def process_incoming_mail(mail: dict) -> str:
    """
    Gelen maili sınıflandır ve personel_support'a yönlendir.
    Döndürür: 'yeni_is' | 'revize' | 'bilinmeyen'
    """
    _upgrade_table()

    from_addr   = mail.get("from_addr", "")
    subject     = mail.get("subject", "")
    body        = mail.get("body", "")
    message_id  = mail.get("message_id", "")
    in_reply_to = mail.get("in_reply_to", "").strip()

    # ── Personel tanıma ──────────────────────────────────────────────────────
    personel_hitap = _find_personel_by_mail(from_addr)
    if not personel_hitap:
        logger.info(f"Bilinmeyen gönderen → atlandı: {from_addr}")
        _mark_processed(message_id, "bilinmeyen")
        return "bilinmeyen"

    # ── Acil & tip ───────────────────────────────────────────────────────────
    is_urgent = _is_urgent_mail(subject, body)
    mail_type = "revize" if in_reply_to else "yeni_is"

    _update_mail_meta(message_id, mail_type, personel_hitap, is_urgent)
    logger.info(f"Mail → {personel_hitap} | tip={mail_type} | acil={is_urgent}")

    # ── Personel destek ajanına ilet ─────────────────────────────────────────
    try:
        from agents.personnel_support import handle_mail_personnel
        handle_mail_personnel(
            from_mail      = from_addr,
            personel_hitap = personel_hitap,
            subject        = subject,
            body           = body,
            message_id     = message_id,
            thread_ref     = in_reply_to,
            is_revize      = (mail_type == "revize"),
            is_urgent      = is_urgent,
        )
    except Exception as e:
        logger.error(f"handle_mail_personnel hatası: {e}")

    _mark_processed(message_id, "islendi")
    return mail_type


# ─── PARÇA 3: Polling ajanı ──────────────────────────────────────────────────

class MailPollingAgent:
    """
    Her 60 saniyede bir IMAP'tan yeni mail çeker.
    Sadece mesai içi (hafta içi 09:30–18:00) çalışır.
    Tatil günleri devre dışı.
    """

    def __init__(self, interval: int = 60):
        self._interval = interval
        self._running  = False

    def _loop(self):
        from core.holiday_checker import is_work_hours, is_holiday
        import datetime
        logger.info("MailPollingAgent döngüsü başladı")
        while self._running:
            now = datetime.datetime.now()
            if is_holiday(now.date()) or not is_work_hours(now):
                time.sleep(self._interval)
                continue
            try:
                _record_poll_time()
                mails = poll_new_mails(limit=20)
                for m in mails:
                    # Daha önce işlenmediyse işle
                    from core.database import get_connection
                    conn = get_connection()
                    row = conn.execute(
                        "SELECT processed FROM mail_threads WHERE message_id=?",
                        (m["message_id"],)
                    ).fetchone()
                    conn.close()
                    if row and row[0]:
                        continue  # Zaten işlendi
                    try:
                        tip = process_incoming_mail(m)
                        logger.info(f"Mail işlendi: {m.get('subject','?')[:40]} → {tip}")
                    except Exception as e:
                        logger.error(f"Mail işleme hatası ({m.get('subject','?')[:30]}): {e}")
            except Exception as e:
                logger.error(f"Mail polling genel hata: {e}")
            time.sleep(self._interval)

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True,
                         name="mail_polling").start()
        logger.info("MailPollingAgent aktif (60s aralık, mesai içi)")

    def stop(self):
        self._running = False
