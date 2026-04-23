# Rosepith AI Modülü — Hibrit mimari
# Müşteri: GPT-4o → Gemini → kuyruk
# Personel: Gemini Flash ONLY (hata → Yasin'e bildir, personele çaktırma)

import threading
import requests
import logging

from google import genai
from google.genai import types as genai_types
from core.config import GEMINI_API_KEY, OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, YASIN_TELEGRAM_ID

logger = logging.getLogger(__name__)

_current_mode = "full"
_mode_lock    = threading.Lock()


def get_mode() -> str:
    return _current_mode


def _notify_yasin(text: str):
    if not YASIN_TELEGRAM_ID or not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": YASIN_TELEGRAM_ID, "text": text},
            timeout=8,
        )
    except Exception:
        pass


def _set_mode(new_mode: str, reason: str = ""):
    global _current_mode
    with _mode_lock:
        if _current_mode == new_mode:
            return
        old = _current_mode
        _current_mode = new_mode
    logger.info(f"Mod: {old} → {new_mode} | {reason}")
    msgs = {
        "backup":    "⚠️ GPT-4o limiti doldu, Gemini devreye girdi",
        "full":      "✅ GPT-4o geri döndü, tam mod aktif",
    }
    if new_mode in msgs:
        threading.Thread(target=_notify_yasin, args=(msgs[new_mode],), daemon=True).start()


# ─── System Prompt ────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """Sen Rosepith Dijital Ajans'ın deneyimli satış asistanısın.
14 yıllık deneyim, 900+ marka, Google Partner ajans.

GÖREV: Müşteriyle doğal sohbet kur, sektörünü öğren, ihtiyacını anla, tek doğru hizmeti öner, randevu al.

FİYAT KURALI:
- Fiyat asla kendin söyleme.
- Müşteri fiyat sorarsa: "Uzmanımız sizinle görüşüp en uygun teklifi sunsun, kaç gibi müsaitsiniz? 😊"

MÜŞTERİ AKIŞI (sırayla ilerle):
1. Sektörünü tam anla
2. Web sitesi var mı öğren
3. Ne istediğini anla
4. O ihtiyaca göre TEK hizmet öner
5. Uzman randevusu veya iletişim bilgisi al

HİZMET ÖNERİSİ:
- Web sitesi VARSA → Google Ads öner
- Web sitesi YOKSA → Önce sektör sor, sonra web sitesi öner
- SEO'yu öne çıkarma, müşteri istemeden önerme
- "Hesap açmanız gerekiyor" gibi teknik detay verme

ARAMA TALEBİ:
- "Beni arayın" derse telefon sorma, numara bizde.
- Sadece: "İsminizi alabilir miyim, kaç gibi müsaitsiniz? 😊"

HAFIZA:
- Müşteri profili ve geçmiş konuşmalar verilecek
- Daha önce öğrenilenleri hatırla, sıfırdan başlama
- Randevu detayını yeni konuşmaya karıştırma

KURALLAR:
- Robot gibi konuşma, gerçek ve samimi ol
- Kısa cevap (1-3 cümle), laf kalabalığı yok
- Konu dışına çıkma
- Google Partner'lığı uygun yerde vurgula
- Sohbeti randevu/iletişimle bitirmeye çalış"""

PERSONEL_PROMPT = """Sen Rosepith ajansının iç koordinasyon asistanısın.
Personelle konuşuyorsun. Ton: tatlı sert, iş odaklı, net.
Görevi anla, onayla, gerekirse sor. Uzun cevap verme."""

ROLE_ADDONS = {
    "yasin":     "\n\nKULLANICI: Yasin (ajans sahibi). Ton: çok kısa, direkt, teknik.",
    "personnel": "",  # PERSONEL_PROMPT kullanılıyor
    "customer":  "\n\nKULLANICI: Potansiyel müşteri. Ton: sıcak, ikna edici, profesyonel.",
}

OFF_HOURS_ADDON = "\n\nŞU AN MESAİ DIŞI. Müşteriye kibarca belirt ama sohbeti sürdür."
WEEKEND_ADDON   = "\n\nŞU AN HAFTA SONU. Sıcak kal, Pazartesi detaylı yardım edileceğini söyle."


def build_system_prompt(role, is_off_hours=False, is_weekend=False, user_profile="") -> str:
    if role == "personnel":
        prompt = PERSONEL_PROMPT
    else:
        prompt = BASE_SYSTEM_PROMPT + ROLE_ADDONS.get(role, ROLE_ADDONS["customer"])
    if user_profile:
        prompt += f"\n\nMÜŞTERİ PROFİLİ:\n{user_profile}"
    if is_weekend:
        prompt += WEEKEND_ADDON
    elif is_off_hours:
        prompt += OFF_HOURS_ADDON
    return prompt


# ─── GPT-4o ───────────────────────────────────────────────────────────────────

def _gpt4o(system_prompt, history, user_message) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        r = "assistant" if h["role"] == "model" else "user"
        messages.append({"role": r, "content": h["parts"][0]})
    messages.append({"role": "user", "content": user_message})
    resp = client.chat.completions.create(
        model="gpt-4o", messages=messages, max_tokens=300, temperature=0.7
    )
    return resp.choices[0].message.content.strip()


# ─── Gemini Flash ──────────────────────────────────────────────────────────────

def _gemini(system_prompt, history, user_message) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    contents = []
    for h in history:
        g_role = "model" if h["role"] == "model" else "user"
        contents.append(genai_types.Content(
            role=g_role, parts=[genai_types.Part(text=h["parts"][0])]
        ))
    contents.append(genai_types.Content(
        role="user", parts=[genai_types.Part(text=user_message)]
    ))
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_prompt, max_output_tokens=300, temperature=0.7
        ),
    )
    return resp.text.strip()


# ─── Ana fonksiyonlar ─────────────────────────────────────────────────────────

def get_response(user_message, role, history, is_off_hours=False,
                 is_weekend=False, user_profile=""):
    """Müşteri ve Yasin için: GPT-4o → Gemini → None"""
    system_prompt = build_system_prompt(role, is_off_hours, is_weekend, user_profile)

    # MOD 1: GPT-4o
    try:
        text = _gpt4o(system_prompt, history, user_message)
        if _current_mode != "full":
            _set_mode("full", "GPT-4o yeniden erişilebilir")
        logger.info(f"GPT-4o yanıt ({role})")
        return text
    except Exception as e:
        err = str(e)
        if any(k in err.lower() for k in ["429", "rate", "quota"]):
            _set_mode("backup", "GPT-4o rate limit")
        logger.warning(f"GPT-4o hata: {e}")

    # MOD 2: Gemini
    try:
        text = _gemini(system_prompt, history, user_message)
        _set_mode("backup", "Gemini devreye girdi")
        logger.info(f"Gemini yanıt ({role})")
        return text
    except Exception as e:
        logger.error(f"Gemini hata: {e}")
        _set_mode("assistant", "Tüm API'ler erişilemedi")

    return None


def get_response_personnel(user_message, history, is_off_hours=False,
                            is_weekend=False, user_profile=""):
    """Personel için: SADECE Gemini Flash. Hata → Yasin bildir, None döner."""
    system_prompt = build_system_prompt("personnel", is_off_hours, is_weekend, user_profile)
    try:
        text = _gemini(system_prompt, history, user_message)
        logger.info("Gemini personel yanıt")
        return text
    except Exception as e:
        logger.error(f"Gemini personel hata: {e}")
        threading.Thread(
            target=_notify_yasin,
            args=(f"⚠️ Personel AI yanıt veremedi (Gemini hata). Elle müdahale gerekebilir.\nHata: {str(e)[:100]}",),
            daemon=True
        ).start()
        return None
