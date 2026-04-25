# Rosepith — Merkezi WhatsApp Gönderici
#
# Meta Cloud API v19.0
# 24 saatlik mesajlaşma penceresi kuralı:
#   - Son 24 saatte müşteri/personel mesaj ATTIYSA → düz metin gönderilir
#   - 24 saat GEÇTİYSE → önce onaylı şablon gönderilir (pencereyi açar),
#     2sn bekle, sonra asıl mesaj gönderilir
#
# Onaylı şablonlar:
#   merhaba_1         → parametre yok,  "genel selamlama"
#   hello_world       → parametre yok,  Meta varsayılanı
#   personel_bildirim → {{1}} = isim,   "Merhaba {{1}}, iyi çalışmalar."
#
# Tüm _send_wa / _send_whatsapp çağrıları buraya taşınmalı.

import time
import logging
import datetime
import requests

from core.config import WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN

logger = logging.getLogger(__name__)

# Meta hata kodu: mesajlaşma penceresi dışı
WA_WINDOW_ERROR_CODES = {131026, 131047}

# Kaç saatlik pencere?
WINDOW_HOURS = 24


# ─── Son mesaj zamanı ──────────────────────────────────────────────────────────

def _last_incoming_time(phone: str) -> datetime.datetime | None:
    """
    Verilen telefon numarasının son gelen (direction='in') mesaj zamanını döndür.
    conversations tablosunu kullanır.
    """
    try:
        from core.database import get_connection
        conn = get_connection()
        row = conn.execute(
            """SELECT MAX(created_at) FROM conversations
               WHERE user_id=? AND direction='in'""",
            (phone,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            return datetime.datetime.fromisoformat(str(row[0]))
    except Exception as e:
        logger.warning(f"last_incoming_time hata ({phone}): {e}")
    return None


def _is_within_window(phone: str) -> bool:
    """Son 24 saat içinde gelen mesaj var mı?"""
    last = _last_incoming_time(phone)
    if last is None:
        return False
    return (datetime.datetime.now() - last).total_seconds() < WINDOW_HOURS * 3600


# ─── Meta API çağrıları ───────────────────────────────────────────────────────

def _wa_headers() -> dict:
    return {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _wa_url() -> str:
    return f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"


def _parse_wa_response(resp: requests.Response) -> tuple[bool, int, str]:
    """
    Döndürür: (başarılı, hata_kodu, hata_mesajı)
    Meta HTTP 200 döner ama body'de error olabilir.
    """
    try:
        body = resp.json()
        if "error" in body:
            err = body["error"]
            code = err.get("code", 0)
            msg  = err.get("message", str(err))[:150]
            return False, code, msg
        # messages[0].id varsa başarılı
        if body.get("messages"):
            return True, 0, ""
        return True, 0, ""   # belirsiz ama hata yok
    except Exception:
        return resp.status_code < 300, 0, resp.text[:100]


def _send_text_raw(to: str, text: str) -> tuple[bool, int, str]:
    """Düz metin gönder, (başarılı, hata_kodu, hata_mesajı) döndür."""
    try:
        resp = requests.post(
            _wa_url(), headers=_wa_headers(),
            json={
                "messaging_product": "whatsapp",
                "to": to, "type": "text",
                "text": {"preview_url": False, "body": text},
            },
            timeout=10,
        )
        ok, code, msg = _parse_wa_response(resp)
        if ok:
            logger.info(f"WA metin ✓ → {to}")
        else:
            logger.warning(f"WA metin ✗ → {to} | kod={code} | {msg}")
        return ok, code, msg
    except Exception as e:
        logger.error(f"WA metin istek hatası ({to}): {e}")
        return False, 0, str(e)


def _send_template_raw(to: str, template: str,
                        params: list[str] | None = None) -> tuple[bool, int, str]:
    """
    Şablon gönder.
    params: ['Eda Hanım'] → {{1}} yerine geçer
    """
    components = []
    if params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params],
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": to, "type": "template",
        "template": {
            "name": template,
            "language": {"code": "tr"},
            **({"components": components} if components else {}),
        },
    }
    try:
        resp = requests.post(_wa_url(), headers=_wa_headers(),
                              json=payload, timeout=10)
        ok, code, msg = _parse_wa_response(resp)
        if ok:
            logger.info(f"WA şablon ✓ → {to} [{template}]")
        else:
            logger.warning(f"WA şablon ✗ → {to} [{template}] kod={code} | {msg}")
        return ok, code, msg
    except Exception as e:
        logger.error(f"WA şablon istek hatası ({to}): {e}")
        return False, 0, str(e)


# ─── Ana gönderici ────────────────────────────────────────────────────────────

def send_wa(to: str, text: str,
            personel_hitap: str = "",
            force_template: bool = False) -> bool:
    """
    Akıllı WhatsApp gönderici:

    1. 24h pencere açıksa → düz metin gönder
    2. Pencere kapalıysa (veya force_template=True):
       a. personel_bildirim şablonu gönder (pencereyi aç)
       b. 2sn bekle
       c. Asıl metni gönder
    3. Herhangi bir adımda hata → logla, Yasin'e bildir

    personel_hitap: şablon {{1}} parametresi ("Eda Hanım" gibi)
    Döndürür: True = asıl metin gönderildi
    """
    if not to or not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.warning(f"WA gönderim atlandı — kimlik bilgisi eksik ({to})")
        return False

    within_window = _is_within_window(to)

    # Pencere açıksa → direkt metin
    if within_window and not force_template:
        ok, code, err_msg = _send_text_raw(to, text)
        if ok:
            return True
        if code in WA_WINDOW_ERROR_CODES:
            logger.warning(f"WA pencere hatası (window=True ama API reddetti) → şablon fallback")
            # Pencere aslında kapalı, fallback'e düş
        else:
            _notify_yasin_wa_error(to, personel_hitap or to, code, err_msg)
            return False

    # Pencere kapalı → şablon ile aç, sonra metin gönder
    logger.info(f"WA 24h pencere dışı → personel_bildirim şablonu gönderiliyor ({to})")
    hitap_param = personel_hitap or to
    tmpl_ok, tmpl_code, tmpl_err = _send_template_raw(
        to, "personel_bildirim", params=[hitap_param]
    )

    if not tmpl_ok:
        logger.error(f"WA şablon başarısız ({to}) — metin de gönderilemiyor")
        _notify_yasin_wa_error(to, hitap_param, tmpl_code, tmpl_err)
        return False

    # Pencere açıldı, asıl mesajı gönder
    time.sleep(2)
    ok, code, err_msg = _send_text_raw(to, text)
    if not ok:
        logger.error(f"WA şablon sonrası metin başarısız ({to}): kod={code}")
        _notify_yasin_wa_error(to, hitap_param, code, err_msg)
        return False

    return True


def send_wa_template(to: str, template: str,
                     params: list[str] | None = None) -> bool:
    """Direkt şablon gönder (24h kontrolü yok)."""
    ok, _, _ = _send_template_raw(to, template, params)
    return ok


# ─── Hata bildirimi ───────────────────────────────────────────────────────────

def _notify_yasin_wa_error(to: str, hitap: str, code: int, msg: str):
    """WA gönderim hatası Yasin'e Telegram bildirimi."""
    try:
        from core.config import TELEGRAM_BOT_TOKEN, YASIN_TELEGRAM_ID
        if not TELEGRAM_BOT_TOKEN or not YASIN_TELEGRAM_ID:
            return
        text = (
            f"⚠️ <b>WA Gönderim Hatası</b>\n"
            f"Alıcı : {hitap} ({to})\n"
            f"Kod   : {code}\n"
            f"Hata  : {msg}"
        )
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": YASIN_TELEGRAM_ID, "text": text, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception:
        pass
