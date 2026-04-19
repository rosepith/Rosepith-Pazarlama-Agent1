# Rosepith Pazarlama Agent - Yapılandırma Modülü
# Ortam değişkenlerini yükler ve sistem genelinde erişim sağlar

import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER")
MAIL_USER = os.getenv("MAIL_USER")
MAIL_PASS = os.getenv("MAIL_PASS")
DB_PATH = os.getenv("DB_PATH", "rosepith.db")

# Aktif AI sağlayıcısı: "gemini" veya "openai"
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")

# Çalışma modu: "full", "backup", "assistant"
SYSTEM_MODE = os.getenv("SYSTEM_MODE", "full")
