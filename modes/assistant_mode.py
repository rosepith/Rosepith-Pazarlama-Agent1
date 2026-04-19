# Rosepith Pazarlama Agent - Asistan Modu
# Tek ajan, düşük kaynak kullanımı; insan onayıyla çalışır

from agents.marketing import MarketingAgent
from core.database import log_event


def run():
    """Sadece pazarlama ajanını başlatır, her eylem için onay ister."""
    log_event("system", "Asistan modu başlatıldı")
    agent = MarketingAgent()

    print("[Assistant Mode] Tek ajan aktif: marketing")
    print("[Assistant Mode] Her eylem için onay gerekli")

    return agent


def confirm_action(description: str) -> bool:
    """Kullanıcıdan eylem onayı alır."""
    answer = input(f"\n[Onay Gerekli] {description}\nDevam edilsin mi? (e/h): ").strip().lower()
    return answer == "e"
