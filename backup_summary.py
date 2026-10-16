"""One shared summary of the data the agent saved, used by the backup copies only:
the static website (build_site.py), the e-mail digest + PDF and the Telegram alerts (notify.py).
It only READS the data folder; the agent and the Streamlit app are not changed by it."""
import csv
import json
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£"}
SPARE = ["#BF8A56", "#057272", "#996444", "#2F41BF", "#67A6E5"]
INDUSTRY_ORDER = ["Media & Entertainment", "Gaming & Lottery", "Publishing & Information", "Education"]


def _json(name, default):
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def _csv(name):
    p = DATA / name
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() and not l.strip().startswith("#")), None)
    return list(csv.DictReader(lines[start:])) if start is not None else []


def _f(v):
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def settings():
    """Plain key=value lines from settings.txt (for the SITE_ links)."""
    s = {}
    p = ROOT / "settings.txt"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                s[k.strip()] = v.strip()
    return s


def site_links():
    s = settings()
    return [(n, s.get(k)) for n, k in (("Interactive (Streamlit)", "SITE_STREAMLIT"),
                                       ("Interactive backup (Hugging Face)", "SITE_HUGGINGFACE"),
                                       ("Fast copy (Cloudflare)", "SITE_CLOUDFLARE")) if s.get(k)]


def company_colors():
    """The same fixed colour per company as the Streamlit app (read from app.py so they never drift)."""
    try:
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        block = re.search(r"COMPANY_COLORS\s*=\s*\{(.*?)\}", text, re.S).group(1)
        return dict(re.findall(r"\"([^\"]+)\"\s*:\s*\"(#[0-9A-Fa-f]{6})\"", block))
    except Exception:  # noqa: BLE001
        return {}


def money(v, cur="USD"):
    """$22.5bn / €1.4bn / £950m from a value in millions."""
    if v is None:
        return "—"
    s = SYMBOL.get(cur, (cur or "") + " ")
    sign = "-" if v < 0 else ""
    v = abs(v)
    return f"{sign}{s}{v / 1000:,.1f}bn" if v >= 1000 else f"{sign}{s}{v:,.0f}m"


def pct(v, signed=True):
    if v is None:
        return "—"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def label_key(label):
    try:
        a, y = str(label).split()
        return (int(y), {"Q1": 3, "Q2": 6, "H1": 6, "Q3": 9, "Q4": 12, "H2": 12, "FY": 12}.get(a, 0))
    except Exception:  # noqa: BLE001
        return (0, 0)


def build():
    with open(ROOT / "companies.csv", encoding="utf-8-sig", newline="") as fh:
        comps = [r for r in csv.DictReader(fh) if (r.get("name") or "").strip() and not r["name"].startswith("#")]
    colors = company_colors()
    fx = {(r["currency"], r["month"]): _f(r["usd_per_unit"]) for r in _csv("fx.csv") if r.get("month")}

    def usd(cur, period_end, months):
        if cur in ("USD", "", None):
            return 1.0
        end = date.fromisoformat(str(period_end)[:10])
        vals = []
        for k in range(int(months or 3)):
            y, m = end.year, end.month - k
            while m <= 0:
                y, m = y - 1, m + 12
            if fx.get((cur, f"{y}-{m:02d}")):
                vals.append(fx[(cur, f"{y}-{m:02d}")])
        if vals:
            return sum(vals) / len(vals)
        known = sorted((m, v) for (c, m), v in fx.items() if c == cur and v)
        return known[-1][1] if known else None

    # quarterly / half-year numbers per company (financials.csv is already merged by the agent)
    per = {}
    for r in _csv("financials.csv"):
        v = _f(r.get("value"))
        if v is None:
            continue
        months = int(_f(r.get("months")) or 3)
        k = (r["company"], months, str(r["period_end"])[:10])
        d = per.setdefault(k, {"label": r.get("period_label") or r["period_end"], "currency": (r.get("currency") or "USD").upper(),
                               "months": months, "period_end": str(r["period_end"])[:10]})
        d[r["metric"]] = v
    by = {}
    for (c, m, pe), d in per.items():
        by.setdefault(c, []).append(d)

    ins = _json("insights.json", {})
    status = _json("status.json", {})
    sector = _json("sector.json", {})
    news = _json("news.json", {})
    runs = _json("run_log.json", [])
    pulse = _json("pulse_titles.json", {})
    industry = _json("industry_news.json", {})
    hist = _json("industry_history.json", {})
    market = {r["company"]: r for r in _csv("market.csv")}
    today = datetime.now(timezone.utc).date()

    rows, history = [], {}
    for i, c in enumerate(comps):
        n = (c.get("short_name") or c["name"]).strip()
        typ = (c.get("type") or "private").strip().lower()
        periods = sorted(by.get(n, []), key=lambda d: d["period_end"])
        q = [d for d in periods if d["months"] == 3]
        history[n] = [{"period": d["label"], "revenue": d.get("revenue"),
                       "op_margin": round(d["operating_income"] / d["revenue"] * 100, 1)
                       if d.get("operating_income") is not None and d.get("revenue") else None} for d in q][-10:]
        last = periods[-1] if periods else {}
        rev, cur = last.get("revenue"), last.get("currency") or (c.get("currency") or "USD").upper()
        yoy = None
        if last:
            same = [d for d in periods if d["months"] == last["months"]]
            step = max(1, 12 // last["months"])
            if len(same) > step and rev and same[-1 - step].get("revenue"):
                yoy = round((rev / same[-1 - step]["revenue"] - 1) * 100, 1)
        f = usd(cur, last["period_end"], last["months"]) if last else None
        it = ins.get(n) or {}
        st = status.get(n) or {}
        rel = st.get("release") or {}
        filed = rel.get("filed")
        recent = bool(filed) and (today - date.fromisoformat(filed[:10])).days <= 60
        read = recent and it.get("release_key") == rel.get("accession") and it.get("results_found")
        nxt = st.get("next_results") or (market.get(n) or {}).get("next_results")
        if typ == "private":
            state = "private"
        elif read:
            state = "out"
        elif nxt and str(nxt)[:10] >= today.isoformat():
            state = "due"
        elif recent:
            state = "out-unread"
        else:
            state = "wait"
        found = bool(it.get("results_found")) and it.get("mode") == "results"
        mk = market.get(n, {})
        rows.append({
            "company": n, "name": c["name"], "industry": (c.get("industry") or "Other").split("|")[0].strip(), "type": typ,
            "color": colors.get(n, SPARE[i % len(SPARE)]), "currency": cur, "note": c.get("note"),
            "period": last.get("label"), "revenue": rev, "revenue_usd": rev * f if rev is not None and f else None, "rev_yoy": yoy,
            "op_margin": round(last["operating_income"] / rev * 100, 1) if rev and last.get("operating_income") is not None else None,
            "net_income": last.get("net_income"),
            "state": state, "reported": state == "out", "filed": filed if state in ("out", "out-unread") else None,
            "due": str(nxt)[:10] if state == "due" else None, "release_url": rel.get("url") if state == "out" else None,
            "release_key": rel.get("accession"),
            "headline": it.get("headline"), "results_period": it.get("period_label") if found else None,
            "sentiment": it.get("sentiment"), "guidance_change": it.get("guidance_change") if found else None,
            "it_outlook": it.get("it_spend_outlook") or "Unclear", "it_reason": it.get("it_spend_reason"),
            "talking_points": [t for t in it.get("talking_points") or [] if t], "it_signals": it.get("it_signals") or [],
            "mcap_usd": _f(mk.get("market_cap_usd_m")), "ret_1y": _f(mk.get("return_1y")), "pe": _f(mk.get("pe_ttm")),
            "insight": it,
        })
    order = {n: k for k, n in enumerate(INDUSTRY_ORDER)}
    listed = [r for r in rows if r["type"] != "private"]
    yoy = [r["rev_yoy"] for r in listed if r["rev_yoy"] is not None]
    mar = [r["op_margin"] for r in listed if r["op_margin"] is not None]
    allnews = [{**it, "company": n} for n, items in news.items() for it in items]
    allnews.sort(key=lambda x: x.get("published") or "", reverse=True)
    last_run = (runs[0].get("finished") or runs[0].get("started") or "")[:16].replace("T", " ") + " UTC" if runs else "—"
    outlooks = {k: sum(1 for r in rows if r["it_outlook"] == k) for k in ("Expanding", "Stable", "Tightening")}
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "last_run": last_run,
        "rows": sorted(rows, key=lambda r: order.get(r["industry"], 9)), "history": history,
        "kpi": {"reported": sum(r["reported"] for r in listed), "listed": len(listed),
                "median_yoy": statistics.median(yoy) if yoy else None,
                "median_margin": statistics.median(mar) if mar else None, "outlooks": outlooks},
        "sector": sector, "news": allnews[:50], "pulse": pulse, "industry": industry, "industry_hist": hist,
    }


def pulse_groups(pulse):
    out = {}
    for g in ("Tracked companies", "Rest of industry"):
        ts = [t for t in (pulse or {}).get("titles", []) if t.get("group") == g]
        ai = [t["ai"] for t in ts if isinstance(t.get("ai"), dict)]
        sc = [a["audience_score"] for a in ai if isinstance(a.get("audience_score"), (int, float))]
        k = len(ai) or 1
        out[g] = {"titles": len(ts), "avg_score": round(statistics.mean(sc)) if sc else None,
                  "positive": round(sum(a.get("audience_sentiment") == "Positive" for a in ai) / k * 100) if ai else None}
    return out


def new_results(summary, state):
    """Companies whose results came out (and were read by the AI) and were not yet announced on a channel."""
    seen = set(state.get("announced", []))
    return [(f"{r['company']}|{r['release_key']}", r) for r in summary["rows"]
            if r["reported"] and f"{r['company']}|{r['release_key']}" not in seen]


def done_keys(summary):
    return {f"{r['company']}|{r['release_key']}" for r in summary["rows"] if r["reported"]}
