"""
Rosepith Hibrit Relay - W10 tarafı
Sunucuya heartbeat atar, mesaj kuyruğunu çeker, işler.
"""

import time
import threading
import logging
import requests

from core.config import RELAY_SECRET, SERVER_RELAY_URL

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 60   # saniye
POLL_INTERVAL      = 5    # saniye
RELAY_HEADERS      = {'X-Relay-Secret': RELAY_SECRET, 'Content-Type': 'application/json'}


def _heartbeat_loop():
    """Sunucuya her dakika canlılık sinyali gönder."""
    while True:
        try:
            r = requests.post(
                f"{SERVER_RELAY_URL}?action=heartbeat",
                headers=RELAY_HEADERS,
                timeout=8
            )
            if r.status_code == 200:
                logger.info("Heartbeat OK")
            else:
                logger.warning(f"Heartbeat {r.status_code}")
        except Exception as e:
            logger.error(f"Heartbeat hata: {e}")
        time.sleep(HEARTBEAT_INTERVAL)


def _poll_loop():
    """Sunucudaki kuyruktan mesaj çek ve işle."""
    from agents.art_director import handle_whatsapp_message
    while True:
        try:
            r = requests.get(
                f"{SERVER_RELAY_URL}?action=queue",
                headers=RELAY_HEADERS,
                timeout=10
            )
            if r.status_code == 200:
                messages = r.json().get('messages', [])
                for msg in messages:
                    logger.info(f"Kuyruktan mesaj: {msg.get('phone')} | {msg.get('text', '')[:60]}")
                    threading.Thread(
                        target=_process_and_mark_done,
                        args=(msg,),
                        daemon=True
                    ).start()
        except Exception as e:
            logger.error(f"Poll hata: {e}")
        time.sleep(POLL_INTERVAL)


def _process_and_mark_done(msg: dict):
    """Mesajı işle, sunucuya tamamlandı bildir."""
    from agents.art_director import handle_whatsapp_message
    try:
        phone = msg.get('phone', '')
        name  = msg.get('name', '')
        text  = msg.get('text', '').strip()
        if phone and text:
            handle_whatsapp_message(phone, name, text)
    except Exception as e:
        logger.error(f"Mesaj işleme hata: {e}")
    finally:
        # Her durumda done bildir (tekrar işlenmesin)
        try:
            requests.post(
                f"{SERVER_RELAY_URL}?action=done",
                headers=RELAY_HEADERS,
                json={'id': msg.get('id')},
                timeout=5
            )
        except Exception:
            pass


def start():
    """Heartbeat ve poller thread'lerini başlat."""
    # İlk heartbeat hemen
    threading.Thread(target=_heartbeat_loop, daemon=True, name="relay_heartbeat").start()
    threading.Thread(target=_poll_loop,      daemon=True, name="relay_poller").start()
    logger.info("Server relay başlatıldı (heartbeat + poller aktif)")
