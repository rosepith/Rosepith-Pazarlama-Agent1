# -*- coding: utf-8 -*-
"""
PARCA 4 — Akşam raporu manuel tetikleme testi.

Kullanim:
  python test_evening.py          -> Raporu tetikle (Telegram + mail)
  python test_evening.py --stats  -> Sadece stats topla, ekrana bas
"""
import sys, os, io, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from agents.evening_report import _collect_stats, _build_telegram_summary, _build_mail_report, _generate_yarinkiler, run_evening_report

print("=" * 60)
print("  Rosepith — Aksam Raporu Testi (PARCA 4)")
print("=" * 60)
print(f"  Tarih : {datetime.date.today()}")
print("=" * 60)

stats = _collect_stats()

print("\n  TOPLANAN VERİ:")
print(f"  Bugun lead          : {stats['bugun_lead']} ({stats['eda_lead']} Eda, {stats['asuman_lead']} Asuman)")
print(f"  Brief gonderildi    : {stats['brief_gonderildi']}")
print(f"  Is tamamlanan       : {stats['is_tamamlanan']}")
print(f"  Is bekleyen         : {stats['is_bekleyen']}")
print(f"  Acil isler          : {stats['acil_isler']}")
print(f"  Mail gelen          : {stats['mail_gelen']}")
print(f"  Mail giden          : {stats['mail_giden']}")
print(f"  Mail revize         : {stats['mail_revize']}")
print(f"  Mail acil           : {stats['mail_acil']}")
print(f"  Maps calistirildi   : {stats['maps_calistirildi']}")
print(f"  Brief calistirildi  : {stats['brief_calistirildi']}")
print(f"  Son hata            : {stats['son_hata'] or 'yok'}")

if "--stats" in sys.argv:
    sys.exit(0)

print("\n  TELEGRAM OZETI ONIZLEME:")
print("  " + "-" * 50)
tg = _build_telegram_summary(stats)
for line in tg.split("\n"):
    print("  " + line)

print("\n  MAİL RAPORU ONIZLEME:")
print("  " + "-" * 50)
yarinkiler = _generate_yarinkiler(stats)
mail = _build_mail_report(stats, yarinkiler)
for line in mail.split("\n"):
    print("  " + line)

print("\n" + "=" * 60)
print("  GONDERIMINUYAPIYORUM (force=True)...")
print("=" * 60)
sonuc = run_evening_report(force=True)
print(f"\n  Telegram : {'GONDERILDI ✓' if sonuc.get('tg_sent') else 'BASARISIZ ✗'}")
print(f"  Mail     : arka planda gonderiliyor → artdirektor@rosepith.net")
if sonuc.get("error"):
    print(f"  HATA     : {sonuc['error']}")
print()
