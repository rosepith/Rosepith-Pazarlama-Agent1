# -*- coding: utf-8 -*-
"""
Google Maps lead cekme testi.
Kullanim:
  python test_maps.py                    -> Bu ayin sektoru, Izmir
  python test_maps.py "dugun salonu"     -> Ozel sektor, Izmir
  python test_maps.py "kuafor" "Ankara"  -> Ozel sektor + bolge
"""

import sys
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from agents.sales_automation import (
    run_maps_lead_fetch,
    get_current_sector,
    get_current_sector_list,
    MAPS_BOLGE,
)
from core.config import GOOGLE_MAPS_API_KEY
import datetime

# ─── Argümanlar ───────────────────────────────────────────────────────────────
sektor = sys.argv[1] if len(sys.argv) > 1 else None
bolge  = sys.argv[2] if len(sys.argv) > 2 else MAPS_BOLGE

# ─── Başlık ───────────────────────────────────────────────────────────────────
print("=" * 60)
print("  Rosepith — Google Maps Lead Test")
print("=" * 60)
print(f"  Tarih   : {datetime.date.today()}")
print(f"  Ay sektörleri: {', '.join(get_current_sector_list())}")
print(f"  Seçilen : {sektor or get_current_sector()}")
print(f"  Bölge   : {bolge}")
print(f"  API Key : {'✅ VAR' if GOOGLE_MAPS_API_KEY else '❌ EKSİK'}")
print("=" * 60)

if not GOOGLE_MAPS_API_KEY:
    print("\n❌ GOOGLE_MAPS_API_KEY .env'de tanımlı değil!")
    sys.exit(1)

# ─── Çalıştır ─────────────────────────────────────────────────────────────────
ozet = run_maps_lead_fetch(sektor=sektor, bolge=bolge, verbose=True)

# ─── Sonuç özeti ──────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  SONUÇ")
print("=" * 60)
toplam = 0
for personel, liste in ozet.items():
    print(f"  {personel}: {len(liste)} yeni müşteri kaydedildi")
    toplam += len(liste)
print(f"  TOPLAM : {toplam} yeni kayıt")
print("=" * 60)
