# Rosepith Pazarlama Agent - Terminal Dashboard
# Rich tabanlı gerçek zamanlı ajan durumu ve görev izleme ekranı

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from rich import box
from core.database import get_connection
import time

console = Console()


def get_recent_logs(limit: int = 20) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT level, agent, message, created_at FROM logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_task_summary() -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as count FROM tasks GROUP BY status"
    ).fetchall()
    conn.close()
    return {row["status"]: row["count"] for row in rows}


def render_dashboard():
    """Terminal'de canlı dashboard gösterir."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3)
    )

    layout["header"].update(Panel(
        "[bold magenta]🌹 Rosepith Pazarlama Agent - Dashboard[/bold magenta]",
        box=box.DOUBLE
    ))

    log_table = Table(title="Son Olaylar", box=box.SIMPLE, expand=True)
    log_table.add_column("Seviye", style="cyan", width=8)
    log_table.add_column("Ajan", style="green", width=15)
    log_table.add_column("Mesaj", style="white")
    log_table.add_column("Zaman", style="dim", width=20)

    for row in get_recent_logs():
        color = {"ERROR": "red", "WARNING": "yellow", "INFO": "green"}.get(row["level"], "white")
        log_table.add_row(
            f"[{color}]{row['level']}[/{color}]",
            row["agent"],
            row["message"],
            row["created_at"]
        )

    layout["body"].update(Panel(log_table))

    summary = get_task_summary()
    footer_text = " | ".join([f"{k}: {v}" for k, v in summary.items()]) or "Henüz görev yok"
    layout["footer"].update(Panel(f"Görevler → {footer_text}"))

    return layout


def run_live(refresh_seconds: float = 5.0):
    """Dashboard'u belirtilen aralıkla canlı günceller."""
    with Live(render_dashboard(), refresh_per_second=1) as live:
        while True:
            time.sleep(refresh_seconds)
            live.update(render_dashboard())


if __name__ == "__main__":
    run_live()
