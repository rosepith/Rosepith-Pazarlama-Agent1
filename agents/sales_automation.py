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
    OPENAI_API_KEY, GOOGLE_MAPS_API_KEY, ANTHROPIC_API_KEY,
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
        "{hitap} hanım, bugünkü kısa özetinizi mailinize yollayabilirseniz süper olur 🌟",
        "Merhaba {hitap} 👋 Gün sonu özeti mailinize gelsin, bugün kaç görüşme yaptınız?",
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


# ─── Zenginleştirme (Claude → GPT-4o fallback) ───────────────────────────────

ENRICHMENT_PROMPT_TMPL = """Sen Rosepith Dijital Ajans'ın satış koçusun.
Aşağıdaki işletme bilgileri verildi. {personel_hitap} için bir satış dosyası hazırla.

İŞLETME:
- İsim: {isim}
- Sektör: {sektor}
- Adres: {adres}
- Web sitesi: {web}
- Google puanı: {rating} ({rating_count} yorum)
- Kategori: {types}
- Bölge/sezon notu: {sezon}

ÇIKTI FORMATI (tam bu başlıklarla):
## NE SUNABİLİRSİN
(Pazarlama dilinde, 2-3 paragraf. Bu işletmenin ihtiyacı ne? Hangi Rosepith hizmetini öneririz? Web sitesi yoksa web öner, varsa Google Ads öner. Robotik değil, gerçek satış koçu gibi yaz.)

## ARAMA TAKTİĞİ
(2-3 madde. Ne desin, nasıl açsın telefonu, ilk cümle nasıl olsun?)

## SEZON BAĞLANTISI
(1-2 cümle. Neden şimdi aramalı, neden bu ay doğru zaman?)

## REKABET DURUMU
(1-2 cümle. Bu sektörde rakipler ne yapıyor, neden Rosepith fark yaratır?)

KURALLAR:
- Satış koçu tonu, robotik değil
- Teknik dil yok
- Fiyat yazma
- Türkçe, {personel_hitap} saygılı hitap kullan
- Kısa, öz, aksiyon odaklı"""


def _parse_enrichment(text: str) -> dict:
    """Claude/GPT çıktısını bölümlere ayır."""
    sections = {
        "ne_sunabilirsin":  "",
        "arama_taktigi":    "",
        "sezon_baglantisi": "",
        "rekabet_durumu":   "",
    }
    keys = [
        ("## NE SUNABİLİRSİN",   "ne_sunabilirsin"),
        ("## ARAMA TAKTİĞİ",     "arama_taktigi"),
        ("## SEZON BAĞLANTISI",   "sezon_baglantisi"),
        ("## REKABET DURUMU",     "rekabet_durumu"),
    ]
    for i, (header, key) in enumerate(keys):
        start = text.find(header)
        if start == -1:
            continue
        start += len(header)
        # Bir sonraki başlığa kadar al
        end = len(text)
        for next_header, _ in keys[i + 1:]:
            pos = text.find(next_header, start)
            if pos != -1:
                end = pos
                break
        sections[key] = text[start:end].strip()
    return sections


def _notify_yasin_sync(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": YASIN_TELEGRAM_ID, "text": text},
            timeout=8
        )
    except Exception:
        pass


def enrich_customer_with_claude(customer: dict, personel_hitap: str,
                                  sezon: str = "") -> dict:
    """
    Müşteri verisini AI ile zenginleştir.
    Önce: Anthropic Claude API (ANTHROPIC_API_KEY varsa)
    Fallback: GPT-4o → GPT-4o-mini
    Döndürür: {ne_sunabilirsin, arama_taktigi, sezon_baglantisi, rekabet_durumu,
               model_used, is_fallback}
    """
    prompt = ENRICHMENT_PROMPT_TMPL.format(
        personel_hitap = personel_hitap,
        isim           = customer.get("isim", "?"),
        sektor         = customer.get("sektor", "?"),
        adres          = customer.get("adres", ""),
        web            = customer.get("web_sitesi") or "YOK",
        rating         = customer.get("rating", 0),
        rating_count   = customer.get("rating_count", 0),
        types          = customer.get("place_types", "")[:80],
        sezon          = sezon or get_season_context(),
    )

    # ── 1. Claude API ────────────────────────────────────────────────────────
    if ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )
            text = msg.content[0].text.strip()
            parsed = _parse_enrichment(text)
            parsed["model_used"]  = "claude-sonnet-4-5"
            parsed["is_fallback"] = False
            logger.info(f"Claude brief: {customer.get('isim','?')[:30]}")
            return parsed
        except Exception as e:
            logger.warning(f"Claude API hata: {e}")
            threading.Thread(
                target=_notify_yasin_sync,
                args=(f"⚠️ W10 Claude erişilemez, brief fallback devrede.\nHata: {str(e)[:100]}",),
                daemon=True
            ).start()

    # ── 2. GPT-4o ─────────────────────────────────────────────────────────────
    if OPENAI_API_KEY:
        for model in ("gpt-4o", "gpt-4o-mini"):
            try:
                from openai import OpenAI
                client = OpenAI(api_key=OPENAI_API_KEY)
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=600, temperature=0.7
                )
                text = resp.choices[0].message.content.strip()
                parsed = _parse_enrichment(text)
                parsed["model_used"]  = model
                parsed["is_fallback"] = True
                logger.info(f"{model} brief (fallback): {customer.get('isim','?')[:30]}")
                return parsed
            except Exception as e:
                logger.warning(f"{model} brief hata: {e}")

    # ── 3. Tamamen başarısız ──────────────────────────────────────────────────
    logger.error(f"Tüm modeller başarısız — {customer.get('isim','?')}")
    return {
        "ne_sunabilirsin":  "Brief üretilemedi.",
        "arama_taktigi":    "Brief üretilemedi.",
        "sezon_baglantisi": "Brief üretilemedi.",
        "rekabet_durumu":   "Brief üretilemedi.",
        "model_used":       "none",
        "is_fallback":      True,
    }


def _save_brief(customer_id: int, brief: dict):
    """customer_briefs tablosuna kaydet."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS customer_briefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            ne_sunabilirsin TEXT,
            arama_taktigi TEXT,
            sezon_baglantisi TEXT,
            rekabet_durumu TEXT,
            model_used TEXT,
            is_fallback INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        """INSERT INTO customer_briefs
           (customer_id, ne_sunabilirsin, arama_taktigi,
            sezon_baglantisi, rekabet_durumu, model_used, is_fallback)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (customer_id,
         brief.get("ne_sunabilirsin", ""),
         brief.get("arama_taktigi", ""),
         brief.get("sezon_baglantisi", ""),
         brief.get("rekabet_durumu", ""),
         brief.get("model_used", ""),
         int(brief.get("is_fallback", False)))
    )
    conn.commit()
    conn.close()


def _update_customer_status(customer_id: int, status: str):
    conn = get_connection()
    conn.execute(
        "UPDATE customers SET son_durum=? WHERE id=?",
        (status, customer_id)
    )
    conn.commit()
    conn.close()


# ─── Mail içeriği oluştur ────────────────────────────────────────────────────

def _build_brief_mail(personel_hitap: str,
                       musteriler_briefs: list[dict],
                       sektor: str,
                       fallback_note: bool = False) -> str:
    """Zenginleştirilmiş müşteri listesinden mail metni oluştur."""
    tarih = datetime.date.today().strftime("%d %B %Y")

    lines = [
        f"Merhaba {personel_hitap},",
        "",
        f"Bugün için {len(musteriler_briefs)} potansiyel müşteri hazırladık. "
        f"Bu ay {sektor} sezonu — yaklaşımlar aşağıda.",
        "",
        "=" * 60,
    ]

    for i, mb in enumerate(musteriler_briefs, 1):
        c = mb["customer"]
        b = mb["brief"]

        web_str = c.get("web_sitesi") or "YOK ⚠️"
        rating_str = f"{c.get('rating', 0)} / {c.get('rating_count', 0)} yorum"

        lines += [
            "",
            f"─── İŞLETME {i}: {c.get('isim', '?')} ───",
            f"📞 Telefon : {c.get('telefon') or 'Bilgi yok'}",
            f"📍 Adres   : {c.get('adres', '')}",
            f"🌐 Web     : {web_str}",
            f"⭐ Puan    : {rating_str}",
            "",
            "💡 NE SUNABİLİRSİN:",
            b.get("ne_sunabilirsin", ""),
            "",
            "🎯 ARAMA TAKTİĞİ:",
            b.get("arama_taktigi", ""),
            "",
            "📅 SEZON BAĞLANTISI:",
            b.get("sezon_baglantisi", ""),
            "",
            "🏆 REKABET DURUMU:",
            b.get("rekabet_durumu", ""),
            "",
            "─" * 50,
        ]

    lines += [
        "",
        f"Bol şans {personel_hitap}, akşam raporunuzu beklerim 🌟",
        "",
        "Rosepith Sistem",
    ]

    if fallback_note:
        lines += [
            "",
            "─" * 50,
            "Not: Bu brief'in bir kısmı bakım çalışması sebebiyle "
            "yedek sistemle hazırlanmıştır.",
        ]

    return "\n".join(lines)


# ─── Müşteri getir ────────────────────────────────────────────────────────────

def _get_todays_customers(personel_hitap: str, limit: int = 10) -> list[dict]:
    """Bugün atanan, henüz brief gönderilmemiş müşterileri getir."""
    bugun = datetime.date.today().isoformat()
    conn  = get_connection()
    rows  = conn.execute(
        """SELECT * FROM customers
           WHERE atanan_personel=?
           AND atama_tarihi=?
           AND son_durum='yeni'
           ORDER BY id ASC LIMIT ?""",
        (personel_hitap, bugun, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Ana brief + mail + WA ───────────────────────────────────────────────────

def run_morning_brief_mail(test_override_mail: str = None,
                            test_override_wa: str = None) -> dict:
    """
    1. Bugün atanan müşterileri çek
    2. Claude/GPT ile zenginleştir
    3. Mail gönder (test_override_mail varsa oraya)
    4. WhatsApp kısa bildirim
    Döndürür: {personel: {mail_sent, customers_count, fallback_used}}
    """
    from core.mail_handler import send_mail

    personeller  = _get_satis_personeli()
    sektor       = get_current_sector()
    sezon        = get_season_context()
    ozet         = {}

    for p in personeller:
        hitap     = p["hitap"]
        musteriler = _get_todays_customers(hitap)

        if not musteriler:
            logger.info(f"Brief mail: {hitap} için bugün müşteri yok")
            ozet[hitap] = {"mail_sent": False, "customers_count": 0}
            continue

        # Her müşteri için brief üret
        musteriler_briefs = []
        fallback_used     = False

        for c in musteriler:
            brief = enrich_customer_with_claude(c, hitap, sezon)
            if brief.get("is_fallback"):
                fallback_used = True
            _save_brief(c["id"], brief)
            _update_customer_status(c["id"], "brief_hazirlandi")
            musteriler_briefs.append({"customer": c, "brief": brief})

        # Mail metni oluştur
        body    = _build_brief_mail(hitap, musteriler_briefs, sektor, fallback_used)
        to_mail = test_override_mail

        # Test değilse personel mailini kullan
        if not to_mail:
            from core.config import PERSONEL_MAIL
            # hitap → isim lower eşleştir
            for isim_key, mail_val in PERSONEL_MAIL.items():
                if isim_key in hitap.lower() and mail_val:
                    to_mail = mail_val
                    break

        if not to_mail:
            logger.warning(f"Brief mail: {hitap} için mail adresi yok")
            ozet[hitap] = {"mail_sent": False, "customers_count": len(musteriler)}
            continue

        tarih   = datetime.date.today().strftime("%d %B %Y")
        subject = f"Gunaydın {hitap} — Bugunun Musteri Dosyasi ({tarih})"
        sent    = send_mail(to=to_mail, subject=subject, body=body)

        if sent:
            for c in musteriler:
                _update_customer_status(c["id"], "brief_gonderildi")
            log_event(AGENT_NAME, f"Brief mail gönderildi → {hitap} ({to_mail})")

        # WhatsApp kısa bildirim
        # test_override_wa varsa oraya, yoksa personel telefonuna
        wa_target = test_override_wa or p.get("phone")
        if wa_target and sent:
            sektor_kisa = sektor.split()[0].capitalize()  # "peyzaj firması" → "Peyzaj"
            wa_msg = (
                f"Günaydın {hitap} 🌅\n"
                f"Bugünkü {len(musteriler)} kişilik müşteri dosyanız mailinizde hazır. "
                f"{sektor_kisa} sezonu başlıyor, "
                f"inceleyip aramaya başlayabilirsiniz 🌟"
            )
            threading.Thread(
                target=_send_wa, args=(wa_target, wa_msg),
                daemon=True, name=f"wa_brief_{hitap[:3]}"
            ).start()
            logger.info(f"Brief WA gönderildi → {hitap} ({wa_target})")

        ozet[hitap] = {
            "mail_sent":       sent,
            "customers_count": len(musteriler),
            "fallback_used":   fallback_used,
            "to_mail":         to_mail,
            "wa_sent":         bool(wa_target and sent),
            "wa_target":       wa_target or "",
        }

    return ozet


# ─── Günlük satış akışı (09:30 → Maps + Brief) ───────────────────────────────

def run_daily_sales_flow():
    """
    09:30'da otomatik tetiklenir:
      1. Tatil / hafta sonu kontrolü
      2. Aynı gün tekrar çalışma engeli (daily_sales DB)
      3. Maps lead çek  (PARÇA 1)
      4. 5 dk bekle
      5. Brief mail + WA gönder (PARÇA 2)
    """
    # ── Tatil / hafta sonu ───────────────────────────────────────────────────
    if is_holiday():
        logger.info("Günlük satış akışı atlandı — tatil/hafta sonu")
        return

    # ── Çift çalışma engeli ──────────────────────────────────────────────────
    if _already_sent("sistem", "maps_fetch"):
        logger.info("Günlük satış akışı bu gün zaten çalıştı — atlandı")
        return

    logger.info("Günlük satış akışı başladı (Maps + Brief)")

    # ── PARÇA 1: Maps lead çek ───────────────────────────────────────────────
    try:
        maps_ozet = run_maps_lead_fetch()
        toplam    = sum(len(v) for v in maps_ozet.values())
        _mark_sent("sistem", "maps_fetch")
        logger.info(f"Maps fetch tamamlandı: {toplam} yeni lead")
    except Exception as e:
        logger.error(f"Maps fetch hatası: {e}")
        return  # Maps başarısız → brief'e geçme

    # ── 5 dakika bekle ───────────────────────────────────────────────────────
    logger.info("Brief için 5 dakika bekleniyor (09:35)...")
    time.sleep(300)

    # ── PARÇA 2: Brief mail + WA ─────────────────────────────────────────────
    if _already_sent("sistem", "brief_mail"):
        logger.info("Brief mail bu gün zaten gönderildi — atlandı")
        return

    try:
        from core.config import TEST_CUSTOMER_WHATSAPP
        # Personel WA boşsa TEST_CUSTOMER_WHATSAPP'a gönder
        personeller = _get_satis_personeli()
        test_wa = None
        if any(not p.get("phone") for p in personeller):
            test_wa = TEST_CUSTOMER_WHATSAPP or None

        brief_ozet = run_morning_brief_mail(test_override_wa=test_wa)
        _mark_sent("sistem", "brief_mail")

        gonderilen = sum(1 for v in brief_ozet.values() if v.get("mail_sent"))
        logger.info(f"Brief mail tamamlandı: {gonderilen}/{len(brief_ozet)} gönderildi")
        log_event(AGENT_NAME, f"Günlük satış akışı tamamlandı: {toplam} lead, {gonderilen} mail")

    except Exception as e:
        logger.error(f"Brief mail hatası: {e}")


# ─── Scheduler thread ─────────────────────────────────────────────────────────

GOREV_SAATLERI = {
    "09:30": lambda: run_daily_sales_flow(),  # Maps + Brief mail + WA
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
