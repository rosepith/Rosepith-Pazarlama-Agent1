# Rosepith Pazarlama Agent - Art Direktör Ajanı
# Telegram kapısı: rol tanıma, mesai kontrolü, AI yanıt üretimi, hafıza yönetimi

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
from core.database import log_event, save_message, load_history, add_to_queue
from core.ai import get_response

AGENT_NAME = "art_director"
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ─── Mesai & Tatil ────────────────────────────────────────────────────────────

WORK_START = datetime.time(9, 30)
WORK_END   = datetime.time(18, 0)

FIXED_HOLIDAYS = {
    "01-01", "23-04", "01-05", "19-05",
    "15-07", "30-08", "29-10",
}

VARIABLE_HOLIDAYS = {
    "2025-03-30", "2025-03-31", "2025-04-01",
    "2025-06-06", "2025-06-07", "2025-06-08", "2025-06-09",
    "2026-03-19", "2026-03-20", "2026-03-21",
    "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
}

# ─── Yardımcılar ──────────────────────────────────────────────────────────────

def _is_holiday(now: datetime.datetime) -> bool:
    return (now.strftime("%d-%m") in FIXED_HOLIDAYS or
            now.strftime("%Y-%m-%d") in VARIABLE_HOLIDAYS)

def _is_weekend(now: datetime.datetime) -> bool:
    return now.weekday() >= 5

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
    return "customer"  # bilinmeyen = müşteri gibi davran

def _human_delay():
    time.sleep(random.uniform(4, 7))

def _send(chat_id, text: str):
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        result = resp.json()
        if result.get("ok"):
            log_event(AGENT_NAME, f"→ {chat_id}: {text[:80]}")
        else:
            log_event(AGENT_NAME, f"Telegram hata: {result}", level="ERROR")
    except Exception as e:
        log_event(AGENT_NAME, f"Gönderim hatası: {e}", level="ERROR")

def _send_typing(chat_id):
    try:
        requests.post(
            f"{BASE_URL}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass

# ─── Ana işlem ────────────────────────────────────────────────────────────────

def handle_message(user_id: str, chat_id, text: str):
    """Gelen mesajı işle: hafızayı yükle, AI yanıtı üret, kaydet."""
    role    = _get_role(user_id)
    now     = datetime.datetime.now()
    holiday = _is_holiday(now)
    weekend = _is_weekend(now)
    off     = not _is_work_hours(now)

    log_event(AGENT_NAME, f"Mesaj | user={user_id} role={role} | {text[:80]}")

    # Gelen mesajı kaydet
    save_message(user_id, role, "in", text)

    # Personel mesai dışı → kuyruğa al, kısa onay ver
    if role == "personnel" and (weekend or off or holiday):
        add_to_queue(user_id, role, text)
        reply = "Mesai dışı. Görevin alındı, sabah işleniyor."
        save_message(user_id, role, "out", reply)
        _send(chat_id, reply)
        return

    # Tüm durumlar için geçmiş konuşmayı yükle (son 10)
    history = load_history(user_id, limit=10)

    # AI yanıtı üret
    reply = get_response(
        user_message=text,
        role=role,
        history=history,
        is_off_hours=(off and not weekend and not holiday),
        is_weekend=weekend,
    )

    # Yanıtı kaydet ve gönder
    save_message(user_id, role, "out", reply)
    _send(chat_id, reply)

# ─── Telegram Polling ─────────────────────────────────────────────────────────

class ArtDirectorAgent:
    def __init__(self):
        self.name     = AGENT_NAME
        self._offset  = 0
        self._running = False

    def _process_update(self, update: dict):
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        chat_id = message["chat"]["id"]
        user_id = str(message["from"]["id"])
        text    = message.get("text", "").strip()
        if not text:
            return

        _send_typing(chat_id)
        _human_delay()
        handle_message(user_id, chat_id, text)

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
                    threading.Thread(
                        target=self._process_update,
                        args=(upd,),
                        daemon=True
                    ).start()
            except Exception as e:
                log_event(self.name, f"Polling hatası: {e}", level="ERROR")
                time.sleep(5)

    def start(self):
        self._running = True
        t = threading.Thread(target=self._poll, daemon=True, name="art_director_poll")
        t.start()
        log_event(self.name, "Art Direktör aktif")
        print("[Art Director] Telegram dinleniyor...")
        return t

    def stop(self):
        self._running = False
        log_event(self.name, "Art Direktör durduruldu")

    def run(self, task: dict) -> str:
        if task.get("type") == "send":
            _send(task.get("chat_id", TELEGRAM_CHAT_ID), task.get("text", ""))
            return "Gönderildi"
        return "[Art Director] Bilinmeyen görev tipi"
