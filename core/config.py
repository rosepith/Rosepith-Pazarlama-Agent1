# Rosepith — Yapılandırma (W10 Hibrit)
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_API_KEY           = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY           = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID         = os.getenv("TELEGRAM_CHAT_ID")
YASIN_TELEGRAM_ID        = os.getenv("YASIN_TELEGRAM_ID") or os.getenv("TELEGRAM_CHAT_ID","")
ROLE_YASIN_ID            = YASIN_TELEGRAM_ID

WHATSAPP_PHONE_NUMBER_ID     = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")
WHATSAPP_ACCESS_TOKEN        = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_VERIFY_TOKEN        = os.getenv("WHATSAPP_VERIFY_TOKEN")
TEST_CUSTOMER_WHATSAPP       = os.getenv("TEST_CUSTOMER_WHATSAPP","")

# Hibrit relay
RELAY_SECRET     = os.getenv("RELAY_SECRET")
SERVER_RELAY_URL = os.getenv("SERVER_RELAY_URL", "https://rosekreatif.com.tr/agent-api/")

SYSTEM_MODE = os.getenv("SYSTEM_MODE", "full")

_db = os.getenv("DB_PATH", "rosepith.db")
DB_PATH = str(PROJECT_ROOT / _db)

# Personel WhatsApp: {phone: isim}
PERSONEL_WHATSAPP: dict[str, str] = {}
_i = 1
while True:
    wa   = os.getenv(f"PERSONEL_{_i}_WHATSAPP","").strip()
    isim = os.getenv(f"PERSONEL_{_i}_ISIM","").strip()
    if not wa or not isim: break
    PERSONEL_WHATSAPP[wa] = isim
    _i += 1

# Personel Telegram: {isim: telegram_id}
PERSONEL: dict[str, str] = {}
ROLE_PERSONNEL_IDS: list[str] = []
ROLE_CUSTOMER_IDS:  list[str] = []
