# -*- coding: utf-8 -*-
"""
merhaba_1 sablonu test scripti
Mevcut sisteme dokunmaz - sadece Meta API'ye istek atar.
"""

import requests
import json
import sys
import io
import os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ─── AYARLAR ──────────────────────────────────────────────────────────────────

HEDEF_NUMARA     = "905077889523"   # <-- Buraya test numarasını yaz (90 ile başlayan)

PHONE_NUMBER_ID  = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
ACCESS_TOKEN     = os.getenv("WHATSAPP_ACCESS_TOKEN", "")

TEMPLATE_ADI     = "merhaba_1"
TEMPLATE_DILI    = "tr"          # Şablon onaylanırken hangi dil seçildiyse

if not PHONE_NUMBER_ID or not ACCESS_TOKEN:
    print("HATA: .env dosyasında WHATSAPP_PHONE_NUMBER_ID veya WHATSAPP_ACCESS_TOKEN eksik!")
    sys.exit(1)

# ─── GÖNDER ───────────────────────────────────────────────────────────────────

url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"

payload = {
    "messaging_product": "whatsapp",
    "to": HEDEF_NUMARA,
    "type": "template",
    "template": {
        "name": TEMPLATE_ADI,
        "language": {
            "code": TEMPLATE_DILI
        }
    }
}

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

print(f"─── İstek gönderiliyor ───")
print(f"Numara  : {HEDEF_NUMARA}")
print(f"Şablon  : {TEMPLATE_ADI} ({TEMPLATE_DILI})")
print(f"URL     : {url}")
print()

resp = requests.post(url, headers=headers, json=payload, timeout=15)

print(f"─── Meta Yanıtı ───")
print(f"HTTP Durum : {resp.status_code}")
print()
try:
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
except Exception:
    print(resp.text)
