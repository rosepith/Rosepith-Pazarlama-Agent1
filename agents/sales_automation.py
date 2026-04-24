# Rosepith — Satış Otomasyonu
# 09:30 Sabah brief → Eda Hanım + Asuman Hanım (ayrı 10'ar müşteri)
# 12:00 / 15:00 / 17:30 → Nazik dürtmece
# 17:30 → Rapor hatırlatma
# 18:00 → Akşam raporuna katkı (evening_report ile koordineli)

import threading
import datetime
import logging
import time
import requests

from core.config import (
    PERSONEL_WHATSAPP,
    WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN,
    TELEGRAM_BOT_TOKEN, YASIN_TELEGRAM_ID,
    OPENAI_API_KEY,
)
from core.database import get_connection, log_event
from core.holiday_checker import is_holiday, is_work_hours, get_season_context

logger = logging.getLogger(__name__)
AGENT_NAME = "sales_automation"

# ─── Satış personeli ──────────────────────────────────────────────────────────

def _get_satis_personeli() -> list[dict]:
    """PERSONEL_WHATSAPP'tan satış personelini çek."""
    result = []
    satis_isimleri = ["eda", "asuman"]
    for phone, isim in PERSONEL_WHATSAPP.items():
        normalized = isim.lower().strip()
        for si in satis_isimleri:
            if si in normalized:
                hitap = "Eda Hanım" if "eda" in normalized else "Asuman Hanım"
                result.append({"phone": phone, "isim": isim, "hitap": hitap})
    return result


# ─── Müşteri listesi (kuyruktaki günün müşterileri) ───────────────────────────

def _get_gunun_musterileri(personel_hitap: str, limit: int = 10) -> list[dict]:
    """Bugün atanmış veya en son konuşulan müşterileri getir."""
    conn = get_connection()
    bugun = datetime.date.today().isoformat()
    rows = conn.execute(
        """SELECT DISTINCT user_id, COUNT(*) as msg_count
           FROM conversations
           WHERE role='customer' AND date(created_at) >= date(?, '-7 days')
           GROUP BY user_id
           ORDER BY MAX(created_at) DESC
           LIMIT ?""",
        (bugun, limit)
    ).fetchall()
    conn.close()
    return [{"user_id": r["user_id"], "msg_count": r["msg_count"]} for r in rows]


# ─── Brief üretici ────────────────────────────────────────────────────────────

def _generate_brief(personel: dict, musteriler: list[dict]) -> str:
    """GPT-4o-mini ile günün briefingi üret."""
    if not musteriler:
        return (
            f"Merhaba {personel['hitap']} 👋\n"
            f"Bugün müşteri listesi boş görünüyor. "
            f"Yeni lead'ler için gün boyunca destek hazırım!"
        )

    try:
        from openai import OpenAI
        conn = get_connection()
        musteri_ozet = []
        for m in musteriler[:10]:
            # Son mesajı çek
            row = conn.execute(
                """SELECT message FROM conversations
                   WHERE user_id=? AND direction='in'
                   ORDER BY id DESC LIMIT 1""",
                (m["user_id"],)
            ).fetchone()
            son_mesaj = row["message"][:80] if row else "..."
            musteri_ozet.append(f"- {m['user_id']}: {son_mesaj} ({m['msg_count']} mesaj)")
        conn.close()

        sezon = get_season_context()
        prompt = f"""Sen Rosepith satış koçusun. Bugün {personel['hitap']} için sabah briefi hazırla.

Sezon: {sezon}
Tarih: {datetime.date.today().strftime('%d %B %Y, %A')}

Müşteri listesi:
{chr(10).join(musteri_ozet)}

Kısa, motive edici, aksiyon odaklı brief yaz (3-4 cümle max).
WhatsApp'a gönderilecek, emoji kullanabilirsin. Fiyat bilgisi VERME."""

        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0.7
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Brief üretim hatası: {e}")
        sezon = get_season_context()
        return (
            f"Günaydın {personel['hitap']} 🌅\n"
            f"Bugün {len(musteriler)} müşteri takibinde. "
            f"Sezon notu: {sezon[:60]}...\n"
            f"Başarılı bir gün! 💪"
        )


# ─── Dürtmece mesajları ───────────────────────────────────────────────────────

DURTMECELER = {
    "12:00": [
        "Merhaba {hitap} 👋 Sabah görüşmeler nasıl gitti? Destek lazımsa buradayım!",
        "{hitap} hanım, öğle arası öncesi bir durum paylaşmak ister misiniz?",
    ],
    "15:00": [
        "{hitap} hanım, öğleden sonra iyi gidiyor mu? Gün sonu kapanış için hazır mısınız?",
        "Merhaba {hitap} 🙂 Müşterilerden geri dönüş var mı, destek gerekiyor mu?",
    ],
    "17:30": [
        "{hitap} hanım, gün sonu raporu için notlarınızı hazırlamayı unutmayın! 📝",
        "Merhaba {hitap} 👋 Bugünkü görüşmelerin özetini paylaşır mısınız?",
    ],
}


def _get_durtmece(saat_key: str, hitap: str, idx: int = 0) -> str:
    msgs = DURTMECELER.get(saat_key, [])
    if not msgs:
        return f"Merhaba {hitap}, bugün nasıl gidiyor? 😊"
    msg = msgs[idx % len(msgs)]
    return msg.format(hitap=hitap)


# ─── Günlük brief kaydı ───────────────────────────────────────────────────────

def _init_daily_table():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            personel TEXT NOT NULL,
            event TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, personel, event)
        )
    """)
    conn.commit()
    conn.close()


def _already_sent(personel_hitap: str, event: str) -> bool:
    _init_daily_table()
    bugun = datetime.date.today().isoformat()
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM daily_sales WHERE date=? AND personel=? AND event=?",
        (bugun, personel_hitap, event)
    ).fetchone()
    conn.close()
    return row is not None


def _mark_sent(personel_hitap: str, event: str):
    bugun = datetime.date.today().isoformat()
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO daily_sales (date, personel, event) VALUES (?, ?, ?)",
        (bugun, personel_hitap, event)
    )
    conn.commit()
    conn.close()


# ─── WhatsApp gönderici ───────────────────────────────────────────────────────

def _send_wa(to: str, text: str):
    try:
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={
                "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "messaging_product": "whatsapp",
                "to": to, "type": "text",
                "text": {"preview_url": False, "body": text}
            },
            timeout=10
        )
        logger.info(f"Satış WA → {to}: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"Satış WA hatası: {e}")


# ─── Görev çalıştırıcılar ─────────────────────────────────────────────────────

def run_sabah_brief():
    """09:30 — Her satış personeline 10 müşteri briefingi gönder."""
    if is_holiday():
        logger.info("Sabah brief atlandı — tatil")
        return

    personeller = _get_satis_personeli()
    if not personeller:
        logger.warning("Sabah brief: satış personeli bulunamadı (.env kontrol)")
        return

    for i, p in enumerate(personeller):
        event = "sabah_brief"
        if _already_sent(p["hitap"], event):
            continue
        # Çakışma önleme: Eda ilk 10, Asuman sonraki 10
        musteriler = _get_gunun_musterileri(p["hitap"], limit=10)
        # Personeller arasında müşteri çakışması önleme (basit offset)
        offset = i * 10
        musteriler_slice = musteriler[offset:offset + 10] if len(musteriler) > offset else musteriler

        brief = _generate_brief(p, musteriler_slice)
        _send_wa(p["phone"], brief)
        _mark_sent(p["hitap"], event)
        log_event(AGENT_NAME, f"Sabah brief gönderildi → {p['hitap']}")


def run_durtmece(saat_key: str):
    """12:00 / 15:00 / 17:30 dürtmecesi."""
    if is_holiday() or not is_work_hours():
        return

    personeller = _get_satis_personeli()
    for i, p in enumerate(personeller):
        event = f"durtmece_{saat_key}"
        if _already_sent(p["hitap"], event):
            continue
        msg = _get_durtmece(saat_key, p["hitap"], idx=i)
        _send_wa(p["phone"], msg)
        _mark_sent(p["hitap"], event)
        log_event(AGENT_NAME, f"Dürtmece {saat_key} → {p['hitap']}")


# ─── Scheduler thread ─────────────────────────────────────────────────────────

GOREV_SAATLERI = {
    "09:30": lambda: run_sabah_brief(),
    "12:00": lambda: run_durtmece("12:00"),
    "15:00": lambda: run_durtmece("15:00"),
    "17:30": lambda: run_durtmece("17:30"),
}


class SalesAutomationAgent:
    def __init__(self):
        self._running   = False
        self._son_dakika: set = set()

    def _loop(self):
        logger.info("Satış otomasyonu başladı")
        while self._running:
            now  = datetime.datetime.now()
            saat = now.strftime("%H:%M")

            if saat not in self._son_dakika and saat in GOREV_SAATLERI:
                self._son_dakika.add(saat)
                threading.Thread(
                    target=GOREV_SAATLERI[saat],
                    daemon=True, name=f"sales_{saat}"
                ).start()
                logger.info(f"Satış görevi tetiklendi: {saat}")

            # Gece yarısında günlük sıfırla
            if saat == "00:01":
                self._son_dakika.clear()

            time.sleep(30)

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True,
                         name="sales_automation").start()
        logger.info("SalesAutomationAgent aktif")

    def stop(self):
        self._running = False
