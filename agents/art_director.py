# Rosepith Pazarlama Agent - Art Director Ajanı
# Görsel içerik yönetimi, tasarım briefleri ve yaratıcı yön kararları

from core.memory import remember, recall
from core.database import log_event

AGENT_NAME = "art_director"


class ArtDirectorAgent:
    def __init__(self):
        self.name = AGENT_NAME

    def create_brief(self, project_name: str, style: str, target_audience: str) -> dict:
        """Yeni bir tasarım briefi oluşturur ve belleğe kaydeder."""
        brief = {
            "project": project_name,
            "style": style,
            "target_audience": target_audience,
            "status": "draft"
        }
        remember(self.name, f"brief_{project_name}", str(brief))
        log_event(self.name, f"Brief oluşturuldu: {project_name}")
        return brief

    def review_content(self, content: str) -> str:
        """İçeriği görsel ve estetik kriterler açısından değerlendirir."""
        log_event(self.name, "İçerik incelemesi yapılıyor")
        # AI entegrasyonu buraya eklenecek
        return f"[ArtDirector] İçerik incelendi: {content[:80]}..."

    def run(self, task: dict) -> str:
        task_type = task.get("type")
        if task_type == "brief":
            return str(self.create_brief(
                task.get("project", ""),
                task.get("style", "modern"),
                task.get("audience", "genel")
            ))
        elif task_type == "review":
            return self.review_content(task.get("content", ""))
        return "[ArtDirector] Bilinmeyen görev tipi"
