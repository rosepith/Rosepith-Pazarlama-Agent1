# -*- coding: utf-8 -*-
"""
PARCA 4 — /durum komutu ve sistem saglik testi.

Kullanim:
  python test_durum.py        -> /durum komut ciktisini goster
  python test_durum.py --17   -> 17:30 hatirlatma mesajini test et
"""
import sys, os, io, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

print("=" * 60)
print("  Rosepith — Sistem Saglik Testi (PARCA 4)")
print("=" * 60)
print(f"  Tarih : {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}")
print("=" * 60)

# ─── /durum komutu ───────────────────────────────────────────────────────────
print("\n  [1] /durum komutu onizleme:")
print("  " + "-" * 50)
from agents.art_director import _cmd_durum
durum = _cmd_durum()
# HTML taglerini sil (okunabilirlik)
durum_clean = durum.replace("<b>","").replace("</b>","")
for line in durum_clean.split("\n"):
    print("  " + line)

# ─── Thread listesi ───────────────────────────────────────────────────────────
print("\n  [2] Sistem thread listesi (main.py scheduler'lari):")
print("  " + "-" * 50)
threads_expected = {
    "art_director_poll":         "Art Direktör Telegram polling",
    "sales_automation":          "Satış otomasyonu (09:30/12:00/15:00/17:30)",
    "evening_report_scheduler":  "Akşam raporu (18:00)",
    "mail_polling":              "Mail polling (60s, mesai ici)",
}
import threading
aktif = {t.name for t in threading.enumerate()}
for thread_name, aciklama in threads_expected.items():
    durum_str = "AKTIF ✓" if thread_name in aktif else "henuz baslamadi (normal - test modu)"
    print(f"    {thread_name:<30} → {durum_str}")
    print(f"    {'':30}   {aciklama}")

# ─── Scheduler saatleri ──────────────────────────────────────────────────────
print("\n  [3] Gunluk zaman cizelgesi:")
print("  " + "-" * 50)
schedule = [
    ("09:30", "run_daily_sales_flow → Maps lead cek + brief mail + WA"),
    ("09:35", "(5dk sonra) Brief mail + WA bildirim gonderimi"),
    ("12:00", "Durtmece WA: 'Sabah gorusmeler nasil gitti?'"),
    ("15:00", "Durtmece WA: 'Ogleden sonra destek gerekiyor mu?'"),
    ("17:30", "Hatirlatma WA: 'Bugunun ozetini mailinize yollayin'"),
    ("18:00", "Aksam raporu: Telegram + mail (Yasin'e)"),
    ("60s",   "Mail polling: IMAP - yeni mail var mi? (mesai ici)"),
]
for saat, aciklama in schedule:
    print(f"    {saat:<8} → {aciklama}")

# ─── 17:30 hatırlatma testi ──────────────────────────────────────────────────
if "--17" in sys.argv:
    print("\n  [TEST] 17:30 hatirlatma mesajlari simule ediliyor...")
    from agents.sales_automation import _get_satis_personeli, _get_durtmece
    personeller = _get_satis_personeli()
    for i, p in enumerate(personeller):
        msg = _get_durtmece("17:30", p["hitap"], idx=i)
        print(f"\n  {p['hitap']}:")
        print(f"  '{msg}'")
    print("\n  Not: Gercek WA gonderimi icin test_wa_brief.py kullanin.")

print("\n" + "=" * 60)
print("  SISTEM DURUM OZETI")
print("=" * 60)
from core.holiday_checker import is_holiday, is_work_hours, get_holiday_name
bugun = datetime.date.today()
print(f"  Bugun tatil : {'EVET - ' + get_holiday_name(bugun) if is_holiday(bugun) else 'Hayir (is gunu)'}")
print(f"  Mesai       : {'Ici' if is_work_hours() else 'Disi'}")
from core.mail_handler import get_last_poll_time
print(f"  Son mail poll: {get_last_poll_time()}")
print("=" * 60)
