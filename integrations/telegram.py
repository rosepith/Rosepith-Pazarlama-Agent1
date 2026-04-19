# Rosepith Pazarlama Agent - Telegram Entegrasyonu
# Bot üzerinden mesaj gönderme, komut alma ve bildirim yönetimi

import requests
from core.config import TELEGRAM_BOT_TOKEN
from core.database import log_event

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Belirtilen sohbete mesaj gönderir."""
    try:
        resp = requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }, timeout=10)
        success = resp.json().get("ok", False)
        log_event("telegram", f"Mesaj gönderildi: chat_id={chat_id}, başarı={success}")
        return success
    except Exception as e:
        log_event("telegram", f"Mesaj gönderilemedi: {e}", level="ERROR")
        return False


def get_updates(offset: int = 0) -> list:
    """Bot'a gelen güncellemeleri (mesajlar/komutlar) çeker."""
    try:
        resp = requests.get(f"{BASE_URL}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=35)
        return resp.json().get("result", [])
    except Exception as e:
        log_event("telegram", f"Güncelleme alınamadı: {e}", level="ERROR")
        return []


def notify_completion(chat_id: str, project: str, url: str, admin_url: str, username: str, password: str):
    """Proje tamamlanınca standart bildirim mesajı gönderir."""
    text = (
        f"<b>✅ Proje Tamamlandı: {project}</b>\n\n"
        f"🔗 <a href='{url}'>Canlı Link</a>\n"
        f"⚙️ <a href='{admin_url}'>Admin Panel</a>\n"
        f"👤 Kullanıcı: <code>{username}</code>\n"
        f"🔑 Şifre: <code>{password}</code>"
    )
    return send_message(chat_id, text)
