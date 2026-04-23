# Rosepith Pazarlama Agent — Hibrit Ana Beyin (W10)
# Sunucudan mesaj çeker, işler, yanıt yollar

import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

from core.database import init_db, log_event
from core.config import SYSTEM_MODE


def main():
    logger.info("=" * 50)
    logger.info("Rosepith Hibrit Agent başlatılıyor...")
    logger.info(f"Mod: {SYSTEM_MODE}")
    logger.info("=" * 50)

    init_db()
    log_event("system", f"Sistem başlatıldı (mod: {SYSTEM_MODE})")

    # Art Direktör — Telegram kapısı
    from agents.art_director import ArtDirectorAgent
    art = ArtDirectorAgent()
    art.start()
    log_event("system", "Art Direktör aktif (Telegram)")

    # Sunucu relay — heartbeat + mesaj kuyruk poller
    from core.server_relay import start as start_relay
    start_relay()
    log_event("system", "Sunucu relay aktif (heartbeat + poller)")

    logger.info("✅ Sistem hazır")
    logger.info("   Telegram: dinleniyor")
    logger.info("   Sunucu relay: heartbeat + poll aktif")
    logger.info("   Çıkış için Ctrl+C")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Kapatılıyor...")
        art.stop()
        log_event("system", "Sistem durduruldu")


if __name__ == "__main__":
    main()
