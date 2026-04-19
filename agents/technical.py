# Rosepith Pazarlama Agent - Teknik Ajan
# Web geliştirme, otomasyon betikleri ve teknik destek görevleri

from core.memory import remember, recall
from core.database import log_event

AGENT_NAME = "technical"


class TechnicalAgent:
    def __init__(self):
        self.name = AGENT_NAME

    def deploy_check(self, url: str) -> dict:
        """Verilen URL'nin canlı olup olmadığını kontrol eder."""
        import urllib.request
        log_event(self.name, f"Deploy kontrolü: {url}")
        try:
            code = urllib.request.urlopen(url, timeout=10).getcode()
            return {"url": url, "status": code, "online": code == 200}
        except Exception as e:
            return {"url": url, "status": "hata", "error": str(e)}

    def generate_script(self, task_description: str) -> str:
        """Görev açıklamasına göre otomasyon betiği üretir."""
        log_event(self.name, f"Betik üretiliyor: {task_description[:50]}")
        # AI entegrasyonu buraya eklenecek
        return f"[Technical] '{task_description}' için betik taslağı hazırlandı"

    def report_issue(self, component: str, description: str):
        """Teknik sorunu kaydeder."""
        remember(self.name, f"issue_{component}", description)
        log_event(self.name, f"Sorun raporlandı: {component} - {description}", level="WARNING")

    def run(self, task: dict) -> str:
        task_type = task.get("type")
        if task_type == "deploy_check":
            return str(self.deploy_check(task.get("url", "")))
        elif task_type == "script":
            return self.generate_script(task.get("description", ""))
        elif task_type == "issue":
            self.report_issue(task.get("component", ""), task.get("description", ""))
            return "[Technical] Sorun kaydedildi"
        return "[Technical] Bilinmeyen görev tipi"
