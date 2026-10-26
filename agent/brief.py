"""
Account update per client, built from the company's OWN documents for each results release.
Written for a sales colleague who wants to know what is going on at the client and where it will spend.

What it reads (all public):
 - the company's results page on its own website ("results_page" in companies.csv): press release,
   results presentation, and the call transcript when the company publishes one (agent/irsite.py)
 - the same release as filed with the SEC (8-K / 6-K and exhibits), used when the website can't be read
 - a public earnings-call transcript if the company doesn't publish one (marked "call")
 - recent news headlines on leadership moves and technology spending (marked "news")

How: every document is read in full, in chunks. For each chunk the AI writes short notes (numbers, segment
revenue, spending plans, changes, leadership, dates). A final step turns the notes into the update.
Checks: every number must appear in the sources, quotes must be word for word, people's names must appear in
the sources. Anything that fails is removed. Amounts stay in the company's currency here; report.py
converts them to US dollars when drawing the PDFs.
"""
import json
import re
from datetime import datetime, timezone

from . import irsite
from . import news as newsmod
from .verify import flat, text_ok

FORMAT = 3
CHUNK = 7500       # characters per AI call (fits the free per-minute limit)
MAX_CHUNKS = 6     # per release; the most relevant chunks are read first
NOTES_BUDGET = 9500

KEYWORDS = {
    3: ["invest", "spend", "capex", "capital expenditure", "technology", "platform", "digital", " ai ", "ai-", "artificial intelligence",
        "cloud", "data", "automation", "systems", "modernis", "moderniz", "transform", "priorit", "outlook", "guidance",
        "expect", "appoint", "chief", "president", "step down", "leave", "join", "reorganis", "reorganiz", "restructur"],
    2: ["strategy", "operating model", "simplif", "efficien", "saving", "cost", "acqui", "partner", "contract", "launch",
        "consolidat", "vendor", "outsourc", "integration", "headcount", "workforce", "medium term", "target", "full year"],
    1: ["segment", "division", "revenue", "sales", "growth", "margin", "risk", "pressure", "decline", "demand"],
}

RULES = """Use ONLY the text given. Every number, name, date and quote must appear in it. No outside knowledge.
Keep amounts EXACTLY as written, in the company's own currency (e.g. "£650m", "€1.2bn", "$3.4bn"); never convert.
The company is an industry player; never call it a client or "our". Plain, short, factual sentences; no sales pitch."""

SYSTEM_MAP = """You take notes from one excerpt of a company's results documents for a sales colleague at an IT services firm.
""" + RULES + """
Capture especially: where the company will SPEND or INVEST (next quarter, next year, next few years), above all on
technology & IT (platforms, systems, vendors, cloud, data, AI, automation, cybersecurity, capex, acquired technology);
revenue by segment / business unit; key changes (reorganisation, acquisitions, disposals, contracts, partnerships,
products, cost programmes); any REORGANISATION in detail (old structure, new business units, what each includes,
their size and leader, effective date, cost, savings); every leadership change (appointed, leaving, retiring, new role). Return ONE JSON object."""

SCHEMA_MAP = """{
 "period": "reporting period exactly as stated, or null",
 "numbers": ["headline figures with their label, e.g. 'Revenue £3.1bn, +5% underlying'"],
 "segments": [{"name": "", "revenue": "as written or null", "growth": "e.g. +4% or null", "period": "or null"}],
 "spend": ["plans to spend / invest / prioritise, with amount and timing when stated; technology & IT first"],
 "changes": ["key changes with timing"],
 "organisation": ["reorganisation details: old structure, each new unit with what it includes, size and leader, effective date, cost, savings"],
 "leadership": [{"person": "", "role": "", "change": "Appointed|Leaving|Retiring|Promoted|New role|Expanded role|Joining", "when": "or null"}],
 "outlook": ["guidance / outlook statements"],
 "dates": ["upcoming events with their date"],
 "quotes": ["verbatim quote (max 30 words) — speaker"]
}"""

SYSTEM_REDUCE = """You write a clear, factual account update for a sales colleague at an IT services firm who wants to know
what is going on at this company and WHERE IT WILL SPEND, especially on technology & IT.
""" + RULES + """
You get notes taken from the company's documents (OFFICIAL = the company's own documents; CALL = a third-party
transcript of the earnings call; NEWS = recent headlines, usable only for leadership and technology spending).
Set "src" to "call" or "news" for items that come only from those.
- period: the reporting period exactly as the documents state it (e.g. "nine months to 30 September 2026").
- key_numbers: the 3-4 figures that matter most (revenue, growth, profit, cash or capex / technology investment).
- segments: revenue by segment or business unit, using the most recent period with figures for EVERY segment;
  if no amounts are given, give each segment's growth instead.
- focus: where the company will spend or invest over the coming quarter, year or few years. Technology & IT first.
- organisation: fill it whenever the company is reorganising or changing its operating model / business units:
  the old structure, every new unit (what it includes, size, leader), effective date, cost and savings. Otherwise null.
- leadership: only real changes. A person leaving is "Leaving", never "Appointed". Do not list people whose role did not change.
Return ONE JSON object."""

SCHEMA_REDUCE = """{
 "document_type": "Quarterly results|Half-year results|Full-year results|Trading update|Investor update|Other",
 "period": "",
 "headline": "max 2 sentences: the most important things happening now",
 "key_numbers": [{"label": "max 4 words", "value": "as written, e.g. £3.1bn or +5%", "context": "max 8 words"}],
 "outlook_line": "one sentence on full-year guidance, or null",
 "segments_basis": "what the segment figures are, e.g. 'Revenue, nine months to 30 September 2026'",
 "segments": [{"name": "", "revenue": "as written or null", "growth": "e.g. +4% or null", "comment": "max 12 words"}],
 "focus": [{"area": "max 5 words", "plan": "what they will spend on / invest in", "amount": "as written or null",
            "timing": "or null", "tech": true, "src": "official|call|news"}],
 "tech_spend": ["technology & IT spending facts: platforms, systems, vendors, cloud, data, AI, capex, acquired technology"],
 "organisation": {"summary": "one sentence", "before": "old structure, or null", "effective": "date or null",
                  "units": [{"name": "", "revenue": "as written or null", "includes": "max 10 words", "leader": "or null"}],
                  "cost": "as written or null", "savings": "what savings are used for, or null", "src": "official|call"},
 "key_changes": [{"type": "Organisation|Acquisition|Disposal|Contract win|Contract loss|Partnership|Product|Cost programme|Other",
                  "change": "max 8 words", "detail": "one sentence", "when": "or null", "src": "official|call|news"}],
 "leadership": [{"person": "", "role": "", "change": "Appointed|Leaving|Retiring|Promoted|New role|Expanded role|Joining",
                 "when": "or null", "src": "official|call|news"}],
 "dates": [{"date": "", "event": ""}],
 "summary": {"focus": ["max 4 bullets, max 20 words each"], "changes": ["max 4 bullets, max 20 words each"]}
}"""


def official_documents(sec, company, rel, log):
    """Text of the release and any other exhibits filed with it. Returns a list of {title, url, text, official}."""
    docs = []
    try:
        if rel.get("form") == "company release":
            t = newsmod.page_text(rel["url"], 20000)
            if t:
                docs.append({"title": rel.get("title") or "Company release", "url": rel["url"], "text": t, "official": True})
        elif sec is not None:
            docs.append({"title": rel.get("title") or f"{rel.get('form')} release", "url": rel["url"],
                         "text": sec.doc_text(rel["url"]), "official": True})
            base = rel.get("index") or rel["url"].rsplit("/", 1)[0]
            try:
                idx = sec.get(f"{base}/index.json")
                names = [x["name"] for x in idx.get("directory", {}).get("item", [])]
            except Exception:  # noqa: BLE001
                names = []
            main = rel["url"].rsplit("/", 1)[-1]
            extra = [n for n in names if n != main and n.lower().endswith((".htm", ".html", ".txt"))
                     and re.search(r"(ex|exhibit|dex)[-_]?99", n, re.I)][:2]
            for n in extra:
                try:
                    docs.append({"title": f"Exhibit {n}", "url": f"{base}/{n}", "text": sec.doc_text(f"{base}/{n}"), "official": True})
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001
        log["errors"].append(f"brief documents {company['short']}: {type(e).__name__}")
    return docs


def call_transcript(company, days=10):
    """A public earnings-call transcript, if one can be found and read (often blocked; that's fine)."""
    try:
        items = newsmod.search(f"{company['search']} earnings call transcript", company["aliases"], days, bing=False)
    except Exception:  # noqa: BLE001
        return None
    for it in items[:3]:
        if "transcript" not in it.get("title", "").lower():
            continue
        t = newsmod.page_text(it.get("link"), 30000)
        if t and len(t) > 2000:
            return {"title": it["title"], "url": it["link"], "text": t, "official": False, "source": it.get("source")}
    return None


def news_context(company, days=90):
    """Recent headlines on leadership moves and technology / IT spending (secondary; used only for those sections)."""
    out = []
    queries = [f"{company['search']} appoints OR names OR \"steps down\" OR chief OR president",
               f"{company['search']} technology OR platform OR AI OR cloud OR partnership OR outsourcing"]
    for q in queries:
        try:
            items = newsmod.search(q, company["aliases"], days, bing=False)
        except Exception:  # noqa: BLE001
            items = []
        for it in items[:7]:
            line = f"- {(it.get('published') or '')[:10]} {it.get('title', '')}"
            if it.get("snippet"):
                line += f": {it['snippet'][:160]}"
            if line not in out:
                out.append(line)
    return out[:12]



def _score(text):
    low = f" {text.lower()} "
    s = sum(w * sum(low.count(k) for k in ks) for w, ks in KEYWORDS.items())
    return s + 2 * len(re.findall(r"[£$€]\s?\d|\d+(?:\.\d+)?\s?%", text))


def chunks(docs):
    """Split every document into CHUNK-sized pieces; keep the most relevant MAX_CHUNKS, release first."""
    rank = {"release": 0, "presentation": 1, "commentary": 2, "transcript": 3}
    out = []
    for di, d in enumerate(docs):
        paras = [p.strip() for p in re.split(r"\n+", d["text"] or "") if len(p.strip()) > 3]
        cur = ""
        part = 0
        for p in paras:
            if len(cur) + len(p) > CHUNK and cur:
                out.append({"doc": di, "part": part, "text": cur})
                part, cur = part + 1, ""
            cur += p[:CHUNK] + "\n"
        if cur.strip():
            out.append({"doc": di, "part": part, "text": cur})
    for c in out:
        d = docs[c["doc"]]
        c["src"] = "official" if d.get("official") else "call"
        c["prio"] = (c["part"] == 0 and rank.get(d.get("kind", "release"), 0) == 0, _score(c["text"]))
    keep = sorted(out, key=lambda c: c["prio"], reverse=True)[:MAX_CHUNKS]
    return sorted(keep, key=lambda c: (c["doc"], c["part"]))


def _norm(s):
    return re.sub(r"[^a-z0-9%£$€.]+", " ", (s or "").lower()).strip()


SRC = {"official", "call", "news"}


def _ok_factory(source_text):
    fc = flat(source_text)

    def ok(s):
        if not isinstance(s, str):
            return True
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s?(%|per ?cent)", s):  # small percentages too
            if not re.search(rf"(?<![\d.]){re.escape(m.group(1))}\s?(%|per ?cent)", fc):
                return False
        return text_ok(s, fc)
    return ok


def take_notes(llm, company, chunk, docs, dropped):
    d = docs[chunk["doc"]]
    user = (f"Company: {company['name']}. Document: {d['title']} ({'OFFICIAL' if d.get('official') else 'CALL transcript, third-party'}).\n"
            f"Excerpt:\n{chunk['text']}\n\nReturn JSON exactly in this shape:\n{SCHEMA_MAP}")
    n = llm.chat_json(SYSTEM_MAP, user, max_tokens=1500)
    if not isinstance(n, dict):
        return None
    ok, nc = _ok_factory(chunk["text"]), _norm(chunk["text"])
    clean = {"src": chunk["src"], "doc": d["title"]}
    for k in ("numbers", "spend", "changes", "organisation", "outlook", "dates"):
        clean[k] = [x for x in (n.get(k) or []) if isinstance(x, str) and (ok(x) or dropped.append(x[:60]))]
    clean["quotes"] = [q for q in (n.get("quotes") or []) if isinstance(q, str)
                       and _norm(q.split("—")[0].strip(' "“”')) in nc]
    clean["segments"] = [s for s in (n.get("segments") or []) if isinstance(s, dict) and s.get("name")
                         and all(ok(s.get(k)) for k in ("revenue", "growth"))]
    clean["leadership"] = [x for x in (n.get("leadership") or []) if isinstance(x, dict) and x.get("person")
                           and _norm(x["person"]) in nc]
    clean["period"] = n.get("period") if ok(n.get("period")) else None
    return clean


def notes_text(notes, news_lines):
    parts = []
    for i, n in enumerate(notes, 1):
        tag = "OFFICIAL" if n["src"] == "official" else "CALL"
        body = {k: v for k, v in n.items() if k not in ("src", "doc") and v}
        parts.append(f"[{i}] {tag} – {n['doc']}\n{json.dumps(body, ensure_ascii=False)}")
    txt = "\n\n".join(parts)
    if len(txt) > NOTES_BUDGET:
        txt = txt[:NOTES_BUDGET] + "\n[...]"
    if news_lines:
        txt += "\n\n[NEWS] recent headlines (leadership and technology only):\n" + "\n".join(news_lines)[:1500]
    return txt


def _check(brief, corpus):
    """Remove anything with a number not in the sources, quotes that are not verbatim, names not in the sources."""
    ok, nc, dropped = _ok_factory(corpus), _norm(corpus), []

    def strings(items, limit=None):
        out = []
        for x in items or []:
            if isinstance(x, str) and x.strip():
                if ok(x):
                    out.append(x.strip())
                else:
                    dropped.append(x[:60])
        return out[:limit] if limit else out

    def objects(items, keys, must):
        out = []
        for x in items or []:
            if not isinstance(x, dict):
                continue
            for k in keys:
                if isinstance(x.get(k), str) and not ok(x[k]):
                    dropped.append(f"{k}: {x[k][:60]}")
                    x[k] = None
            if x.get("src") not in SRC:
                x["src"] = "official"
            if all(x.get(m) for m in must):
                out.append(x)
        return out

    for k in ("headline", "outlook_line", "period", "segments_basis"):
        if not ok(brief.get(k)):
            dropped.append(k)
            brief[k] = None
    brief["key_numbers"] = objects(brief.get("key_numbers"), ["label", "value", "context"], ["label", "value"])[:4]
    brief["segments"] = objects(brief.get("segments"), ["revenue", "growth", "comment"], ["name"])
    brief["focus"] = sorted(objects(brief.get("focus"), ["area", "plan", "amount", "timing"], ["area", "plan"]),
                            key=lambda x: not x.get("tech"))
    brief["tech_spend"] = strings(brief.get("tech_spend"))
    org = brief.get("organisation") if isinstance(brief.get("organisation"), dict) else None
    if org:
        for k in ("summary", "before", "effective", "cost", "savings"):
            if not ok(org.get(k)):
                dropped.append(f"organisation {k}")
                org[k] = None
        org["units"] = objects(org.get("units"), ["revenue", "includes"], ["name"])
        for u in org["units"]:
            if u.get("leader") and _norm(u["leader"]) not in nc:
                dropped.append(f"leader not in sources: {u['leader']}")
                u["leader"] = None
        if org.get("src") not in SRC:
            org["src"] = "official"
        org = org if (org.get("summary") or org["units"]) else None
    brief["organisation"] = org
    brief["key_changes"] = objects(brief.get("key_changes"), ["change", "detail", "when"], ["change"])
    brief["dates"] = objects(brief.get("dates"), ["date", "event"], ["date", "event"])
    lead = []
    for x in objects(brief.get("leadership"), ["role", "when"], ["person", "change"]):
        if str(x["change"]).lower() in ("unchanged", "none", "n/a"):
            continue
        if _norm(x["person"]) in nc:
            lead.append(x)
        else:
            dropped.append(f"person not in sources: {x.get('person')}")
    brief["leadership"] = lead
    sm = brief.get("summary") if isinstance(brief.get("summary"), dict) else {}
    brief["summary"] = {"focus": strings(sm.get("focus"), 4), "changes": strings(sm.get("changes"), 4)}
    brief["unverified_dropped"] = dropped
    return brief


def gather_documents(sec, company, rel, log):
    """Company website first; the SEC copy when the website gives nothing; a public transcript if none."""
    docs = []
    try:
        docs = irsite.official_site_documents(company, rel.get("filed"), log)
    except Exception as e:  # noqa: BLE001
        log["errors"].append(f"results page {company['short']}: {type(e).__name__}")
    if not any(d.get("kind") == "release" for d in docs):
        for i, d in enumerate(official_documents(sec, company, rel, log)):
            d["kind"] = "release" if i == 0 else "commentary"  # main filing, then its other exhibits
            docs.append(d)
    if not any(d.get("kind") == "transcript" for d in docs):
        tr = call_transcript(company)
        if tr:
            tr["kind"] = "transcript"
            docs.append(tr)
    return [d for d in docs if (d.get("text") or "").strip()]


def make_brief(llm, sec, company, rel, log):
    docs = gather_documents(sec, company, rel, log)
    if not docs:
        return None
    news_lines = news_context(company)
    dropped, notes = [], []
    for ch in chunks(docs):
        try:
            n = take_notes(llm, company, ch, docs, dropped)
        except Exception as e:  # noqa: BLE001
            if "allowance" in str(e):
                raise
            log["errors"].append(f"notes {company['short']}: {str(e)[:120]}")
            continue
        if n:
            notes.append(n)
    if not notes:
        return None
    user = (f"Company: {company['name']} (also called {', '.join(company['aliases'][:4])}). Industry: {', '.join(company['industries'])}.\n"
            f"Business areas: {company['segment']}. Reporting currency: {company['currency']}. Release dated {rel.get('filed')}.\n\n"
            f"Notes:\n{notes_text(notes, news_lines)}\n\nReturn JSON exactly in this shape:\n{SCHEMA_REDUCE}")
    out = llm.chat_json(SYSTEM_REDUCE, user, max_tokens=2800)
    corpus = "\n".join(d["text"] for d in docs) + "\n" + "\n".join(news_lines)
    brief = _check(out if isinstance(out, dict) else {}, corpus)
    brief["unverified_dropped"] = dropped + brief["unverified_dropped"]
    brief.update({
        "format": FORMAT, "company": company["short"], "name": company["name"], "industry": company["industry"],
        "currency": company["currency"], "release_key": rel.get("accession"), "release_date": rel.get("filed"),
        "documents": [{"title": d["title"], "url": d.get("url"), "official": d["official"], "kind": d.get("kind"),
                       "site": bool(d.get("site")), "source": d.get("source")} for d in docs],
        "news_used": bool(news_lines), "chunks_read": len(notes),
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return brief


def run(llm, sec, companies, status, log, force=False):
    """Write an account update for every client whose latest release has none yet in the current format."""
    from .settings import read_json, write_json
    briefs = read_json("briefs.json", {})
    done = []
    newest = sorted(companies, key=lambda c: str(((status.get(c["short"]) or {}).get("release") or {}).get("filed") or ""), reverse=True)
    for c in newest:  # newest releases first, in case the free AI allowance runs out
        rel = (status.get(c["short"]) or {}).get("release")
        if not rel or c["type"] == "private":
            continue
        old = briefs.get(c["short"]) or {}
        if not force and old.get("release_key") == rel.get("accession") and old.get("format") == FORMAT:
            continue
        if llm.left_today() < 45000:
            print("   Not enough free AI allowance left today; the remaining updates wait for the next run.")
            break
        print(f"   {c['short']}: reading the company's documents ({rel.get('form')}, {rel.get('filed')})...")
        try:
            b = make_brief(llm, sec, c, rel, log)
        except Exception as e:  # noqa: BLE001
            print(f"      problem: {e}")
            log["errors"].append(f"brief {c['short']}: {str(e)[:150]}")
            if "allowance" in str(e) or "refused" in str(e):
                break
            continue
        if b:
            briefs[c["short"]] = b
            done.append(c["short"])
            write_json("briefs.json", briefs)  # save as we go
            print(f"      -> {len(b['documents'])} documents ({sum(1 for d in b['documents'] if d['site'])} from the website), "
                  f"{b['chunks_read']} parts read, {len(b['segments'])} segments, {len(b['focus'])} focus areas, "
                  f"{len(b['leadership'])} leadership changes" + (f", removed unverified: {len(b['unverified_dropped'])}" if b.get("unverified_dropped") else ""))
    write_json("briefs.json", briefs)
    log["steps"].append(f"account updates written: {', '.join(done) or 'none'}")
    return briefs
