# Rosepith Pazarlama Agent - Yedek Mod
# Birincil AI sağlayıcısı devre dışıysa alternatif sağlayıcıya geçer

from core.config import AI_PROVIDER
from core.database import log_event


def run():
    """Yedek modu başlatır; Gemini devre dışıysa OpenAI'ya, o da devre dışıysa temel moda geçer."""
    log_event("system", f"Yedek mod başlatıldı (birincil: {AI_PROVIDER})")

    fallback_order = ["gemini", "openai", "local"]
    current_index = fallback_order.index(AI_PROVIDER) if AI_PROVIDER in fallback_order else 0
    active_provider = fallback_order[min(current_index + 1, len(fallback_order) - 1)]

    print(f"[Backup Mode] Birincil sağlayıcı: {AI_PROVIDER} → Yedek: {active_provider}")
    log_event("system", f"Yedek sağlayıcı aktif: {active_provider}")

    return active_provider
