"""
Turns one client's account update (data/briefs.json, written by agent/brief.py) into:
  * a full PDF    - key numbers, revenue by segment (bar chart), area of focus (where they will spend,
                    technology & IT first), key changes, leadership changes, key dates, sources
  * a summary PDF - the same on one page, main points only
  * summary_email(b) - the summary as e-mail-safe HTML (inline styles; works in Outlook and Gmail)

All amounts are shown in US dollars: amounts in pounds, euros etc. are converted with the latest monthly
rate in data/fx.csv, and the rate used is printed under the sources. Numbers are highlighted in bold.

PDFs are drawn by a headless Chromium (Playwright). If Chromium is missing the e-mail still goes, without PDFs.
Try it:  python report.py Pearson   (writes the PDFs into data/reports/)
"""
import csv
import html
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent
REPORTS = ROOT / "data" / "reports"

BLUE, INK, MUTED, LINE, SOFT, CARD = "#2F41BF", "#1B2333", "#5B6475", "#E6E9F0", "#F4F6FB", "#DCE1EA"
GREEN, RED, AMBER, NEG = "#0B7A0B", "#B42318", "#A86400", "#C2410C"
LEAD_COLOR = {"appointed": GREEN, "promoted": GREEN, "new role": GREEN, "expanded role": GREEN, "joining": GREEN,
              "leaving": RED, "retiring": RED}
TYPE_COLOR = {"acquisition": GREEN, "contract win": GREEN, "partnership": GREEN, "product": GREEN,
              "contract loss": RED, "disposal": AMBER, "cost programme": AMBER, "organisation": BLUE}

# ------------------------------------------------------------------ styles (classes for the PDF, inline for e-mail)
STYLE = {
    "top": f"border-bottom:3px solid {BLUE};padding-bottom:10px;margin-bottom:20px",
    "kicker": f"color:{BLUE};font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase",
    "h1": f"font-family:Georgia,'Times New Roman',serif;font-size:26px;font-weight:600;margin:4px 0 2px;color:{INK}",
    "meta": f"color:{MUTED};font-size:12px",
    "lead": f"background:{SOFT};border-left:4px solid {BLUE};padding:12px 16px;margin:0 0 22px;font-size:14px",
    "card": f"border:1px solid {CARD};border-radius:8px;padding:14px 16px 10px;margin:0 0 22px",
    "h2": f"font-size:15px;font-weight:700;margin:0 0 10px;color:{INK}",
    "n": f"display:inline-block;min-width:20px;color:{BLUE}",
    "sub": f"font-size:12px;font-weight:700;color:{MUTED};text-transform:uppercase;letter-spacing:.05em;margin:12px 0 4px",
    "tile": f"border:1px solid {CARD};border-radius:8px;padding:10px 12px;vertical-align:top;background:#FFFFFF",
    "tlabel": f"color:{MUTED};font-size:10.5px;text-transform:uppercase;letter-spacing:.05em",
    "tvalue": f"color:{BLUE};font-size:22px;font-weight:700;line-height:1.25;margin:2px 0",
    "tctx": f"color:{MUTED};font-size:11.5px",
    "table": "border-collapse:collapse;width:100%;margin:2px 0 6px",
    "th": f"text-align:left;font-weight:600;color:{MUTED};font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;"
          f"padding:5px 8px;border-bottom:1.5px solid #C9D0DC",
    "td": f"padding:7px 8px;border-bottom:1px solid {LINE};vertical-align:top;font-size:13px",
    "note": f"color:{MUTED};font-size:11.5px",
    "num": f"font-weight:700;color:{INK}",
    "ul": "margin:2px 0 6px;padding-left:18px",
    "li": "margin:4px 0",
    "src": f"color:{MUTED};font-size:11px;line-height:1.5",
    "bartrack": "background:#EEF1F7;border-radius:4px",
}

CSS = f"""
@page {{ size: A4; margin: 16mm 16mm 14mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: "Segoe UI", Inter, "DejaVu Sans", Arial, sans-serif; color: {INK}; font-size: 13px; line-height: 1.5; margin: 0; }}
.card {{ page-break-inside: avoid; }}
.card.long {{ page-break-inside: auto; }}
h2, .sub {{ page-break-after: avoid; }}
tr, li {{ page-break-inside: avoid; }}
a {{ color: {BLUE}; text-decoration: none; }}
.tile {{ min-height: 118px; }}
td.tilecell {{ height: 1px; }}
body.one {{ font-size: 11.5px; line-height: 1.4; }}
@page one {{ margin: 12mm 14mm 10mm 14mm; }}
body.one .card {{ padding: 7px 12px 3px; margin-bottom: 9px; }}
body.one .h2 {{ font-size: 13px; margin-bottom: 6px; }}
body.one .lead {{ margin-bottom: 12px; padding: 8px 12px; font-size: 12px; }}
body.one .top {{ margin-bottom: 12px; padding-bottom: 8px; }}
body.one .h1 {{ font-size: 22px; }}
body.one .tile {{ padding: 6px 10px; min-height: 68px; }}
body.one .tvalue {{ font-size: 16px; }}
body.one .tctx {{ font-size: 10.5px; }}
body.one td {{ font-size: 11.5px; }}
body.one .li {{ margin: 1px 0; }}
""" + "\n".join(f".{k} {{ {v} }}" for k, v in STYLE.items())


class R:
    """Renderer: mode 'pdf' uses classes + a stylesheet, mode 'email' writes inline styles."""

    def __init__(self, mode="pdf"):
        self.mode = mode

    def a(self, cls, extra=""):
        if self.mode == "email":
            return f" style=\"{STYLE[cls]};{extra}\"" if extra else f" style=\"{STYLE[cls]}\""
        return f" class=\"{cls}\"" + (f" style=\"{extra}\"" if extra else "")


def e(x):
    return html.escape(str(x)) if x not in (None, "") else ""


def nice_date(d):
    try:
        return datetime.fromisoformat(str(d)[:10]).strftime("%-d %B %Y")
    except (ValueError, TypeError):
        return str(d or "")


# ------------------------------------------------------------------ US dollars
SYMBOLS = {"£": "GBP", "€": "EUR", "A$": "AUD", "C$": "CAD", "GBP": "GBP", "EUR": "EUR", "AUD": "AUD", "CAD": "CAD"}
_CUR = r"(?:A\$|C\$|£|€|GBP\s?|EUR\s?|AUD\s?|CAD\s?)"
_N = r"\d[\d,]*(?:\.\d+)?"
_U = r"(?:bn|billion|mn|million|m|k|thousand)"
MONEY = re.compile(rf"(?P<cur>{_CUR})(?P<n1>{_N})\s?(?P<u1>{_U})?\b(?:\s?(?P<sep>[-–‑]|to)\s?(?:{_CUR})?(?P<n2>{_N})\s?(?P<u2>{_U})?\b)?")
MULT = {"bn": 1e9, "billion": 1e9, "mn": 1e6, "million": 1e6, "m": 1e6, "k": 1e3, "thousand": 1e3, None: 1}


def load_fx():
    """Latest US-dollar rate per currency from data/fx.csv -> {cur: (rate, 'Month YYYY')}."""
    out = {}
    try:
        with open(ROOT / "data" / "fx.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                c, m = r["currency"].upper(), r["month"]
                if c not in out or m > out[c][1]:
                    out[c] = (float(r["usd_per_unit"]), m)
    except (OSError, ValueError, KeyError):
        pass
    return {c: (v, datetime.strptime(m, "%Y-%m").strftime("%B %Y")) for c, (v, m) in out.items()}


FALLBACK_FX = {"GBP": (1.33, "fallback rate"), "EUR": (1.16, "fallback rate"), "AUD": (0.66, "fallback rate"), "CAD": (0.72, "fallback rate")}


def usd(value):
    """Format a dollar amount: $1.6bn, $874m, $67m, $12.5m, $5.30."""
    if value >= 1e9:
        return f"${value / 1e9:.1f}bn".replace(".0bn", "bn") if value < 1e10 else f"${value / 1e9:.0f}bn"
    if value >= 1e6:
        m = value / 1e6
        return f"${m:.0f}m" if m >= 10 else f"${m:.1f}m".replace(".0m", "m")
    if value >= 1e3:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


class Money:
    def __init__(self, fx=None):
        self.fx = fx if fx is not None else load_fx()
        self.used = {}

    def rate(self, cur):
        r = self.fx.get(cur) or FALLBACK_FX.get(cur)
        if r:
            self.used[cur] = r
        return r[0] if r else None

    def value(self, text):
        """First amount in the text, in US dollars (None if there is none)."""
        if not text:
            return None
        m = MONEY.search(str(text))
        if m:
            cur = SYMBOLS[m.group("cur").strip()]
            rate = self.rate(cur)
            u = m.group("u1") or m.group("u2")
            return float(m.group("n1").replace(",", "")) * MULT[u] * rate if rate else None
        m = re.search(rf"\$(?P<n>{_N})\s?(?P<u>{_U})?\b", str(text))
        if m:
            return float(m.group("n").replace(",", "")) * MULT[m.group("u")]
        return None

    def text(self, s):
        """Every £ / € / ... amount in the text, rewritten in US dollars."""
        if not s:
            return s

        def sub(m):
            cur = SYMBOLS[m.group("cur").strip()]
            rate = self.rate(cur)
            if not rate:
                return m.group(0)
            u1, u2 = m.group("u1"), m.group("u2")
            a = usd(float(m.group("n1").replace(",", "")) * MULT[u1 or u2] * rate)
            if not m.group("n2"):
                return a
            b = usd(float(m.group("n2").replace(",", "")) * MULT[u2 or u1] * rate)
            return f"{a}–{b}"
        return MONEY.sub(sub, str(s))

    def note(self):
        if not self.used:
            return ""
        sym = {"GBP": "£1", "EUR": "€1", "AUD": "A$1", "CAD": "C$1"}
        parts = [f"{sym.get(c, '1 ' + c)} = ${r:.2f} ({m})" for c, (r, m) in sorted(self.used.items())]
        return "Amounts converted to US dollars at " + ", ".join(parts) + "."


NUMS = re.compile(r"(\$\d[\d,]*(?:\.\d+)?(?:bn|m|k)?(?:–\$\d[\d,]*(?:\.\d+)?(?:bn|m|k)?)?"
                  r"|[+\-−–]?\d+(?:\.\d+)?\s?(?:%|pts|ppt|bps)|\b\d+(?:\.\d+)?x\b)")


class Doc:
    """Holds the renderer and money converter for one document."""

    def __init__(self, b, mode="pdf", fx=None):
        self.b, self.r, self.m = b, R(mode), Money(fx)

    def t(self, s, highlight=True):
        """Escape, convert to US dollars, highlight numbers, grey (call)/(news) markers."""
        s = e(self.m.text(s))
        if highlight:
            s = NUMS.sub(lambda x: f"<b{self.r.a('num')}>{x.group(1)}</b>", s)
        return re.sub(r"\s*\((?:on the )?(call|news|official)\)\s*\.?$",
                      lambda x: "" if x.group(1) == "official" else f" <span{self.r.a('note')}>({x.group(1)})</span>", s)

    def src(self, x):
        return f" <span{self.r.a('note')}>({x['src']})</span>" if x.get("src") in ("call", "news") else ""

    def tag(self, word, colors):
        if not word:
            return ""
        c = colors.get(str(word).lower(), MUTED)
        return (f"<span style=\"display:inline-block;font-size:10.5px;font-weight:700;padding:0 8px;border-radius:10px;"
                f"border:1px solid {c};color:{c};white-space:nowrap\">{e(str(word).capitalize())}</span>")

    def ul(self, items):
        items = [i for i in items if i]
        if not items:
            return ""
        return f"<ul{self.r.a('ul')}>" + "".join(f"<li{self.r.a('li')}>{i}</li>" for i in items) + "</ul>"

    def table(self, head, rows, widths):
        if not rows:
            return ""
        th = "".join(f"<th{self.r.a('th', f'width:{w}')}>{e(h)}</th>" for h, w in zip(head, widths))
        body = "".join("<tr>" + "".join(f"<td{self.r.a('td')}>{c}</td>" for c in row) + "</tr>" for row in rows)
        return f"<table{self.r.a('table')}><tr>{th}</tr>{body}</table>"

    def card(self, n, title, body, long=False):
        if not body:
            return ""
        num = f"<span{self.r.a('n')}>{n}</span>" if n else ""
        cls = "card long" if long and self.r.mode == "pdf" else "card"
        attr = f" class=\"{cls}\"" if self.r.mode == "pdf" else self.r.a("card")
        return f"<div{attr}><div{self.r.a('h2')}>{num}{e(title)}</div>{body}</div>"

    # ---------------------------------------------------------------- blocks
    def header(self, kind):
        b = self.b
        meta = " · ".join(x for x in [e(b.get("document_type")), e(b.get("period")),
                                      f"released {e(nice_date(b.get('release_date')))}" if b.get("release_date") else ""] if x)
        return (f"<div{self.r.a('top')}><div{self.r.a('kicker')}>Account update · {kind}</div>"
                f"<div{self.r.a('h1')}>{e(b.get('name') or b.get('company'))}</div><div{self.r.a('meta')}>{meta}</div></div>")

    def lead(self):
        b = self.b
        if not b.get("headline"):
            return ""
        out = self.t(b["headline"])
        if b.get("outlook_line"):
            out += f"<div style=\"margin-top:6px;color:{MUTED};font-size:12px\">Outlook: {self.t(b['outlook_line'])}</div>"
        return f"<div{self.r.a('lead')}>{out}</div>"

    def tiles(self):
        k = (self.b.get("key_numbers") or [])[:4]
        if not k:
            return ""
        w = f"{100 // len(k)}%"
        cells = "".join(
            f"<td class=\"tilecell\" style=\"width:{w};padding:0 5px;vertical-align:top\"><div{self.r.a('tile')}><div{self.r.a('tlabel')}>{e(x.get('label'))}</div>"
            f"<div{self.r.a('tvalue')}>{e(self.m.text(x.get('value')))}</div>"
            f"<div{self.r.a('tctx')}>{e(self.m.text(x.get('context')))}</div></div></td>" for x in k)
        return f"<table style=\"width:calc(100% + 10px);margin:0 -5px;border-collapse:separate;table-layout:fixed\"><tr>{cells}</tr></table>"

    def bars(self, compact=False):
        """Revenue by segment in US dollars; growth by segment when no amounts are given."""
        segs = self.b.get("segments") or []
        vals = [(s, self.m.value(s.get("revenue"))) for s in segs]
        use_rev = sum(1 for _, v in vals if v) >= 2
        rows = []
        if use_rev:
            data = [(s, v) for s, v in vals if v]
            top = max(v for _, v in data)
            for s, v in sorted(data, key=lambda x: -x[1]):
                rows.append((s, v / top, usd(v), s.get("growth")))
        else:
            data = []
            for s in segs:
                m = re.search(r"([+\-−–]?)\s?(\d+(?:\.\d+)?)\s?%", str(s.get("growth") or ""))
                if m:
                    data.append((s, float(m.group(2)) * (-1 if m.group(1) in "-−–" and m.group(1) else 1)))
            if len(data) < 2:
                return ""
            top = max(abs(v) for _, v in data) or 1
            for s, v in sorted(data, key=lambda x: -x[1]):
                rows.append((s, abs(v) / top, f"{v:+g}%", None, v < 0))
        h = 9 if compact else 12
        out = []
        for row in rows:
            s, frac, label, growth = row[0], row[1], row[2], row[3]
            neg = row[4] if len(row) > 4 else False
            pct = max(2, round(frac * 100))
            color = NEG if neg else BLUE
            bar = (f"<table style=\"width:100%;border-collapse:collapse\"><tr>"
                   f"<td style=\"width:{pct}%;height:{h}px;background:{color};border-radius:0 4px 4px 0;padding:0\"></td>"
                   f"<td style=\"padding:0\"></td></tr></table>")
            name = f"<b>{e(s.get('name'))}</b>"
            if s.get("comment") and not compact:
                name += f"<div{self.r.a('note')}>{self.t(s['comment'], False)}</div>"
            g = f" <span{self.r.a('note')}>{e(growth)}</span>" if growth else ""
            pad = "2px" if compact else "6px"
            out.append(f"<tr><td style=\"padding:{pad} 10px {pad} 0;width:34%;vertical-align:middle;font-size:{12 if compact else 13}px\">{name}</td>"
                       f"<td style=\"padding:{pad} 0;vertical-align:middle\">{bar}</td>"
                       f"<td style=\"padding:{pad} 0 {pad} 10px;width:20%;vertical-align:middle;white-space:nowrap\">"
                       f"<b{self.r.a('num')}>{e(label)}</b>{g}</td></tr>")
        basis = self.b.get("segments_basis") or ("Revenue" if use_rev else "Revenue growth")
        unit = " (US$)" if use_rev else ""
        return (f"<div{self.r.a('note')} style=\"margin:-4px 0 6px\">{e(self.m.text(basis))}{unit}</div>"
                f"<table style=\"width:100%;border-collapse:collapse\">{''.join(out)}</table>")

    def focus_table(self, limit=None):
        f = (self.b.get("focus") or [])[:limit] if limit else (self.b.get("focus") or [])
        rows = []
        for x in f:
            area = f"<b>{e(x.get('area'))}</b>" + (f"<div style=\"margin-top:3px\">{self.tag('Technology', {'technology': BLUE})}</div>" if x.get("tech") else "")
            rows.append([area, self.t(x.get("plan")) + self.src(x), self.t(x.get("amount")) or "—", self.t(x.get("timing")) or "—"])
        return self.table(["Area", "Where they will spend", "Amount", "When"], rows, ["24%", "46%", "15%", "15%"])

    def changes_table(self, limit=None):
        c = self.b.get("key_changes") or []
        rows = [[self.tag(x.get("type"), TYPE_COLOR), f"<b>{e(x.get('change'))}</b><div>{self.t(x.get('detail'))}{self.src(x)}</div>",
                 self.t(x.get("when")) or "—"] for x in (c[:limit] if limit else c)]
        return self.table(["Type", "What changed", "When"], rows, ["18%", "64%", "18%"])

    def organisation(self, compact=False):
        """Old structure -> new business units, with size (US$), what each includes, leader, timing, cost."""
        o = self.b.get("organisation") or {}
        if not (o.get("summary") or o.get("units")):
            return ""
        out = ""
        if o.get("summary"):
            out += f"<div style=\"margin:0 0 8px\">{self.t(o['summary'])}{self.src(o)}</div>"
        facts = [(lab, o.get(k)) for lab, k in (("Before", "before"), ("Effective", "effective"), ("One-off cost", "cost"),
                                               ("Savings", "savings")) if o.get(k)]
        if facts and compact:
            short = [f"{lab}: {self.t(v)}" for lab, v in facts if lab in ("Effective", "One-off cost")]
            if short:
                out += f"<div{self.r.a('note')} style=\"margin:-4px 0 4px\">{' · '.join(short)}</div>"
        elif facts:
            cells = "".join(f"<td style=\"padding:0 14px 6px 0;vertical-align:top\"><div{self.r.a('tlabel')}>{e(lab)}</div>"
                            f"<div style=\"font-size:{12 if compact else 13}px\">{self.t(v)}</div></td>" for lab, v in facts)
            out += f"<table style=\"border-collapse:collapse;margin:0 0 6px\"><tr>{cells}</tr></table>"
        units = o.get("units") or []
        if units:
            rows = []
            for u in units:
                v = self.m.value(u.get("revenue"))
                rev = (("c." if "c." in str(u.get("revenue")) or "about" in str(u.get("revenue")) else "") + usd(v)) if v else (e(u.get("revenue")) or "—")
                row = [f"<b>{e(u.get('name'))}</b>", f"<b{self.r.a('num')}>{rev}</b>" if v else rev]
                if not compact:
                    row.append(self.t(u.get("includes")) or "—")
                row.append(e(u.get("leader")) or "—")
                rows.append(row)
            head = ["New unit", "Size (US$)"] + ([] if compact else ["What it includes"]) + ["Leader"]
            widths = ["34%", "18%", "48%"] if compact else ["24%", "14%", "38%", "24%"]
            out += self.table(head, rows, widths)
        return out

    def leadership_table(self):
        rows = [[f"<b>{e(x.get('person'))}</b>", e(x.get("role")), self.tag(x.get("change"), LEAD_COLOR) + self.src(x),
                 self.t(x.get("when")) or "—"] for x in self.b.get("leadership") or []]
        return (self.table(["Person", "Role", "Change", "When"], rows, ["24%", "38%", "20%", "18%"])
                or f"<div{self.r.a('note')}>No leadership changes in this release or recent news.</div>")

    def sources(self):
        links = []
        for d in self.b.get("documents") or []:
            if d.get("url"):
                where = "Company website" if d.get("site") else ("SEC filing" if "sec.gov" in d["url"] else
                                                                 ("Official" if d.get("official") else "Earnings call (third-party transcript)"))
                links.append(f"{where}: <a href=\"{e(d['url'])}\">{e(d.get('title') or 'document')}</a>")
        if self.b.get("news_used"):
            links.append("Items marked (news): recent news headlines")
        links.append(self.m.note())
        links.append("Read automatically from public documents; numbers, names and quotes not found in them were removed.")
        return f"<div{self.r.a('src')}>" + "<br>".join(x for x in links if x) + "</div>"


# ------------------------------------------------------------------ documents
def full_html(b, fx=None):
    d = Doc(b, "pdf", fx)
    parts, n = [d.header("full detail"), d.lead()], 0

    def add(title, body, long=False):
        nonlocal n
        if body:
            n += 1
            parts.append(d.card(n, title, body, long))

    add("Key numbers", d.tiles())
    add("Organisation change", d.organisation())
    add(seg_title(b), d.bars())
    focus = d.focus_table()
    tech = d.ul([d.t(x) for x in b.get("tech_spend") or []])
    add("Area of focus — where they will spend", (focus + (f"<div{d.r.a('sub')}>Technology &amp; IT spending</div>" + tech if tech else ""))
        or f"<div{d.r.a('note')}>No spending plans stated in this release.</div>", long=True)
    add("Key changes", d.changes_table(), long=True)
    add("Leadership changes", d.leadership_table())
    add("Key dates", d.table(["Date", "Event"], [[f"<b>{e(x.get('date'))}</b>", d.t(x.get("event"))] for x in b.get("dates") or []], ["26%", "74%"]))
    parts.append(d.card(0, "Sources", d.sources()))
    return page("full", "".join(parts), b)


def seg_title(b):
    has_rev = sum(1 for x in b.get("segments") or [] if Money().value(x.get("revenue"))) >= 2
    return "Revenue by segment" if has_rev else "Growth by segment"


def _same_units(b):
    """True when the segment chart would only repeat the new units already listed under Organisation change."""
    units = {str(u.get("name")).lower() for u in ((b.get("organisation") or {}).get("units") or [])}
    segs = {str(x.get("name")).lower() for x in b.get("segments") or []}
    return bool(units) and segs <= units


def summary_parts(d):
    b = d.b
    sm = b.get("summary") or {}
    focus = sm.get("focus") or [f"{x.get('area')}: {x.get('plan')}" for x in (b.get("focus") or [])[:4]]
    changes = sm.get("changes") or [f"{x.get('change')}: {x.get('detail')}" for x in (b.get("key_changes") or [])[:4]]
    unit_heads = {str(u.get("leader")).lower() for u in ((b.get("organisation") or {}).get("units") or []) if u.get("leader")}
    people = [x for x in b.get("leadership") or [] if not (str(x.get("person")).lower() in unit_heads
                                                           and str(x.get("change")).lower() in ("new role", "expanded role", "promoted"))]
    lead = [f"<b>{e(x.get('person'))}</b>, {e(x.get('role'))} — "
            f"<span style=\"color:{LEAD_COLOR.get(str(x.get('change')).lower(), MUTED)};font-weight:600\">{e(str(x.get('change') or '').lower())}</span>"
            + (f" ({d.t(x.get('when'), False)})" if x.get("when") else "") + d.src(x) for x in people[:5]]
    if len(people) < len(b.get("leadership") or []):
        lead.append(f"<span{d.r.a('note')}>Heads of the new units: see Organisation change.</span>")
    return [
        d.header("summary"), d.lead(),
        d.card(None, "Key numbers", d.tiles()),
        d.card(None, "Organisation change", d.organisation(compact=True)),
        d.card(None, seg_title(b), d.bars(compact=True)) if not _same_units(b) else "",
        d.card(None, "Area of focus — where they will spend", d.ul([d.t(x) for x in focus])),
        d.card(None, "Key changes", d.ul([d.t(x) for x in changes[:3 if b.get("organisation") else 4]])),
        d.card(None, "Leadership changes", d.ul(lead) or f"<div{d.r.a('note')}>None in this release or recent news.</div>"),
    ]


def summary_html(b, fx=None):
    d = Doc(b, "pdf", fx)
    parts = summary_parts(d)
    official = next((x for x in b.get("documents") or [] if x.get("url") and x.get("kind") == "release"), None)
    parts.append(f"<div{d.r.a('src')}>Source: " + (f"<a href=\"{e(official['url'])}\">{e(official.get('title'))}</a>" if official else "company documents")
                 + f". {e(d.m.note())} Full detail in the companion document.</div>")
    return page("one", "".join(parts), b)


def page(cls, body, b):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{e(b.get('name'))} account update</title>"
            f"<style>{CSS}</style></head><body class='{cls}'>{body}</body></html>")


# ------------------------------------------------------------------ PDFs
def pdf_names(b):
    dt = str(b.get("release_date") or date.today().isoformat())[:10]
    stem = re.sub(r"[^A-Za-z0-9]+", "-", b.get("company") or b.get("name") or "client").strip("-")
    return REPORTS / f"{stem}-summary-{dt}.pdf", REPORTS / f"{stem}-full-{dt}.pdf"


def _pages(path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return 1


def make_pdfs(b):
    """Writes the summary and full PDFs; returns their paths ([] if Chromium is not available)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("PDF: skipped (playwright not installed)")
        return []
    REPORTS.mkdir(parents=True, exist_ok=True)
    summ, full = pdf_names(b)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.set_content(summary_html(b), wait_until="load")
        for scale in (1, 0.94, 0.88, 0.82, 0.76):  # shrink slightly until the summary fits on one page
            pg.pdf(path=str(summ), format="A4", print_background=True, prefer_css_page_size=True, scale=scale)
            if _pages(summ) <= 1:
                break
        pg.set_content(full_html(b), wait_until="load")
        pg.pdf(path=str(full), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
    return [summ, full]


# ------------------------------------------------------------------ e-mail
def summary_email(b, color=BLUE, fx=None):
    """The one-page summary for one client, as an e-mail block (inline styles only)."""
    d = Doc(b, "email", fx)
    body = "".join(summary_parts(d))
    body = re.sub(r"<div style=\"[^\"]*\">Account update · summary</div>", "", body, count=1)
    return (f"<div style=\"border-top:5px solid {color};padding:14px 0 4px;margin:18px 0 26px\">{body}"
            f"<div{d.r.a('src')}>{e(d.m.note())}</div></div>")


if __name__ == "__main__":
    import json
    briefs = json.loads((ROOT / "data" / "briefs.json").read_text(encoding="utf-8"))
    for co in sys.argv[1:] or list(briefs):
        print(co, [str(p) for p in make_pdfs(briefs[co])])
