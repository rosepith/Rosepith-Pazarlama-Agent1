# Rosepith Art Direktör — Hibrit Mimari
# Telegram: Yasin yönetimi | WhatsApp: Müşteri + Personel routing

import time
import random
import datetime
import threading
import logging
import requests

from core.config import (
    TELEGRAM_BOT_TOKEN, YASIN_TELEGRAM_ID,
    PERSONEL_WHATSAPP, PERSONEL,
    WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN,
    TEST_CUSTOMER_WHATSAPP,
)
from core.database import log_event, save_message, load_history, add_to_queue, get_user_profile, save_user_profile
from core.ai import get_response, get_response_personnel, get_mode

logger = logging.getLogger(__name__)

AGENT_NAME = "art_director"
BASE_URL   = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

WORK_START = datetime.time(9, 30)
WORK_END   = datetime.time(18, 0)

FIXED_HOLIDAYS = {"01-01","23-04","01-05","19-05","15-07","30-08","29-10"}
VARIABLE_HOLIDAYS = {
    "2026-03-19","2026-03-20","2026-03-21",
    "2026-05-26","2026-05-27","2026-05-28","2026-05-29",
}

# ─── Yardımcılar ──────────────────────────────────────────────────────────────

def _is_holiday(now): return now.strftime("%d-%m") in FIXED_HOLIDAYS or now.strftime("%Y-%m-%d") in VARIABLE_HOLIDAYS
def _is_weekend(now): return now.weekday() >= 5
def _is_work_hours(now): return WORK_START <= now.time() <= WORK_END

def _get_role(user_id: str) -> str:
    if str(user_id) == str(YASIN_TELEGRAM_ID): return "yasin"
    return "customer"

def _get_whatsapp_role(phone: str) -> str:
    return "personnel" if phone in PERSONEL_WHATSAPP else "customer"

def _typing_delay(text: str):
    """Metin uzunluğuna göre gerçekçi yazma gecikmesi."""
    n = len(text)
    if   n < 100: delay = random.uniform(3, 4)
    elif n < 250: delay = random.uniform(5, 6)
    else:         delay = random.uniform(7, 8)
    logger.info(f"Yazma gecikmesi: {delay:.1f}s")
    time.sleep(delay)

# ─── Gönderim ─────────────────────────────────────────────────────────────────

def _send_telegram(chat_id, text: str):
    try:
        requests.post(f"{BASE_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram hata: {e}")

def _send_typing_action(chat_id):
    try:
        requests.post(f"{BASE_URL}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception: pass

def _send_whatsapp(to: str, text: str):
    try:
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": to, "type": "text",
                  "text": {"preview_url": False, "body": text}},
            timeout=10
        )
        logger.info(f"WA gönderildi → {to}: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"WA gönderme hata: {e}")

def _notify_yasin(text: str):
    _send_telegram(YASIN_TELEGRAM_ID, text)

# ─── WhatsApp: Müşteri ────────────────────────────────────────────────────────

def _handle_customer(phone: str, name: str, text: str):
    now     = datetime.datetime.now()
    off     = not _is_work_hours(now)
    weekend = _is_weekend(now)
    holiday = _is_holiday(now)

    save_message(phone, "customer", "in", text)
    history = load_history(phone, limit=40)
    profile = get_user_profile(phone)

    # Telegram bildirimi
    _notify_yasin(f"📱 Müşteri: {name or phone}\n{text[:100]}")

    reply = get_response(
        user_message=text, role="customer", history=history,
        is_off_hours=(off and not weekend and not holiday),
        is_weekend=weekend, user_profile=profile
    )

    if reply is None:
        add_to_queue(phone, "customer", text)
        reply = "Mesajınız alındı, en kısa sürede dönüş yapacağız 😊"

    _typing_delay(reply)
    _send_whatsapp(phone, reply)
    save_message(phone, "customer", "out", reply)

    # Profil güncelle (arka plan)
    threading.Thread(target=_update_profile, args=(phone, text, reply, profile), daemon=True).start()


# ─── WhatsApp: Personel ────────────────────────────────────────────────────────

def _handle_personnel(phone: str, name: str, text: str):
    # Yeni personel destek ajanına yönlendir
    from agents.personnel_support import handle_whatsapp_personnel
    handle_whatsapp_personnel(phone, name, text)


# ─── Ana WhatsApp handler ─────────────────────────────────────────────────────

def handle_whatsapp_message(phone: str, name: str, text: str):
    role = _get_whatsapp_role(phone)
    logger.info(f"WA | {phone} ({role}) | {text[:80]}")
    if role == "personnel":
        _handle_personnel(phone, name, text)
    else:
        _handle_customer(phone, name, text)


# ─── Telegram: Yasin komutları ────────────────────────────────────────────────

def _cmd_durum() -> str:
    from core.database import get_connection
    from core.holiday_checker import is_holiday, is_work_hours, get_holiday_name
    from core.mail_handler import get_last_poll_time
    import datetime as dt

    conn  = get_connection()
    today = dt.date.today().isoformat()
    now   = dt.datetime.now()

    # Temel sayılar
    msgs      = _safe_q(conn, "SELECT COUNT(*) FROM conversations WHERE date(created_at)=?", (today,))
    wa_kuyruk = _safe_q(conn, "SELECT COUNT(*) FROM task_queue WHERE status='pending'")
    is_bekl   = _safe_q(conn, "SELECT COUNT(*) FROM work_items WHERE status='pending'")
    is_acil   = _safe_q(conn, "SELECT COUNT(*) FROM work_items WHERE is_urgent=1 AND status='pending'")
    mail_gel  = _safe_q(conn, "SELECT COUNT(*) FROM mail_threads WHERE direction='in' AND date(created_at)=?", (today,))
    mail_git  = _safe_q(conn, "SELECT COUNT(*) FROM mail_threads WHERE direction='out' AND date(created_at)=?", (today,))

    # Son hata
    try:
        son_hata_row = conn.execute(
            "SELECT message FROM log_events WHERE level='ERROR' AND date(created_at)=? ORDER BY id DESC LIMIT 1",
            (today,)
        ).fetchone()
        son_hata = son_hata_row["message"][:80] if son_hata_row else "yok"
    except Exception:
        son_hata = "tablo yok"

    conn.close()

    tatil_bugun = is_holiday(now.date())
    tatil_isim  = get_holiday_name(now.date()) or "tatil/hafta sonu"
    mesai_ici   = is_work_hours(now)
    mode        = get_mode()
    son_poll    = get_last_poll_time()

    lines = [
        f"<b>🖥 Sistem Durumu — {today} {now.strftime('%H:%M')}</b>",
        "",
        f"🌐 W10           : Aktif ✅",
        f"🤖 AI Modu       : {mode}",
        f"📅 Mesai         : {'İçi ✅' if mesai_ici else 'Dışı ⏸'}",
        f"🎌 Tatil         : {'EVET — ' + tatil_isim if tatil_bugun else 'Hayır'}",
        "",
        f"📧 Mail polling  : {son_poll}",
        f"   Bugün gelen   : {mail_gel} | giden: {mail_git}",
        "",
        f"💬 WA mesaj      : {msgs} (bugün)",
        f"📥 WA kuyruk     : {wa_kuyruk}",
        f"💼 Bekleyen iş   : {is_bekl}",
        f"🚨 ACİL bekleyen : {is_acil}",
        "",
        f"⚠️ Son hata      : {son_hata}",
    ]
    return "\n".join(lines)


def _safe_q(conn, sql: str, params: tuple = ()) -> int:
    try:
        return conn.execute(sql, params).fetchone()[0]
    except Exception:
        return 0

def _cmd_rapor() -> str:
    from core.database import get_connection
    conn  = get_connection()
    today = datetime.date.today().isoformat()
    rows  = conn.execute(
        "SELECT user_id, COUNT(*) c FROM conversations WHERE date(created_at)=? AND role='customer' GROUP BY user_id ORDER BY c DESC",
        (today,)
    ).fetchall()
    conn.close()
    if not rows: return f"Bugün ({today}) müşteri konuşması yok."
    lines = [f"<b>Rapor — {today}</b>"]
    for r in rows:
        p = get_user_profile(r["user_id"])
        ozet = p.split("\n")[0] if p else "bilgi yok"
        lines.append(f"• {r['user_id']} ({r['c']} mesaj) — {ozet}")
    return "\n".join(lines)

def _forward_to_personel(chat_id, isim: str, mesaj: str):
    pid = PERSONEL.get(isim.lower())
    if not pid:
        kayitli = ", ".join(PERSONEL.keys()) or "tanımlı yok"
        _send_telegram(chat_id, f"'{isim}' bulunamadı. Kayıtlı: {kayitli}")
        return
    _send_telegram(pid, f"<b>[Yasin'den]</b> {mesaj}")
    _send_telegram(chat_id, f"✓ {isim.capitalize()}'e iletildi.")

def _detect_forward(text: str):
    lower    = text.lower()
    keywords = ["ilet","yaz","söyle","soyle","bildir","gönder","gonder","haber ver"]
    for isim in PERSONEL:
        if isim in lower:
            for kw in keywords:
                if kw in lower:
                    idx   = lower.find(kw) + len(kw)
                    mesaj = text[idx:].strip().lstrip(":").strip()
                    return isim, mesaj or text
    return None

def _handle_yasin(user_id: str, chat_id, text: str):
    cmd = text.strip().lower()
    if cmd == "/durum":
        _send_telegram(chat_id, _cmd_durum()); return
    if cmd == "/rapor":
        _send_telegram(chat_id, _cmd_rapor()); return
    if cmd.startswith("/personel "):
        parts = text.strip()[10:].split(" ", 1)
        if len(parts) == 2: _forward_to_personel(chat_id, parts[0], parts[1])
        else: _send_telegram(chat_id, "Kullanım: /personel [isim] [mesaj]")
        return
    fwd = _detect_forward(text.strip())
    if fwd:
        _forward_to_personel(chat_id, fwd[0], fwd[1]); return
    # AI sohbet
    save_message(user_id, "yasin", "in", text)
    history = load_history(user_id, limit=20)
    reply   = get_response(text, role="yasin", history=history)
    if reply:
        _send_telegram(chat_id, reply)
        save_message(user_id, "yasin", "out", reply)
    else:
        _send_telegram(chat_id, "AI şu an yanıt veremiyor.")


# ─── Profil güncelle ──────────────────────────────────────────────────────────

def _update_profile(user_id, user_msg, reply, existing):
    from openai import OpenAI
    from core.config import OPENAI_API_KEY
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        prompt = (
            f"Mevcut özet:\n{existing or 'Henüz bilgi yok'}\n\n"
            f"Yeni konuşma:\nMüşteri: {user_msg}\nBot: {reply}\n\n"
            "Önemli bilgileri (sektör, isim, ihtiyaç, karar) kısa madde madde güncelle. Türkçe."
        )
        resp = OpenAI(api_key=OPENAI_API_KEY).chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            max_tokens=200, temperature=0.3
        )
        save_user_profile(user_id, resp.choices[0].message.content.strip())
    except Exception as e:
        logger.warning(f"Profil güncelleme hata: {e}")


# ─── Telegram Polling ─────────────────────────────────────────────────────────

class ArtDirectorAgent:
    def __init__(self):
        self._offset  = 0
        self._running = False

    def _process_update(self, update: dict):
        msg = update.get("message") or update.get("edited_message")
        if not msg: return
        chat_id = msg["chat"]["id"]
        user_id = str(msg["from"]["id"])
        text    = msg.get("text","").strip()
        if not text: return

        role = _get_role(user_id)
        _send_typing_action(chat_id)
        if role != "yasin":
            time.sleep(random.uniform(3, 5))
        _handle_yasin(user_id, chat_id, text) if role == "yasin" else \
            _send_telegram(chat_id, "Bu bot yalnızca yetkili kullanıcılara açıktır.")

    def _poll(self):
        logger.info("Telegram polling başladı")
        while self._running:
            try:
                resp = requests.get(f"{BASE_URL}/getUpdates",
                    params={"offset": self._offset, "timeout": 30}, timeout=35)
                for upd in resp.json().get("result", []):
                    self._offset = upd["update_id"] + 1
                    threading.Thread(target=self._process_update, args=(upd,), daemon=True).start()
            except Exception as e:
                logger.error(f"Polling hata: {e}")
                time.sleep(5)

    def start(self):
        self._running = True
        threading.Thread(target=self._poll, daemon=True, name="art_director_poll").start()
        logger.info("Art Direktör aktif")

    def stop(self):
        self._running = False
