# Rosepith — Akşam Raporu Ajanı
# 18:00 → Yasin'e Telegram (kısa özet) + mail (detaylı rapor)
# PARÇA 4: Genişletilmiş stats (mail, müşteri, sezon), AI öneri

import threading
import datetime
import logging
import time
import requests

from core.config import (
    TELEGRAM_BOT_TOKEN, YASIN_TELEGRAM_ID,
)
from core.database import get_connection, log_event
from core.holiday_checker import is_holiday, get_season_context

logger = logging.getLogger(__name__)
AGENT_NAME = "evening_report"


# ─── Rapor verisi topla ───────────────────────────────────────────────────────

def _safe_count(conn, sql: str, params: tuple = ()) -> int:
    try:
        return conn.execute(sql, params).fetchone()[0]
    except Exception:
        return 0


def _collect_stats() -> dict:
    conn  = get_connection()
    bugun = datetime.date.today().isoformat()
    s     = {}

    # ── Müşteri konuşmaları ───────────────────────────────────────────────────
    s["musteri_mesaj"]  = _safe_count(conn,
        "SELECT COUNT(*) FROM conversations WHERE role='customer' AND date(created_at)=?",
        (bugun,))
    s["musteri_tekil"]  = _safe_count(conn,
        "SELECT COUNT(DISTINCT user_id) FROM conversations WHERE role='customer' AND date(created_at)=?",
        (bugun,))
    s["personel_mesaj"] = _safe_count(conn,
        "SELECT COUNT(*) FROM conversations WHERE role='personnel' AND date(created_at)=?",
        (bugun,))

    # ── İş kuyruğu (work_items) ───────────────────────────────────────────────
    s["is_tamamlanan"] = _safe_count(conn,
        "SELECT COUNT(*) FROM work_items WHERE status='done' AND date(created_at)=?", (bugun,))
    s["is_bekleyen"]   = _safe_count(conn,
        "SELECT COUNT(*) FROM work_items WHERE status='pending'")
    s["acil_isler"]    = _safe_count(conn,
        "SELECT COUNT(*) FROM work_items WHERE is_urgent=1 AND date(created_at)=?", (bugun,))

    # ── WA kuyruğu (task_queue — varsa) ──────────────────────────────────────
    s["wa_kuyruk"] = _safe_count(conn,
        "SELECT COUNT(*) FROM task_queue WHERE status='pending'")

    # ── Google Maps leads ─────────────────────────────────────────────────────
    s["bugun_lead"]     = _safe_count(conn,
        "SELECT COUNT(*) FROM customers WHERE atama_tarihi=?", (bugun,))
    s["eda_lead"]       = _safe_count(conn,
        "SELECT COUNT(*) FROM customers WHERE atama_tarihi=? AND atanan_personel='Eda Hanım'",
        (bugun,))
    s["asuman_lead"]    = _safe_count(conn,
        "SELECT COUNT(*) FROM customers WHERE atama_tarihi=? AND atanan_personel='Asuman Hanım'",
        (bugun,))
    s["brief_gonderildi"] = _safe_count(conn,
        "SELECT COUNT(*) FROM customers WHERE atama_tarihi=? AND son_durum='brief_gonderildi'",
        (bugun,))

    # ── Mail ─────────────────────────────────────────────────────────────────
    s["mail_gelen"]  = _safe_count(conn,
        "SELECT COUNT(*) FROM mail_threads WHERE direction='in'  AND date(created_at)=?", (bugun,))
    s["mail_giden"]  = _safe_count(conn,
        "SELECT COUNT(*) FROM mail_threads WHERE direction='out' AND date(created_at)=?", (bugun,))
    s["mail_acil"]   = _safe_count(conn,
        "SELECT COUNT(*) FROM mail_threads WHERE is_urgent=1 AND date(created_at)=?", (bugun,))
    s["mail_revize"] = _safe_count(conn,
        "SELECT COUNT(*) FROM mail_threads WHERE mail_type='revize' AND date(created_at)=?", (bugun,))

    # ── Personel iş dağılımı ─────────────────────────────────────────────────
    try:
        rows = conn.execute(
            """SELECT assigned_to, COUNT(*) c FROM work_items
               WHERE date(created_at)=? GROUP BY assigned_to ORDER BY c DESC""",
            (bugun,)
        ).fetchall()
        s["personel_is"] = [(r["assigned_to"], r["c"]) for r in rows]
    except Exception:
        s["personel_is"] = []

    # ── Daily sales (akışlar çalıştı mı) ─────────────────────────────────────
    s["maps_calistirildi"] = _safe_count(conn,
        "SELECT COUNT(*) FROM daily_sales WHERE date=? AND personel='sistem' AND event='maps_fetch'",
        (bugun,)) > 0
    s["brief_calistirildi"] = _safe_count(conn,
        "SELECT COUNT(*) FROM daily_sales WHERE date=? AND personel='sistem' AND event='brief_mail'",
        (bugun,)) > 0

    # ── Son sistem hatası ─────────────────────────────────────────────────────
    try:
        row = conn.execute(
            """SELECT message FROM log_events
               WHERE level='ERROR' AND date(created_at)=?
               ORDER BY id DESC LIMIT 1""",
            (bugun,)
        ).fetchone()
        s["son_hata"] = row["message"][:120] if row else ""
    except Exception:
        s["son_hata"] = ""

    conn.close()
    return s


# ─── Yarın öneri (AI) ─────────────────────────────────────────────────────────

def _generate_yarinkiler(stats: dict) -> str:
    """GPT ile yarın için kısa öneri oluştur."""
    try:
        from openai import OpenAI
        from core.config import OPENAI_API_KEY
        sezon = get_season_context()
        prompt = (
            f"Rosepith dijital ajans satış koçusun. Bugünün özeti:\n"
            f"- Maps lead: {stats['bugun_lead']} ({stats['eda_lead']} Eda, "
            f"{stats['asuman_lead']} Asuman)\n"
            f"- Brief gönderildi: {stats['brief_gonderildi']}\n"
            f"- İş tamamlanan: {stats['is_tamamlanan']}\n"
            f"- ACİL durum: {'Var' if stats['mail_acil'] > 0 or stats['acil_isler'] > 0 else 'Yok'}\n"
            f"- Sezon: {sezon}\n\n"
            f"Yarın için 2-3 maddelik kısa aksiyon önerisi yaz. "
            f"Fiyat yok, robotik değil, satış koçu tonu. "
            f"Başlık koyma, düz liste. Türkçe."
        )
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0.65
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Yarın öneri üretme hatası: {e}")
        sezon = get_season_context()
        return f"Sezon notu: {sezon[:100]}...\nYarın sabah 09:30 akışı otomatik çalışacak."


# ─── Rapor metni oluştur ─────────────────────────────────────────────────────

def _build_telegram_summary(stats: dict) -> str:
    """Yasin'e kısa Telegram özeti (1 paragraf, emoji'li)."""
    bugun = datetime.date.today().strftime("%d.%m.%Y")

    ozet_parcalar = [f"📊 <b>Günlük Özet — {bugun}</b>"]

    # Müşteri + brief
    if stats["bugun_lead"] > 0:
        ozet_parcalar.append(
            f"🗺 Bugün {stats['bugun_lead']} yeni lead çekildi "
            f"({stats['eda_lead']} Eda Hanım, {stats['asuman_lead']} Asuman Hanım). "
            f"{stats['brief_gonderildi']} briefi mail ile gönderildi."
        )

    # İşler
    is_satiri = f"💼 {stats['is_tamamlanan']} iş tamamlandı"
    if stats["is_bekleyen"] > 0:
        is_satiri += f", {stats['is_bekleyen']} bekliyor"
    ozet_parcalar.append(is_satiri + ".")

    # Mail
    if stats["mail_gelen"] > 0 or stats["mail_giden"] > 0:
        mail_satiri = f"📧 {stats['mail_gelen']} mail alındı, {stats['mail_giden']} gönderildi"
        if stats["mail_revize"] > 0:
            mail_satiri += f" ({stats['mail_revize']} revize)"
        ozet_parcalar.append(mail_satiri + ".")

    # ACİL
    toplam_acil = stats["mail_acil"] + stats["acil_isler"]
    if toplam_acil > 0:
        ozet_parcalar.append(f"🚨 {toplam_acil} ACİL durum işlendi — detay mailde.")

    # Hata
    if stats["son_hata"]:
        ozet_parcalar.append(f"⚠️ Son hata: {stats['son_hata'][:80]}")

    # WA kuyruk
    if stats["wa_kuyruk"] > 0:
        ozet_parcalar.append(f"📥 WA kuyrukta {stats['wa_kuyruk']} bekliyor.")

    if len(ozet_parcalar) == 1:
        ozet_parcalar.append("Bugün akış çalışmadı veya veri yok.")

    return "\n".join(ozet_parcalar)


def _build_mail_report(stats: dict, yarinkiler: str) -> str:
    """Yasin'e detaylı mail raporu."""
    bugun     = datetime.date.today().strftime("%d %B %Y")
    gun_adi   = datetime.date.today().strftime("%A")
    sezon     = get_season_context()
    separator = "─" * 55

    lines = [
        f"Merhaba Yasin,",
        "",
        f"Bugün ({bugun}, {gun_adi}) için sistem raporu aşağıda.",
        "",
        separator,
        "MÜŞTERI & LEAD",
        separator,
        f"• Bugün çekilen lead    : {stats['bugun_lead']}",
        f"  → Eda Hanım           : {stats['eda_lead']}",
        f"  → Asuman Hanım        : {stats['asuman_lead']}",
        f"• Brief gönderildi      : {stats['brief_gonderildi']}",
        f"• WhatsApp müşteri      : {stats['musteri_tekil']} tekil, {stats['musteri_mesaj']} mesaj",
        "",
        separator,
        "İŞ & PERSONEL",
        separator,
        f"• Tamamlanan iş         : {stats['is_tamamlanan']}",
        f"• Bekleyen iş           : {stats['is_bekleyen']}",
        f"• ACİL durum            : {stats['acil_isler'] + stats['mail_acil']} adet" +
            (" ⚠️" if stats["acil_isler"] + stats["mail_acil"] > 0 else " (yok)"),
    ]

    if stats["personel_is"]:
        for isim, sayi in stats["personel_is"]:
            lines.append(f"  → {isim:<20}: {sayi} iş")

    lines += [
        "",
        separator,
        "MAİL",
        separator,
        f"• Gelen mail            : {stats['mail_gelen']}",
        f"• Giden mail            : {stats['mail_giden']}",
        f"• Revize talebi         : {stats['mail_revize']}",
        "",
        separator,
        "SİSTEM",
        separator,
        f"• Maps akışı            : {'✓ Çalıştı' if stats['maps_calistirildi'] else '✗ Çalışmadı'}",
        f"• Brief mail akışı      : {'✓ Çalıştı' if stats['brief_calistirildi'] else '✗ Çalışmadı'}",
    ]

    if stats["son_hata"]:
        lines += ["", f"SON HATA:", f"  {stats['son_hata']}"]

    lines += [
        "",
        separator,
        "SEZON & YARIN",
        separator,
        f"Sezon: {sezon}",
        "",
        "Aksiyon önerileri:",
        yarinkiler,
        "",
        separator,
        "",
        "İyi akşamlar 🌙",
        "Rosepith Sistem",
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


def _send_mail_report_async(mail_body: str):
    try:
        from core.mail_handler import send_mail
        from core.config import YANDEX_MAIL
        if not YANDEX_MAIL:
            return
        tarih = datetime.date.today().strftime("%d.%m.%Y")
        send_mail(
            to      = YANDEX_MAIL,
            subject = f"Rosepith Günlük Rapor — {tarih}",
            body    = mail_body
        )
        logger.info("Akşam raporu mail gönderildi")
    except Exception as e:
        logger.error(f"Rapor mail hatası: {e}")


def run_evening_report(force: bool = False):
    """
    18:00'de çalıştırılır.
    force=True → tatil/mesai kontrolü atla (test için).
    """
    if not force and is_holiday():
        logger.info("Akşam raporu atlandı — tatil")
        return
    try:
        stats      = _collect_stats()
        yarinkiler = _generate_yarinkiler(stats)

        tg_text    = _build_telegram_summary(stats)
        mail_body  = _build_mail_report(stats, yarinkiler)

        _send_telegram(tg_text)
        threading.Thread(
            target=_send_mail_report_async,
            args=(mail_body,),
            daemon=True
        ).start()

        log_event(AGENT_NAME, "Akşam raporu gönderildi")
        return {"tg_sent": True, "stats": stats}
    except Exception as e:
        logger.error(f"Akşam raporu hatası: {e}")
        return {"tg_sent": False, "error": str(e)}


# ─── Scheduler ────────────────────────────────────────────────────────────────

class EveningReportAgent:
    def __init__(self):
        self._running  = False
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
