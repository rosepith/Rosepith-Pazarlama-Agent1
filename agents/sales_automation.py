# Rosepith — Satış Otomasyonu
# 09:30 Sabah brief → Eda Hanım + Asuman Hanım (ayrı 10'ar müşteri)
# 12:00 / 15:00 / 17:30 → Nazik dürtmece
# 17:30 → Rapor hatırlatma
# 18:00 → Akşam raporuna katkı (evening_report ile koordineli)
# Google Maps Places API (New) ile lead çekme

import threading
import datetime
import logging
import time
import requests

from core.config import (
    PERSONEL_WHATSAPP,
    WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN,
    TELEGRAM_BOT_TOKEN, YASIN_TELEGRAM_ID,
    OPENAI_API_KEY, GOOGLE_MAPS_API_KEY,
)
from core.database import get_connection, log_event
from core.holiday_checker import is_holiday, is_work_hours, get_season_context

logger = logging.getLogger(__name__)
AGENT_NAME = "sales_automation"

# ─── Sezon takvimi ────────────────────────────────────────────────────────────

SEZON_SEKTORLER = {
    1:  ["mobilya", "ısıtma sistemleri", "kış giyim mağazası"],
    2:  ["mobilya", "tadilat firması", "boya badana"],
    3:  ["bahçe peyzaj", "çocuk parkı ekipmanları", "tohum fide bahçe merkezi"],
    4:  ["peyzaj firması", "bahçe düzenleme", "çocuk parkı"],
    5:  ["düğün salonu", "kuaför güzellik salonu", "fotoğrafçı düğün"],
    6:  ["otel", "tur firması", "klima servisi"],
    7:  ["otel", "tatil köyü", "klima montaj servisi"],
    8:  ["klima servisi", "otel", "plaj tesisi"],
    9:  ["kırtasiye", "kreş", "dershane etüt merkezi"],
    10: ["düğün salonu", "davet organizasyon", "kına organizasyon"],
    11: ["düğün organizasyon", "davet firması", "catering"],
    12: ["e-ticaret", "kuyumcu", "çiçekçi"],
}

MAPS_BOLGE = "İzmir"  # Başlangıçta sabit, ileride dinamik


def get_current_sector() -> str:
    """Bu ayın hedef sektörünü döndür (ilk sektör)."""
    month = datetime.date.today().month
    return SEZON_SEKTORLER.get(month, ["işletme"])[0]


def get_current_sector_list() -> list[str]:
    """Bu ayın tüm hedef sektörlerini döndür."""
    month = datetime.date.today().month
    return SEZON_SEKTORLER.get(month, ["işletme"])


# ─── Customers tablosu ────────────────────────────────────────────────────────

def _init_customers_table():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isim TEXT,
            telefon TEXT UNIQUE,
            adres TEXT,
            sektor TEXT,
            web_sitesi TEXT,
            rating REAL,
            rating_count INTEGER,
            place_types TEXT,
            atanan_personel TEXT,
            atama_tarihi TEXT,
            son_durum TEXT DEFAULT 'yeni',
            maps_query TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _is_recently_assigned(telefon: str, gun: int = 30) -> bool:
    """Son 30 günde bu telefon atandı mı?"""
    if not telefon:
        return False
    conn = get_connection()
    row = conn.execute(
        """SELECT id FROM customers
           WHERE telefon=?
           AND atama_tarihi >= date('now', ?)""",
        (telefon, f"-{gun} days")
    ).fetchone()
    conn.close()
    return row is not None


def _save_customer(isim: str, telefon: str, adres: str, sektor: str,
                   web_sitesi: str, rating: float, rating_count: int,
                   place_types: str, atanan_personel: str,
                   maps_query: str) -> bool:
    """Müşteriyi kaydet. Daha önce varsa False döner."""
    _init_customers_table()
    try:
        conn = get_connection()
        conn.execute(
            """INSERT INTO customers
               (isim, telefon, adres, sektor, web_sitesi, rating, rating_count,
                place_types, atanan_personel, atama_tarihi, maps_query)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (isim, telefon or None, adres, sektor, web_sitesi,
             rating, rating_count, place_types, atanan_personel,
             datetime.date.today().isoformat(), maps_query)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        # UNIQUE constraint — telefon zaten var
        return False


# ─── Google Maps Places API (New) ─────────────────────────────────────────────

# Sunucu proxy üzerinden istek — API key sunucuya IP kısıtlı
MAPS_PROXY_URL = "https://rosekreatif.com.tr/agent-api/maps_proxy.php"


def fetch_maps_leads(sektor: str, bolge: str = MAPS_BOLGE,
                     limit: int = 20) -> list[dict]:
    """
    Google Maps Places API (New) ile işletme listesi çek.
    Sunucu proxy kullanır (IP kısıtlı key).
    Ham veri döndür — zenginleştirme yapma.
    """
    from core.config import RELAY_SECRET
    query = f"{sektor} {bolge}"
    payload = {
        "textQuery": query,
        "pageSize":  min(limit, 20),
        "languageCode": "tr",
    }
    headers = {
        "X-Relay-Secret": RELAY_SECRET,
        "Content-Type":   "application/json",
    }

    try:
        resp = requests.post(
            MAPS_PROXY_URL, headers=headers, json=payload, timeout=20
        )
        if resp.status_code != 200:
            logger.error(f"Maps proxy hata {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        if "error" in data:
            logger.error(f"Maps API hata: {data['error']}")
            return []

        places = data.get("places", [])
        logger.info(f"Maps: '{query}' → {len(places)} sonuç")

        results = []
        for p in places:
            results.append({
                "isim":         p.get("displayName", {}).get("text", ""),
                "telefon":      p.get("internationalPhoneNumber", ""),
                "adres":        p.get("formattedAddress", ""),
                "web_sitesi":   p.get("websiteUri", ""),
                "rating":       float(p.get("rating", 0.0)),
                "rating_count": int(p.get("userRatingCount", 0)),
                "place_types":  ",".join(p.get("types", []))[:200],
                "query":        query,
            })
        return results

    except Exception as e:
        logger.error(f"Maps proxy istek hatası: {e}")
        return []


def assign_leads_to_personel(leads: list[dict],
                              sektor: str) -> dict[str, list[dict]]:
    """
    20 adayı filtrele (son 30 gün çakışma hariç),
    10'u Eda Hanım'a, 10'u Asuman Hanım'a ata.
    Aynı işletme iki hanıma gitmiyor.
    """
    _init_customers_table()
    personeller = _get_satis_personeli()
    if len(personeller) < 2:
        logger.warning("assign_leads: 2 satış personeli bulunamadı")
        # Tek personel varsa tüm listeyi ona ver
        if personeller:
            return {personeller[0]["hitap"]: leads[:10]}
        return {}

    # Çakışma filtresi
    temiz = []
    for lead in leads:
        tel = lead.get("telefon", "").strip()
        if tel and _is_recently_assigned(tel):
            logger.info(f"Çakışma atlandı: {lead['isim']} ({tel})")
            continue
        temiz.append(lead)

    # İlk 20'yi al, yarıya böl
    temiz = temiz[:20]
    yari  = len(temiz) // 2 or len(temiz)

    p0_hitap = personeller[0]["hitap"]  # Eda Hanım
    p1_hitap = personeller[1]["hitap"]  # Asuman Hanım

    return {
        p0_hitap: temiz[:yari],
        p1_hitap: temiz[yari:yari * 2],
    }


def run_maps_lead_fetch(sektor: str = None,
                        bolge: str = MAPS_BOLGE,
                        verbose: bool = False) -> dict:
    """
    Maps'ten lead çek, çakışma kontrolü yap, customers tablosuna kaydet.
    verbose=True → ekrana yazdır (CLI test için).
    Sonuç: {personel: [kayıt listesi], ...}
    """
    if sektor is None:
        sektor = get_current_sector()

    if verbose:
        print(f"\n🗺  Maps lead çekiliyor: '{sektor}' / {bolge}")

    leads = fetch_maps_leads(sektor, bolge, limit=20)
    if not leads:
        if verbose:
            print("❌ Sonuç gelmedi (API hatası veya key yok)")
        return {}

    atamalar = assign_leads_to_personel(leads, sektor)
    ozet = {}

    for personel_hitap, liste in atamalar.items():
        kaydedilenler = []
        for lead in liste:
            ok = _save_customer(
                isim          = lead["isim"],
                telefon       = lead["telefon"],
                adres         = lead["adres"],
                sektor        = sektor,
                web_sitesi    = lead["web_sitesi"],
                rating        = lead["rating"],
                rating_count  = lead["rating_count"],
                place_types   = lead["place_types"],
                atanan_personel = personel_hitap,
                maps_query    = lead["query"],
            )
            if ok:
                kaydedilenler.append(lead)
                if verbose:
                    tel = lead["telefon"] or "tel yok"
                    web = "✓ web" if lead["web_sitesi"] else "✗ web"
                    print(f"  [{personel_hitap[:3]}] {lead['isim'][:35]:<35} {tel:<18} {web} ⭐{lead['rating']}")
            else:
                if verbose:
                    print(f"  [ATLA] {lead['isim']} — zaten kayıtlı")

        ozet[personel_hitap] = kaydedilenler
        if verbose:
            print(f"  → {personel_hitap}: {len(kaydedilenler)} yeni kayıt")

    log_event(AGENT_NAME, f"Maps lead fetch: {sektor}/{bolge} — "
              + " | ".join(f"{p}: {len(v)}" for p, v in ozet.items()))
    return ozet


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
