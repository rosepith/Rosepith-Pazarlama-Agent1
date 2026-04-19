# Rosepith Pazarlama Agent - Ana Giriş Noktası
# Sistemi başlatır, modu seçer ve ajan orkestrasyon döngüsünü çalıştırır

import sys
from core.database import init_db, log_event
from core.config import SYSTEM_MODE


def main():
    print("🌹 Rosepith Pazarlama Agent başlatılıyor...")

    # Veritabanını kur
    init_db()
    log_event("system", f"Sistem başlatıldı (mod: {SYSTEM_MODE})")

    # Moda göre uygun modülü yükle
    if SYSTEM_MODE == "full":
        from modes.full_mode import run
    elif SYSTEM_MODE == "backup":
        from modes.backup_mode import run
    elif SYSTEM_MODE == "assistant":
        from modes.assistant_mode import run
    else:
        print(f"[Hata] Bilinmeyen mod: {SYSTEM_MODE}")
        sys.exit(1)

    agents = run()

    print(f"\n✅ Sistem hazır (mod: {SYSTEM_MODE})")
    print("Dashboard için: python -m terminal.dashboard")
    print("Çıkmak için Ctrl+C\n")

    # Ana döngü (Telegram polling veya görev kuyruğu buraya bağlanacak)
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("\n[System] Kapatılıyor...")
        log_event("system", "Sistem durduruldu")


if __name__ == "__main__":
    main()
