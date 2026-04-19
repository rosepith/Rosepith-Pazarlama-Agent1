# Rosepith Pazarlama Agent - WhatsApp Entegrasyonu
# WhatsApp Business API veya Twilio üzerinden mesajlaşma

from core.config import WHATSAPP_NUMBER
from core.database import log_event


def send_message(to: str, text: str) -> bool:
    """WhatsApp üzerinden mesaj gönderir (API entegrasyonu yapılacak)."""
    log_event("whatsapp", f"Mesaj kuyruğa alındı: {to}")
    # Twilio veya Meta WhatsApp Business API buraya eklenecek
    print(f"[WhatsApp] {to} -> {text}")
    return True


def receive_webhook(payload: dict) -> dict:
    """WhatsApp webhook gelen mesajı işler."""
    log_event("whatsapp", "Webhook alındı")
    # Webhook doğrulama ve mesaj ayrıştırma buraya eklenecek
    return {"status": "received", "payload": payload}
