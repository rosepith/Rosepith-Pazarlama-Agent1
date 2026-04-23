# Rosepith Pazarlama Agent - WhatsApp Meta Business API Entegrasyonu

import requests
from core.config import (
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_ACCESS_TOKEN,
)
from core.database import log_event

_BASE_URL = "https://graph.facebook.com/v19.0"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def send_message(to: str, text: str) -> bool:
    """WhatsApp üzerinden metin mesajı gönderir."""
    url = f"{_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=10)
        resp.raise_for_status()
        log_event("whatsapp", f"Mesaj gönderildi: {to}")
        return True
    except requests.RequestException as e:
        log_event("whatsapp", f"Mesaj gönderilemedi ({to}): {e}")
        return False


def send_template(to: str, template_name: str, language: str = "tr", components: list = None) -> bool:
    """WhatsApp onaylı template mesajı gönderir."""
    url = f"{_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
        },
    }
    if components:
        payload["template"]["components"] = components
    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=10)
        resp.raise_for_status()
        log_event("whatsapp", f"Template gönderildi ({template_name}): {to}")
        return True
    except requests.RequestException as e:
        log_event("whatsapp", f"Template gönderilemedi ({to}): {e}")
        return False


def parse_webhook(payload: dict) -> list[dict]:
    """Meta webhook payload'ından gelen mesajları ayrıştırır."""
    messages = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    messages.append({
                        "from": msg.get("from"),
                        "id": msg.get("id"),
                        "timestamp": msg.get("timestamp"),
                        "type": msg.get("type"),
                        "text": msg.get("text", {}).get("body", "") if msg.get("type") == "text" else "",
                        "raw": msg,
                    })
    except Exception as e:
        log_event("whatsapp", f"Webhook parse hatası: {e}")
    return messages


def mark_as_read(message_id: str) -> bool:
    """Gelen mesajı okundu olarak işaretler."""
    url = f"{_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException:
        return False
