"""
Account update per client, built from the OFFICIAL documents of each results release.
It is written for a sales SPOC who needs to know what is going on at the client right now.

What it reads (all public):
 - the official release (SEC 8-K Exhibit 99.1 / 6-K / company release page), with the outlook, strategy,
   organisation, technology and deal paragraphs picked first, plus other exhibits filed with it
 - the earnings-call transcript if a public copy can be found (secondary: items are marked "call")
 - recent news headlines about leadership moves and technology / IT spending (secondary: marked "news")

What it writes (data/briefs.json, one entry per client, kept until the next release), in the same sections
as the PDFs: at a glance, guidance, business units, organisation changes, leadership changes,
technology & IT spending, contracts & partnerships, pressures & risks, management quotes, key dates,
and short summary bullets for the one-page version.

Checks: every number must appear in the sources, quotes must be word for word, people's names must appear
in the sources. Anything that fails is removed. Two AI calls per release keep each request inside the
free per-minute limit.
"""
import re
from datetime import datetime, timezone

from . import news as newsmod
from .verify import flat, text_ok

KEYWORDS = {
    3: ["outlook", "guidance", "expect", "medium term", "medium-term", "target", "full year", "full-year", "reaffirm",
        "narrow", "raise", "lower", "range", "forecast"],
    2: ["strategy", "strategic", "priorit", "invest", "operating model", "reorganis", "reorganiz", "restructur",
        "simplif", "efficien", "saving", "cost", "platform", "technology", "digital", "ai ", "artificial intelligence",
        "cloud", "data", "automation", "acqui", "partner", "contract", "customer", "launch", "transform", "consolidat",
        "vendor", "outsourc", "headcount", "workforce", "leadership", "appoint", "chief", "president", "join",
        "step down", "depart", "succeed", "said", "capex", "capital expenditure", "systems", "integration"],
    1: ["segment", "division", "revenue", "growth", "margin", "headwind", "risk", "pressure", "decline", "demand"],
}

RULES = """You read a company's OFFICIAL results documents (numbered sources) and write a clear, factual account update
for a sales colleague at an IT services firm who wants to know everything that is going on at this company right now.
Rules:
- Use ONLY the numbered sources. Every number, name, date and quote must appear in them. No outside knowledge.
- OFFICIAL sources are the company's own documents. CALL sources are third-party transcripts of the earnings call:
  use them, and set "src": "call" (or end a text point with " (call)"). NEWS sources are recent headlines:
  use them only for leadership moves and technology / IT spending, with "src": "news" (or " (news)").
- Plain, short sentences a busy person can scan. State facts; no sales pitch, no advice, no opinions.
- The company is an industry player; never call it a client or "our"."""

SYSTEM_A = RULES + """
This part: results, guidance, business units, contracts, risks, quotes and dates.
- Guidance: list EVERY guided item separately (revenue, growth, profit, margin, EPS, cash flow, capex, tax, interest,
  buybacks). "narrowed" = range tightened (say in the note whether the midpoint moved); "reaffirmed" = unchanged.
  Never call a narrowed range "cut" unless the midpoint went down.
- Quotes must be copied word for word (max 30 words). If unsure, leave them out.
Return ONE JSON object."""

SCHEMA_A = """{
 "document_type": "Quarterly results|Half-year results|Full-year results|Trading update|Investor update|Other",
 "period": "e.g. Nine months to 30 September 2026",
 "headline": "2-3 sentences: the most important things happening at the company now",
 "at_a_glance": ["4-6 short bullets: growth, strongest and weakest areas, big moves"],
 "guidance_verdict": "Raised|Lowered|Narrowed|Reaffirmed|Mixed|Introduced|Withdrawn|None given",
 "guidance": [{"metric": "", "new": "", "previous": "or null", "change": "raised|lowered|narrowed|reaffirmed|introduced|withdrawn|n/a",
               "note": "e.g. midpoint unchanged, or null", "src": "official|call"}],
 "guidance_notes": ["basis, exchange rates, phasing, what is excluded"],
 "unit_outlook": [{"unit": "", "outlook": ""}],
 "medium_term": ["medium-term targets, one per bullet"],
 "units": [{"unit": "business unit", "numbers": "headline growth as stated", "points": ["2-4 facts: drivers, wins, problems"]}],
 "deals": [{"name": "", "type": "Acquisition|Disposal|Partnership|Contract win|Contract loss|Extension|Launch|Other", "detail": "", "src": "official|call|news"}],
 "risks": ["pressures and risks stated"],
 "quotes": [{"speaker": "name and role", "quote": "verbatim"}],
 "dates": [{"date": "", "event": ""}]
}"""

SYSTEM_B = RULES + """
This part: organisation changes, leadership changes, and technology & IT spending.
- Organisation: any reorganisation, new operating model, new business units (with size and leader when stated),
  restructuring cost, savings and what they are reinvested in, timing.
- Leadership: EVERY person named as appointed, leaving, retiring, promoted, given a new or bigger role, or leading
  a new unit (including people joining through acquisitions). Unchanged CEO/CFO go in "unchanged".
- Technology & IT spending: anything about technology platforms, systems, vendors, consolidation, cloud, data, AI,
  automation, digital products, capex or technology investment, acquired technology to integrate, technology partners.
  Group the points under short topics. Include amounts and timing when stated.
- Summary: very short bullets for a one-page version.
Return ONE JSON object."""

SCHEMA_B = """{
 "organisation": {"summary": "1-2 sentences or null", "effective": "date or null",
                  "units": [{"unit": "", "size": "e.g. revenue, or null", "includes": "", "leader": "or null", "src": "official|call"}],
                  "points": ["cost, savings, reinvestment, timing"]},
 "leadership": [{"person": "", "role": "", "change": "Appointed|Leaving|Retiring|Promoted|New role|Expanded role|Joining|Other",
                 "detail": "timing or context", "src": "official|call|news"}],
 "unchanged": ["e.g. Jane Doe (Chief Executive)"],
 "technology": [{"topic": "e.g. Platform & vendor consolidation / Acquisitions to integrate / AI products / Technology partners / Technology investment",
                 "points": ["facts; end with (call) or (news) when not from the official documents"]}],
 "summary": {"happening": ["max 4 bullets, max 20 words each"], "technology": ["max 5 bullets, max 25 words each"]}
}"""


def select_text(text, budget):
    """Keep the opening, then the most relevant paragraphs (in their original order) until the budget is used."""
    text = re.sub(r"[ \t\xa0]+", " ", text or "")
    paras = [p.strip() for p in re.split(r"\n+", text) if len(p.strip()) > 40]
    if sum(len(p) for p in paras) <= budget:
        return "\n".join(paras)
    head, used, keep = [], 0, set()
    head_budget = min(1600, budget // 5)  # the opening (headline numbers), then the most relevant paragraphs
    for i, p in enumerate(paras):
        if used >= head_budget:
            break
        head.append(i)
        p = p[:head_budget]
        paras[i] = p
        used += len(p)
    scored = []
    for i, p in enumerate(paras):
        if i in head:
            continue
        low = p.lower()
        s = sum(w * sum(low.count(k) for k in ks) for w, ks in KEYWORDS.items())
        s += 2 * len(re.findall(r"[£$€]\s?\d|\d+(?:\.\d+)?\s?%|\bbps\b", p))
        scored.append((s, i))
    for s, i in sorted(scored, reverse=True):
        if s <= 0 or used + len(paras[i]) > budget:
            continue
        keep.add(i)
        used += len(paras[i])
    order = sorted(set(head) | keep)
    out, last = [], -1
    for i in order:
        if last >= 0 and i != last + 1:
            out.append("[...]")
        out.append(paras[i][:1500])
        last = i
    return "\n".join(out)


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


def build_corpus(docs, news_lines=None, budget=11000):
    off = [d for d in docs if d.get("official")]
    call = [d for d in docs if not d.get("official")]
    news_txt = "\n".join(news_lines or [])[:1600]
    budget -= len(news_txt)
    lines = []
    share_off = budget if not call else int(budget * 0.72)
    per = max(2500, share_off // max(1, len(off))) if off else 0
    for i, d in enumerate(off):
        b = per if i else max(per, share_off - per * (len(off) - 1))
        lines.append(f"[{len(lines) + 1}] OFFICIAL: {d['title']}\n{select_text(d['text'], b)}")
    for d in call:
        lines.append(f"[{len(lines) + 1}] CALL (earnings call transcript, third-party): {d['title']}\n"
                     f"{select_text(d['text'], budget - share_off)}")
    if news_txt:
        lines.append(f"[{len(lines) + 1}] NEWS (recent headlines, secondary):\n{news_txt}")
    return "\n\n".join(lines)


def _norm(s):
    return re.sub(r"[^a-z0-9%£$€.]+", " ", (s or "").lower()).strip()


SRC = {"official", "call", "news"}


def _check(brief, corpus):
    """Remove anything with a number not in the sources, quotes that are not verbatim, names not in the sources."""
    fc, nc, dropped = flat(corpus), _norm(corpus), []

    def ok(s):
        if not isinstance(s, str):
            return True
        # small percentages ("9%") are skipped by the shared check, so test them here
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s?(%|per ?cent)", s):
            if not re.search(rf"(?<![\d.]){re.escape(m.group(1))}\s?(%|per ?cent)", fc):
                return False
        return text_ok(s, fc)

    def strings(items):
        out = []
        for x in items or []:
            if isinstance(x, str) and x.strip():
                if ok(x):
                    out.append(x.strip())
                else:
                    dropped.append(x[:60])
        return out

    def objects(items, keys, must):
        out = []
        for x in items or []:
            if not isinstance(x, dict):
                continue
            for k in keys:
                if isinstance(x.get(k), str) and not ok(x[k]):
                    dropped.append(f"{k}: {x[k][:60]}")
                    x[k] = None
                elif isinstance(x.get(k), list):
                    x[k] = strings(x[k])
            if x.get("src") not in SRC:
                x["src"] = "official"
            if all(x.get(m) for m in must):
                out.append(x)
        return out

    def named(items, key):
        out = []
        for x in items:
            if x.get(key) and _norm(x[key]) not in nc:
                dropped.append(f"name not in sources: {x[key]}")
                x[key] = None
            out.append(x)
        return out

    for k in ("headline",):
        if not ok(brief.get(k)):
            dropped.append(k)
            brief[k] = None
    for k in ("at_a_glance", "guidance_notes", "medium_term", "risks", "unchanged"):
        brief[k] = strings(brief.get(k))
    brief["guidance"] = objects(brief.get("guidance"), ["metric", "new", "previous", "note"], ["metric", "new"])
    brief["unit_outlook"] = objects(brief.get("unit_outlook"), ["unit", "outlook"], ["unit", "outlook"])
    brief["units"] = objects(brief.get("units"), ["unit", "numbers", "points"], ["unit"])
    brief["deals"] = objects(brief.get("deals"), ["name", "detail"], ["name"])
    brief["dates"] = objects(brief.get("dates"), ["date", "event"], ["event"])
    brief["technology"] = [t for t in objects(brief.get("technology"), ["topic", "points"], ["topic"]) if t.get("points")]
    org = brief.get("organisation") if isinstance(brief.get("organisation"), dict) else {}
    for k in ("summary", "effective"):
        if not ok(org.get(k)):
            dropped.append(f"organisation {k}")
            org[k] = None
    org["units"] = named(objects(org.get("units"), ["unit", "size", "includes", "leader"], ["unit"]), "leader")
    org["points"] = strings(org.get("points"))
    brief["organisation"] = org
    lead = []
    for x in objects(brief.get("leadership"), ["role", "detail"], ["person"]):
        if _norm(x["person"]) in nc:
            lead.append(x)
        else:
            dropped.append(f"person not in sources: {x.get('person')}")
    brief["leadership"] = lead
    quotes = []
    for q in brief.get("quotes") or []:
        if isinstance(q, dict) and q.get("quote") and len(_norm(q["quote"])) > 15 and _norm(q["quote"]) in nc:
            quotes.append(q)
        elif isinstance(q, dict):
            dropped.append(f"quote not verbatim: {str(q.get('quote'))[:50]}")
    brief["quotes"] = quotes[:5]
    sm = brief.get("summary") if isinstance(brief.get("summary"), dict) else {}
    brief["summary"] = {"happening": strings(sm.get("happening"))[:4], "technology": strings(sm.get("technology"))[:5]}
    allowed = {"Raised", "Lowered", "Narrowed", "Reaffirmed", "Mixed", "Introduced", "Withdrawn", "None given"}
    if brief.get("guidance_verdict") not in allowed:
        brief["guidance_verdict"] = "Mixed" if brief["guidance"] else "None given"
    brief["unverified_dropped"] = dropped
    return brief


def make_brief(llm, sec, company, rel, log):
    docs = official_documents(sec, company, rel, log)
    if not docs:
        return None
    tr = call_transcript(company)
    if tr:
        docs.append(tr)
    news_lines = news_context(company)
    corpus = build_corpus(docs, news_lines)
    intro = (f"Company: {company['name']} (also called {', '.join(company['aliases'][:4])}). Industry: {', '.join(company['industries'])}.\n"
             f"Business areas: {company['segment']}. Reporting currency: {company['currency']}. Note: {company['note'] or 'none'}.\n\n"
             f"Sources:\n{corpus}\n\n")
    out = llm.chat_json(SYSTEM_A, intro + f"Return JSON exactly in this shape:\n{SCHEMA_A}", max_tokens=3000)
    if not isinstance(out, dict):
        out = {}
    try:
        part_b = llm.chat_json(SYSTEM_B, intro + f"Return JSON exactly in this shape:\n{SCHEMA_B}", max_tokens=2600)
        if isinstance(part_b, dict):
            out.update({k: part_b.get(k) for k in ("organisation", "leadership", "unchanged", "technology", "summary")})
    except Exception as e:  # noqa: BLE001  # part A alone still makes a useful update
        log["errors"].append(f"brief part B {company['short']}: {str(e)[:120]}")
    brief = _check(out, corpus)
    brief.update({
        "format": 2,
        "company": company["short"], "name": company["name"], "industry": company["industry"],
        "release_key": rel.get("accession"), "release_date": rel.get("filed"),
        "documents": [{"title": d["title"], "url": d.get("url"), "official": d["official"], "source": d.get("source")} for d in docs],
        "news_used": bool(news_lines),
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return brief


def run(llm, sec, companies, status, log, force=False):
    """Write an account update for every client whose latest official release has none yet (or an old-format one)."""
    from .settings import read_json, write_json
    briefs = read_json("briefs.json", {})
    done = []
    for c in companies:
        rel = (status.get(c["short"]) or {}).get("release")
        if not rel or c["type"] == "private":
            continue
        old = briefs.get(c["short"]) or {}
        if not force and old.get("release_key") == rel.get("accession") and old.get("format") == 2:
            continue
        if llm.left_today() < 20000:
            print("   Not enough free AI allowance left today; the remaining updates wait for the next run.")
            break
        print(f"   {c['short']}: reading the official documents ({rel.get('form')}, {rel.get('filed')})...")
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
            print(f"      -> guidance {b.get('guidance_verdict')}: {len(b['guidance'])} guided items, "
                  f"{len(b['leadership'])} leadership changes, {len(b['technology'])} technology topics"
                  + (f" (removed unverified: {len(b['unverified_dropped'])})" if b.get("unverified_dropped") else ""))
    write_json("briefs.json", briefs)
    log["steps"].append(f"account updates written: {', '.join(done) or 'none'}")
    return briefs
