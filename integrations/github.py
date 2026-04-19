# Rosepith Pazarlama Agent - GitHub Entegrasyonu
# Repo yönetimi, issue takibi ve otomatik commit/push işlemleri

import subprocess
import requests
from core.database import log_event

GITHUB_API = "https://api.github.com"


def git_push(repo_path: str, commit_message: str, branch: str = "main") -> bool:
    """Belirtilen repo'da değişiklikleri commit edip push'lar."""
    try:
        subprocess.run(["git", "-C", repo_path, "add", "-A"], check=True)
        subprocess.run(["git", "-C", repo_path, "commit", "-m", commit_message], check=True)
        subprocess.run(["git", "-C", repo_path, "push", "origin", branch], check=True)
        log_event("github", f"Push başarılı: {repo_path} -> {branch}")
        return True
    except subprocess.CalledProcessError as e:
        log_event("github", f"Push başarısız: {e}", level="ERROR")
        return False


def create_issue(token: str, owner: str, repo: str, title: str, body: str) -> dict:
    """GitHub üzerinde yeni bir issue oluşturur."""
    resp = requests.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/issues",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
        json={"title": title, "body": body},
        timeout=10
    )
    log_event("github", f"Issue oluşturuldu: {title}")
    return resp.json()


def list_issues(token: str, owner: str, repo: str, state: str = "open") -> list:
    """Repo'daki açık/kapalı issue'ları listeler."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/issues",
        headers={"Authorization": f"token {token}"},
        params={"state": state},
        timeout=10
    )
    return resp.json()
