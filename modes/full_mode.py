# Rosepith Pazarlama Agent - Tam Mod
# Tüm ajanlar aktif, tüm entegrasyonlar çalışır durumda

from agents.art_director import ArtDirectorAgent
from agents.marketing import MarketingAgent
from agents.technical import TechnicalAgent
from agents.arge import ArgeAgent
from core.database import log_event


def run():
    """Tüm ajanları başlatır ve görev kuyruğunu işler."""
    log_event("system", "Tam mod başlatıldı")

    agents = {
        "art_director": ArtDirectorAgent(),
        "marketing": MarketingAgent(),
        "technical": TechnicalAgent(),
        "arge": ArgeAgent()
    }

    print("[Full Mode] Tüm ajanlar aktif:")
    for name in agents:
        print(f"  ✅ {name}")

    return agents
