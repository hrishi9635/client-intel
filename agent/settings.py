"""Reads settings.txt, the secret keys (from GitHub secrets or your computer) and the company list."""
import csv
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KEY_DIR = Path.home() / ".client-intel"

DEFAULTS = {
    "LLM_BASE_URL": "https://api.groq.com/openai/v1",
    "LLM_MODEL": "openai/gpt-oss-120b",
    "LLM_FALLBACK_MODEL": "openai/gpt-oss-20b",
    "LLM_PAUSE_SECONDS": "25",
    "LLM_DAILY_TOKENS": "180000",     # per model; Groq's free tier allows about 200,000 a day
    "LLM_MAX_PROMPT_CHARS": "15000",  # keeps each request under the free tier's per-minute token limit
    "NEWS_DAYS": "30",
    "INDUSTRY_NEWS_DAYS": "14",
    "PULSE_DAYS_BACK": "90",
    "PULSE_DAYS_AHEAD": "90",
    "PULSE_TITLES_PER_GROUP": "12",
    "PULSE_UPCOMING_PER_GROUP": "6",
    "BENCHMARK_US": "^GSPC",
    "BENCHMARK_EU": "^STOXX",
}

# secrets: on GitHub they come from Settings -> Secrets; on your laptop from files in ~/.client-intel
SECRET_NAMES = ["LLM_API_KEY", "SEC_CONTACT", "TMDB_KEY", "OMDB_KEY", "REDDIT_ID", "REDDIT_SECRET"]


def load_settings():
    s = dict(DEFAULTS)
    f = ROOT / "settings.txt"
    if f.exists():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()
    for k in list(s):  # environment variables win
        if os.environ.get(k):
            s[k] = os.environ[k]
    for k in SECRET_NAMES:
        v = os.environ.get(k, "").strip()
        if not v and (KEY_DIR / f"{k}.txt").exists():
            v = (KEY_DIR / f"{k}.txt").read_text(encoding="utf-8").strip()
        s[k] = v
    for k in ("LLM_PAUSE_SECONDS",):
        s[k] = float(s[k] or 0)
    for k in ("LLM_DAILY_TOKENS", "LLM_MAX_PROMPT_CHARS", "NEWS_DAYS", "INDUSTRY_NEWS_DAYS", "PULSE_DAYS_BACK",
              "PULSE_DAYS_AHEAD", "PULSE_TITLES_PER_GROUP", "PULSE_UPCOMING_PER_GROUP"):
        s[k] = int(float(s[k] or 0))
    return s


def save_secret(name, value):
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    p = KEY_DIR / f"{name}.txt"
    p.write_text(value.strip(), encoding="utf-8")
    return p


def _split(text, sep="|"):
    return [x.strip() for x in (text or "").split(sep) if x.strip()]


def load_companies():
    rows = []
    with open(ROOT / "companies.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if not (r.get("name") or "").strip() or r["name"].strip().startswith("#"):
                continue
            industries = _split(r.get("industry"))
            cik = (r.get("sec_cik") or "").strip()
            rows.append({
                "name": r["name"].strip(),
                "short": (r.get("short_name") or r["name"]).strip(),
                "type": (r.get("type") or "private").strip().lower(),
                "industry": industries[0] if industries else "Other",
                "industries": industries or ["Other"],
                "tickers": _split(r.get("ticker")),
                "cik": str(int(cik)) if cik.isdigit() else "",
                "search": (r.get("search_name") or r["name"]).strip(),
                "aliases": _split(r.get("aliases")) or [r["name"].strip()],
                "segment": (r.get("segment_to_track") or "").strip(),
                "currency": (r.get("currency") or "USD").strip().upper(),
                "benchmark": (r.get("benchmark") or "").strip(),
                "official_domains": _split(r.get("official_domains")),
                "report_url": (r.get("report_url") or "").strip(),
                "note": (r.get("note") or "").strip(),
            })
    return rows


def read_json(name, default):
    p = DATA / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def write_json(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def read_csv(name):
    p = DATA / name
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    # hand-edited files may have notes (lines starting with #) above the header
    start = next((i for i, l in enumerate(lines) if l.strip() and not l.strip().startswith("#")), None)
    if start is None:
        return []
    return [r for r in csv.DictReader(lines[start:]) if not str(next(iter(r.values()), "")).startswith("#")]


def write_csv(name, rows, fields):
    DATA.mkdir(exist_ok=True)
    with open(DATA / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
