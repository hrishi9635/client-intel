"""Industry News: education, publishing, lottery and gaming. Free RSS feeds plus Google/Bing News searches,
last 14 days, de-duplicated, then one AI call per industry."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from . import news as newsmod
from .settings import read_csv
from .verify import flat, scrub

AREAS = {
    "Education": ["higher education enrollment", "edtech", "university AI", "standardized testing"],
    "Publishing": ["publishing industry", "news media layoffs", "AI licensing deal publishers"],
    "Lottery": ["lottery industry", "iLottery", "lottery contract"],
    "Gaming": ["casino revenue", "iGaming legalization", "sports betting"],
}
THEMES = ["AI", "Regulation", "M&A", "Layoffs", "Enrolment", "Legalisation", "Funding", "Technology",
          "Earnings", "Labour", "Policy", "Litigation", "Digital", "Consumer demand"]

SYSTEM = """You are an industry analyst writing a daily brief for a technology / IT services team. You read numbered
headlines (with short snippets) about ONE industry from the last two weeks. Rules:
- Use ONLY the numbered items. Every number you write must appear in them.
- Pick 5-7 genuinely important stories (not duplicates of each other) and say in one line why each matters.
- Organisations are industry players; never call them clients.
- Short, plain, neutral sentences. Return ONE JSON object."""

SCHEMA = """{"mood": "Positive|Mixed|Negative", "mood_reason": "one sentence",
 "themes": ["2-5 from: AI, Regulation, M&A, Layoffs, Enrolment, Legalisation, Funding, Technology, Earnings, Labour, Policy, Litigation, Digital, Consumer demand"],
 "top_stories": [{"id": number, "why": "one line: why it matters"}],
 "it_implications": "2-3 sentences: what this means for IT services / technology vendors",
 "tracked_mentions": [{"company": "short name from the tracked list", "note": "what was said"}]}"""


def gather(area, feeds, days, companies):
    items, status = [], []
    for f in feeds:
        got, err = [], "no feed"
        if (f.get("url") or "").strip():
            got, err = newsmod.fetch_feed(f["url"].strip(), f["name"])
            for g in got:
                g["source"] = f["name"]
        via = "RSS feed"
        if not got and (f.get("site") or "").strip():
            got = newsmod.google_news(f"site:{f['site'].strip()}", days)
            via = "Google News (site search)"
        status.append({"area": area, "name": f["name"], "ok": bool(got), "via": via,
                       "error": None if got else err,
                       "checked": datetime.now(timezone.utc).isoformat(timespec="minutes")})
        items += got
    for q in AREAS[area]:
        items += newsmod.google_news(q, days) + newsmod.bing_news(q)
    items = newsmod.dedupe(newsmod.recent(items, days))
    for it in items:
        text = f"{it['title']} {it.get('snippet', '')}"
        it["mentions"] = [c["short"] for c in companies if newsmod.mentions(text, c["aliases"])]
        it["area"] = area
    return items, status


def analyse(llm, area, items, companies):
    # stories that mention tracked companies first, then the newest
    ranked = [x for x in items if x.get("mentions")][:10] + [x for x in items if not x.get("mentions")]
    lines, used, size = [], [], 0
    for it in ranked:
        line = f"[{len(used) + 1}] {it['title']} ({it.get('source', '')}, {(it.get('published') or '')[:10]})"
        if it.get("snippet"):
            line += f" — {it['snippet'][:200]}"
        if size + len(line) > 9000 or len(used) >= 40:
            break
        lines.append(line)
        used.append(it)
        size += len(line)
    corpus = "\n".join(lines)
    tracked = ", ".join(c["short"] for c in companies)
    user = (f"Industry: {area}. Today: {date.today().isoformat()}.\nTracked organisations (short names): {tracked}\n\n"
            f"Items:\n{corpus}\n\nReturn JSON exactly in this shape:\n{SCHEMA}")
    out = llm.chat_json(SYSTEM, user, max_tokens=1800)
    dropped = []
    scrub(out, flat(corpus), dropped)
    stories = []
    for s in out.get("top_stories") or []:
        i = s.get("id")
        if isinstance(i, int) and 1 <= i <= len(used) and s.get("why"):
            it = used[i - 1]
            stories.append({"title": it["title"], "link": it["link"], "source": it.get("source"),
                            "published": (it.get("published") or "")[:10], "why": s["why"],
                            "mentions": it.get("mentions") or []})
    names = {c["short"] for c in companies}
    mood = out.get("mood") if out.get("mood") in ("Positive", "Mixed", "Negative") else "Mixed"
    return {"area": area, "mood": mood, "mood_reason": out.get("mood_reason"),
            "themes": [t for t in (out.get("themes") or []) if isinstance(t, str)][:5],
            "top_stories": stories[:7], "it_implications": out.get("it_implications"),
            "tracked_mentions": [m for m in (out.get("tracked_mentions") or []) if isinstance(m, dict) and m.get("company") in names],
            "unverified_dropped": dropped, "analysed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def run(settings, llm, companies, old, history, log, force=False, skip_ai=False):
    days = settings["INDUSTRY_NEWS_DAYS"]
    feeds = read_csv("feeds.csv")
    out = {"areas": {}, "items": [], "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    all_status = []
    for area in AREAS:
        items, status = gather(area, [f for f in feeds if (f.get("area") or "").strip() == area], days, companies)
        all_status += status
        out["items"] += [{k: it.get(k) for k in ("area", "title", "link", "source", "published", "mentions")} for it in items[:120]]
        print(f"   {area}: {len(items)} stories ({sum(s['ok'] for s in status)}/{len(status)} feeds working)")
        prev = (old.get("areas") or {}).get(area) or {}
        h = hashlib.sha1(json.dumps([i["title"] for i in items[:25]]).encode()).hexdigest()[:12]
        recent_enough = prev.get("analysed_at", "") >= (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
        if prev and not force and (prev.get("input_hash") == h or recent_enough):
            out["areas"][area] = prev
            continue
        if skip_ai or not llm.available() or len(items) < 3:
            if prev:
                out["areas"][area] = prev
            continue
        try:
            res = analyse(llm, area, items, companies)
            res["input_hash"] = h
            res["stories_count"] = len(items)
            out["areas"][area] = res
            history.setdefault(area, []).append({"date": date.today().isoformat(), "mood": res["mood"]})
            history[area] = history[area][-60:]
            print(f"      mood {res['mood']}; themes: {', '.join(res['themes'])}")
        except Exception as e:  # noqa: BLE001
            log["errors"].append(f"industry {area}: {e}")
            print(f"      AI problem: {e}")
            if prev:
                out["areas"][area] = prev
    return out, all_status
