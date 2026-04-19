# Rosepith Pazarlama Agent - AI Modülü
# Gemini 2.0 Flash (birincil) + OpenAI GPT-4o-mini (yedek)

from google import genai
from google.genai import types as genai_types
from core.config import GEMINI_API_KEY, OPENAI_API_KEY
from core.database import log_event

AGENT_NAME = "ai_core"

# ─── System Prompt ────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """Sen Rosepith Dijital Ajans'ın AI asistanısın.
14 yıllık deneyim, 900+ marka, Google Partner ajans.

HİZMETLER:
Web Sitesi, SEO, Google Ads, Meta Ads, Sosyal Medya Yönetimi,
E-ticaret, Mobil Uygulama, Video & Tasarım.

FİYATLAR (sadece sorulursa söyle):
- Yıllık web paketi: 2.900 TL + KDV
- Tek seferlik web: 8.000 TL + KDV
- SEO: 9.000 TL/ay + KDV
- Sosyal Medya Yönetimi: 7.000 TL/ay + KDV
- Google Ads: 7.000 TL/ay + KDV
- Meta Ads: 7.000 TL/ay + KDV

MÜŞTERİ AKIŞI (sırayla ilerle):
1. Sektörünü sor
2. Web sitesi var mı sor
3. Ne istediğini anla
4. Uygun hizmeti öner
5. Uzman randevusu al

KURALLAR:
- Robot gibi konuşma, doğal ve samimi ol
- Kısa cevap ver (1-3 cümle yeterli)
- Fiyat detaylarını sormadan verme
- Konu dışına çıkma
- Google Partner olduğumuzu vurgula (uygun yerde)
- Harita ≠ Web sitesi; bunu nezaketle ayırt et
- Sohbeti randevu/teklif almayla sonlandırmaya çalış"""

ROLE_ADDONS = {
    "yasin":     "\n\nKULLANICI: Yasin (ajans sahibi, yetkili).\nTon: Çok kısa, direkt, teknik. Laf kalabalığı yok.",
    "personnel": "\n\nKULLANICI: Ajans personeli.\nTon: Tatlı sert, iş odaklı. Görevi net al.",
    "customer":  "\n\nKULLANICI: Potansiyel müşteri.\nTon: Sıcak, ikna edici, profesyonel. Müşteri akışını takip et.",
    "unknown":   "\n\nKULLANICI: Bilinmiyor, müşteri gibi davran.\nTon: Sıcak, meraklı, yönlendirici.",
}

OFF_HOURS_ADDON = """

ŞU AN MESAİ DIŞI (09:30-18:00 arası çalışıyoruz).
- Müşteriye: Kibarca belirt ama sohbeti sürdür, iletişim bilgisi al.
- Personele: Görevi not et, sabah iletileceğini söyle.
- Yasin'e: Normal yanıt ver, kısıtlama yok."""

WEEKEND_ADDON = """

ŞU AN HAFTA SONU.
- Müşteriye: Hafta sonu olduğunu belirt ama sıcak kal, sektörünü sor.
- Personele: Görevi kuyruğa al, Pazartesi işleneceğini söyle.
- Yasin'e: Normal yanıt ver."""


def build_system_prompt(role: str, is_off_hours: bool = False, is_weekend: bool = False) -> str:
    prompt = BASE_SYSTEM_PROMPT + ROLE_ADDONS.get(role, ROLE_ADDONS["unknown"])
    if is_weekend:
        prompt += WEEKEND_ADDON
    elif is_off_hours:
        prompt += OFF_HOURS_ADDON
    return prompt


# ─── Gemini ───────────────────────────────────────────────────────────────────

def _gemini_response(system_prompt: str, history: list, user_message: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Geçmiş konuşmaları Gemini formatına çevir
    contents = []
    for h in history:
        g_role = "model" if h["role"] == "model" else "user"
        contents.append(genai_types.Content(
            role=g_role,
            parts=[genai_types.Part(text=h["parts"][0])]
        ))
    # Yeni mesajı ekle
    contents.append(genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_message)]
    ))

    resp = client.models.generate_content(
        model="gemini-2.0-flash-001",
        contents=contents,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=300,
            temperature=0.7,
        ),
    )
    return resp.text.strip()


# ─── OpenAI fallback ──────────────────────────────────────────────────────────

def _openai_response(system_prompt: str, history: list, user_message: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        oai_role = "assistant" if h["role"] == "model" else "user"
        messages.append({"role": oai_role, "content": h["parts"][0]})
    messages.append({"role": "user", "content": user_message})

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=300,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


# ─── Ana fonksiyon ────────────────────────────────────────────────────────────

def get_response(
    user_message: str,
    role: str,
    history: list,
    is_off_hours: bool = False,
    is_weekend: bool = False,
) -> str:
    """Gemini ile yanıt üret, hata olursa OpenAI'ye geç."""
    system_prompt = build_system_prompt(role, is_off_hours, is_weekend)

    try:
        text = _gemini_response(system_prompt, history, user_message)
        log_event(AGENT_NAME, f"Gemini yanıtı üretildi ({role})")
        return text
    except Exception as e:
        log_event(AGENT_NAME, f"Gemini hata ({e}), OpenAI'ye geçiliyor", level="WARNING")

    try:
        text = _openai_response(system_prompt, history, user_message)
        log_event(AGENT_NAME, f"OpenAI yanıtı üretildi ({role})")
        return text
    except Exception as e:
        log_event(AGENT_NAME, f"OpenAI de hata: {e}", level="ERROR")
        return "Şu an teknik bir sorun var, birazdan tekrar dene."
