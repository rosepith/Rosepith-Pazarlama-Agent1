# Rosepith Pazarlama Agent - Art Direktör Ajanı
# Telegram üzerinden gelen mesajları analiz eder, role göre yanıtlar ve departmanlara yönlendirir.

import time
import random
import datetime
import threading
import requests

from core.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ROLE_YASIN_ID,
    ROLE_PERSONNEL_IDS,
    ROLE_CUSTOMER_IDS,
)
from core.database import log_event
from core.memory import remember, recall

# ─── Sabitler ────────────────────────────────────────────────────────────────

AGENT_NAME = "art_director"
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

WORK_START = datetime.time(9, 30)
WORK_END   = datetime.time(18, 0)

# Sabit Türkiye resmi tatilleri (GG-AA)
FIXED_HOLIDAYS = {
    "01-01",  # Yılbaşı
    "23-04",  # Ulusal Egemenlik ve Çocuk Bayramı
    "01-05",  # Emek ve Dayanışma Günü
    "19-05",  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    "15-07",  # Demokrasi ve Millî Birlik Günü
    "30-08",  # Zafer Bayramı
    "29-10",  # Cumhuriyet Bayramı
}

# Değişken dini tatiller (manuel güncellenir, YYYY-MM-DD)
VARIABLE_HOLIDAYS = {
    "2025-03-30", "2025-03-31",  # Ramazan Bayramı 2025
    "2025-04-01",
    "2025-06-06", "2025-06-07",  # Kurban Bayramı 2025
    "2025-06-08", "2025-06-09",
    "2026-03-19", "2026-03-20",  # Ramazan Bayramı 2026
    "2026-03-21",
    "2026-05-26", "2026-05-27",  # Kurban Bayramı 2026
    "2026-05-28", "2026-05-29",
}

# ─── Anahtar kelime → departman eşleştirmesi ─────────────────────────────────

ROUTING_RULES = {
    "marketing": [
        "kampanya", "instagram", "reklam", "içerik", "post", "paylaşım",
        "sosyal medya", "facebook", "tiktok", "linkedin", "strateji",
        "hedef kitle", "analiz", "metrik", "insight", "bütçe",
    ],
    "technical": [
        "site", "web", "hata", "bug", "kod", "domain", "hosting",
        "deploy", "sunucu", "ssl", "yavaş", "çöktü", "bağlantı",
        "güncelleme", "teknik", "api", "entegrasyon",
    ],
    "arge": [
        "araştır", "rakip", "trend", "pazar", "analiz et", "rapor",
        "veri", "istatistik", "sektör", "benchmark", "fırsat",
    ],
}

# ─── Ton kütüphanesi ──────────────────────────────────────────────────────────

TONE = {
    "greeting_yasin":     "Yasin bey, buyurun.",
    "greeting_personnel": "Merhaba. Ne var?",
    "greeting_customer":  "Merhaba, Rosepith'e hoş geldiniz.",
    "greeting_unknown":   "Merhaba. Sizi tanıyamadım, kimsiniz?",

    "off_hours_yasin":    "Mesai dışı. Acil mi?",
    "off_hours_personnel":"Mesai bitti. Yarın 09:30'da görüşelim.",
    "off_hours_customer": "Şu an çalışma saatlerimiz dışındayız (09:30–18:00). Yarın dönüyoruz.",

    "weekend_yasin":      "Hafta sonu. Yine de dinliyorum.",
    "weekend_personnel":  "Hafta sonu. Acil değilse Pazartesi.",
    "weekend_customer":   "Hafta sonu kapalıyız. Pazartesi 09:30'da hizmetinizdeyiz.",

    "holiday":            "Bugün resmi tatil. Yarın döneceğim.",

    "route_marketing":    "Pazarlama departmanına iletiyorum.",
    "route_technical":    "Teknik ekibe yönlendiriyorum.",
    "route_arge":         "AR-GE birimine aktarıyorum.",
    "route_unknown":      "Tam anlayamadım. Biraz daha açar mısınız?",

    "understood":         "Anladım.",
    "noted":              "Not aldım.",
    "wait":               "Bir saniye.",
}

# ─── Yardımcı fonksiyonlar ────────────────────────────────────────────────────

def _is_holiday(now: datetime.datetime) -> bool:
    if now.strftime("%d-%m") in FIXED_HOLIDAYS:
        return True
    if now.strftime("%Y-%m-%d") in VARIABLE_HOLIDAYS:
        return True
    return False


def _is_weekend(now: datetime.datetime) -> bool:
    return now.weekday() >= 5  # 5=Cmt, 6=Paz


def _is_work_hours(now: datetime.datetime) -> bool:
    return WORK_START <= now.time() <= WORK_END


def _get_role(user_id: str) -> str:
    uid = str(user_id)
    if uid == str(ROLE_YASIN_ID):
        return "yasin"
    if uid in ROLE_PERSONNEL_IDS:
        return "personnel"
    if uid in ROLE_CUSTOMER_IDS:
        return "customer"
    return "unknown"


def _detect_department(text: str) -> str | None:
    text_lower = text.lower()
    for dept, keywords in ROUTING_RULES.items():
        for kw in keywords:
            if kw in text_lower:
                return dept
    return None


def _human_delay():
    """4–7 saniye arası rastgele gecikme: insan gibi görünsün."""
    time.sleep(random.uniform(4, 7))


def _send(chat_id: str | int, text: str):
    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        log_event(AGENT_NAME, f"→ {chat_id}: {text[:60]}")
    except Exception as e:
        log_event(AGENT_NAME, f"Gönderim hatası: {e}", level="ERROR")


def _send_typing(chat_id: str | int):
    """Kullanıcıya 'yazıyor...' gösterir."""
    try:
        requests.post(
            f"{BASE_URL}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass

# ─── Ana yanıt motoru ─────────────────────────────────────────────────────────

def build_response(user_id: str, text: str) -> str:
    """Gelen mesajı değerlendirip uygun yanıtı döndürür."""
    role = _get_role(user_id)
    now  = datetime.datetime.now()

    # 1. Resmi tatil kontrolü
    if _is_holiday(now):
        return TONE["holiday"]

    # 2. Hafta sonu kontrolü
    if _is_weekend(now):
        return TONE[f"weekend_{role}"] if role != "unknown" else TONE["weekend_customer"]

    # 3. Mesai saati kontrolü
    if not _is_work_hours(now):
        return TONE[f"off_hours_{role}"] if role != "unknown" else TONE["off_hours_customer"]

    # 4. Selamlama komutları
    greet_triggers = ["/start", "/merhaba", "merhaba", "selam", "iyi günler", "günaydın"]
    if any(text.lower().startswith(t) for t in greet_triggers):
        return TONE[f"greeting_{role}"]

    # 5. Durum/bilgi sorusu (Yasin'e özel)
    if role == "yasin":
        status_triggers = ["durum", "nasıl", "rapor", "özet", "ne var", "ne oldu"]
        if any(t in text.lower() for t in status_triggers):
            last = recall(AGENT_NAME, "last_summary") or "Henüz özetlenecek bir şey yok."
            return f"Son durum: {last}"

    # 6. Departman yönlendirmesi
    dept = _detect_department(text)
    if dept:
        remember(AGENT_NAME, f"last_route_{user_id}", dept)
        remember(AGENT_NAME, "last_summary", f"{role} → {dept} ({now.strftime('%H:%M')})")
        log_event(AGENT_NAME, f"Yönlendirme: {role} → {dept}")
        return TONE[f"route_{dept}"]

    # 7. Kısa onay mesajları
    ack_triggers = ["tamam", "ok", "peki", "anladım", "teşekkür", "tşk", "👍"]
    if any(t in text.lower() for t in ack_triggers):
        return TONE["noted"]

    # 8. Anlaşılamadı
    return TONE["route_unknown"]

# ─── Telegram polling döngüsü ─────────────────────────────────────────────────

class ArtDirectorAgent:
    def __init__(self):
        self.name = AGENT_NAME
        self._offset = 0
        self._running = False

    def _process_update(self, update: dict):
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        user_id = str(message["from"]["id"])
        text    = message.get("text", "")

        if not text:
            return

        log_event(self.name, f"Mesaj alındı | user={user_id} | text={text[:80]}")

        # Yazıyor... göster, sonra bekle
        _send_typing(chat_id)
        _human_delay()

        response = build_response(user_id, text)
        _send(chat_id, response)

    def _poll(self):
        log_event(self.name, "Polling başlatıldı")
        while self._running:
            try:
                resp = requests.get(
                    f"{BASE_URL}/getUpdates",
                    params={"offset": self._offset, "timeout": 30},
                    timeout=35,
                )
                updates = resp.json().get("result", [])
                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    t = threading.Thread(target=self._process_update, args=(upd,), daemon=True)
                    t.start()
            except Exception as e:
                log_event(self.name, f"Polling hatası: {e}", level="ERROR")
                time.sleep(5)

    def start(self):
        """Art Direktör ajanını ayrı thread'de başlatır."""
        self._running = True
        thread = threading.Thread(target=self._poll, daemon=True, name="art_director_poll")
        thread.start()
        log_event(self.name, "Art Direktör aktif")
        print("[Art Director] Telegram dinleniyor...")
        return thread

    def stop(self):
        self._running = False
        log_event(self.name, "Art Direktör durduruldu")

    # Tek seferlik görev arayüzü (diğer ajanlarla uyum için)
    def run(self, task: dict) -> str:
        task_type = task.get("type")
        if task_type == "respond":
            return build_response(
                str(task.get("user_id", "")),
                task.get("text", "")
            )
        if task_type == "send":
            _send(task.get("chat_id", TELEGRAM_CHAT_ID), task.get("text", ""))
            return "Gönderildi"
        return "[Art Director] Bilinmeyen görev tipi"
