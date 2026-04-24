# Rosepith — Akşam Raporu Ajanı
# 18:00 → Yasin'e Telegram + mail özeti
# Gün boyunca: müşteri konuşmaları, personel işler, kuyruk, AI mod

import threading
import datetime
import logging
import time
import requests

from core.config import (
    TELEGRAM_BOT_TOKEN, YASIN_TELEGRAM_ID,
)
from core.database import get_connection, log_event
from core.holiday_checker import is_holiday

logger = logging.getLogger(__name__)
AGENT_NAME = "evening_report"


# ─── Rapor verisi topla ───────────────────────────────────────────────────────

def _collect_stats() -> dict:
    conn   = get_connection()
    bugun  = datetime.date.today().isoformat()
    stats  = {}

    # Müşteri mesajları
    stats["musteri_mesaj"] = conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE role='customer' AND date(created_at)=?",
        (bugun,)
    ).fetchone()[0]

    stats["musteri_tekil"] = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM conversations WHERE role='customer' AND date(created_at)=?",
        (bugun,)
    ).fetchone()[0]

    # Personel mesajları
    stats["personel_mesaj"] = conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE role='personnel' AND date(created_at)=?",
        (bugun,)
    ).fetchone()[0]

    # İş kuyruğu
    try:
        stats["is_tamamlanan"] = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE status='done' AND date(created_at)=?",
            (bugun,)
        ).fetchone()[0]
        stats["is_bekleyen"] = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE status='pending'",
        ).fetchone()[0]
        stats["acil_isler"] = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE is_urgent=1 AND status='pending'",
        ).fetchone()[0]
    except Exception:
        stats["is_tamamlanan"] = 0
        stats["is_bekleyen"]   = 0
        stats["acil_isler"]    = 0

    # Görev kuyruğu (WhatsApp bekleyenler)
    stats["wa_kuyruk"] = conn.execute(
        "SELECT COUNT(*) FROM task_queue WHERE status='pending'",
    ).fetchone()[0]

    # Son 5 müşteri
    rows = conn.execute(
        """SELECT DISTINCT user_id FROM conversations
           WHERE role='customer' AND date(created_at)=?
           ORDER BY MAX(id) DESC LIMIT 5""",
        (bugun,)
    ).fetchall()
    stats["son_musteriler"] = [r["user_id"] for r in rows]

    # Personel iş dağılımı
    try:
        rows = conn.execute(
            """SELECT assigned_to, COUNT(*) c FROM work_items
               WHERE date(created_at)=? GROUP BY assigned_to ORDER BY c DESC""",
            (bugun,)
        ).fetchall()
        stats["personel_is"] = [(r["assigned_to"], r["c"]) for r in rows]
    except Exception:
        stats["personel_is"] = []

    conn.close()
    return stats


def _build_report(stats: dict) -> str:
    bugun = datetime.date.today().strftime("%d %B %Y, %A")
    lines = [
        f"📊 <b>Günlük Rapor — {bugun}</b>",
        "",
        f"👥 Müşteri: {stats['musteri_tekil']} tekil, {stats['musteri_mesaj']} mesaj",
        f"💼 Personel mesajı: {stats['personel_mesaj']}",
    ]

    if stats["personel_is"]:
        is_line = " | ".join(f"{isim}: {c}" for isim, c in stats["personel_is"])
        lines.append(f"📋 Personel işleri: {is_line}")

    lines += [
        f"✅ Tamamlanan iş: {stats['is_tamamlanan']}",
        f"⏳ Bekleyen iş: {stats['is_bekleyen']}",
    ]

    if stats["acil_isler"] > 0:
        lines.append(f"🚨 ACİL bekleyen: {stats['acil_isler']}")

    if stats["wa_kuyruk"] > 0:
        lines.append(f"📥 WA kuyruk: {stats['wa_kuyruk']}")

    if stats["son_musteriler"]:
        lines.append("")
        lines.append(f"Son müşteriler: {', '.join(stats['son_musteriler'][:3])}")

    lines += [
        "",
        "Günaydın olsun! 🌙"
    ]

    return "\n".join(lines)


# ─── Gönderim ─────────────────────────────────────────────────────────────────

def _send_telegram(text: str):
    if not YASIN_TELEGRAM_ID or not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": YASIN_TELEGRAM_ID, "text": text, "parse_mode": "HTML"},
            timeout=8
        )
        logger.info("Akşam raporu Telegram gönderildi")
    except Exception as e:
        logger.error(f"Rapor Telegram hatası: {e}")


def _send_mail_report(text: str):
    try:
        from core.mail_handler import send_mail
        from core.config import YANDEX_MAIL
        if not YANDEX_MAIL:
            return
        plain = text.replace("<b>", "").replace("</b>", "")
        send_mail(
            to=YANDEX_MAIL,
            subject=f"Günlük Rapor — {datetime.date.today().isoformat()}",
            body=plain
        )
        logger.info("Akşam raporu mail gönderildi")
    except Exception as e:
        logger.error(f"Rapor mail hatası: {e}")


def run_evening_report():
    """18:00'de çalıştırılır."""
    if is_holiday():
        logger.info("Akşam raporu atlandı — tatil")
        return
    try:
        stats  = _collect_stats()
        report = _build_report(stats)
        _send_telegram(report)
        threading.Thread(target=_send_mail_report, args=(report,), daemon=True).start()
        log_event(AGENT_NAME, "Akşam raporu gönderildi")
    except Exception as e:
        logger.error(f"Akşam raporu hatası: {e}")


# ─── Scheduler ────────────────────────────────────────────────────────────────

class EveningReportAgent:
    def __init__(self):
        self._running   = False
        self._son_gun: str = ""

    def _loop(self):
        logger.info("Akşam raporu ajanı başladı")
        while self._running:
            now  = datetime.datetime.now()
            saat = now.strftime("%H:%M")
            gun  = now.strftime("%Y-%m-%d")

            if saat == "18:00" and gun != self._son_gun:
                self._son_gun = gun
                threading.Thread(target=run_evening_report,
                                  daemon=True, name="evening_report").start()
                logger.info("Akşam raporu tetiklendi")

            time.sleep(30)

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True,
                         name="evening_report_scheduler").start()
        logger.info("EveningReportAgent aktif")

    def stop(self):
        self._running = False
