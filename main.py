# Rosepith Pazarlama Agent - Ana Giriş Noktası
# Sistemi başlatır, modu seçer ve ajan orkestrasyon döngüsünü çalıştırır

import sys
import time
from core.database import init_db, log_event
from core.config import SYSTEM_MODE


def main():
    print("Rosepith Pazarlama Agent baslatiliyor...")

    init_db()
    log_event("system", f"Sistem başlatıldı (mod: {SYSTEM_MODE})")

    # Art Direktör her zaman aktif — Telegram kapısını o tutar
    from agents.art_director import ArtDirectorAgent
    art_director = ArtDirectorAgent()
    art_director.start()

    # Moda göre diğer ajanları yükle
    if SYSTEM_MODE == "full":
        from modes.full_mode import run
        run()
    elif SYSTEM_MODE == "backup":
        from modes.backup_mode import run
        run()
    elif SYSTEM_MODE == "assistant":
        from modes.assistant_mode import run
        run()
    else:
        print(f"[Hata] Bilinmeyen mod: {SYSTEM_MODE}")
        sys.exit(1)

    print(f"\n[OK] Sistem hazir (mod: {SYSTEM_MODE})")
    print("Dashboard icin: python -m terminal.dashboard")
    print("Cikis icin Ctrl+C\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[System] Kapatılıyor...")
        art_director.stop()
        log_event("system", "Sistem durduruldu")


if __name__ == "__main__":
    main()
