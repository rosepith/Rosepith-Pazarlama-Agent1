# -*- coding: utf-8 -*-
"""
PARCA 4 — Tatil kontrol testi.

Kullanim:
  python test_holiday.py           -> Cache goster, bugun/yarin kontrol
  python test_holiday.py --fake    -> Sahte tatil ekle (yarin) + test
  python test_holiday.py --clean   -> Sahte tatili kaldir
"""
import sys, os, io, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from core.holiday_checker import is_holiday, get_holiday_name, is_work_hours, _ensure_year
from core.database import get_connection

bugun  = datetime.date.today()
yarin  = bugun + datetime.timedelta(days=1)
SAHTE_ISIM = "TEST_SAHTE_TATIL"

print("=" * 60)
print("  Rosepith — Tatil Kontrol Testi (PARCA 4)")
print("=" * 60)

# ─── --clean ──────────────────────────────────────────────────────────────────
if "--clean" in sys.argv:
    conn = get_connection()
    conn.execute(
        "DELETE FROM holiday_cache WHERE holiday_name=?", (SAHTE_ISIM,)
    )
    conn.commit()
    conn.close()
    print(f"\n  Sahte tatil kaldirildi ({yarin}). Sistem normal duruma döndu.")
    sys.exit(0)

# ─── Cache durumu ─────────────────────────────────────────────────────────────
_ensure_year(bugun.year)
conn = get_connection()
rows = conn.execute(
    """SELECT date, holiday_name FROM holiday_cache
       WHERE is_holiday=1 AND date >= ? ORDER BY date LIMIT 10""",
    (bugun.isoformat(),)
).fetchall()
conn.close()

print(f"\n  Bugun  : {bugun} — {'TAT?L: ' + get_holiday_name(bugun) if is_holiday(bugun) else 'Is Gunu'}")
print(f"  Yarin  : {yarin} — {'TAT?L: ' + get_holiday_name(yarin) if is_holiday(yarin) else 'Is Gunu'}")
print(f"  Mesai  : {'Ici' if is_work_hours() else 'Disi'}")
print(f"\n  Yaklasan tatiller (DB cache):")
for r in rows:
    print(f"    {r[0]} — {r[1]}")

# ─── --fake: Sahte tatil testi ────────────────────────────────────────────────
if "--fake" in sys.argv:
    print(f"\n  [FAKE] Yarin ({yarin}) icin sahte tatil ekleniyor...")
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO holiday_cache (date, is_holiday, holiday_name) VALUES (?, 1, ?)",
        (yarin.isoformat(), SAHTE_ISIM)
    )
    conn.commit()
    conn.close()

    # Verify
    sonuc = is_holiday(yarin)
    isim  = get_holiday_name(yarin)
    print(f"  is_holiday({yarin}) = {sonuc} ({'DOGRU ✓' if sonuc else 'YANLIS ✗'})")
    print(f"  get_holiday_name()   = '{isim}'")

    # Mail polling tatilde duruyor mu simule et
    print(f"\n  Mail polling tatil kontrol simülasyonu:")
    from core.holiday_checker import is_work_hours as iwh
    import datetime as dt
    sabah_yarin = dt.datetime.combine(yarin, dt.time(10, 0))  # 10:00 yarin
    poll_aktif  = not is_holiday(sabah_yarin.date()) and iwh(sabah_yarin)
    print(f"  Yarin 10:00'da poll calisir mi? {'HAYIR ✓ (tatil)' if not poll_aktif else 'EVET (yanlis!)'}")

    # Sabah brief tatilde atlanıyor mu
    from agents.sales_automation import run_daily_sales_flow
    print(f"\n  run_daily_sales_flow() yarin cagrilsa:")
    # Overwrite date check: simulate
    _orig = __import__("core.holiday_checker", fromlist=["is_holiday"])
    orig_is_holiday = _orig.is_holiday
    _orig.is_holiday = lambda d=None: True  # Force holiday
    import agents.sales_automation as sa
    orig_sa = sa.is_holiday
    sa.is_holiday = lambda d=None: True
    # Bu direkt cagrilamaz (sleep var), sadece log kontrolu gosteriyoruz
    sa.is_holiday = orig_sa
    print(f"  is_holiday=True oldugunda 09:30 akisi 'atlandı — tatil' loglar.")
    print(f"  (Gercek calistirilmadi — sleep(300) iceriyor)")

    print(f"\n  Temizlemek icin: python test_holiday.py --clean")
    sys.exit(0)

# ─── Normal: mevcut cache dogrulama ───────────────────────────────────────────
print(f"\n  is_work_hours() testi:")
for saat_str in ["08:00", "09:30", "12:00", "17:30", "18:00", "20:00"]:
    h, m = map(int, saat_str.split(":"))
    simule = datetime.datetime.combine(bugun, datetime.time(h, m))
    sonuc  = is_work_hours(simule) if not is_holiday(bugun) else False
    print(f"    {saat_str} → {'MESAI ICI' if sonuc else 'mesai disi'}")

print("\n  Tatil cache hazir. --fake ile sahte tatil testini calistir.")
