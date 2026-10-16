"""
Publishes the static dashboard copy (docs/index.html, built by build_site.py) to a free Hugging Face
"static" Space after every agent run. (Hugging Face now charges for interactive Docker/Gradio Spaces,
but static Spaces are free.)
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
sdk: static
app_file: index.html
pinned: true
short_description: Results, IT signals, audience pulse and industry news
---
Backup copy of the Client Intelligence dashboard. It is refreshed automatically after every agent run.
"""


def main():
    token, space = os.environ.get("HF_TOKEN"), os.environ.get("HF_SPACE")
    if not (token and space):
        print("Hugging Face: skipped (HF_TOKEN / HF_SPACE not set)")
        return
    page = ROOT / "docs" / "index.html"
    if not page.exists():
        print("Hugging Face: skipped (docs/index.html not built yet)")
        return
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    api.create_repo(space, repo_type="space", space_sdk="static", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        shutil.copy(page, t / "index.html")
        (t / "README.md").write_text(README, encoding="utf-8")
        api.upload_folder(folder_path=str(t), repo_id=space, repo_type="space",
                          commit_message="Update dashboard")
    print(f"Hugging Face: updated https://huggingface.co/spaces/{space}")


if __name__ == "__main__":
    main()
