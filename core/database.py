# Rosepith Pazarlama Agent - Veritabanı Modülü
# SQLite bağlantısı, tablo oluşturma ve CRUD işlemleri

import sqlite3
from core.config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            task_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            payload TEXT,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(agent, key)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            agent TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            direction TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def log_event(agent: str, message: str, level: str = "INFO"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO logs (level, agent, message) VALUES (?, ?, ?)",
        (level, agent, message)
    )
    conn.commit()
    conn.close()


def save_message(user_id: str, role: str, direction: str, message: str):
    """Konuşmayı kaydet. direction: 'in' (kullanıcıdan) veya 'out' (bottan)."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO conversations (user_id, role, direction, message) VALUES (?, ?, ?, ?)",
        (user_id, role, direction, message)
    )
    conn.commit()
    conn.close()


def load_history(user_id: str, limit: int = 10) -> list[dict]:
    """Kullanıcının son N mesajını yükle, AI formatında döndür."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT direction, message FROM conversations
           WHERE user_id = ?
           ORDER BY id DESC LIMIT ?""",
        (user_id, limit)
    ).fetchall()
    conn.close()
    # Ters çevir (en eskiden en yeniye)
    history = []
    for row in reversed(rows):
        ai_role = "user" if row["direction"] == "in" else "model"
        history.append({"role": ai_role, "parts": [row["message"]]})
    return history


def add_to_queue(user_id: str, role: str, message: str):
    """Personel görevini kuyruğa ekle."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO task_queue (user_id, role, message) VALUES (?, ?, ?)",
        (user_id, role, message)
    )
    conn.commit()
    conn.close()


def get_user_profile(user_id: str) -> str:
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM memory WHERE agent = 'user_profile' AND key = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row["value"] if row else ""


def save_user_profile(user_id: str, profile: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO memory (agent, key, value) VALUES ('user_profile', ?, ?) "
        "ON CONFLICT(agent, key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
        (user_id, profile)
    )
    conn.commit()
    conn.close()
