# Rosepith — Personel Destek Ajanı
# 5 Personel: Eda (Satış), Asuman (Satış), Kağan (Teknik), Furkan (Teknik), Deniz (E-Ticaret)
#
# Yardım tipleri:
#   1. data_research  → Anında yap, akşam rapora yaz
#   2. tactic         → Anında öneri, fiyat yok, akşam rapora yaz
#   3. price_offer    → "Ekibe iletiyorum" → ANLIK Telegram Yasin
#   4. personal_abnormal → "Yetkiliye iletiyorum" → ANLIK Telegram Yasin
#
# Model zinciri:
#   Basit → Gemini Flash
#   Orta  → GPT-4o-mini
#   Kritik → GPT-4o

import logging
import threading
import datetime
import requests

from core.config import (
    TELEGRAM_BOT_TOKEN, YASIN_TELEGRAM_ID,
    PERSONEL_WHATSAPP,
    WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN,
)
from core.database import (
    get_connection, log_event, save_message, load_history
)
from core.holiday_checker import is_work_hours, is_holiday, get_holiday_name

logger = logging.getLogger(__name__)
AGENT_NAME = "personnel_support"

# ─── Personel profilleri ──────────────────────────────────────────────────────

PERSONEL_PROFILLER = {
    # phone: {isim, hitap, rol, departman}
    # WhatsApp numaraları .env'den geliyor → PERSONEL_WHATSAPP[phone] = isim
    # Rol ve hitap isim ile eşleştiriliyor
}

ISIM_TO_PROFIL = {
    "eda":    {"hitap": "Eda Hanım",   "rol": "satis",     "departman": "Satış"},
    "asuman": {"hitap": "Asuman Hanım","rol": "satis",     "departman": "Satış"},
    "kagan":  {"hitap": "Kağan",       "rol": "teknik",    "departman": "Teknik"},
    "furkan": {"hitap": "Furkan",      "rol": "teknik",    "departman": "Teknik"},
    "deniz":  {"hitap": "Deniz",       "rol": "eticaret",  "departman": "E-Ticaret"},
}


def _get_profil(phone: str) -> dict:
    isim_raw = PERSONEL_WHATSAPP.get(phone, "").lower().strip()
    # İsim normalizasyon (Eda Ulusoy → eda, Kağan Burmalar → kagan)
    for key in ISIM_TO_PROFIL:
        if key in isim_raw:
            return {**ISIM_TO_PROFIL[key], "isim": isim_raw.title(), "phone": phone}
    return {"hitap": isim_raw.title() or phone, "rol": "genel",
            "departman": "Genel", "isim": isim_raw.title(), "phone": phone}


# ─── Yardım tipi tespiti ──────────────────────────────────────────────────────

PRICE_KEYWORDS = [
    "fiyat", "teklif", "kaç para", "kaç lira", "ücret", "maliyet",
    "bütçe", "ne kadar", "paket", "indirim", "kampanya fiyat"
]

PERSONAL_KEYWORDS = [
    "şikayet", "rahatsız", "kötü", "saçma", "anlamsız", "bıktım",
    "istifa", "ayrılmak", "baskı", "küfür", "hakaret", "zorla",
    "haksız", "ayrımcı", "taciz"
]

DATA_KEYWORDS = [
    "araştır", "bul", "listele", "veri", "rapor", "analiz",
    "kaç tane", "istatistik", "bilgi ver", "kontrol et", "bak"
]


def _detect_help_type(text: str) -> str:
    t = text.lower()
    for kw in PERSONAL_KEYWORDS:
        if kw in t:
            return "personal_abnormal"
    for kw in PRICE_KEYWORDS:
        if kw in t:
            return "price_offer"
    for kw in DATA_KEYWORDS:
        if kw in t:
            return "data_research"
    return "tactic"  # Default: taktik/operasyonel


def _detect_complexity(text: str) -> str:
    """Mesaj karmaşıklığına göre model seç."""
    n = len(text)
    t = text.lower()
    critical_kws = ["strateji", "kriz", "acil karar", "yatırım", "büyük müşteri", "anlaşma"]
    if any(k in t for k in critical_kws) or n > 500:
        return "critical"
    if n > 150:
        return "medium"
    return "simple"


# ─── AI çağrıları ─────────────────────────────────────────────────────────────

PERSONEL_SYSTEM = """Sen Rosepith ajansının iç koordinasyon asistanısın.
Personelle konuşuyorsun. Ton: profesyonel, net, tatlı-sert.
Görevi anla, onayla, gerekirse sor. Kısa cevap ver.
Fiyat bilgisi VERME — fiyat soruları yetkili ekibe iletilir."""


def _call_gemini(prompt: str, history: list, message: str) -> str | None:
    try:
        from google import genai
        from google.genai import types as genai_types
        from core.config import GEMINI_API_KEY
        client = genai.Client(api_key=GEMINI_API_KEY)
        contents = []
        for h in history:
            g_role = "model" if h["role"] == "model" else "user"
            contents.append(genai_types.Content(
                role=g_role, parts=[genai_types.Part(text=h["parts"][0])]
            ))
        contents.append(genai_types.Content(
            role="user", parts=[genai_types.Part(text=message)]
        ))
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=prompt, max_output_tokens=250, temperature=0.6
            ),
        )
        return resp.text.strip()
    except Exception as e:
        logger.warning(f"Gemini personel hatası: {e}")
        return None


def _call_gpt_mini(prompt: str, history: list, message: str) -> str | None:
    try:
        from openai import OpenAI
        from core.config import OPENAI_API_KEY
        client = OpenAI(api_key=OPENAI_API_KEY)
        messages = [{"role": "system", "content": prompt}]
        for h in history:
            r = "assistant" if h["role"] == "model" else "user"
            messages.append({"role": r, "content": h["parts"][0]})
        messages.append({"role": "user", "content": message})
        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages,
            max_tokens=250, temperature=0.6
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"GPT-mini personel hatası: {e}")
        return None


def _call_gpt4o(prompt: str, history: list, message: str) -> str | None:
    try:
        from openai import OpenAI
        from core.config import OPENAI_API_KEY
        client = OpenAI(api_key=OPENAI_API_KEY)
        messages = [{"role": "system", "content": prompt}]
        for h in history:
            r = "assistant" if h["role"] == "model" else "user"
            messages.append({"role": r, "content": h["parts"][0]})
        messages.append({"role": "user", "content": message})
        resp = client.chat.completions.create(
            model="gpt-4o", messages=messages,
            max_tokens=300, temperature=0.65
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"GPT-4o personel hatası: {e}")
        return None


def _get_ai_response(complexity: str, history: list, message: str,
                     system_prompt: str) -> str | None:
    """Model zinciri: simple→Gemini, medium→GPT-mini, critical→GPT-4o"""
    if complexity == "simple":
        return _call_gemini(system_prompt, history, message) or \
               _call_gpt_mini(system_prompt, history, message)
    elif complexity == "medium":
        return _call_gpt_mini(system_prompt, history, message) or \
               _call_gemini(system_prompt, history, message)
    else:  # critical
        return _call_gpt4o(system_prompt, history, message) or \
               _call_gpt_mini(system_prompt, history, message)


# ─── Bildirimler ──────────────────────────────────────────────────────────────

def _notify_yasin(text: str):
    if not YASIN_TELEGRAM_ID or not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": YASIN_TELEGRAM_ID, "text": text, "parse_mode": "HTML"},
            timeout=8
        )
    except Exception as e:
        logger.error(f"Yasin bildirim hatası: {e}")


def _send_whatsapp(to: str, text: str):
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
        logger.info(f"WA personel → {to}: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"WA gönderme hatası: {e}")


# ─── İş kuyruğu ───────────────────────────────────────────────────────────────

def _init_work_queue():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assigned_to TEXT NOT NULL,
            phone TEXT NOT NULL,
            help_type TEXT NOT NULL,
            complexity TEXT NOT NULL,
            is_urgent INTEGER DEFAULT 0,
            content TEXT NOT NULL,
            result TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            notified_yasin INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def _add_work_item(assigned_to: str, phone: str, help_type: str,
                   complexity: str, content: str, is_urgent: bool = False) -> int:
    _init_work_queue()
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO work_items
           (assigned_to, phone, help_type, complexity, is_urgent, content)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (assigned_to, phone, help_type, complexity, int(is_urgent), content)
    )
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    return item_id


def _complete_work_item(item_id: int, result: str):
    conn = get_connection()
    conn.execute(
        """UPDATE work_items SET status='done', result=?, completed_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (result, item_id)
    )
    conn.commit()
    conn.close()


# ─── Ana handler ──────────────────────────────────────────────────────────────

def handle_whatsapp_personnel(phone: str, name: str, text: str):
    """
    art_director.py'den çağrılır.
    Personel mesajını sınıflandır, uygun şekilde yanıtla.
    """
    profil     = _get_profil(phone)
    hitap      = profil["hitap"]
    rol        = profil["rol"]
    now        = datetime.datetime.now()
    is_off     = not is_work_hours(now)
    holiday    = is_holiday(now.date())
    holiday_nm = get_holiday_name(now.date())

    save_message(phone, "personnel", "in", text)
    help_type  = _detect_help_type(text)
    complexity = _detect_complexity(text)

    logger.info(f"Personel | {hitap} | tip={help_type} | mod={complexity} | mesai={'dışı' if is_off else 'içi'}")

    # ── Tatil / Mesai dışı ───────────────────────────────────────────────────
    if holiday:
        reply = f"Bugün {holiday_nm} tatili. İyi bayramlar/tatiller 🎉 İş planına alındı, mesai başlayınca işliyorum."
        _send_whatsapp(phone, reply)
        save_message(phone, "personnel", "out", reply)
        _add_work_item(hitap, phone, help_type, complexity, text)
        return

    if is_off:
        if rol in ("teknik", "eticaret"):
            reply = "Mesai dışındayım, iş planına aldık. Sabah mesaiye başlayınca yapıp ileteceğim. 🙏"
        else:  # satis
            reply = "Mesai dışındayım. Bilgileri not aldım, sabah 09:30'da değerlendirip dönüş yapacağım."
        _send_whatsapp(phone, reply)
        save_message(phone, "personnel", "out", reply)
        _add_work_item(hitap, phone, help_type, complexity, text)
        return

    # ── Fiyat / Teklif → Yasin'e ANLIK bildirim ─────────────────────────────
    if help_type == "price_offer":
        reply = "Fiyat/teklif konusunu ekibe iletiyorum, en kısa sürede dönüş yapılacak. 👍"
        _send_whatsapp(phone, reply)
        save_message(phone, "personnel", "out", reply)
        _add_work_item(hitap, phone, help_type, complexity, text, is_urgent=True)
        threading.Thread(
            target=_notify_yasin,
            args=(f"💰 <b>Fiyat/Teklif Talebi</b>\n{hitap} ({profil['departman']})\n\n{text[:300]}",),
            daemon=True
        ).start()
        return

    # ── Kişisel / Anormal → Yasin'e ANLIK bildirim ───────────────────────────
    if help_type == "personal_abnormal":
        reply = "Durumu yetkiliye iletiyorum, seninle ilgilenecekler. 🤝"
        _send_whatsapp(phone, reply)
        save_message(phone, "personnel", "out", reply)
        _add_work_item(hitap, phone, help_type, complexity, text, is_urgent=True)
        threading.Thread(
            target=_notify_yasin,
            args=(f"⚠️ <b>Kişisel/Anormal Durum</b>\n{hitap}\n\n{text[:300]}",),
            daemon=True
        ).start()
        return

    # ── Data/Araştırma & Taktik → AI ile yanıtla ─────────────────────────────
    history  = load_history(phone, limit=20)
    system_p = PERSONEL_SYSTEM + f"\n\nPersonel: {hitap} | Departman: {profil['departman']}"

    item_id = _add_work_item(hitap, phone, help_type, complexity, text)

    reply = _get_ai_response(complexity, history, text, system_p)

    if reply is None:
        reply = "Talebinizi aldım, en kısa sürede ilgileniyorum."
        logger.error(f"Personel AI tüm modeller başarısız — {hitap}")
        threading.Thread(
            target=_notify_yasin,
            args=(f"⚠️ Personel AI yanıt veremedi\n{hitap} mesajı bekliyor:\n{text[:200]}",),
            daemon=True
        ).start()

    _send_whatsapp(phone, reply)
    save_message(phone, "personnel", "out", reply)
    _complete_work_item(item_id, reply)
    log_event(AGENT_NAME, f"{hitap} → {help_type}/{complexity} yanıtlandı")
