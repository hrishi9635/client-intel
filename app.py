"""
Industry Intelligence Dashboard
-------------------------------
Draws everything the agent saved in the "data" folder. You don't need to edit this file.
Start it on a laptop with:  python -m streamlit run app.py
"""
import csv
import html
import json
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).parent
DATA = ROOT / "data"
APP_VERSION = "client-intel v1.0"

st.set_page_config(page_title="Industry Intelligence Dashboard", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------- look & feel
INK, MUTED, LINE, PANEL, BG = "#16213E", "#5B6475", "#E4E7EC", "#FFFFFF", "#FFFFFF"
GOOD, BAD, WARN, ACCENT = "#0CA30C", "#D03B3B", "#C98500", "#2A78D6"
PEER = "#C3C7CF"
# one fixed colour per company, chosen so every pair stays apart for the three common types of colour blindness
# (checked by simulation); company names are always printed on charts as well
COMPANY_COLORS = {
    "Disney": "#2A78D6", "WBD / Skydance": "#260BE5", "Versant": "#09BFBF", "Cox": "#723B33", "LA Times": "#334B72",
    "Caesars": "#E5930B", "Bally's": "#992B07", "Light & Wonder": "#26997C", "Brightstar (IGT)": "#4F4499",
    "Wolters Kluwer": "#BF6409", "Scholastic": "#67A6E5", "Pearson": "#2F41BF",
    "NYU": "#057272", "SLU": "#BF8A56", "ACT": "#996444",
}
SPARE = ["#BF8A56", "#057272", "#996444", "#2F41BF", "#67A6E5"]
BENCH_STYLE = {"S&P 500": ("#52514E", "dash"), "STOXX Europe 600": ("#8A8F98", "dot")}
GROUP_COLORS = {"Tracked companies": "#2A78D6", "Rest of industry": "#E5930B"}
INDUSTRY_ORDER = ["Media & Entertainment", "Gaming & Lottery", "Publishing & Information", "Education"]

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:wght@500;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stDataFrame {{ font-family: 'Inter', system-ui, sans-serif; }}
[data-testid="stAppViewContainer"], [data-testid="stHeader"] {{ background: {BG}; }}
[data-testid="stAppViewContainer"] .stMarkdown p, [data-testid="stAppViewContainer"] li {{ color: {INK}; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1380px; }}
h1, h2, h3, h4, h5 {{ color: {INK} !important; letter-spacing: -0.015em; }}
h1 {{ font-family: 'Source Serif 4', Georgia, serif; font-weight: 600; }}
.lead {{ font-size: 1.08rem; color: {INK}; line-height: 1.55; max-width: 66rem; margin: -0.2rem 0 0.4rem; }}
.sub {{ color: {MUTED}; font-size: 0.84rem; }}
.kpi {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 14px; padding: 14px 16px; height: 100%; }}
.kpi .lab {{ color: {MUTED}; font-size: 0.74rem; font-weight: 500; text-transform: uppercase; letter-spacing: .04em; }}
.kpi .big {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 1.75rem; color: {INK}; line-height: 1.15; margin-top: 6px; }}
.kpi .note {{ color: {MUTED}; font-size: 0.76rem; margin-top: 4px; }}
.card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 14px; padding: 14px 16px; margin-bottom: 12px; }}
.card h4 {{ margin: 0 0 6px; font-size: 0.98rem; color: {INK}; display: flex; justify-content: space-between; gap: 8px; align-items: center; }}
.card p, .card li {{ font-size: 0.88rem; color: {INK}; line-height: 1.5; margin: 3px 0; }}
.card ul {{ margin: 2px 0 4px 1.1rem; padding: 0; }}
.card a {{ color: {ACCENT}; text-decoration: none; }}
.callout {{ border-left: 4px solid {ACCENT}; background: #F3F6FF; padding: 12px 16px; border-radius: 8px; color: {INK}; font-size: 1rem; margin: 6px 0 14px; }}
.pill {{ display: inline-block; font-size: 0.72rem; font-weight: 600; border-radius: 999px; padding: 2px 10px; border: 1px solid currentColor; white-space: nowrap; }}
.pos {{ color: {GOOD}; }} .neg {{ color: {BAD}; }} .mid {{ color: {WARN}; }} .na {{ color: {MUTED}; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 8px; }}
.chip {{ border: 1px solid {LINE}; background: {PANEL}; border-radius: 10px; padding: 6px 10px; font-size: 0.82rem; color: {INK}; }}
.chip b {{ font-weight: 600; }}
.dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; vertical-align: middle; }}
.tag {{ display:inline-block; background:#EEF2F8; color:{INK}; border-radius:6px; padding:1px 7px; font-size:0.74rem; margin:2px 4px 2px 0; }}
.tag.hl {{ background:#FFF3D6; border:1px solid #E5930B; }}
.news a {{ color: {INK}; text-decoration: none; font-weight: 500; }}
.news a:hover {{ text-decoration: underline; }}
.news div {{ padding: 8px 0; border-bottom: 1px solid {LINE}; font-size: 0.9rem; }}
.news span {{ color: {MUTED}; font-size: 0.78rem; }}
.title-card {{ display:flex; gap:12px; }}
.title-card img {{ width:84px; height:126px; object-fit:cover; border-radius:8px; border:1px solid {LINE}; flex-shrink:0; }}
.title-card .noimg {{ width:84px; height:126px; border-radius:8px; background:#EEF0F4; flex-shrink:0; display:flex; align-items:center; justify-content:center; color:{MUTED}; font-size:0.7rem; }}
.scores {{ font-size:0.8rem; color:{MUTED}; margin:2px 0 4px; }}
.caveat {{ color:{MUTED}; font-size:0.82rem; font-style: italic; margin: 0 0 10px; }}
section[data-testid="stSidebar"] {{ background: #F7F8FB; }}
section[data-testid="stSidebar"] * {{ color: {INK}; }}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- small helpers
def esc(x):
    return html.escape(str(x)) if x is not None else ""


def isna(v):
    try:
        return v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v)
    except (TypeError, ValueError):
        return False


def tone_class(word):
    w = (word or "").lower()
    if w in ("positive", "raised", "introduced", "expanding", "hit", "high", "up"):
        return "pos"
    if w in ("negative", "cut", "tightening", "under-performing", "down"):
        return "neg"
    if w in ("mixed", "neutral", "retained", "stable", "on track", "medium", "flat"):
        return "mid"
    return "na"


def pill(word, missing="—"):
    if not word:
        return f"<span class='pill na'>{esc(missing)}</span>"
    return f"<span class='pill {tone_class(word)}'>{esc(word)}</span>"


SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$"}


def money(v, cur="USD"):
    """v is in millions."""
    if isna(v):
        return "—"
    s = SYMBOL.get(cur, cur + " ")
    sign = "−" if v < 0 else ""
    v = abs(v)
    if v >= 1000:
        return f"{sign}{s}{v / 1000:,.2f} bn"
    return f"{sign}{s}{v:,.0f} m"


def pct(v, signed=True):
    if isna(v):
        return "—"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def num(v, fmt="{:,.1f}"):
    return "—" if isna(v) else fmt.format(v)


def nice_date(d, fmt="%d %b %Y"):
    if not d:
        return "—"
    try:
        return pd.Timestamp(str(d)[:10]).strftime(fmt)
    except Exception:  # noqa: BLE001
        return str(d)[:10]


def style(fig, height=380, title=None, legend=True):
    fig.update_layout(
        height=height, title=dict(text=title, font=dict(size=15, color=INK)) if title else None,
        margin=dict(l=8, r=16, t=48 if title else 16, b=8), paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="Inter, system-ui, sans-serif", color=INK, size=12),
        hoverlabel=dict(bgcolor="white", font_size=12), showlegend=legend,
        legend=dict(orientation="h", yanchor="top", y=-0.14, x=0, title=None),
    )
    fig.update_xaxes(showgrid=False, linecolor=LINE, tickcolor=LINE)
    fig.update_yaxes(gridcolor="#EEF0F4", zerolinecolor="#C9CED6", linecolor=LINE)
    return fig


def show_chart(fig):
    try:
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    except Exception:  # noqa: BLE001  (older Streamlit versions)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def show_table(df, fmt=None, **kw):
    """Show a table with a dash, never 'None' or 'nan', where a value wasn't found.
    Numbers keep their numeric type (so columns still sort properly); only their display is formatted."""
    df = df.copy().reset_index(drop=True)
    fmt = dict(fmt or {})
    for c in df.columns:
        if pd.api.types.is_bool_dtype(df[c]):
            df[c] = df[c].map({True: "yes", False: "no"})
        elif pd.api.types.is_numeric_dtype(df[c]):
            if c not in fmt:
                vals = df[c].dropna()
                fmt[c] = "{:,.0f}" if len(vals) and (vals % 1 == 0).all() else "{:,.1f}"
        else:
            df[c] = df[c].astype(object).where(df[c].notna(), None)
            df[c] = df[c].map(lambda x: "—" if x is None or str(x).strip() in ("None", "nan", "NaN", "", "NaT", "[]") else x)
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    shown = df
    if num_cols:
        try:
            shown = df.style.format({c: fmt[c] for c in num_cols}, na_rep="—")
        except Exception:  # noqa: BLE001  (no styling available: fall back to text)
            for c in num_cols:
                df[c] = df[c].map(lambda v, f=fmt[c]: "—" if pd.isna(v) else f.format(v))
            shown = df
    try:
        st.dataframe(shown, width="stretch", hide_index=True, **kw)
    except TypeError:  # older Streamlit versions
        st.dataframe(shown, use_container_width=True, hide_index=True, **kw)


def kpi(col, label, value, note=""):
    col.markdown(f"<div class='kpi'><div class='lab'>{esc(label)}</div><div class='big'>{esc(value)}</div>"
                 f"<div class='note'>{esc(note)}</div></div>", unsafe_allow_html=True)


def page_header(title, sub=None):
    st.title(title)
    if sub:
        st.markdown(f"<p class='sub'>{esc(sub)}</p>", unsafe_allow_html=True)


def link(url, text):
    if not url:
        return esc(text)
    return f"<a href='{esc(url)}' target='_blank' rel='noopener'>{esc(text)}</a>"


def news_list(items, highlight=None, limit=30):
    if not items:
        return "<p class='sub'>Nothing yet.</p>"
    rows = []
    for i in items[:limit]:
        tags = "".join(f"<span class='tag{' hl' if highlight else ''}'>{esc(m)}</span>" for m in (i.get("mentions") or []))
        rows.append(f"<div>{'📄 ' if i.get('official') else ''}{link(i.get('link'), i.get('title'))} {tags}<br>"
                    f"<span>{esc(i.get('source'))} · {esc(nice_date(i.get('published')))}</span></div>")
    return "<div class='news'>" + "".join(rows) + "</div>"


def lines_with_focus(fig, frame, xcol, ycol, focus, names, fmt=",.1f", suffix=""):
    """Every company as a thin grey line, the chosen one in its colour on top, benchmarks dashed.
    Names are written at the end of the highlighted and benchmark lines."""
    order = [n for n in names if n != focus] + ([focus] if focus in names else [])
    for n in order:
        g = frame[frame["_name"] == n].dropna(subset=[ycol])
        if g.empty:
            continue
        on, bench = n == focus, n in BENCH_STYLE
        color = BENCH_STYLE[n][0] if bench else (COLOR.get(n, ACCENT) if on else PEER)
        fig.add_trace(go.Scatter(
            x=g[xcol], y=g[ycol], name=n, mode="lines+markers" if on and len(g) < 30 else "lines",
            line=dict(color=color, width=3 if on else (1.8 if bench else 1.3), dash=BENCH_STYLE[n][1] if bench else "solid"),
            marker=dict(size=8, color=color, line=dict(color="white", width=2)) if on else None,
            opacity=1 if (on or bench) else 0.75,
            hovertemplate=f"<b>{esc(n)}</b> · %{{x}}: %{{y:{fmt}}}{suffix}<extra></extra>"))
        if on or bench:
            last = g.tail(1)
            fig.add_annotation(x=last[xcol].iloc[0], y=last[ycol].iloc[0], text=f"<b>{esc(n)}</b>" if on else esc(n),
                               showarrow=False, xanchor="left", xshift=8, font=dict(color=INK if on else MUTED, size=12))
    return fig


# ---------------------------------------------------------------- data
def stamp():
    """Changes whenever any data file changes, so the cache below reloads fresh data."""
    files = [p for p in sorted(DATA.glob("*")) if p.is_file()] + [ROOT / "companies.csv"]
    return tuple((p.name, p.stat().st_mtime, p.stat().st_size) for p in files if p.exists())


@st.cache_data(ttl=600, show_spinner=False)
def load(data_version):
    def rj(name, default):
        p = DATA / name
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
        except (json.JSONDecodeError, OSError):
            return default

    def rc(name):
        p = DATA / name
        if not p.exists() or p.stat().st_size == 0:
            return pd.DataFrame()
        lines = p.read_text(encoding="utf-8-sig").splitlines()
        start = next((i for i, l in enumerate(lines) if l.strip() and not l.strip().startswith("#")), None)
        if start is None:
            return pd.DataFrame()
        import io
        try:
            return pd.read_csv(io.StringIO("\n".join(lines[start:])))
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    with open(ROOT / "companies.csv", encoding="utf-8-sig", newline="") as fh:
        comps = [r for r in csv.DictReader(fh) if (r.get("name") or "").strip() and not r["name"].startswith("#")]
    return {
        "companies": comps, "fin": rc("financials.csv"), "market": rc("market.csv"), "prices": rc("prices.csv"),
        "fx": rc("fx.csv"), "insights": rj("insights.json", {}), "sector": rj("sector.json", {}),
        "news": rj("news.json", {}), "status": rj("status.json", {}), "runs": rj("run_log.json", []),
        "pulse": rj("pulse_titles.json", {}), "industry": rj("industry_news.json", {}),
        "industry_hist": rj("industry_history.json", {}), "feeds": rj("feed_status.json", []),
    }


D = load(stamp())
COMPS = D["companies"]
ORDER = [(c.get("short_name") or c["name"]).strip() for c in COMPS]
INFO = {(c.get("short_name") or c["name"]).strip(): c for c in COMPS}
NAMES = {n: INFO[n]["name"] for n in ORDER}
COLOR = {}
for i, n in enumerate(ORDER):
    COLOR[n] = COMPANY_COLORS.get(n, SPARE[i % len(SPARE)])
INDUSTRY = {n: [x.strip() for x in (INFO[n].get("industry") or "Other").split("|")] for n in ORDER}
TYPE = {n: (INFO[n].get("type") or "private").strip().lower() for n in ORDER}
LISTED = [n for n in ORDER if TYPE[n] != "private"]
INDUSTRIES = [i for i in INDUSTRY_ORDER if any(i in v for v in INDUSTRY.values())] + sorted(
    {i for v in INDUSTRY.values() for i in v} - set(INDUSTRY_ORDER))
INS, SECTOR, STATUS = D["insights"], D["sector"], D["status"]
TODAY = date.today()

nothing_yet = D["fin"].empty and not INS and not D["pulse"] and not D["industry"]

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### 📊 Industry Intelligence")
    st.markdown("<div class='sub'>Media · Gaming & Lottery · Publishing · Education</div>", unsafe_allow_html=True)
    page = st.radio("Go to", ["Overview", "Industry view", "Company deep-dive", "IT opportunity signals",
                              "Audience pulse", "Industry news", "Financial trends", "Share price & valuation",
                              "News", "About & data"], label_visibility="collapsed")
    st.markdown("---")
    money_mode = st.radio("Show money in", ["Each company's own currency", "US dollars"], index=0,
                          help="US dollars use the average exchange rate of each period.")
    USD = money_mode == "US dollars"
    if D["runs"]:
        st.markdown(f"<div class='sub'>Last agent run: {esc((D['runs'][0].get('finished') or '')[:16].replace('T', ' '))} UTC</div>",
                    unsafe_allow_html=True)
    st.markdown("<div class='sub'>Free & open source: SEC EDGAR, Yahoo Finance, Google/Bing News, TMDB, OMDb, "
                "an open AI model, Streamlit. Not investment advice.</div>", unsafe_allow_html=True)

if nothing_yet:
    st.title("Industry Intelligence Dashboard")
    st.info("No data yet. The agent fills this in on its first run: on GitHub, open **Actions → Run the agent → "
            "Run workflow**. When it finishes (about 15–30 minutes), refresh this page.")
    st.stop()


# ---------------------------------------------------------------- financial table (one row per company and period)
def fx_table():
    fx = D["fx"]
    if fx.empty:
        return {}
    return {(r.currency, str(r.month)): float(r.usd_per_unit) for r in fx.itertuples()}


FX = fx_table()


def usd_factor(cur, period_end, months):
    """Average US-dollar value of one unit of the currency over the period's months."""
    if cur in ("USD", "", None) or isna(cur):
        return 1.0
    end = pd.Timestamp(str(period_end)[:10])
    vals = []
    for k in range(int(months or 3)):
        m = (end - pd.DateOffset(months=k)).strftime("%Y-%m")
        if (cur, m) in FX:
            vals.append(FX[(cur, m)])
    if vals:
        return sum(vals) / len(vals)
    known = sorted((m, v) for (c, m), v in FX.items() if c == cur)
    return known[-1][1] if known else None


def label_key(label):
    """Sort 'Q3 2026', 'H1 2026' in time order."""
    try:
        a, y = str(label).split()
        return (int(y), {"Q1": 3, "Q2": 6, "H1": 6, "Q3": 9, "Q4": 12, "H2": 12, "FY": 12}.get(a, 0))
    except Exception:  # noqa: BLE001
        return (0, 0)


def latest_fx(cur):
    if cur in ("USD", "", None):
        return 1.0
    known = sorted((m, v) for (c, m), v in FX.items() if c == cur)
    return known[-1][1] if known else None


fin = D["fin"].copy()
if not fin.empty and {"company", "period_end", "metric", "value"} <= set(fin.columns):
    fin = fin[fin["company"].isin(ORDER)]
    fin["value"] = pd.to_numeric(fin["value"], errors="coerce")
    fin["months"] = pd.to_numeric(fin.get("months", 3), errors="coerce").fillna(3).astype(int)
    if "currency" not in fin:
        fin["currency"] = "USD"
    fin["period_end"] = fin["period_end"].astype(str).str[:10]
    fin = fin.dropna(subset=["value"])
    if "period_label" not in fin:
        fin["period_label"] = None
    fin["period_label"] = fin["period_label"].where(fin["period_label"].notna(), fin["period_end"]).astype(str)
    fin["currency"] = fin["currency"].astype(str).str.upper().replace({"NAN": "USD", "": "USD"})
    if "source" not in fin:
        fin["source"] = ""
    fin["source"] = fin["source"].fillna("").astype(str)
    src = fin.pivot_table(index=["company", "period_end"], columns="metric", values="source", aggfunc="first")
    wide = fin.pivot_table(index=["company", "period_end", "period_label", "months", "currency"], columns="metric",
                           values="value", aggfunc="last").reset_index()
    for m in ("revenue", "operating_income", "net_income"):
        if m not in wide:
            wide[m] = float("nan")
    wide["rev_source"] = [src.loc[(c, p), "revenue"] if (c, p) in src.index and "revenue" in src else None
                          for c, p in zip(wide["company"], wide["period_end"])]
    wide["fx"] = [usd_factor(c, p, m) for c, p, m in zip(wide["currency"], wide["period_end"], wide["months"])]
    if USD:
        for m in ("revenue", "operating_income", "net_income"):
            wide[m] = wide[m] * wide["fx"]
        wide["show_cur"] = "USD"
    else:
        wide["show_cur"] = wide["currency"]
    wide["rev_usd"] = wide["revenue"] if USD else wide["revenue"] * wide["fx"]
    wide = wide.sort_values(["company", "months", "period_end"])
    wide["op_margin"] = wide["operating_income"] / wide["revenue"] * 100
    wide["net_margin"] = wide["net_income"] / wide["revenue"] * 100
    g = wide.groupby(["company", "months"])["revenue"]
    wide["rev_pop"] = g.pct_change(fill_method=None) * 100
    wide["rev_yoy"] = float("nan")
    for (c, m), idx in wide.groupby(["company", "months"]).groups.items():
        step = max(1, 12 // int(m))
        wide.loc[idx, "rev_yoy"] = wide.loc[idx, "revenue"].pct_change(step, fill_method=None).values * 100
        wide.loc[idx, "ni_yoy"] = wide.loc[idx, "net_income"].pct_change(step, fill_method=None).values * 100
    wide = wide.sort_values(["company", "period_end"])
    latest = wide.groupby("company").tail(1).set_index("company")
else:
    wide, latest = pd.DataFrame(), pd.DataFrame()

mkt = D["market"].copy()
if not mkt.empty:
    mkt = mkt[mkt["company"].isin(ORDER)].set_index("company")


def lv(name, col):
    try:
        v = latest.loc[name, col]
        return None if isna(v) else (float(v) if not isinstance(v, str) else v)
    except (KeyError, TypeError, ValueError):
        return None


def mv(name, col):
    try:
        v = mkt.loc[name, col]
        return None if isna(v) else v
    except (KeyError, TypeError, ValueError):
        return None


def cur_of(name):
    return "USD" if USD else (INFO[name].get("currency") or "USD").strip().upper()


def ins_of(name):
    return INS.get(name) or {}


def results_state(name):
    """('out', date) when an official results release came out in the last 60 days, ('due', date) or ('wait', None)."""
    if TYPE.get(name) == "private":
        return "private", None
    st_ = STATUS.get(name) or {}
    rel = st_.get("release") or {}
    ins = ins_of(name)
    filed = rel.get("filed")
    if filed and (TODAY - date.fromisoformat(filed[:10])).days <= 60 and ins.get("release_key") == rel.get("accession") \
            and ins.get("results_found"):
        return "out", filed
    nxt = st_.get("next_results") or mv(name, "next_results")
    if nxt and str(nxt)[:10] >= TODAY.isoformat():
        return "due", str(nxt)[:10]
    if filed and (TODAY - date.fromisoformat(filed[:10])).days <= 60:
        return "out-unread", filed
    return "wait", None


# ---------------------------------------------------------------- scorecard (shared)
def scorecard():
    rows = []
    for n in ORDER:
        ins = ins_of(n)
        res = ins.get("results_found") and ins.get("mode") == "results"
        cur = cur_of(n)
        mc = mv(n, "market_cap_usd_m")
        rows.append({
            "Company": n, "Industry": INDUSTRY[n][0], "Type": {"sec": "Listed (SEC)", "listed_other": "Listed (EU)",
                                                              "private": "Private"}.get(TYPE[n], TYPE[n]),
            "Period": lv(n, "period_label"),
            "Revenue": money(lv(n, "revenue"), cur) if lv(n, "revenue") is not None else None,
            "_rev_usd": lv(n, "rev_usd"),
            "Revenue YoY %": lv(n, "rev_yoy"), "Op. margin %": lv(n, "op_margin"),
            "Net income": money(lv(n, "net_income"), cur) if lv(n, "net_income") is not None else None,
            "Guidance": ins.get("guidance_change") if res else None,
            "Mood": ins.get("sentiment"),
            "IT spend outlook": ins.get("it_spend_outlook"),
            "Market cap ($ bn)": round(float(mc) / 1000, 1) if mc is not None else None,
            "1Y share %": mv(n, "return_1y"),
        })
    return pd.DataFrame(rows)


METRIC_NAMES = {"revenue_m": "revenue (m)", "revenue_growth_yoy_pct": "revenue growth %", "operating_income_m": "operating income (m)",
                "operating_margin_pct": "operating margin %", "net_income_m": "net income (m)", "eps": "EPS"}
SC_FMT = {"Revenue YoY %": "{:+.1f}", "Op. margin %": "{:.1f}", "Market cap ($ bn)": "{:,.1f}", "1Y share %": "{:+.1f}"}


def it_signals_flat(industry=None):
    rows = []
    for n in ORDER:
        if industry and industry not in INDUSTRY[n]:
            continue
        ins = ins_of(n)
        for s in ins.get("it_signals") or []:
            rows.append({"Company": n, "Industry": INDUSTRY[n][0], "Signal": s.get("type"), "What was said": s.get("detail"),
                         "Date": (s.get("published") or ins.get("signals_at") or ins.get("analysed_at") or "")[:10],
                         "Source": s.get("source"), "Link": s.get("link")})
    return pd.DataFrame(rows)


# ================================================================ pages
if page == "Overview":
    page_header("Industry Intelligence · Media, Gaming, Publishing & Education",
                f"{len(ORDER)} organisations tracked as industry players · {len(LISTED)} listed · official results "
                "first (SEC EDGAR, company releases), Yahoo Finance for history, news read by an AI agent")
    if SECTOR.get("headline"):
        st.markdown(f"<p class='lead'>{esc(SECTOR['headline'])}</p>", unsafe_allow_html=True)
    sc = scorecard()
    states = {n: results_state(n) for n in ORDER}
    out_n = sum(1 for n in LISTED if states[n][0] == "out")
    yoy = [v for v in sc["Revenue YoY %"] if not isna(v)]
    mar = [v for v in sc["Op. margin %"] if not isna(v)]
    outl = [ins_of(n).get("it_spend_outlook") for n in ORDER]
    p = D["prices"]
    spx = p[p["company"] == "S&P 500"].sort_values("date")["close"] if not p.empty else pd.Series(dtype=float)
    k = st.columns(5)
    kpi(k[0], "Results out (last 60 days)", f"{out_n}/{len(LISTED)}", "listed companies, official releases only")
    kpi(k[1], "Median revenue growth", pct(statistics.median(yoy)) if yoy else "—", "latest period vs a year earlier")
    kpi(k[2], "Median operating margin", pct(statistics.median(mar), False) if mar else "—", "latest period")
    kpi(k[3], "IT spend outlook", f"{outl.count('Expanding')} ↑ · {outl.count('Stable')} → · {outl.count('Tightening')} ↓",
        "expanding · stable · tightening")
    kpi(k[4], "S&P 500, 1 year", pct((spx.iloc[-1] / spx.iloc[0] - 1) * 100) if len(spx) > 1 else "—", "benchmark index")

    st.markdown("#### Results-season tracker")

    def chip(n):
        s, d = states[n]
        dot = f"<span class='dot' style='background:{COLOR[n]}'></span>"
        if s == "out":
            tag = f"<span class='pos'>✓ results out {esc(nice_date(d, '%d %b'))}</span>"
        elif s == "out-unread":
            tag = f"<span class='mid'>release filed {esc(nice_date(d, '%d %b'))} · being read</span>"
        elif s == "due":
            tag = f"<span class='na'>due {esc(nice_date(d, '%d %b'))}</span>"
        elif s == "private":
            tag = "<span class='na'>private · news only</span>"
        else:
            tag = "<span class='na'>awaiting date</span>"
        return f"<div class='chip'>{dot}<b>{esc(n)}</b> · {tag}</div>"
    for ind in INDUSTRIES:
        members = [n for n in ORDER if INDUSTRY[n][0] == ind]
        if members:
            st.markdown(f"<div class='sub' style='margin-top:6px'>{esc(ind)}</div><div class='chips'>"
                        + "".join(chip(n) for n in members) + "</div>", unsafe_allow_html=True)

    st.markdown("#### Scorecard")
    st.caption("Latest reported period per company (labelled by calendar quarter or half-year). Numbers: SEC filings and "
               "official releases first, Yahoo Finance otherwise. Guidance, mood and IT outlook are read by the AI from "
               "official releases and news. Click a column to sort. '—' = not available.")
    show_table(sc.drop(columns=["_rev_usd"]), fmt=SC_FMT)

    c1, c2 = st.columns([1.15, 1])
    with c1:
        d = sc.dropna(subset=["Op. margin %", "Revenue YoY %"]).copy()
        if d.empty:
            st.caption("Growth-vs-margin chart appears once two periods of financials are available.")
        else:
            size = d["Market cap ($ bn)"].fillna(d["Market cap ($ bn)"].median() if d["Market cap ($ bn)"].notna().any() else 1)
            fig = go.Figure(go.Scatter(
                x=d["Revenue YoY %"], y=d["Op. margin %"], mode="markers+text", text=d["Company"], textposition="top center",
                marker=dict(size=size, sizemode="area", sizeref=2.0 * max(float(size.max()), 1) / (50 ** 2), sizemin=8,
                            color=[COLOR.get(n, ACCENT) for n in d["Company"]], opacity=0.85, line=dict(color="white", width=2)),
                customdata=d[["Market cap ($ bn)", "Period"]],
                hovertemplate="<b>%{text}</b> (%{customdata[1]})<br>Growth %{x:+.1f}%<br>Margin %{y:.1f}%<br>"
                              "Market cap $%{customdata[0]:,.1f} bn<extra></extra>"))
            fig.add_vline(x=0, line=dict(color=LINE, width=1))
            fig.update_xaxes(title="Revenue growth vs a year earlier (%)", ticksuffix="%")
            fig.update_yaxes(title="Operating margin (%)", ticksuffix="%")
            show_chart(style(fig, 430, "Growth vs margin (bubble = market value)", legend=False))
    with c2:
        d = sc.dropna(subset=["_rev_usd"]).sort_values("_rev_usd")
        if not d.empty:
            fig = go.Figure(go.Bar(x=d["_rev_usd"], y=d["Company"], orientation="h",
                                   marker=dict(color=[COLOR.get(n, ACCENT) for n in d["Company"]], cornerradius=4),
                                   text=[money(v) + f" · {pp}" for v, pp in zip(d["_rev_usd"], d["Period"])],
                                   textposition="outside", cliponaxis=False,
                                   hovertemplate="%{y}: $%{x:,.0f} m<extra></extra>"))
            fig.update_xaxes(showticklabels=False, range=[0, float(d["_rev_usd"].max()) * 1.45])
            show_chart(style(fig, 430, "Revenue, latest period (in US$ for comparison)", legend=False))

    st.markdown("#### Top IT signals this week")
    sig = it_signals_flat()
    if not sig.empty:
        week = (TODAY - timedelta(days=7)).isoformat()
        recent = sig[sig["Date"] >= week]
        if recent.empty:
            recent = sig.sort_values("Date", ascending=False).head(6)
            st.caption("Nothing new in the last 7 days; showing the most recent signals.")
        recent = recent.sort_values("Date", ascending=False).head(6)
        cols = st.columns(3)
        for i, r in enumerate(recent.to_dict("records")):
            src_html = link(r["Link"], r["Source"] or "source") if r.get("Link") else esc(r.get("Source") or "")
            cols[i % 3].markdown(
                f"<div class='card'><h4><span><span class='dot' style='background:{COLOR.get(r['Company'], ACCENT)}'></span>"
                f"{esc(r['Company'])}</span><span class='tag'>{esc(r['Signal'])}</span></h4><p>{esc(r['What was said'])}</p>"
                f"<p class='sub'>{src_html} · {esc(nice_date(r['Date']))}</p></div>",
                unsafe_allow_html=True)
    else:
        st.caption("Signals appear after the agent's first AI analysis.")

elif page == "Industry view":
    page_header("Industry view", "Written by the AI agent from every company's latest results and news, grouped by industry. "
                "Check key points against the sources on each company's page.")
    if not SECTOR:
        st.info("The industry view appears after the agent has analysed the companies (first run).")
    else:
        st.markdown(f"<div class='callout'><b>{esc(SECTOR.get('headline'))}</b><br>{esc(SECTOR.get('summary'))}</div>",
                    unsafe_allow_html=True)
        st.markdown(f"<p class='sub'>Written {esc(nice_date(SECTOR.get('written_at')))}</p>", unsafe_allow_html=True)
        inds = SECTOR.get("industries") or []
        for ind in sorted(inds, key=lambda x: INDUSTRY_ORDER.index(x.get("industry")) if x.get("industry") in INDUSTRY_ORDER else 9):
            st.markdown(f"### {esc(ind.get('industry'))} &nbsp;{pill(ind.get('mood'))}", unsafe_allow_html=True)
            st.markdown(f"<p class='lead' style='font-size:1rem'>{esc(ind.get('summary'))}</p>", unsafe_allow_html=True)
            c1, c2, c3 = st.columns([1, 1, 1.1])
            with c1:
                st.markdown("<div class='card'><h4>Leading <span class='pill pos'>leaders</span></h4><ul>" + "".join(
                    f"<li><b>{esc(x.get('company'))}</b>: {esc(x.get('why'))}</li>" for x in ind.get("leaders") or [])
                    + "</ul></div>" if ind.get("leaders") else "<div class='card'><h4>Leading</h4><p class='sub'>—</p></div>",
                    unsafe_allow_html=True)
            with c2:
                st.markdown("<div class='card'><h4>Under pressure <span class='pill neg'>laggards</span></h4><ul>" + "".join(
                    f"<li><b>{esc(x.get('company'))}</b>: {esc(x.get('why'))}</li>" for x in ind.get("laggards") or [])
                    + "</ul></div>" if ind.get("laggards") else "<div class='card'><h4>Under pressure</h4><p class='sub'>—</p></div>",
                    unsafe_allow_html=True)
            with c3:
                st.markdown(f"<div class='card'><h4>IT spend outlook {pill(ind.get('it_outlook'))}</h4>"
                            f"<p>{esc(ind.get('it_note') or '—')}</p></div>", unsafe_allow_html=True)
            th = ind.get("themes") or []
            if th:
                cols = st.columns(min(3, len(th)))
                for i, t in enumerate(th[:6]):
                    cols[i % len(cols)].markdown(
                        f"<div class='card'><h4>{esc(t.get('title'))}</h4><p>{esc(t.get('detail'))}</p>"
                        f"<p class='sub'>{esc(', '.join(t.get('companies') or []))}</p></div>", unsafe_allow_html=True)
        if SECTOR.get("watch_next"):
            st.markdown("#### What to watch next")
            st.markdown("".join(f"- {esc(w)}\n" for w in SECTOR["watch_next"]))
    st.markdown("#### Company headlines")
    rows = []
    for n in ORDER:
        ins = ins_of(n)
        rows.append({"Company": n, "Industry": INDUSTRY[n][0], "Latest": ins.get("period_label") if ins.get("results_found") else "news",
                     "Headline": ins.get("headline"), "Guidance": ins.get("guidance_change") if ins.get("results_found") else None,
                     "Mood": ins.get("sentiment"), "IT outlook": ins.get("it_spend_outlook")})
    show_table(pd.DataFrame(rows), column_config={"Headline": st.column_config.TextColumn(width="large")})

elif page == "Company deep-dive":
    name = st.selectbox("Company", ORDER, format_func=lambda n: NAMES.get(n, n))
    ins, info, stt = ins_of(name), INFO[name], STATUS.get(name) or {}
    is_private = TYPE[name] == "private"
    tick = mv(name, "ticker") or (info.get("ticker") or "").split("|")[0]
    sub = f"{' · '.join(INDUSTRY[name])} · " + ("Private / non-profit · news and signals only" if is_private else f"Ticker {tick}")
    page_header(NAMES[name], sub)
    if info.get("note"):
        st.markdown(f"<p class='sub'>ℹ️ {esc(info['note'])}</p>", unsafe_allow_html=True)
    rel = stt.get("release") or {}
    if rel:
        st.markdown(f"<p class='sub'>📄 Latest official results release: {link(rel.get('url'), rel.get('title') or rel.get('form'))} "
                    f"· {esc(rel.get('form'))} · filed {esc(nice_date(rel.get('filed')))}</p>", unsafe_allow_html=True)
    s, d = results_state(name)
    if s == "due":
        st.markdown(f"<p class='sub'>🗓️ Next results expected {esc(nice_date(d))} (Yahoo Finance calendar)</p>", unsafe_allow_html=True)
    if info.get("report_url"):
        st.markdown(f"<p class='sub'>📘 {link(info['report_url'], 'Latest annual financial statements')}</p>", unsafe_allow_html=True)
    if ins.get("headline"):
        st.markdown(f"<div class='callout'>{esc(ins['headline'])} &nbsp;{pill(ins.get('sentiment'))}"
                    f"<br><span class='sub'>{esc(ins.get('sentiment_reason'))}"
                    f"{' · results for ' + esc(ins.get('period_label')) if ins.get('results_found') and ins.get('period_label') else ''}"
                    f"{' (' + esc(ins.get('fiscal_label')) + ')' if ins.get('results_found') and ins.get('fiscal_label') else ''}"
                    f" · analysed {esc(nice_date(ins.get('analysed_at')))}</span></div>", unsafe_allow_html=True)

    if not is_private:
        cur = cur_of(name)
        peers = [n for n in LISTED if INDUSTRY[n][0] == INDUSTRY[name][0]]
        peers = peers if len(peers) >= 3 else LISTED

        def rank(col, value):
            vals = {n: lv(n, col) for n in peers}
            vals = {k: v for k, v in vals.items() if v is not None}
            if value is None or name not in vals or len(vals) < 3:
                return ""
            r = sorted(vals.values(), reverse=True).index(vals[name]) + 1
            return f" · #{r} of {len(vals)} peers"

        rev_src = lv(name, "rev_source") or "—"
        m = ins.get("metrics") or {} if ins.get("results_found") else {}
        tiles = [
            ("Revenue", money(lv(name, "revenue"), cur), f"{lv(name, 'period_label') or ''} · {rev_src}{rank('rev_usd', lv(name, 'rev_usd'))}"),
            ("Revenue growth", pct(lv(name, "rev_yoy")), "vs a year earlier" + rank("rev_yoy", lv(name, "rev_yoy"))),
            ("Operating margin", pct(lv(name, "op_margin"), False), "latest period" + rank("op_margin", lv(name, "op_margin"))),
            ("Net income", money(lv(name, "net_income"), cur), "latest period" + rank("net_income", lv(name, "net_income"))),
            ("Guidance", (ins.get("guidance_change") or "—").capitalize() if ins.get("results_found") else "—",
             "from the official release" if ins.get("results_found") else "no results analysed yet"),
            ("Market value", money(mv(name, "market_cap_usd_m")), f"US$ · share price {num(mv(name, 'price'), '{:,.2f}')} "
                                                                   f"{mv(name, 'price_currency') or ''}"),
            ("P/E (trailing)", num(mv(name, "pe_ttm")), "market value ÷ last 12 months' net income"),
            ("IT spend outlook", ins.get("it_spend_outlook") or "—", "AI reading of releases & news"),
        ]
        for row in (tiles[:4], tiles[4:]):
            cols = st.columns(4)
            for c, (lab, val, note) in zip(cols, row):
                kpi(c, lab, val, note)
            st.write("")
        if m:
            st.caption("Figures stated in the official release (as read by the AI): "
                       + " · ".join(f"{METRIC_NAMES.get(k, k)} {v:,}" for k, v in m.items() if v is not None))

        w = wide[wide["company"] == name].tail(9) if not wide.empty else pd.DataFrame()
        c1, c2, c3 = st.columns(3)
        if not w.empty:
            with c1:  # revenue and margin are separate charts: different units never share one chart
                last = len(w) - 1
                fig = go.Figure(go.Bar(x=w["period_label"], y=w["revenue"], marker=dict(color=COLOR[name], cornerradius=4),
                                       text=[money(v, cur) if i == last else "" for i, v in enumerate(w["revenue"])],
                                       textposition="outside", cliponaxis=False, textfont=dict(size=12, color=INK),
                                       customdata=w[["rev_source"]].fillna("—"),
                                       hovertemplate="%{x}: %{y:,.0f} m<br>%{customdata[0]}<extra></extra>"))
                show_chart(style(fig, 320, f"Revenue by period ({cur} millions)", legend=False))
            with c2:
                fig = go.Figure(go.Scatter(x=w["period_label"], y=w["op_margin"], mode="lines+markers+text",
                                           line=dict(color=COLOR[name], width=2.5),
                                           marker=dict(size=8, color=COLOR[name], line=dict(color="white", width=2)),
                                           text=[pct(v, False) if i in (0, len(w) - 1) else "" for i, v in enumerate(w["op_margin"])],
                                           textposition="top center", hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
                fig.update_yaxes(ticksuffix="%")
                show_chart(style(fig, 320, "Operating margin by period", legend=False))
        else:
            c1.caption("No financial history yet.")
        with c3:
            p = D["prices"]
            bench = "STOXX Europe 600" if (info.get("benchmark") or "").upper() == "^STOXX" else "S&P 500"
            if not p.empty and name in set(p["company"]):
                p = p[p["company"].isin([name, bench])].copy().sort_values("date")
                cutoff = max(p.groupby("company")["date"].min())
                p = p[p["date"] >= cutoff]
                p["idx"] = p.groupby("company")["close"].transform(lambda x: x / x.iloc[0] * 100)
                p["_name"] = p["company"]
                fig = lines_with_focus(go.Figure(), p, "date", "idx", name, [bench, name])
                fig.add_hline(y=100, line=dict(color=LINE, width=1, dash="dash"))
                show_chart(style(fig, 320, f"Share price vs {bench} (1 year, start = 100)", legend=False))

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Highlights")
            st.markdown("".join(f"- {esc(h)}\n" for h in ins.get("highlights") or []) or "_None found yet._")
            st.markdown(f"<div class='card'><h4>Guidance {pill(ins.get('guidance_change') if ins.get('results_found') else None)}</h4>"
                        f"<p>{esc(ins.get('guidance') or 'Not stated in the sources found.')}</p></div>", unsafe_allow_html=True)
            if ins.get("management_view"):
                st.markdown(f"<div class='card'><h4>Management view</h4><p>{esc(ins['management_view'])}</p></div>",
                            unsafe_allow_html=True)
        with c2:
            st.markdown("#### Risks")
            st.markdown("".join(f"- {esc(h)}\n" for h in ins.get("risks") or []) or "_None found yet._")
            if ins.get("segments"):
                st.markdown("#### Segments")
                show_table(pd.DataFrame(ins["segments"]).rename(columns={"name": "Segment", "trend": "Trend", "note": "What was said"}))
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### What's happening")
            st.markdown("".join(f"- {esc(h)}\n" for h in ins.get("highlights") or []) or "_Nothing analysed yet._")
        with c2:
            st.markdown("#### Risks")
            st.markdown("".join(f"- {esc(h)}\n" for h in ins.get("risks") or []) or "_None found yet._")
            if ins.get("segments"):
                show_table(pd.DataFrame(ins["segments"]).rename(columns={"name": "Area", "trend": "Trend", "note": "What was said"}))

    st.markdown(f"#### IT services signals &nbsp;{pill(ins.get('it_spend_outlook'))}", unsafe_allow_html=True)
    if ins.get("it_spend_reason"):
        st.markdown(f"<p class='sub'>{esc(ins['it_spend_reason'])}</p>", unsafe_allow_html=True)
    sigs = ins.get("it_signals") or []
    if sigs:
        cols = st.columns(2)
        for i, s_ in enumerate(sigs):
            cols[i % 2].markdown(f"<div class='card'><h4>{esc(s_.get('type'))}</h4><p>{esc(s_.get('detail'))}</p>"
                                 f"<p class='sub'>{link(s_.get('link'), s_.get('source') or 'source') if s_.get('link') else ''}"
                                 f"{' · ' + esc(nice_date(s_.get('published'))) if s_.get('published') else ''}</p></div>",
                                 unsafe_allow_html=True)
    else:
        st.caption("No technology signals found yet.")
    if ins.get("talking_points"):
        st.markdown("<div class='card'><h4>Talking points for a technology account team</h4><ul>"
                    + "".join(f"<li>{esc(t)}</li>" for t in ins["talking_points"]) + "</ul></div>", unsafe_allow_html=True)
    if ins.get("unverified_dropped"):
        st.caption("Removed because a number could not be found in any source: " + ", ".join(ins["unverified_dropped"][:12]))
    st.markdown("#### Sources the AI used")
    srcs = (ins.get("sources") or []) + (ins.get("signal_sources") or [])
    st.markdown(news_list(srcs), unsafe_allow_html=True)
    with st.expander("All recent news for this organisation"):
        st.markdown(news_list(D["news"].get(name, []), limit=40), unsafe_allow_html=True)

elif page == "IT opportunity signals":
    page_header("IT opportunity signals", "Technology investment, platform rebuilds, cloud moves, cost-cutting, layoffs and "
                "M&A that matter to IT services and technology vendors — read by the AI from official releases and news.")
    ind = st.selectbox("Industry", ["All industries"] + INDUSTRIES)
    flt = None if ind == "All industries" else ind
    names = [n for n in ORDER if not flt or flt in INDUSTRY[n]]
    outl = {n: ins_of(n).get("it_spend_outlook") or "Unclear" for n in names}
    k = st.columns(4)
    for c, lab in zip(k, ["Expanding", "Stable", "Tightening", "Unclear"]):
        who = [n for n in names if outl[n] == lab]
        kpi(c, f"IT spend · {lab}", str(len(who)), ", ".join(who) or "—")
    st.write("")
    c1, c2 = st.columns([1, 1.25])
    with c1:
        levels = ["Tightening", "Stable", "Expanding"]
        d = [(n, outl[n]) for n in names if outl[n] in levels]
        if d:
            fig = go.Figure()
            for n, o in d:
                fig.add_trace(go.Scatter(x=[levels.index(o)], y=[n], mode="markers+text", text=[o], textposition="middle right",
                                         marker=dict(size=16, color=COLOR.get(n, ACCENT), line=dict(color="white", width=2)),
                                         hovertemplate=f"<b>{esc(n)}</b>: {o}<extra></extra>", showlegend=False))
            fig.update_xaxes(tickvals=[0, 1, 2], ticktext=levels, range=[-0.4, 2.9])
            fig.update_yaxes(categoryorder="array", categoryarray=[n for n in reversed(names) if n in dict(d)])
            show_chart(style(fig, 70 + 32 * len(d), "IT spend outlook by organisation", legend=False))
    sig = it_signals_flat(flt)
    with c2:
        if not sig.empty:
            cnt = sig.groupby(["Company", "Signal"]).size().unstack(fill_value=0)
            cnt = cnt.reindex([n for n in reversed(names) if n in cnt.index])
            fig = go.Figure(go.Heatmap(z=cnt.values, x=list(cnt.columns), y=list(cnt.index), colorscale=[[0, "#F4F6FA"], [1, ACCENT]],
                                       text=cnt.values, texttemplate="%{text}", showscale=False,
                                       hovertemplate="%{y} · %{x}: %{z}<extra></extra>"))
            show_chart(style(fig, 90 + 30 * len(cnt), "Signals by type", legend=False))
    st.markdown("#### All signals")
    if sig.empty:
        st.info("No signals yet. They appear after the agent's AI analysis.")
    else:
        types = sorted(sig["Signal"].dropna().unique())
        pick = st.multiselect("Signal type", types, default=types)
        show_table(sig[sig["Signal"].isin(pick)].sort_values("Date", ascending=False),
                   column_config={"What was said": st.column_config.TextColumn(width="large"),
                                  "Link": st.column_config.LinkColumn("Open", display_text="open")})
    with st.expander("Talking points by organisation"):
        for n in names:
            tp = ins_of(n).get("talking_points") or []
            if tp:
                st.markdown(f"**{esc(n)}**\n" + "".join(f"- {esc(t)}\n" for t in tp))

elif page == "Audience pulse":
    page_header("Audience pulse · movies & shows", "What people are saying about recent and upcoming titles, split into the "
                "tracked media companies' studios and networks versus the rest of the industry.")
    st.markdown("<p class='caveat'>Online audience opinion, not a representative survey.</p>", unsafe_allow_html=True)
    titles = (D["pulse"] or {}).get("titles") or []
    if not titles:
        st.info("No titles yet. The Audience Pulse fills in once a day after the TMDB_KEY secret is added (see the guide).")
        st.stop()
    T = pd.DataFrame(titles)
    for col in ("imdb_rating", "rt", "metascore", "tmdb_vote", "box_office_usd", "popularity"):
        if col not in T:
            T[col] = float("nan")
        T[col] = pd.to_numeric(T[col], errors="coerce")
    T["sentiment"] = [(a or {}).get("audience_sentiment") if isinstance(a, dict) else None for a in T.get("ai", [None] * len(T))]
    T["score"] = [(a or {}).get("audience_score") if isinstance(a, dict) else None for a in T.get("ai", [None] * len(T))]
    T["score"] = pd.to_numeric(T["score"], errors="coerce")
    st.markdown(f"<p class='sub'>Updated {esc(nice_date((D['pulse'] or {}).get('updated')))} · TMDB, OMDb (IMDb / Rotten Tomatoes / "
                "Metascore), Reddit and trade-press headlines, summarised by an AI.</p>", unsafe_allow_html=True)
    view = st.radio("Show", ["Tracked companies", "Rest of industry", "Both (side by side)"], horizontal=True)
    groups = ["Tracked companies", "Rest of industry"] if view.startswith("Both") else [view]

    def group_kpis(col, g):
        G = T[(T["group"] == g) & (~T["upcoming"].astype(bool))]
        n = len(G)
        sent = G["sentiment"].value_counts()
        share = lambda k: f"{sent.get(k, 0) / max(1, sent.sum()) * 100:.0f}%"  # noqa: E731
        k = col.columns(3)
        kpi(k[0], "Titles out now", str(n), f"+ {int(T[(T['group'] == g) & T['upcoming'].astype(bool)].shape[0])} upcoming")
        kpi(k[1], "Avg audience score", num(G["score"].mean(), "{:+.0f}"), "AI score, −100 to +100")
        kpi(k[2], "Positive · Mixed · Negative", f"{share('Positive')} · {share('Mixed')} · {share('Negative')}",
            f"{int(sent.sum())} titles with enough comments")

    def scoreboard(g):
        G = T[(T["group"] == g) & (~T["upcoming"].astype(bool))]
        if G.empty:
            return pd.DataFrame()
        s = G.groupby(["parent", "studio"]).agg(Titles=("title", "count"), Score=("score", "mean"),
                                                 IMDb=("imdb_rating", "mean"), RT=("rt", "mean")).reset_index()
        s = s.rename(columns={"parent": "Parent", "studio": "Studio / network", "Score": "Avg audience score",
                              "IMDb": "Avg IMDb", "RT": "Avg RT %"}).sort_values("Avg audience score", ascending=False)
        return s.round(1)

    def title_card(r):
        ai = r.get("ai") if isinstance(r.get("ai"), dict) else {}
        img = f"<img src='{esc(r['poster'])}' alt=''>" if r.get("poster") and isinstance(r.get("poster"), str) else "<div class='noimg'>no poster</div>"
        scores = " · ".join(x for x in [f"IMDb {r['imdb_rating']:.1f}" if not isna(r.get("imdb_rating")) else "",
                                        f"RT {r['rt']:.0f}%" if not isna(r.get("rt")) else "",
                                        f"Metascore {r['metascore']:.0f}" if not isna(r.get("metascore")) else "",
                                        f"TMDB {r['tmdb_vote']:.1f}" if not isna(r.get("tmdb_vote")) else ""] if x) or "no ratings yet"
        verdict = ai.get("box_office_verdict")
        verdict_pill = (f"<span class='pill {tone_class(verdict)}'>box office: {esc(verdict)}</span>"
                        if verdict and verdict != "not stated" else "")
        links = [link(r.get("tmdb_url"), "TMDB")]
        links += [link(x.get("link"), x.get("source") or "trade press") for x in (r.get("trade") or [])[:2]]
        links += [link(x.get("url"), f"r/{x.get('sub')}") for x in (r.get("reddit") or [])[:1]]
        return (f"<div class='card'><div class='title-card'>{img}<div>"
                f"<h4 style='display:block'>{esc(r['title'])}</h4>"
                f"<div class='sub'>{esc(r['studio'])} · {'TV' if r['kind'] == 'tv' else 'Film'} · {esc(nice_date(r.get('release_date')))}</div>"
                f"<div class='scores'>{esc(scores)}</div>"
                f"{pill(ai.get('audience_sentiment'), 'not analysed')} "
                f"{verdict_pill}"
                f"<p style='margin-top:6px'>{esc(ai.get('summary') or '')}</p>"
                + (f"<p><b>👍</b> {esc('; '.join(ai.get('praises') or []))}</p>" if ai.get("praises") else "")
                + (f"<p><b>👎</b> {esc('; '.join(ai.get('complaints') or []))}</p>" if ai.get("complaints") else "")
                + f"<p class='sub'>{' · '.join(links)}</p></div></div></div>")

    cols = st.columns(len(groups))
    for col, g in zip(cols, groups):
        with col:
            st.markdown(f"### <span class='dot' style='background:{GROUP_COLORS[g]}'></span>{esc(g)}", unsafe_allow_html=True)
            group_kpis(col, g)
            sb = scoreboard(g)
            st.markdown("##### Studio scoreboard")
            if sb.empty:
                st.caption("No titles out now in this group.")
            else:
                show_table(sb)
    st.markdown("#### Critics vs audience")
    S = T[(~T["upcoming"].astype(bool)) & T["group"].isin(groups)].copy()
    S["critics"] = S["rt"].fillna(S["metascore"])
    S["audience"] = (S["imdb_rating"] * 10).fillna(S["tmdb_vote"] * 10)
    S = S.dropna(subset=["critics", "audience"])
    if S.empty:
        st.caption("Needs Rotten Tomatoes / Metascore numbers (OMDb key) for released titles.")
    else:
        fig = go.Figure()
        for g in groups:
            G = S[S["group"] == g]
            fig.add_trace(go.Scatter(x=G["critics"], y=G["audience"], mode="markers+text", name=g, text=G["title"],
                                     textposition="top center", textfont=dict(size=10, color=MUTED),
                                     marker=dict(size=12, color=GROUP_COLORS[g], line=dict(color="white", width=1.5)),
                                     customdata=G[["studio"]],
                                     hovertemplate="<b>%{text}</b> (%{customdata[0]})<br>Critics %{x:.0f}<br>Audience %{y:.0f}<extra></extra>"))
        fig.add_shape(type="line", x0=0, y0=0, x1=100, y1=100, line=dict(color=LINE, dash="dash"))
        fig.update_xaxes(title="Critics (Rotten Tomatoes %, or Metascore)", range=[0, 105])
        fig.update_yaxes(title="Audience (IMDb, or TMDB user score, × 10)", range=[0, 105])
        show_chart(style(fig, 460, "Above the dashed line = audiences like it more than critics", legend=True))

    st.markdown("#### Titles out now")
    sort_by = st.selectbox("Sort by", ["Most talked about (popularity)", "Audience score", "Newest"])
    for g in groups:
        G = T[(T["group"] == g) & (~T["upcoming"].astype(bool))]
        G = G.sort_values({"Most talked about (popularity)": "popularity", "Audience score": "score",
                           "Newest": "release_date"}[sort_by], ascending=False, na_position="last")
        if len(groups) > 1:
            st.markdown(f"##### {esc(g)}")
        cc = st.columns(3)
        for i, r in enumerate(G.to_dict("records")):
            cc[i % 3].markdown(title_card(r), unsafe_allow_html=True)
    st.markdown("#### Coming soon · early buzz")
    U = T[T["upcoming"].astype(bool) & T["group"].isin(groups)].sort_values("release_date")
    if U.empty:
        st.caption("No upcoming titles in the next 90 days.")
    else:
        show_table(pd.DataFrame([{
            "Title": r["title"], "Studio / network": r["studio"], "Group": r["group"], "Release": r.get("release_date"),
            "Buzz": (r.get("ai") or {}).get("buzz") if isinstance(r.get("ai"), dict) else None,
            "What people say": (r.get("ai") or {}).get("summary") if isinstance(r.get("ai"), dict) else None,
            "TMDB popularity": r.get("popularity")} for r in U.to_dict("records")]),
            column_config={"What people say": st.column_config.TextColumn(width="large")})

elif page == "Industry news":
    page_header("Industry news", "Education, publishing, lottery and gaming: the last 14 days from trade publications and news "
                "searches, de-duplicated and summarised once a day by the AI.")
    IN = D["industry"] or {}
    areas = IN.get("areas") or {}
    items = pd.DataFrame(IN.get("items") or [])
    if not areas and items.empty:
        st.info("Industry news appears after the agent's first daily run.")
        st.stop()
    st.markdown(f"<p class='sub'>Updated {esc(nice_date(IN.get('updated')))}</p>", unsafe_allow_html=True)
    MOODV = {"Positive": 1, "Mixed": 0, "Negative": -1}
    tabs = st.tabs(["Education", "Publishing", "Lottery", "Gaming"])
    for tab, area in zip(tabs, ["Education", "Publishing", "Lottery", "Gaming"]):
        with tab:
            a = areas.get(area) or {}
            hist = D["industry_hist"].get(area) or []
            last_week = [h for h in hist if h["date"] <= (TODAY - timedelta(days=6)).isoformat()]
            prev = last_week[-1]["mood"] if last_week else None
            change = ""
            if prev and a.get("mood"):
                dv = MOODV.get(a["mood"], 0) - MOODV.get(prev, 0)
                change = "↑ better than last week" if dv > 0 else ("↓ worse than last week" if dv < 0 else "→ same as last week")
            k = st.columns([1, 1, 2])
            kpi(k[0], "Mood now", a.get("mood") or "—", a.get("mood_reason") or "")
            kpi(k[1], "Last week", prev or "—", change or "history builds up day by day")
            k[2].markdown("<div class='kpi'><div class='lab'>Key themes</div><div style='margin-top:8px'>"
                          + "".join(f"<span class='tag'>{esc(t)}</span>" for t in a.get("themes") or [])
                          + f"</div><div class='note'>{a.get('stories_count') or 0} stories read</div></div>", unsafe_allow_html=True)
            if a.get("it_implications"):
                st.markdown(f"<div class='callout'><b>What this means for IT services & technology vendors.</b> "
                            f"{esc(a['it_implications'])}</div>", unsafe_allow_html=True)
            c1, c2 = st.columns([1.6, 1])
            with c1:
                st.markdown("##### Top stories")
                for s in a.get("top_stories") or []:
                    tags = "".join(f"<span class='tag hl'>{esc(m)}</span>" for m in s.get("mentions") or [])
                    st.markdown(f"<div class='card'><h4 style='display:block'>{link(s.get('link'), s.get('title'))}</h4>"
                                f"<p>{esc(s.get('why'))}</p><p class='sub'>{esc(s.get('source'))} · {esc(nice_date(s.get('published')))} {tags}</p></div>",
                                unsafe_allow_html=True)
                if not a.get("top_stories"):
                    st.caption("The AI summary appears after the daily run.")
            with c2:
                st.markdown("##### Tracked organisations in the news")
                tm = a.get("tracked_mentions") or []
                if tm:
                    for m in tm:
                        st.markdown(f"<div class='card'><h4><span><span class='dot' style='background:{COLOR.get(m.get('company'), ACCENT)}'></span>"
                                    f"{esc(m.get('company'))}</span></h4><p>{esc(m.get('note'))}</p></div>", unsafe_allow_html=True)
                else:
                    st.caption("None this time.")
            st.markdown("##### All stories")
            A = items[items["area"] == area].copy() if not items.empty else pd.DataFrame()
            q = st.text_input("Search headlines", "", key=f"q_{area}")
            if not A.empty:
                if q:
                    A = A[A["title"].str.contains(q, case=False, na=False, regex=False)]
                A["Tracked"] = A["mentions"].map(lambda x: ", ".join(x) if isinstance(x, list) and x else None)
                A["Date"] = A["published"].astype(str).str[:10]
                show_table(A[["Date", "title", "source", "Tracked", "link"]].rename(columns={"title": "Headline", "source": "Source"}),
                           column_config={"Headline": st.column_config.TextColumn(width="large"),
                                          "link": st.column_config.LinkColumn("Open", display_text="open")})

elif page == "Financial trends":
    page_header("Financial trends", "Quarterly (or half-yearly) figures. Official SEC / company numbers where available, "
                "Yahoo Finance otherwise. Pick a company to highlight it; peers are grey.")
    if wide.empty:
        st.info("No financial data yet.")
    else:
        c1, c2, c3 = st.columns([1, 1, 1.3])
        ind = c1.selectbox("Industry", ["All industries"] + [i for i in INDUSTRIES if any(i in INDUSTRY[n] for n in LISTED)])
        pool = [n for n in LISTED if ind == "All industries" or ind in INDUSTRY[n]]
        focus = c2.selectbox("Highlight", pool, format_func=lambda n: NAMES.get(n, n))
        mode = c3.radio("Show revenue as", ["Indexed (first period = 100)", "US dollars"], horizontal=True)
        w = wide[wide["company"].isin(pool)].copy()
        w["_name"] = w["company"]
        cut = (TODAY - timedelta(days=3 * 365)).isoformat()
        w = w[w["period_end"] >= cut]
        w["x"] = pd.to_datetime(w["period_end"])

        def chart(col, title, suffix="", index=False):
            g = w.sort_values("period_end").copy()
            if index:
                g[col] = g.groupby("company")[col].transform(lambda y: y / y.dropna().iloc[0] * 100 if y.notna().any() else y)
            fig = lines_with_focus(go.Figure(), g, "x", col, focus, pool, suffix=suffix)
            if suffix:
                fig.update_yaxes(ticksuffix=suffix)
            return style(fig, 400, title, legend=False)

        show_chart(chart("rev_usd" if mode == "US dollars" else "revenue",
                         "Revenue, indexed (each company's first period = 100)" if mode.startswith("Indexed") else "Revenue (US$ millions)",
                         index=mode.startswith("Indexed")))
        st.caption("Half-yearly reporters (Wolters Kluwer, Pearson) show one point per half-year. Indexing compares growth "
                   "fairly across currencies and sizes.")
        c1, c2 = st.columns(2)
        with c1:
            show_chart(chart("op_margin", "Operating margin", "%"))
        with c2:
            show_chart(chart("net_margin", "Net margin", "%"))
        q = w[w["months"] == 3].copy()
        if not q.empty:
            q = q[q["period_end"] >= (TODAY - timedelta(days=2 * 365)).isoformat()]
            hm = q.pivot_table(index="company", columns="period_label", values="rev_pop")
            hm = hm.reindex(columns=sorted(hm.columns, key=label_key)).reindex([n for n in pool if n in hm.index]).dropna(axis=1, how="all")
            if not hm.empty:
                fig = go.Figure(go.Heatmap(z=hm.values, x=list(hm.columns), y=list(hm.index),
                                           colorscale=[[0, "#D03B3B"], [0.5, "#F0EFEC"], [1, "#2A78D6"]], zmid=0,
                                           text=[[pct(v) for v in r] for r in hm.values], texttemplate="%{text}",
                                           hovertemplate="%{y} · %{x}: %{z:+.1f}%<extra></extra>", colorbar=dict(title="QoQ %")))
                show_chart(style(fig, 90 + 36 * len(hm), "Revenue change vs previous quarter (blue = grew, red = fell)", legend=False))
                st.caption("Seasonal businesses (theme parks, school books, casinos) swing quarter to quarter; compare with "
                           "the same quarter a year earlier on the scorecard.")
        with st.expander("Data table"):
            show_table(w[["company", "period_label", "period_end", "show_cur", "revenue", "operating_income", "net_income",
                          "op_margin", "rev_yoy", "rev_source"]].rename(columns={
                "company": "Company", "period_label": "Period", "period_end": "Period end", "show_cur": "Currency",
                "revenue": "Revenue (m)", "operating_income": "Operating income (m)", "net_income": "Net income (m)",
                "op_margin": "Op. margin %", "rev_yoy": "Revenue YoY %", "rev_source": "Revenue source"}).round(1))

elif page == "Share price & valuation":
    page_header("Share price & valuation", "Daily closing prices from Yahoo Finance (each in its own trading currency). "
                "P/E = market value ÷ last 12 months' net income.")
    p = D["prices"]
    if p.empty:
        st.info("No price data yet.")
    else:
        names = [n for n in LISTED if n in set(p["company"])]
        focus = st.selectbox("Highlight", names, format_func=lambda n: NAMES.get(n, n))
        pp = p.sort_values("date").copy()
        pp["idx"] = pp.groupby("company")["close"].transform(lambda x: x / x.iloc[0] * 100)
        pp["_name"] = pp["company"]
        fig = lines_with_focus(go.Figure(), pp, "date", "idx", focus, names + [b for b in BENCH_STYLE if b in set(pp["company"])])
        fig.add_hline(y=100, line=dict(color=LINE, width=1, dash="dash"))
        show_chart(style(fig, 440, f"One year of share prices, start = 100 ({NAMES.get(focus, focus)} vs peers and benchmarks)", legend=False))
        m = D["market"].copy()
        if not m.empty:
            m = m[m["company"].isin(LISTED)]
            c1, c2 = st.columns(2)
            with c1:
                per = st.radio("Return over", ["1 month", "3 months", "1 year"], index=2, horizontal=True)
                colname = {"1 month": "return_1m", "3 months": "return_3m", "1 year": "return_1y"}[per]
                d = m.dropna(subset=[colname]).sort_values(colname)
                fig = go.Figure(go.Bar(x=d[colname], y=d["company"], orientation="h",
                                       marker=dict(color=[COLOR.get(n, ACCENT) for n in d["company"]], cornerradius=4),
                                       text=[pct(v) for v in d[colname]], textposition="outside", cliponaxis=False,
                                       hovertemplate="%{y}: %{x:+.1f}%<extra></extra>"))
                fig.update_xaxes(ticksuffix="%", zeroline=True, zerolinecolor="#52514E")
                show_chart(style(fig, 80 + 34 * len(d), f"Share-price return, {per}", legend=False))
            with c2:
                d = m.dropna(subset=["market_cap_usd_m"]).sort_values("market_cap_usd_m")
                fig = go.Figure(go.Bar(x=d["market_cap_usd_m"], y=d["company"], orientation="h",
                                       marker=dict(color=[COLOR.get(n, ACCENT) for n in d["company"]], cornerradius=4),
                                       text=[money(v) for v in d["market_cap_usd_m"]], textposition="outside", cliponaxis=False,
                                       hovertemplate="%{y}: $%{x:,.0f} m<extra></extra>"))
                fig.update_xaxes(showticklabels=False, range=[0, float(d["market_cap_usd_m"].max() or 1) * 1.35] if not d.empty else None)
                show_chart(style(fig, 80 + 34 * len(d), "Market value (US$)", legend=False))
            show_table(m[["company", "ticker", "price", "price_currency", "price_date", "market_cap_usd_m", "pe_ttm", "return_1m",
                          "return_3m", "return_1y", "high_52w", "low_52w", "next_results"]].rename(columns={
                "company": "Company", "ticker": "Ticker", "price": "Price", "price_currency": "Currency", "price_date": "As of",
                "market_cap_usd_m": "Market value ($ m)", "pe_ttm": "P/E", "return_1m": "1M %", "return_3m": "3M %",
                "return_1y": "1Y %", "high_52w": "52-wk high", "low_52w": "52-wk low", "next_results": "Next results"}),
                fmt={"Market value ($ m)": "{:,.0f}", "Price": "{:,.2f}", "1M %": "{:+.1f}", "3M %": "{:+.1f}", "1Y %": "{:+.1f}",
                     "52-wk high": "{:,.2f}", "52-wk low": "{:,.2f}", "P/E": "{:.1f}"})

elif page == "News":
    page_header("News", "Latest coverage per organisation from Google News and Bing News (incl. Bloomberg and Reuters headlines).")
    rows = []
    for n, items in D["news"].items():
        if n not in INFO:
            continue
        for i in items:
            rows.append({"Date": (i.get("published") or "")[:10], "Company": n, "Industry": INDUSTRY[n][0],
                         "Headline": i.get("title"), "Source": i.get("source"), "Link": i.get("link")})
    if not rows:
        st.info("No news yet.")
    else:
        df = pd.DataFrame(rows).sort_values("Date", ascending=False)
        c1, c2, c3 = st.columns([1, 1, 1.2])
        who = c1.multiselect("Company", ORDER, default=[])
        ind = c2.multiselect("Industry", INDUSTRIES, default=[])
        q = c3.text_input("Search headlines", "")
        if who:
            df = df[df["Company"].isin(who)]
        if ind:
            df = df[df["Industry"].isin(ind)]
        if q:
            df = df[df["Headline"].str.contains(q, case=False, na=False, regex=False)]
        st.caption(f"{len(df)} stories")
        show_table(df, column_config={"Headline": st.column_config.TextColumn(width="large"),
                                      "Link": st.column_config.LinkColumn("Open", display_text="open")})

else:
    page_header("About & data")
    st.markdown("""
**What this is.** A free, automatic dashboard that follows 15 organisations in media & entertainment, gaming & lottery,
publishing & information, and education **as industry players**, with a focus on what matters to technology and IT
services vendors. It holds no internal or private data.

**How it works.** An agent runs on GitHub, for free:
- **Four times a day (results):** share prices and financial history from Yahoo Finance (checked for plausibility: currency,
  revenue vs market value, missing or out-of-line periods); official results straight from the source — the SEC's EDGAR
  system for US filers (8-K earnings releases, 6-K reports, and exact XBRL numbers from 10-Qs and 10-Ks) and the company's own
  releases for Wolters Kluwer; news from Google News and Bing News, including Bloomberg and Reuters headlines and a
  technology / AI / outsourcing / layoffs search. When a new official release appears, an open AI model reads it with the news
  and extracts results, guidance, segments, risks and IT-services signals. Every number the AI writes must appear in a source
  or it is deleted. A company counts as "results out" only when an official release exists.
- **Once a day (audience pulse):** recent and upcoming movies and shows from TMDB, ratings from OMDb, Reddit discussion (if
  set up) and trade-press headlines; the AI summarises audience mood per title.
- **Once a day (industry news):** education, publishing, lottery and gaming news from trade feeds and news searches, with an AI brief per industry.

**Which number wins.** Your hand-checked `data/overrides.csv` → SEC XBRL → the official release (read by the AI) → Yahoo Finance.

**Read with care.** AI summaries can be wrong; check important facts against the linked sources. Audience pulse is online
opinion, not a representative survey. Quarters are labelled by calendar quarter (a quarter ending 28 Jun 2026 is "Q2 2026"),
so fiscal labels differ (Disney's fiscal year ends in late September, Scholastic's in May). US-dollar figures use the average
exchange rate of each period. Not investment advice.
""")
    st.markdown("#### Download the data")
    files = [("Financials (CSV)", "financials.csv"), ("Market data (CSV)", "market.csv"), ("AI insights (JSON)", "insights.json"),
             ("Audience pulse (JSON)", "pulse_titles.json"), ("Industry news (JSON)", "industry_news.json"),
             ("News (JSON)", "news.json"), ("Official numbers (CSV)", "filed_financials.csv"), ("Studios map (CSV)", "studios.csv")]
    cols = st.columns(4)
    for i, (label, fname) in enumerate(files):
        f = DATA / fname
        if f.exists():
            try:
                cols[i % 4].download_button(f"⬇ {label}", f.read_bytes(), file_name=fname, width="stretch")
            except TypeError:  # older Streamlit versions
                cols[i % 4].download_button(f"⬇ {label}", f.read_bytes(), file_name=fname, use_container_width=True)
    if D["feeds"]:
        st.markdown("#### News feeds")
        show_table(pd.DataFrame(D["feeds"]).rename(columns={"area": "Area", "name": "Publication", "ok": "Working",
                                                             "via": "Read via", "error": "Problem", "checked": "Checked"}))
    if D["runs"]:
        st.markdown("#### Recent agent runs")
        show_table(pd.DataFrame([{"Finished (UTC)": (r.get("finished") or "")[:16].replace("T", " "), "Part": r.get("part"),
                                  "AI calls": r.get("ai_calls"), "AI tokens": r.get("ai_tokens"),
                                  "What happened": "; ".join(r.get("steps") or []),
                                  "Problems": "; ".join(r.get("errors") or [])[:400]} for r in D["runs"]]),
                   column_config={"What happened": st.column_config.TextColumn(width="large"),
                                  "Problems": st.column_config.TextColumn(width="large")})
    st.caption(APP_VERSION)
