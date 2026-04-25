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

# Revize sinyali anahtar kelimeleri (WA'dan)
REVIZE_KEYWORDS = [
    "revize", "düzelt", "değiştir", "güncelle", "yenile",
    "tekrar yaz", "değişiklik", "yanlış", "hatalı",
]

# ─── Türkçe karakter normalizasyonu ──────────────────────────────────────────

_TR_MAP = str.maketrans("ğşıöüçĞŞİÖÜÇ", "gsioucGSIOUC")
# Not: ç→c ayrımı önemli değil (ISIM_TO_PROFIL'de c yok)


def _normalize(s: str) -> str:
    """Türkçe karakterleri ASCII karşılıklarına çevirir, lowercase yapar.
    Örnek: 'Kağan' → 'kagan', 'Asuman Hanım' → 'asuman hanim'
    """
    return s.lower().translate(_TR_MAP)


def _get_profil(phone: str) -> dict:
    from core.config import PERSONEL_MAIL
    isim_raw = PERSONEL_WHATSAPP.get(phone, "").lower().strip()
    isim_norm = _normalize(isim_raw)   # ğ→g, ş→s vs.
    for key in ISIM_TO_PROFIL:
        if key in isim_norm:
            # Mail adresini de bul (normalize ile karşılaştır)
            mail_addr = ""
            for isim_key, mail_val in PERSONEL_MAIL.items():
                if key in _normalize(isim_key):
                    mail_addr = mail_val
                    break
            return {**ISIM_TO_PROFIL[key], "isim": isim_raw.title(),
                    "phone": phone, "mail": mail_addr}
    return {"hitap": isim_raw.title() or phone, "rol": "genel",
            "departman": "Genel", "isim": isim_raw.title(),
            "phone": phone, "mail": ""}


def _get_profil_by_mail(from_mail: str) -> dict | None:
    """Mail adresinden personel profilini bul."""
    from core.config import PERSONEL_MAIL
    from_clean = from_mail.lower().strip()
    if "<" in from_clean:
        from_clean = from_clean.split("<")[-1].rstrip(">").strip()

    for isim_key, mail_val in PERSONEL_MAIL.items():
        if mail_val and mail_val.lower().strip() == from_clean:
            for key in ISIM_TO_PROFIL:
                if key in _normalize(isim_key):
                    # Telefon numarasını da bul
                    phone = ""
                    for ph, isim in PERSONEL_WHATSAPP.items():
                        if key in isim.lower():
                            phone = ph
                            break
                    return {**ISIM_TO_PROFIL[key], "isim": isim_key.title(),
                            "phone": phone, "mail": mail_val}
            return {"hitap": isim_key.title(), "rol": "genel",
                    "departman": "Genel", "isim": isim_key.title(),
                    "phone": "", "mail": mail_val}
    return None


def _is_revize_request(text: str) -> bool:
    """WA mesajında revize sinyali var mı?"""
    t = text.lower()
    return any(kw in t for kw in REVIZE_KEYWORDS)


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


def _send_whatsapp(to: str, text: str, personel_hitap: str = ""):
    """
    Personel WA gönderici — core.whatsapp.send_wa üzerinden.
    24h pencere kontrolü + şablon fallback otomatik.
    """
    from core.whatsapp import send_wa
    send_wa(to, text, personel_hitap=personel_hitap)


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

    # ── Revize sinyali tespiti (WA'dan) ──────────────────────────────────────
    if _is_revize_request(text):
        from core.mail_handler import get_last_sent_mail_id
        last_mail_id = get_last_sent_mail_id(hitap)
        if last_mail_id:
            reply = (
                f"{hitap}, revize talebinizi mail üzerinden iletirseniz "
                f"daha düzenli takip edebilirim. "
                f"Son gönderdiğim maile cevap yazabilirsiniz 🌟"
            )
            _send_whatsapp(phone, reply)
            save_message(phone, "personnel", "out", reply)
            log_event(AGENT_NAME, f"WA revize yönlendirmesi → {hitap}")
            return

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

    # İş sonucunu mail olarak da gönder (arka planda)
    mail_addr = profil.get("mail", "")
    if mail_addr:
        threading.Thread(
            target=_send_work_result_mail,
            args=(hitap, mail_addr, help_type, text, reply),
            daemon=True
        ).start()

    log_event(AGENT_NAME, f"{hitap} → {help_type}/{complexity} yanıtlandı")


# ─── İş sonucu mail gönderici ─────────────────────────────────────────────────

def _send_work_result_mail(hitap: str, to_mail: str,
                            help_type: str, original_text: str,
                            result_text: str):
    """
    İş tamamlandığında personelin mailine sonuç gönder.
    WA üzerinden "mailine yolladım" bildirimi yapılır.
    """
    if not to_mail:
        return
    from core.mail_handler import send_mail
    tip_map = {
        "data_research": "Araştırma Sonucu",
        "tactic":        "Taktik Önerisi",
        "price_offer":   "Fiyat/Teklif Yönlendirmesi",
        "personal_abnormal": "Yönlendirme Notu",
    }
    tip_str = tip_map.get(help_type, "İş Sonucu")
    tarih   = __import__("datetime").datetime.now().strftime("%d.%m.%Y %H:%M")

    body = (
        f"Merhaba {hitap},\n\n"
        f"[{tarih}] ilettiğiniz talep için hazırladığım {tip_str}:\n\n"
        f"─────────────────────────────────\n"
        f"TALEP:\n{original_text[:400]}\n\n"
        f"SONUÇ:\n{result_text}\n"
        f"─────────────────────────────────\n\n"
        f"İyi çalışmalar 🌟\nRosepith Sistem"
    )
    subject = f"İş Sonucu — {tip_str} ({tarih})"
    sent    = send_mail(to=to_mail, subject=subject, body=body)

    if sent:
        # WA'dan kısa bildirim
        phone = ""
        for ph, isim in PERSONEL_WHATSAPP.items():
            for key in ISIM_TO_PROFIL:
                if key in _normalize(isim) and ISIM_TO_PROFIL[key]["hitap"] == hitap:
                    phone = ph
                    break
        if phone:
            short = result_text[:80] + ("..." if len(result_text) > 80 else "")
            wa_msg = f"{hitap}, {tip_str.lower()} mailine yolladım, kontrol et 🌟"
            threading.Thread(target=_send_whatsapp, args=(phone, wa_msg), daemon=True).start()

        logger.info(f"İş sonucu mail gönderildi → {hitap} ({to_mail})")


# ─── Mail üzerinden personel desteği ─────────────────────────────────────────

def _handle_mail_revize(from_mail: str, profil: dict,
                         subject: str, body: str,
                         message_id: str, thread_ref: str,
                         is_urgent: bool):
    """
    Revize akışı:
    Önceki mail body'sini bağlam olarak ekle → AI ile yeniden üret
    → Orijinal thread'e reply olarak gönder → WA bildirim.
    """
    from core.mail_handler import send_mail, get_thread_body

    hitap = profil["hitap"]
    phone = profil.get("phone", "")

    # Önceki çalışmayı bağlam olarak al
    prev_body  = get_thread_body(thread_ref) if thread_ref else ""
    context    = f"\n\nÖNCEKİ ÇALIŞMA (revize edilecek):\n{prev_body[:600]}" if prev_body else ""

    revize_sys = (
        PERSONEL_SYSTEM
        + f"\n\nPersonel: {hitap} | Kanal: E-posta | REVİZE TALEBI{context}"
    )
    complexity  = _detect_complexity(body)
    revize_text = f"Revize talebi:\n{body}"

    item_id = _add_work_item(
        hitap, phone or from_mail, "tactic", complexity,
        f"[MAIL REVİZE] {subject}\n\n{body}", is_urgent=is_urgent
    )

    reply_text = _get_ai_response(complexity, [], revize_text, revize_sys)
    if reply_text is None:
        reply_text = "Revize talebinizi aldım, inceleyip güncellenmiş versiyonu ayrıca göndereceğim."

    _complete_work_item(item_id, reply_text)

    sent = send_mail(
        to         = from_mail,
        subject    = f"Re: {subject}",
        body       = (
            f"Merhaba {hitap},\n\n"
            f"Revize talebiniz işlendi:\n\n{reply_text}\n\nRosepith Sistem"
        ),
        reply_to_id = thread_ref or message_id,
    )

    if phone and sent:
        threading.Thread(
            target=_send_whatsapp,
            args=(phone, f"{hitap}, revize talebinizi işledim, mail olarak gönderdim 🌟"),
            daemon=True
        ).start()

    log_event(AGENT_NAME, f"Mail revize → {hitap} | {subject[:40]}")


def handle_mail_personnel(from_mail: str, personel_hitap: str,
                           subject: str, body: str,
                           message_id: str, thread_ref: str = "",
                           is_revize: bool = False,
                           is_urgent: bool = False):
    """
    mail_handler.process_incoming_mail() tarafından çağrılır.

    is_revize=True  → _handle_mail_revize (önceki iş bağlamı + reply)
    is_revize=False → Yeni iş; sınıflandır, AI ile yanıtla, mail cevap + WA bildirim
    """
    from core.mail_handler import send_mail

    profil = _get_profil_by_mail(from_mail)
    if profil is None:
        # hitap biliniyor ama profil detayı yok → minimal profil kur
        profil = {"hitap": personel_hitap, "rol": "genel",
                  "departman": "Genel", "isim": personel_hitap,
                  "phone": "", "mail": from_mail}

    hitap = profil["hitap"]
    phone = profil.get("phone", "")

    logger.info(f"handle_mail_personnel | {hitap} | revize={is_revize} | acil={is_urgent}")

    # ── ACİL: Yasin'e anında bildir + ön cevap ───────────────────────────────
    if is_urgent:
        threading.Thread(
            target=_notify_yasin,
            args=(
                f"🚨 <b>ACİL Mail</b>\n{hitap} → <b>{subject}</b>\n"
                f"Öne alayım mı?\n\n{body[:200]}",
            ),
            daemon=True
        ).start()
        send_mail(
            to          = from_mail,
            subject     = f"Re: {subject}",
            body        = (
                f"Merhaba {hitap},\n\n"
                f"ACİL talebinizi aldım. Yetkililere bildirdim, beklemede tutuyorum.\n\n"
                f"Rosepith Sistem"
            ),
            reply_to_id = message_id,
        )

    # ── Revize ───────────────────────────────────────────────────────────────
    if is_revize:
        _handle_mail_revize(from_mail, profil, subject, body,
                             message_id, thread_ref, is_urgent)
        return

    # ── Yeni iş ──────────────────────────────────────────────────────────────
    help_type  = _detect_help_type(body)
    complexity = _detect_complexity(body)

    # Fiyat talebi
    if help_type == "price_offer":
        threading.Thread(
            target=_notify_yasin,
            args=(f"💰 <b>Mail Fiyat Talebi</b>\n{hitap}\nKonu: {subject}\n\n{body[:300]}",),
            daemon=True
        ).start()
        send_mail(
            to          = from_mail,
            subject     = f"Re: {subject}",
            body        = (
                f"Merhaba {hitap},\n\nFiyat/teklif talebinizi yetkili ekibe ilettim. "
                f"En kısa sürede dönüş yapılacak.\n\nRosepith Sistem"
            ),
            reply_to_id = message_id,
        )
        _add_work_item(hitap, phone or from_mail, help_type, complexity,
                       f"[MAIL] {subject}\n\n{body}", is_urgent=is_urgent)
        log_event(AGENT_NAME, f"Mail fiyat talebi → {hitap}")
        return

    # Kişisel / anormal
    if help_type == "personal_abnormal":
        threading.Thread(
            target=_notify_yasin,
            args=(f"⚠️ <b>Mail Kişisel/Anormal</b>\n{hitap}\nKonu: {subject}\n\n{body[:300]}",),
            daemon=True
        ).start()
        send_mail(
            to          = from_mail,
            subject     = f"Re: {subject}",
            body        = (
                f"Merhaba {hitap},\n\nDurumunuzu yetkililere ilettim. "
                f"En kısa sürede ilgilenilecek.\n\nRosepith Sistem"
            ),
            reply_to_id = message_id,
        )
        _add_work_item(hitap, phone or from_mail, help_type, complexity,
                       f"[MAIL] {subject}\n\n{body}", is_urgent=is_urgent)
        log_event(AGENT_NAME, f"Mail kişisel/anormal → {hitap}")
        return

    # Data / Taktik → AI
    item_id = _add_work_item(
        hitap, phone or from_mail, help_type, complexity,
        f"[MAIL] {subject}\n\n{body}", is_urgent=is_urgent
    )

    system_p   = PERSONEL_SYSTEM + f"\n\nPersonel: {hitap} | Kanal: E-posta"
    full_input = f"Konu: {subject}\n\n{body}"
    reply_text = _get_ai_response(complexity, [], full_input, system_p)

    if reply_text is None:
        reply_text = "Talebinizi aldım, inceleyip en kısa sürede dönüş yapacağım."
        threading.Thread(
            target=_notify_yasin,
            args=(f"⚠️ Personel AI (mail) başarısız\n{hitap}: {subject[:60]}",),
            daemon=True
        ).start()

    _complete_work_item(item_id, reply_text)

    # Mail ile cevap (thread'e)
    sent = send_mail(
        to          = from_mail,
        subject     = f"Re: {subject}",
        body        = (
            f"Merhaba {hitap},\n\n{reply_text}\n\nRosepith Sistem"
        ),
        reply_to_id = message_id,
    )

    # WA kısa bildirimi
    if phone and sent:
        tip_str = "araştırma sonucu" if help_type == "data_research" else "taktik önerisi"
        threading.Thread(
            target=_send_whatsapp,
            args=(phone, f"{hitap}, {tip_str} mailine yolladım, kontrol et 🌟"),
            daemon=True
        ).start()

    log_event(AGENT_NAME, f"Mail yanıtlandı → {hitap} | {help_type}/{complexity}")
