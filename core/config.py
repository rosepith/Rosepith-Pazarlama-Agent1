# Rosepith Pazarlama Agent - Yapılandırma Modülü
# Ortam değişkenlerini yükler ve sistem genelinde erişim sağlar

import os
from pathlib import Path
from dotenv import load_dotenv

# Proje kök dizini — config.py her zaman core/ altında
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# .env'i proje kökünden yükle
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER")
MAIL_USER = os.getenv("MAIL_USER")
MAIL_PASS = os.getenv("MAIL_PASS")

# DB her zaman proje kökünde oluşsun, çalışma dizininden bağımsız
_db_name = os.getenv("DB_PATH", "rosepith.db")
DB_PATH = str(PROJECT_ROOT / _db_name)

# Aktif AI sağlayıcısı: "gemini" veya "openai"
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")

# Çalışma modu: "full", "backup", "assistant"
SYSTEM_MODE = os.getenv("SYSTEM_MODE", "full")

# Rol tanımları
ROLE_YASIN_ID = os.getenv("ROLE_YASIN_ID", "")
ROLE_PERSONNEL_IDS = [x.strip() for x in os.getenv("ROLE_PERSONNEL_IDS", "").split(",") if x.strip()]
ROLE_CUSTOMER_IDS = [x.strip() for x in os.getenv("ROLE_CUSTOMER_IDS", "").split(",") if x.strip()]
