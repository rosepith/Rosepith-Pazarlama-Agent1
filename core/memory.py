# Rosepith Pazarlama Agent - Bellek Modülü
# Ajanların uzun süreli ve kısa süreli belleğini yönetir

from core.database import get_connection


def remember(agent: str, key: str, value: str):
    """Ajan için bir anahtar-değer çifti saklar veya günceller."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO memory (agent, key, value, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(agent, key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
        (agent, key, value)
    )
    conn.commit()
    conn.close()


def recall(agent: str, key: str) -> str | None:
    """Ajan için saklanan değeri döndürür."""
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM memory WHERE agent=? AND key=?", (agent, key)
    ).fetchone()
    conn.close()
    return row["value"] if row else None


def recall_all(agent: str) -> dict:
    """Bir ajana ait tüm bellek kayıtlarını sözlük olarak döndürür."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT key, value FROM memory WHERE agent=?", (agent,)
    ).fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}


def forget(agent: str, key: str):
    """Belirli bir bellek kaydını siler."""
    conn = get_connection()
    conn.execute("DELETE FROM memory WHERE agent=? AND key=?", (agent, key))
    conn.commit()
    conn.close()
