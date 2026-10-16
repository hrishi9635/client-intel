"""
Copies the Streamlit dashboard and the latest data to a free Hugging Face Space, so a second
interactive copy keeps running even if Streamlit Community Cloud is down.
Needs two GitHub secrets: HF_TOKEN (a Hugging Face "write" token) and HF_SPACE (e.g. yourname/client-intel).
Skips quietly if they are missing.
"""
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent

README = """---
title: Client Intelligence
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
short_description: Results, IT signals, audience pulse and industry news
---
Backup copy of the Client Intelligence dashboard. It is refreshed automatically after every agent run.
"""

DOCKERFILE = """FROM python:3.12-slim
ENV HOME=/tmp PYTHONUNBUFFERED=1 STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 7860
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true", \\
     "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
"""


def main():
    token, space = os.environ.get("HF_TOKEN"), os.environ.get("HF_SPACE")
    if not (token and space):
        print("Hugging Face: skipped (HF_TOKEN / HF_SPACE not set)")
        return
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for name in ("app.py", "companies.csv", "requirements.txt"):
            shutil.copy(ROOT / name, t / name)
        shutil.copytree(ROOT / "data", t / "data", ignore=shutil.ignore_patterns("notify_state.json"))
        shutil.copytree(ROOT / "agent", t / "agent", ignore=shutil.ignore_patterns("__pycache__"))
        if (ROOT / "settings.txt").exists():
            shutil.copy(ROOT / "settings.txt", t / "settings.txt")
        if (ROOT / ".streamlit").exists():
            shutil.copytree(ROOT / ".streamlit", t / ".streamlit")
        (t / "README.md").write_text(README, encoding="utf-8")
        (t / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
        api.upload_folder(folder_path=str(t), repo_id=space, repo_type="space",
                          commit_message="Update dashboard and data", delete_patterns=["data/*", "agent/*"])
    print(f"Hugging Face: updated https://huggingface.co/spaces/{space}")


if __name__ == "__main__":
    main()
