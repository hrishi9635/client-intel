"""The 'thinking' part of the results agent: reads the official release and the news, extracts results and
IT-services signals, deletes any number it can't find in a source, and writes the sector view."""
import json
import re
from datetime import date, datetime, timedelta, timezone

from . import news as newsmod
from .verify import check_metrics, flat, scrub

SIGNAL_TYPES = ["AI & tech investment", "Digital / platform rebuild", "Cloud & data", "Cost-cutting / restructuring",
                "Layoffs", "M&A / spin-off", "Vendor / outsourcing", "Other"]

RULES = """Rules:
- Use ONLY the numbered sources. Never use outside knowledge for numbers, names or dates.
- Sources whose title starts with "OFFICIAL" are the company's own results release. They come first and win
  over news reports.
- If something is not stated in the sources, use null or an empty list. Do not guess.
- Every number you write (in any field) must appear in a source. Amounts in MILLIONS of the reporting currency
  as plain numbers (23650 not "$23.65 billion"); percentages as numbers (5.2 not "5.2%").
- Previews, expectations, analyst estimates, "results date" announcements, "what to watch" and generic topic pages
  are NOT results.
- guidance_change: "narrowed" when a range is tightened (e.g. 640-685 to 650-675); use "cut" only if the midpoint or
  the whole range went down; "retained" when unchanged.
- IT services signals = anything an IT services / technology vendor account team should know: technology or AI
  investment plans, digital or platform rebuilds, cloud or data moves, cost-cutting, restructuring, layoffs,
  M&A or spin-offs, vendor or outsourcing mentions, big systems projects.
- Neutral, plain, short sentences. These companies are written about as industry players. Return ONE JSON object."""

RESULTS_SYSTEM = ("You are a careful equity-research analyst. You read numbered sources about ONE company and extract "
                  "its latest reported results and its technology-spending signals.\n" + RULES)

RESULTS_SCHEMA = """{
 "results_found": true or false,
 "period_label": "calendar period of the results, e.g. Q3 2026, H1 2026, FY 2026, or null",
 "fiscal_label": "the company's own name for the period, e.g. 'fiscal Q4 2026', or null",
 "period_end": "YYYY-MM-DD last day of the period, or null",
 "results_date": "YYYY-MM-DD the day the results were released, or null",
 "headline": "one sentence: the most important takeaway",
 "metrics": {"revenue_m": number|null, "revenue_growth_yoy_pct": number|null, "operating_income_m": number|null,
             "operating_margin_pct": number|null, "net_income_m": number|null, "eps": number|null},
 "guidance": "text or null", "guidance_change": "raised|cut|narrowed|retained|introduced|withdrawn|none|unknown",
 "segments": [{"name": "segment, e.g. Parks / Streaming / Casinos / iGaming / Lottery / Education", "trend": "Up|Down|Flat|Mixed", "note": "short"}],
 "highlights": ["3-5 short points"],
 "management_view": "one-sentence paraphrase of management commentary, or null",
 "risks": ["1-3 short points"],
 "sentiment": "Positive|Neutral|Negative", "sentiment_reason": "short",
 "it_signals": [{"type": "AI & tech investment|Digital / platform rebuild|Cloud & data|Cost-cutting / restructuring|Layoffs|M&A / spin-off|Vendor / outsourcing|Other", "detail": "what was said", "source_id": number}],
 "it_spend_outlook": "Expanding|Stable|Tightening|Unclear",
 "it_spend_reason": "one sentence",
 "talking_points": ["2-3 conversation starters for a technology account team"],
 "source_ids": [numbers of the sources you used],
 "missing": ["important facts you could not find"],
 "follow_up_queries": ["up to 2 news searches that would find the missing facts"]
}"""

SIGNALS_SYSTEM = ("You are a careful industry analyst. You read numbered recent news about ONE organisation and pick "
                  "out what matters to a technology / IT services account team. It is not a results report.\n" + RULES)

SIGNALS_SCHEMA = """{
 "headline": "one sentence: the most important recent development",
 "highlights": ["3-5 short points from the news"],
 "risks": ["1-3 short points"],
 "sentiment": "Positive|Neutral|Negative", "sentiment_reason": "short",
 "segments": [{"name": "business area", "trend": "Up|Down|Flat|Mixed", "note": "short"}],
 "it_signals": [{"type": "AI & tech investment|Digital / platform rebuild|Cloud & data|Cost-cutting / restructuring|Layoffs|M&A / spin-off|Vendor / outsourcing|Other", "detail": "what was said", "source_id": number}],
 "it_spend_outlook": "Expanding|Stable|Tightening|Unclear",
 "it_spend_reason": "one sentence",
 "talking_points": ["2-3 conversation starters for a technology account team"],
 "source_ids": [numbers of the sources you used]
}"""

SECTOR_SYSTEM = """You are the head of research. From per-company summaries prepared by your analysts, write a crisp
cross-industry view grouped by industry. Use ONLY the information given. Plain language, short sentences, no hype.
Companies are industry players (never call them clients). Every number you write must appear in the input.
Return one JSON object only."""

SECTOR_SCHEMA = """{
 "headline": "one sentence across all industries",
 "summary": "3-4 sentences",
 "industries": [{"industry": "name", "mood": "Positive|Mixed|Negative|Not enough data", "summary": "2-3 sentences",
                 "leaders": [{"company": "name", "why": "short"}], "laggards": [{"company": "name", "why": "short"}],
                 "themes": [{"title": "short", "detail": "1-2 sentences", "companies": ["names"]}],
                 "it_outlook": "Expanding|Stable|Tightening|Mixed|Unclear", "it_note": "1-2 sentences for a technology account team"}],
 "watch_next": ["3-5 things to watch"]
}"""

PREVIEW = ("preview", "expect", "estimate", "likely", "to announce", "will announce", "will report", "to report",
           "date", "when ", "what to watch", "ahead of", "could", "may ", "poll", "live updates", "how to", "options",
           "earnings call transcript")
REPORTED = ("revenue", "profit", "loss", "earnings", "sales", "income", "results", "rises", "falls", "jumps", "drops",
            "beats", "misses", "posts", "reports", "%", "margin", "trading update")


def official_news(company, items):
    """Results releases published on the company's own site or an official newswire (non-SEC listed companies)."""
    out = []
    doms = [d.lower() for d in company.get("official_domains") or []]
    for it in items:
        dom = (it.get("domain") or "").lower()
        t = it.get("title", "").lower()
        if doms and any(dom.endswith(d) for d in doms) and newsmod.mentions(it["title"], company["aliases"]) \
                and any(w in t for w in ("results", "trading update", "trading statement", "half-year", "half year",
                                         "nine-month", "full-year", "full year", "first quarter", "third quarter")) \
                and not any(w in t for w in ("date", "will publish", "to publish", "conference call", "webcast", "invitation")):
            out.append(it)
    return out


def headline_reports_results(items, since_iso):
    good = []
    for s in items:
        t = s.get("title", "").lower()
        if (s.get("published") or "")[:10] >= since_iso and not any(w in t for w in PREVIEW) \
                and any(w in t for w in REPORTED):
            good.append(s)
    return good


def build_corpus(items, official=None, budget=9500):
    """Number the sources so the AI can cite them. Official releases go first. Stays within the size budget."""
    lines, used, size = [], [], 0
    for it in official or []:
        line = f"[{len(used) + 1}] OFFICIAL: {it['title']} ({it.get('source', '')}, {(it.get('published') or '')[:10]})"
        if it.get("text"):
            line += f"\n    Release text: {it['text']}"
        lines.append(line)
        used.append(it)
        size += len(line)
    for it in items:
        line = f"[{len(used) + 1}] {it['title']} ({it.get('source', '')}, {(it.get('published') or '')[:10]})"
        if it.get("snippet"):
            line += f" — {it['snippet'][:260]}"
        if size + len(line) > budget:
            break
        lines.append(line)
        used.append(it)
        size += len(line)
    return "\n".join(lines), used


def _sources(result, used, n_official):
    ids = [i for i in (result.get("source_ids") or []) if isinstance(i, int) and 1 <= i <= len(used)]
    for i in range(n_official, 0, -1):  # always cite the official release
        if i not in ids:
            ids.insert(0, i)
    for s in result.get("it_signals") or []:
        sid = s.get("source_id")
        if isinstance(sid, int) and 1 <= sid <= len(used):
            s["link"] = used[sid - 1].get("link")
            s["source"] = used[sid - 1].get("source")
            s["published"] = (used[sid - 1].get("published") or "")[:10]
    return [{"title": used[i - 1]["title"], "link": used[i - 1]["link"], "source": used[i - 1].get("source"),
             "published": used[i - 1].get("published"), "official": i <= n_official} for i in ids]


def _clean_choice(v, allowed, default):
    v = (v or "").strip() if isinstance(v, str) else ""
    for a in allowed:
        if v.lower() == a.lower():
            return a
    return default


def analyse_results(llm, company, items, official, known, days):
    """Full results analysis (listed company with a fresh official release). Up to two rounds."""
    corpus, used = build_corpus(items, official)
    result = None
    for round_no in (1, 2):
        user = (f"Organisation: {company['name']} (also called {', '.join(company['aliases'][:5])}).\n"
                f"Industry: {', '.join(company['industries'])}. Business areas to track: {company['segment']}.\n"
                f"Reporting currency: {company['currency']}. Note: {company['note'] or 'none'}.\n"
                f"Figures already known from regulatory data (context only; do not copy unless a source states them): "
                f"{json.dumps(known)}\n\nSources:\n{corpus}\n\nReturn JSON exactly in this shape:\n{RESULTS_SCHEMA}")
        result = llm.chat_json(RESULTS_SYSTEM, user)
        queries = [q for q in (result.get("follow_up_queries") or []) if isinstance(q, str)][:2]
        # search again only when the headline numbers are missing (saves the free AI allowance)
        important = [m for m in (result.get("missing") or [])
                     if any(w in str(m).lower() for w in ("revenue", "income", "guidance"))] \
            if (result.get("metrics") or {}).get("revenue_m") is None and result.get("results_found") else []
        if round_no == 2 or not queries or not important or llm.left_today() < 30000:
            break
        print(f"      Looking for missing facts: {', '.join(queries)}")
        extra = []
        for q in queries:
            extra += newsmod.search(q, company["aliases"], days, bing=False)
        known_titles = {it["title"] for it in used}
        extra = [it for it in extra if it["title"] not in known_titles][:8]
        if not extra:
            break
        more, more_used = build_corpus(extra, budget=2000)
        offset = len(used)
        more = re.sub(r"^\[(\d+)\]", lambda m: f"[{int(m.group(1)) + offset}]", more, flags=re.M)
        corpus += "\n" + more
        used += more_used
    fc = flat(corpus)
    dropped = []
    check_metrics(result.get("metrics"), fc, dropped)
    scrub(result, fc, dropped)
    result["unverified_dropped"] = dropped
    result["sources"] = _sources(result, used, len(official or []))
    return _finish(result, company, "results")


def analyse_signals(llm, company, items):
    """News-only analysis: private companies, and weekly refresh of IT signals for everyone."""
    corpus, used = build_corpus(items, budget=10000)
    user = (f"Organisation: {company['name']} (also called {', '.join(company['aliases'][:5])}).\n"
            f"Industry: {', '.join(company['industries'])}. Areas to track: {company['segment']}. "
            f"Note: {company['note'] or 'none'}.\n\nSources:\n{corpus}\n\nReturn JSON exactly in this shape:\n{SIGNALS_SCHEMA}")
    result = llm.chat_json(SIGNALS_SYSTEM, user)
    fc = flat(corpus)
    dropped = []
    scrub(result, fc, dropped)
    result["unverified_dropped"] = dropped
    result["sources"] = _sources(result, used, 0)
    return _finish(result, company, "signals")


def _finish(result, company, mode):
    result["company"] = company["short"]
    result["mode"] = mode
    result["analysed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["sentiment"] = _clean_choice(result.get("sentiment"), ["Positive", "Neutral", "Negative"], None)
    result["it_spend_outlook"] = _clean_choice(result.get("it_spend_outlook"), ["Expanding", "Stable", "Tightening", "Unclear"], "Unclear")
    result["guidance_change"] = _clean_choice(result.get("guidance_change"),
                                              ["raised", "cut", "narrowed", "retained", "introduced", "withdrawn", "none", "unknown"], None)
    for s in result.get("it_signals") or []:
        s["type"] = _clean_choice(s.get("type"), SIGNAL_TYPES, "Other")
    for k in ("follow_up_queries", "source_ids", "missing"):
        result.pop(k, None)
    return result


def results_check(result, release, period_hint=None):
    """Reject 'results found' when the facts make it impossible. Returns the reason, or '' if fine."""
    if not result.get("results_found"):
        return ""
    if not release:
        return "there is no official results release"
    d = result.get("results_date") or release.get("filed")
    try:
        rd = date.fromisoformat(str(d)[:10])
    except ValueError:
        return "no release date"
    if rd > date.today() + timedelta(days=1):
        return f"the date {rd} is in the future (a preview)"
    pe = result.get("period_end")
    if pe:
        try:
            ped = date.fromisoformat(str(pe)[:10])
            if ped > rd:
                return f"the period end {ped} is after the release date {rd}"
            if (rd - ped).days > 150:
                return f"the period ({ped}) is too old for a release filed {rd}"
        except ValueError:
            result["period_end"] = None
    return ""


def sector_view(llm, insights, companies, scorecard):
    by_ind = {}
    for c in companies:
        ins = insights.get(c["short"]) or {}
        if not ins:
            continue
        brief = {"company": c["short"], "type": c["type"], "period": ins.get("period_label") if ins.get("results_found") else None,
                 "headline": ins.get("headline"), "guidance_change": ins.get("guidance_change"),
                 "sentiment": ins.get("sentiment"), "it_spend_outlook": ins.get("it_spend_outlook"),
                 "it_signals": [f"{s.get('type')}: {s.get('detail')}" for s in (ins.get("it_signals") or [])[:3]],
                 "numbers": scorecard.get(c["short"], {})}
        for ind in c["industries"]:
            by_ind.setdefault(ind, []).append(brief)
    payload = json.dumps(by_ind, ensure_ascii=False)
    if len(payload) > 11000:  # stay inside the free AI's request size
        for ind in by_ind.values():
            for b in ind:
                b["it_signals"] = b["it_signals"][:1]
        payload = json.dumps(by_ind, ensure_ascii=False)[:11000]
    user = (f"Today: {date.today().isoformat()}.\nCompany summaries grouped by industry (numbers in millions of each "
            f"company's currency, growth in %):\n{payload}\n\nCover every industry in the input.\n"
            f"Return JSON exactly in this shape:\n{SECTOR_SCHEMA}")
    out = llm.chat_json(SECTOR_SYSTEM, user, max_tokens=2500)
    dropped = []
    scrub(out, flat(payload), dropped)
    out["unverified_dropped"] = dropped
    out["written_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out
