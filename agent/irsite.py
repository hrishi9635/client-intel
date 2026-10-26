"""
Reads a company's own investor-relations results page (the "results_page" column in companies.csv),
finds the documents published with the latest results (press release, presentation, transcript),
and returns their text. PDFs are read with pypdf.

Example: https://plc.pearson.com/en-GB/investors/performance/results-reports-presentations
Many sites block automated readers or draw their pages with JavaScript; then nothing is returned
and the agent falls back to the same release filed with the SEC.
"""
import io
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36", "Accept-Language": "en-GB,en;q=0.9"}
KINDS = [  # (kind, words in the link text or address), in the order they are read
    ("release", ["press release", "press-release", "trading update", "trading-update", "results announcement", "earnings release",
                 "news release", "results", "release", "report"]),
    ("presentation", ["presentation", "slides", "webcast slides", "investor deck", "ppt"]),
    ("transcript", ["transcript"]),
    ("commentary", ["commentary", "prepared remarks", "shareholder letter", "letter to shareholders", "supplement"]),
]
SKIP = (".mp4", ".mp3", ".wav", ".m4a", ".xls", ".xlsx", ".zip", ".jpg", ".png", "webcast", "youtube", "vimeo", "mailto:", "javascript:")


def _get(url, timeout=40):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


def _date_forms(d):
    """Ways a release date is written on results pages."""
    forms = {d.strftime("%d/%m/%Y"), d.strftime("%m/%d/%Y"), d.strftime("%Y-%m-%d"), d.strftime("%d.%m.%Y"),
             f"{d.day} {d:%B %Y}", f"{d:%B} {d.day}, {d.year}", f"{d.day} {d:%b %Y}", f"{d:%b} {d.day}, {d.year}",
             f"{d:%b}. {d.day}, {d.year}", d.strftime("%d %B %Y"), d.strftime("%d %b %Y")}
    return {f.lower() for f in forms}


def _row_text(a):
    """Text of the table row / list item / block the link sits in."""
    node = a
    for _ in range(6):
        node = node.parent
        if node is None:
            break
        if node.name in ("tr", "li", "article") or (node.name == "div" and len(node.get_text(" ", strip=True)) > 40):
            return node.get_text(" ", strip=True)
    return a.get_text(" ", strip=True)


def _kind(text):
    low = text.lower()
    for kind, words in sorted(KINDS, key=lambda k: ["transcript", "presentation", "commentary", "release"].index(k[0])):
        if any(w in low for w in words):
            return kind
    return None


def find_documents(page_url, release_date, max_docs=4):
    """Links to the documents of the release published on (or within a few days of) release_date."""
    from bs4 import BeautifulSoup
    try:
        d0 = datetime.fromisoformat(str(release_date)[:10])
    except ValueError:
        return []
    days = [d0 + timedelta(days=k) for k in (0, -1, 1, -2, 2)]
    forms = set().union(*(_date_forms(d) for d in days))
    months = {f"{d0:%Y-%m}", f"{d0:%Y/%m}", f"{d0:%Y%m}", f"{(d0 + timedelta(days=12)):%Y-%m}"}
    try:
        soup = BeautifulSoup(_get(page_url).text, "html.parser")
    except Exception:  # noqa: BLE001
        return []
    found, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"].strip())
        low_href = href.lower()
        if any(s in low_href for s in SKIP) or href in seen or urlparse(href).scheme not in ("http", "https"):
            continue
        label = " ".join([a.get_text(" ", strip=True), a.get("title") or "", a.get("aria-label") or ""])
        row = _row_text(a)
        row_low = row.lower()
        dated = any(f in row_low for f in forms) or any(m in low_href for m in months)
        if not dated:
            continue
        kind = _kind(label + " " + low_href.rsplit("/", 1)[-1].replace("-", " ")) or _kind(row)
        if not kind:
            continue
        seen.add(href)
        name = re.sub(r"\b(PDF|PPT|MPEG|MP4|XHTML|HTML|View|Download)\b", "", row, flags=re.I)
        name = re.sub(r"\d{1,2}[/.]\d{1,2}[/.]\d{4}|\s+", " ", name).strip()[:80]
        title = f"{name} ({ {'release': 'press release'}.get(kind, kind) })"
        found.append({"kind": kind, "url": href, "title": title})
    order = [k for k, _ in KINDS]
    found.sort(key=lambda x: order.index(x["kind"]))
    out, kinds = [], {}
    for f in found:  # at most one of each kind, two presentations/commentaries
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
        if kinds[f["kind"]] <= (1 if f["kind"] in ("release", "transcript") else 2):
            out.append(f)
    return out[:max_docs]


def document_text(url, max_chars=90000):
    """Text of a PDF or HTML document."""
    try:
        r = _get(url, timeout=60)
    except Exception:  # noqa: BLE001
        return ""
    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf") or r.content[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(r.content))
            parts = []
            for p in reader.pages[:80]:
                parts.append(p.extract_text() or "")
                if sum(len(x) for x in parts) > max_chars:
                    break
            text = "\n".join(parts)
        except Exception:  # noqa: BLE001
            return ""
    else:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "header", "footer"]):
            t.decompose()
        text = soup.get_text("\n", strip=True)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text[:max_chars] if len(text) > 500 else ""


def official_site_documents(company, release_date, log=None):
    """[{title, url, text, official, kind}] read from the company's own results page."""
    page = company.get("results_page")
    if not page:
        return []
    docs = []
    for f in find_documents(page, release_date):
        t = document_text(f["url"])
        if t:
            docs.append({"title": f["title"], "url": f["url"], "text": t, "official": True,
                         "kind": f["kind"], "site": True})
    if log is not None:
        log.setdefault("steps", []).append(f"{company['short']}: {len(docs)} documents from the company's results page")
    return docs
