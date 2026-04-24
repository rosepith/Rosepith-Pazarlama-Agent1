# -*- coding: utf-8 -*-
"""
WhatsApp brief bildirim testi (PARCA 2 EK).

Ne test eder:
  1. run_morning_brief_mail(test_override_wa=TEST_WA) → WA bildirimi
  2. run_daily_sales_flow() çift çalışma engeli

Kullanim:
  python test_wa_brief.py              -> Bugunkü 'yeni' musterilerle test
  python test_wa_brief.py --reset      -> Durumu sifirla, yeniden test
  python test_wa_brief.py --full-flow  -> run_daily_sales_flow() simule (Maps atlar)
"""

import sys
import os
import io
import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from core.database import get_connection
from core.config import YANDEX_MAIL, TEST_CUSTOMER_WHATSAPP
from agents.sales_automation import (
    run_morning_brief_mail,
    _get_satis_personeli,
    _get_todays_customers,
    _already_sent,
    _mark_sent,
    _init_daily_table,
    get_current_sector,
)

TEST_MAIL = YANDEX_MAIL
TEST_WA   = TEST_CUSTOMER_WHATSAPP or ""

bugun = datetime.date.today().isoformat()

print("=" * 60)
print("  Rosepith — WA Brief Bildirim Testi (PARCA 2 EK)")
print("=" * 60)
print(f"  Tarih    : {bugun}")
print(f"  Sektor   : {get_current_sector()}")
print(f"  Test mail: {TEST_MAIL}")
print(f"  Test WA  : {TEST_WA or '!! .env TEST_CUSTOMER_WHATSAPP eksik !!'}")
print("=" * 60)

# ─── --reset: durum sifirla ──────────────────────────────────────────────────
if "--reset" in sys.argv:
    print("\n[RESET] Bugune ait brief durumu sifirlanıyor...")
    conn = get_connection()

    # Son_durum='brief_gonderildi' → 'yeni' yap (SQLite uyumlu subquery)
    conn.execute(
        """UPDATE customers
           SET son_durum = 'yeni'
           WHERE id IN (
               SELECT id FROM customers
               WHERE atama_tarihi = ?
               AND son_durum IN ('brief_hazirlandi', 'brief_gonderildi')
           )""",
        (bugun,)
    )
    guncellenen = conn.total_changes

    # daily_sales: bugunun brief/maps kayitlarini sil
    conn.execute(
        "DELETE FROM daily_sales WHERE date=? AND personel='sistem'",
        (bugun,)
    )
    conn.execute(
        "DELETE FROM daily_sales WHERE date=? AND event LIKE 'sabah%'",
        (bugun,)
    )
    conn.commit()
    conn.close()
    print(f"  {guncellenen} musteri durumu 'yeni' yapildi")
    print("  daily_sales bugun kayitlari silindi")
    print("  Yeniden test edebilirsiniz.\n")

# ─── Musteri kontrolu ───────────────────────────────────────────────────────
personeller = _get_satis_personeli()
toplam_musteri = 0
for p in personeller:
    m_list = _get_todays_customers(p["hitap"])
    print(f"\n  {p['hitap']}: {len(m_list)} musteri ('yeni' durumda)")
    toplam_musteri += len(m_list)

if toplam_musteri == 0:
    print("\n  Bugune ait 'yeni' musteri yok.")
    print("  Oneri: once test_brief.py --refetch calistirin.")
    print("  Ya da: python test_wa_brief.py --reset")
    sys.exit(0)

# ─── Cift calisma durumu kontrolu ───────────────────────────────────────────
if "--full-flow" not in sys.argv:
    maps_sent   = _already_sent("sistem", "maps_fetch")
    brief_sent  = _already_sent("sistem", "brief_mail")
    print(f"\n  Cift-engel durumu:")
    print(f"    maps_fetch  : {'GONDERILDI (atlanir)' if maps_sent else 'yok'}")
    print(f"    brief_mail  : {'GONDERILDI (atlanir)' if brief_sent else 'yok'}")

# ─── run_morning_brief_mail: mail + WA testi ─────────────────────────────────
if "--full-flow" not in sys.argv:
    print(f"\n[TEST] run_morning_brief_mail() baslatiliyor...")
    print(f"  Mail → {TEST_MAIL}")
    print(f"  WA   → {TEST_WA or '(atlanir — TEST_CUSTOMER_WHATSAPP eksik)'}\n")

    ozet = run_morning_brief_mail(
        test_override_mail = TEST_MAIL,
        test_override_wa   = TEST_WA or None,
    )

    print("\n" + "=" * 60)
    print("  SONUC")
    print("=" * 60)
    for personel, durum in ozet.items():
        mail_durum = "GONDERILDI ✓" if durum.get("mail_sent") else "GONDERILEMEDI ✗"
        wa_durum   = "GONDERILDI ✓" if durum.get("wa_sent")   else "atlandi"
        fallback   = f" [{durum.get('model_used','?')}]" if durum.get("fallback_used") else ""
        print(f"  {personel}:")
        print(f"    Musteri sayisi : {durum.get('customers_count', 0)}")
        print(f"    Mail           : {mail_durum} → {durum.get('to_mail','')}")
        print(f"    WA bildirimi   : {wa_durum} → {durum.get('wa_target','')}")
        if fallback:
            print(f"    AI modeli      : {fallback.strip()}")
    print("=" * 60)

# ─── --full-flow: run_daily_sales_flow simule (Maps adimini atla) ─────────────
else:
    print("\n[FULL-FLOW] Cift-calisma engel testi baslatiliyor...")
    print("  Adim 1: maps_fetch isaretleniyor (Maps adimini simule et)...")
    _init_daily_table()
    _mark_sent("sistem", "maps_fetch")
    print("  maps_fetch: ISARETLENDI")

    print("\n  Adim 2: Brief mail + WA (run_morning_brief_mail)...")
    ozet = run_morning_brief_mail(
        test_override_mail = TEST_MAIL,
        test_override_wa   = TEST_WA or None,
    )
    _mark_sent("sistem", "brief_mail")

    print("\n  Adim 3: Tekrar calistirma engel testi...")
    if _already_sent("sistem", "maps_fetch") and _already_sent("sistem", "brief_mail"):
        print("  ENGEL AKTIF ✓ — ikinci calistirma engellenir")
    else:
        print("  HATA: Engel aktif degil!")

    print("\n" + "=" * 60)
    print("  FULL-FLOW SONUC")
    print("=" * 60)
    for personel, durum in ozet.items():
        mail_durum = "GONDERILDI ✓" if durum.get("mail_sent") else "GONDERILEMEDI ✗"
        wa_durum   = "GONDERILDI ✓" if durum.get("wa_sent")   else "atlandi"
        print(f"  {personel}: {mail_durum} | WA: {wa_durum}")
    print("=" * 60)

print(f"\nWA bildirimi {TEST_WA} numarasina gonderildi (bekleniyor).")
print("Gercek gonderim icin .env PERSONEL_1_WHATSAPP ve PERSONEL_2_WHATSAPP tanimli olmali.")
