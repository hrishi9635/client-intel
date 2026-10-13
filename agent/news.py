"""Free news: Google News and Bing News RSS searches, plus publishers' own RSS feeds. No keys needed."""
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
TAG = re.compile(r"<[^>]+>")
ATOM = "{http://www.w3.org/2005/Atom}"


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", text or ""))).strip()


def _date(text):
    if not text:
        return None
    try:
        d = parsedate_to_datetime(text)
    except Exception:  # noqa: BLE001
        try:
            d = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_feed(content, provider):
    """Read RSS 2.0 or Atom. Returns a list of items."""
    root = ET.fromstring(content)
    items = []
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        src = it.find("source")
        source = clean(src.text) if src is not None and src.text else ""
        source_url = src.get("url", "") if src is not None else ""
        if provider == "Bing" and "apiclick" in link:
            link = parse_qs(urlparse(link).query).get("url", [link])[0]
        if provider == "Google" and source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        elif provider == "Google" and " - " in title and not source:
            title, source = title.rsplit(" - ", 1)
        desc = clean(it.findtext("description"))
        domain = urlparse(source_url or link).netloc.replace("www.", "")
        items.append({"title": title, "link": link, "source": source or urlparse(link).netloc.replace("www.", ""),
                      "domain": domain, "provider": provider, "published": _date(it.findtext("pubDate")),
                      "snippet": "" if provider == "Google" else desc[:400]})
    for it in root.iter(f"{ATOM}entry"):
        link_el = it.find(f"{ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        items.append({"title": clean(it.findtext(f"{ATOM}title")), "link": link,
                      "source": provider or urlparse(link).netloc.replace("www.", ""), "provider": provider,
                      "domain": urlparse(link).netloc.replace("www.", ""),
                      "published": _date(it.findtext(f"{ATOM}updated") or it.findtext(f"{ATOM}published")),
                      "snippet": clean(it.findtext(f"{ATOM}summary"))[:400]})
    return items


def fetch_feed(url, provider):
    """Returns (items, error). Never raises."""
    try:
        r = requests.get(url, headers=UA, timeout=25)
        if r.status_code != 200:
            return [], f"HTTP {r.status_code}"
        return parse_feed(r.content, provider), None
    except Exception as e:  # noqa: BLE001
        return [], type(e).__name__


def google_news(query, days):
    q = quote_plus(f"{query} when:{days}d")
    items, err = fetch_feed(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en", "Google")
    if err:
        print(f"      (Google News unavailable: {err})")
    return items


def bing_news(query):
    items, err = fetch_feed(f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&mkt=en-US", "Bing")
    if err:
        print(f"      (Bing News unavailable: {err})")
    return items


def recent(items, days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [it for it in items if not it.get("published") or datetime.fromisoformat(it["published"]) >= cutoff]


def dedupe(items):
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x.get("published") or "", reverse=True):
        key = re.sub(r"[^a-z0-9]", "", (it.get("title") or "").lower())[:70]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def mentions(text, aliases):
    t = f" {text.lower()} "
    for a in aliases:
        a = a.lower()
        if len(a) <= 4:  # short names like "NYU", "SLU", "IGT", "WBD": whole word only
            if re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", t):
                return True
        elif a in t:
            return True
    return False


def search(query, aliases, days, bing=True):
    """Search Google News (and Bing News); keep recent items that actually name the company."""
    items = google_news(query, days) + (bing_news(query) if bing else [])
    time.sleep(1)
    keep = [it for it in recent(items, days) if not aliases or mentions(it["title"] + " " + it["snippet"], aliases)]
    return dedupe(keep)


def page_text(url, max_chars=2500, headers=None):
    """Read the main paragraphs of a web page. Many sites block this; that's fine."""
    if not url or "news.google.com" in url:
        return ""
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, headers=headers or UA, timeout=20)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = " ".join(p for p in paras if len(p) > 60)
        return text[:max_chars] if len(text) > 300 else ""
    except Exception:  # noqa: BLE001
        return ""
