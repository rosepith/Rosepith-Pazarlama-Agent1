# Rosepith — Tatil Kontrol Modülü
# Nager.Date API (TR milli tatilleri) + hardcoded dini bayramlar + arife
# SQLite cache: holiday_cache tablosu

import datetime
import requests
import logging

logger = logging.getLogger(__name__)

WORK_START = datetime.time(9, 30)
WORK_END   = datetime.time(18, 0)

# Dini bayramlar + arifeler (2025-2027)
DINI_TATILLER = {
    # 2025 Ramazan Bayramı
    "2025-03-28",  # arife
    "2025-03-29", "2025-03-30", "2025-03-31",
    # 2025 Kurban Bayramı
    "2025-06-04",  # arife
    "2025-06-05", "2025-06-06", "2025-06-07", "2025-06-08",
    # 2026 Ramazan Bayramı
    "2026-03-18",  # arife
    "2026-03-19", "2026-03-20", "2026-03-21",
    # 2026 Kurban Bayramı
    "2026-05-25",  # arife
    "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    # 2027 Ramazan Bayramı
    "2027-03-07",  # arife
    "2027-03-08", "2027-03-09", "2027-03-10",
    # 2027 Kurban Bayramı
    "2027-05-14",  # arife
    "2027-05-15", "2027-05-16", "2027-05-17", "2027-05-18",
}

DINI_ISIMLER = {
    "2025-03-28": "Ramazan Bayramı Arifesi",
    "2025-03-29": "Ramazan Bayramı",
    "2025-03-30": "Ramazan Bayramı",
    "2025-03-31": "Ramazan Bayramı",
    "2025-06-04": "Kurban Bayramı Arifesi",
    "2025-06-05": "Kurban Bayramı",
    "2025-06-06": "Kurban Bayramı",
    "2025-06-07": "Kurban Bayramı",
    "2025-06-08": "Kurban Bayramı",
    "2026-03-18": "Ramazan Bayramı Arifesi",
    "2026-03-19": "Ramazan Bayramı",
    "2026-03-20": "Ramazan Bayramı",
    "2026-03-21": "Ramazan Bayramı",
    "2026-05-25": "Kurban Bayramı Arifesi",
    "2026-05-26": "Kurban Bayramı",
    "2026-05-27": "Kurban Bayramı",
    "2026-05-28": "Kurban Bayramı",
    "2026-05-29": "Kurban Bayramı",
    "2027-03-07": "Ramazan Bayramı Arifesi",
    "2027-03-08": "Ramazan Bayramı",
    "2027-03-09": "Ramazan Bayramı",
    "2027-03-10": "Ramazan Bayramı",
    "2027-05-14": "Kurban Bayramı Arifesi",
    "2027-05-15": "Kurban Bayramı",
    "2027-05-16": "Kurban Bayramı",
    "2027-05-17": "Kurban Bayramı",
    "2027-05-18": "Kurban Bayramı",
}

# In-memory cache (process ömrü boyunca)
_cache: dict[str, dict] = {}
_api_fetched_years: set = set()


def _init_table():
    from core.database import get_connection
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holiday_cache (
            date TEXT PRIMARY KEY,
            is_holiday INTEGER DEFAULT 0,
            holiday_name TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _fetch_nager(year: int) -> list[dict]:
    try:
        resp = requests.get(
            f"https://date.nager.at/api/v3/PublicHolidays/{year}/TR",
            timeout=8
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"Tatil API hatası ({year}): {e}")
    return []


def _ensure_year(year: int):
    if year in _api_fetched_years:
        return
    _init_table()
    from core.database import get_connection
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM holiday_cache WHERE date LIKE ?",
        (f"{year}%",)
    ).fetchone()[0]
    conn.close()

    if count == 0:
        holidays = _fetch_nager(year)
        conn = get_connection()
        for h in holidays:
            conn.execute(
                "INSERT OR REPLACE INTO holiday_cache (date, is_holiday, holiday_name) VALUES (?, 1, ?)",
                (h["date"], h.get("localName", "Milli Tatil"))
            )
        # Dini tatilleri ekle
        for d, name in DINI_ISIMLER.items():
            if d.startswith(str(year)):
                conn.execute(
                    "INSERT OR REPLACE INTO holiday_cache (date, is_holiday, holiday_name) VALUES (?, 1, ?)",
                    (d, name)
                )
        conn.commit()
        conn.close()
        logger.info(f"{year} tatil cache hazırlandı")

    _api_fetched_years.add(year)


def is_holiday(date: datetime.date = None) -> bool:
    """Bugün (veya verilen tarih) tatil mi? Hafta sonu dahil."""
    import os
    if os.getenv("TEST_MODE", "").lower() in ("true", "1", "yes"):
        return False   # TEST_MODE: tatil yok → her gün çalış
    if date is None:
        date = datetime.date.today()
    if date.weekday() >= 5:
        return True
    date_str = date.isoformat()
    if date_str in DINI_TATILLER:
        return True
    _ensure_year(date.year)
    from core.database import get_connection
    conn = get_connection()
    row = conn.execute(
        "SELECT is_holiday FROM holiday_cache WHERE date = ?",
        (date_str,)
    ).fetchone()
    conn.close()
    return bool(row and row["is_holiday"])


def get_holiday_name(date: datetime.date = None) -> str:
    """Tatil adını döndür (tatil değilse boş string)."""
    if date is None:
        date = datetime.date.today()
    if date.weekday() == 5:
        return "Cumartesi"
    if date.weekday() == 6:
        return "Pazar"
    date_str = date.isoformat()
    if date_str in DINI_ISIMLER:
        return DINI_ISIMLER[date_str]
    _ensure_year(date.year)
    from core.database import get_connection
    conn = get_connection()
    row = conn.execute(
        "SELECT holiday_name FROM holiday_cache WHERE date = ? AND is_holiday = 1",
        (date_str,)
    ).fetchone()
    conn.close()
    return row["holiday_name"] if row else ""


def is_work_hours(now: datetime.datetime = None) -> bool:
    """Mesai saati mi? (tatil ve hafta sonu = hayır)"""
    import os
    if os.getenv("TEST_MODE", "").lower() in ("true", "1", "yes"):
        return True    # TEST_MODE: her saat mesai içi
    if now is None:
        now = datetime.datetime.now()
    if is_holiday(now.date()):
        return False
    return WORK_START <= now.time() <= WORK_END


def get_season_context() -> str:
    """Şu anki satış sezonunu döndür (brief için)."""
    month = datetime.date.today().month
    seasons = {
        (1, 2):   "Kış sezonu — Şubat kapanışlarına dikkat, yeni yıl bütçeleri sorgulanıyor",
        (3, 4):   "İlkbahar — Yeni bütçeler açıldı, karar alma hızlı",
        (5, 6):   "Yaz öncesi — Kampanya planlamaları yoğun, web ve reklam talebi yüksek",
        (7, 8):   "Yaz sezonu — Yavaş dönem, kalifeye yönelik sıcak tutma mesajları",
        (9, 10):  "Back-to-business — EN YOĞUN dönem, hızlı kapanış hedefi",
        (11, 12): "Yılsonu — Black Friday, yılsonu kampanyaları, bütçe tüketimi",
    }
    for months, desc in seasons.items():
        if month in months:
            return desc
    return ""
