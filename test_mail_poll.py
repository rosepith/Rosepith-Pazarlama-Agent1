# -*- coding: utf-8 -*-
"""
PARCA 3 test — Mail polling ve revize akisi.

Kullanim:
  python test_mail_poll.py              -> Gelen kutusu poll et, isle
  python test_mail_poll.py --check      -> Sadece DB durumunu goster
  python test_mail_poll.py --acil       -> ACİL simüle et (DB'deki son maili)
  python test_mail_poll.py --upgrade    -> Tablo guncelleme test

Not: Gercek mail testi icin artdirektor@rosepith.net'e kendi mailinizden
     bir test maili gonderip bu scripti calistirin (60s bekleyin).
"""

import sys
import os
import io
import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from core.config import YANDEX_MAIL, PERSONEL_MAIL, PERSONEL_WHATSAPP
from core.database import get_connection
from core.mail_handler import (
    _upgrade_table, poll_new_mails, process_incoming_mail,
    _is_urgent_mail, _find_personel_by_mail,
)

print("=" * 60)
print("  Rosepith — Mail Polling Testi (PARCA 3)")
print("=" * 60)
print(f"  Tarih      : {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}")
print(f"  IMAP hesap : {YANDEX_MAIL}")
print(f"  Personel mail tanımları:")
for isim, mail in (PERSONEL_MAIL or {}).items():
    print(f"    {isim:12} → {mail}")
if not PERSONEL_MAIL:
    print("    !! .env'de PERSONEL_N_MAIL tanımlı degil — "
          "gelen mailler 'bilinmeyen' sayılır !!")
print("=" * 60)

# ─── --upgrade ────────────────────────────────────────────────────────────────
if "--upgrade" in sys.argv:
    print("\n[UPGRADE] mail_threads tablo guncellemesi...")
    _upgrade_table()
    conn = get_connection()
    cols = [row[1] for row in conn.execute("PRAGMA table_info(mail_threads)").fetchall()]
    conn.close()
    print(f"  Sutunlar: {', '.join(cols)}")
    print("  Tamamlandi.")
    sys.exit(0)

# ─── --check: DB durumu ───────────────────────────────────────────────────────
if "--check" in sys.argv:
    _upgrade_table()
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, direction, from_addr, subject, mail_type, personel,
                  is_urgent, processed, status, created_at
           FROM mail_threads ORDER BY id DESC LIMIT 20"""
    ).fetchall()
    conn.close()
    print(f"\n  Son 20 mail_threads kaydı:")
    print(f"  {'ID':<4} {'DIR':<4} {'TİP':<10} {'PERSONEL':<14} {'ACİL':<5} "
          f"{'İŞLENDİ':<8} {'DURUM':<12} {'KONU'}")
    print("  " + "-" * 80)
    for r in rows:
        acil    = "EVET" if r[6] else ""
        islendi = "✓" if r[7] else ""
        print(f"  {r[0]:<4} {r[1]:<4} {(r[4] or '?'):<10} {(r[5] or ''):<14} "
              f"{acil:<5} {islendi:<8} {(r[8] or ''):<12} {(r[3] or '')[:35]}")
    sys.exit(0)

# ─── --acil: ACİL simülasyonu ─────────────────────────────────────────────────
if "--acil" in sys.argv:
    print("\n[ACİL SİMÜLASYON] Yapay ACİL mail verisi oluşturuluyor...")
    # PERSONEL_MAIL'den ilk personeli al
    if not PERSONEL_MAIL:
        print("  !! PERSONEL_MAIL boş, .env kontrol et !!")
        sys.exit(1)
    ilk_isim = next(iter(PERSONEL_MAIL))
    ilk_mail = PERSONEL_MAIL[ilk_isim]
    test_mail = {
        "message_id":  f"<test-acil-{datetime.datetime.now().timestamp()}@test>",
        "in_reply_to": "",
        "from_addr":   ilk_mail,
        "subject":     "ACİL — Müşteri Toplantısı Yarın",
        "body":        "Merhaba,\n\nACİL durum var. Yarın büyük müşteri toplantısı için "
                       "strateji önerisi lazım. Lütfen hızlıca hazırlayın.\n\nSaygılarımla",
    }
    # DB'ye kaydet
    _upgrade_table()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO mail_threads
               (message_id, in_reply_to, from_addr, to_addr, subject, body, direction)
               VALUES (?, ?, ?, ?, ?, ?, 'in')""",
            (test_mail["message_id"], "", ilk_mail,
             YANDEX_MAIL, test_mail["subject"], test_mail["body"])
        )
        conn.commit()
        print(f"  Test mail DB'ye eklendi: {test_mail['subject']}")
    except Exception as e:
        print(f"  DB hatası: {e}")
    finally:
        conn.close()

    print(f"\n  process_incoming_mail() çağrılıyor...")
    tip = process_incoming_mail(test_mail)
    print(f"  Sonuç: {tip}")
    print("  Yasin Telegram'ına ACİL bildirimi gitmiş olmali.")
    sys.exit(0)

# ─── Ana test: IMAP poll ──────────────────────────────────────────────────────
print("\n[1/3] mail_threads tablo güncelleniyor...")
_upgrade_table()
print("  Tamam.")

print("\n[2/3] IMAP polling (artdirektor@rosepith.net)...")
mails = poll_new_mails(limit=10)
print(f"  {len(mails)} okunmamış mail geldi.")

if not mails:
    print("\n  Okunmamış mail yok. Test için:")
    print("  1. Herhangi bir mailinizden artdirektor@rosepith.net'e mail gönderin")
    print("  2. Bu scripti tekrar çalıştırın")
    print("  3. Veya: python test_mail_poll.py --acil  (simülasyon)")
    print()
    # DB durumu göster
    conn = get_connection()
    toplam = conn.execute("SELECT COUNT(*) FROM mail_threads").fetchone()[0]
    conn.close()
    print(f"  DB'de toplam {toplam} mail_threads kaydı var.")
    print("  Detay için: python test_mail_poll.py --check")
    sys.exit(0)

print("\n[3/3] Mailler işleniyor...")
print()
for i, m in enumerate(mails, 1):
    print(f"  [{i}] Gönderen : {m.get('from_addr','?')}")
    print(f"      Konu     : {m.get('subject','?')[:50]}")
    in_rep = m.get("in_reply_to","")
    print(f"      Tip      : {'REVİZE' if in_rep else 'YENİ İŞ'}")
    acil = _is_urgent_mail(m.get("subject",""), m.get("body",""))
    print(f"      ACİL     : {'EVET ⚠️' if acil else 'Hayır'}")
    personel = _find_personel_by_mail(m.get("from_addr",""))
    print(f"      Personel : {personel or '!! BİLİNMEYEN !!'}")

    if personel:
        tip = process_incoming_mail(m)
        print(f"      Sonuç    : {tip} ✓")
    else:
        print(f"      Sonuç    : atlandı (bilinmeyen gönderen)")
    print()

print("=" * 60)
print("  ÖZET")
print("=" * 60)
conn = get_connection()
rows = conn.execute(
    "SELECT mail_type, COUNT(*) FROM mail_threads GROUP BY mail_type"
).fetchall()
conn.close()
for r in rows:
    print(f"  {r[0] or 'unknown':15}: {r[1]} kayıt")
print("=" * 60)
print("\nCevap maili artdirektor@rosepith.net'e gönderilmiş olmali.")
print("Personel mail adresi .env'de tanımlıysa doğrudan personele gider.")
