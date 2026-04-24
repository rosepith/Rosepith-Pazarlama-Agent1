# -*- coding: utf-8 -*-
"""
PARCA 2 test — Musteri zenginlestirme + mail
Test maili artdirektor@rosepith.net'e gider (personel mailine degil).

Kullanim:
  python test_brief.py              -> Bugun DB'deki musteriler
  python test_brief.py --refetch    -> Once Maps'ten yeniden cek, sonra brief
"""

import sys
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import datetime
from core.database import get_connection
from core.config import ANTHROPIC_API_KEY, OPENAI_API_KEY, YANDEX_MAIL
from agents.sales_automation import (
    run_maps_lead_fetch, run_morning_brief_mail,
    get_current_sector, _get_todays_customers, _get_satis_personeli,
)

TEST_MAIL = YANDEX_MAIL  # artdirektor@rosepith.net

print("=" * 60)
print("  Rosepith — Brief + Mail Test (PARCA 2)")
print("=" * 60)
print(f"  Tarih    : {datetime.date.today()}")
print(f"  Sektor   : {get_current_sector()}")
print(f"  Claude   : {'VAR' if ANTHROPIC_API_KEY else 'YOK — GPT fallback'}")
print(f"  OpenAI   : {'VAR' if OPENAI_API_KEY else 'YOK'}")
print(f"  Test mail: {TEST_MAIL}")
print("=" * 60)

# ─── Refetch flag kontrol ──────────────────────────────────────────────────────
if "--refetch" in sys.argv:
    print("\n[1/3] Maps'ten yeniden lead cekiliyor...")
    ozet = run_maps_lead_fetch(verbose=True)
    for p, liste in ozet.items():
        print(f"  {p}: {len(liste)} kayit")
else:
    # DB'deki bugunun musterilerini kontrol
    personeller = _get_satis_personeli()
    toplam = 0
    for p in personeller:
        bugun_musteriler = _get_todays_customers(p["hitap"])
        print(f"\n  {p['hitap']}: {len(bugun_musteriler)} musteri DB'de ('yeni' durumda)")
        toplam += len(bugun_musteriler)
    if toplam == 0:
        print("\nBugune ait 'yeni' musteri yok.")
        print("Yeniden Maps'ten cekip deneme icin: python test_brief.py --refetch")
        print("Veya mevcut kayitlari sifirlamak icin once DB'yi kontrol edin.")
        sys.exit(0)

# ─── Zenginlestir + Mail ───────────────────────────────────────────────────────
print(f"\n[2/3] Zenginlestirme + mail uretiliyor (test mail: {TEST_MAIL})...")
print("  (Her musteri icin AI cagrisi yapiliyor, birka dakika surebilir)\n")

ozet = run_morning_brief_mail(test_override_mail=TEST_MAIL)

# ─── Sonuc ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  SONUC")
print("=" * 60)
for personel, durum in ozet.items():
    mail_durum = "GONDERILDI" if durum.get("mail_sent") else "GONDERILEMEDI"
    fallback   = " (fallback kullanildi)" if durum.get("fallback_used") else ""
    print(f"  {personel}: {durum.get('customers_count', 0)} musteri, "
          f"mail {mail_durum}{fallback}")
    if durum.get("to_mail"):
        print(f"    -> {durum['to_mail']}")
print("=" * 60)
print(f"\nTest maili {TEST_MAIL} adresine gonderildi.")
print("Gercek gonderim icin .env'e PERSONEL_1_MAIL ve PERSONEL_2_MAIL ekle.")
