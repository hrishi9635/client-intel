"""
Turns one client's account update (data/briefs.json, written by agent/brief.py) into:
  * a full PDF   - every point, in numbered, well-spaced sections
  * a summary PDF - one page with the main points
  * summary_email(b) - the same one-page summary as e-mail-safe HTML (inline styles, works in Outlook and Gmail)

PDFs are drawn by a headless Chromium (Playwright). If Chromium is not installed the e-mail is still sent,
just without attachments.

Try it on your own computer:  python report.py PSO   (writes the PDFs into data/reports/)
"""
import html
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent
REPORTS = ROOT / "data" / "reports"

BLUE, INK, MUTED, LINE, SOFT = "#2F41BF", "#1B2333", "#5B6475", "#E8EBF1", "#F4F6FB"
AMBER, GREEN, RED, GREY = "#A86400", "#0B7A0B", "#B42318", "#5B6475"
CHANGE_COLOR = {"raised": GREEN, "introduced": GREEN, "reaffirmed": AMBER, "kept": AMBER, "narrowed": AMBER,
                "lowered": RED, "withdrawn": RED}
LEAD_COLOR = {"appointed": GREEN, "promoted": GREEN, "new role": GREEN, "expanded role": GREEN, "joining": GREEN,
              "leaving": RED, "retiring": RED}
DEAL_COLOR = {"contract win": GREEN, "partnership": GREEN, "extension": GREEN, "acquisition": GREEN, "launch": GREEN,
              "contract loss": RED, "disposal": AMBER}

CSS = """
@page { size: A4; margin: 18mm 18mm 16mm 18mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Inter, "DejaVu Sans", Arial, sans-serif; color: #1B2333; font-size: 10.5pt; line-height: 1.55; margin: 0; }
.top { border-bottom: 3px solid #2F41BF; padding-bottom: 10px; margin-bottom: 22px; }
.kicker { color: #2F41BF; font-size: 9pt; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
h1 { font-family: Georgia, "Times New Roman", serif; font-size: 22pt; font-weight: 600; margin: 4px 0 2px; }
.meta { color: #5B6475; font-size: 9.5pt; }
section { margin: 0 0 22px; }
h2 { font-size: 13pt; margin: 0 0 8px; padding-bottom: 4px; border-bottom: 1px solid #DCE1EA; page-break-after: avoid; }
h2 .n { color: #2F41BF; margin-right: 6px; }
h3 { font-size: 10.5pt; margin: 12px 0 3px; page-break-after: avoid; }
p { margin: 4px 0 8px; }
ul { margin: 4px 0 8px 0; padding-left: 18px; }
li { margin: 3px 0; page-break-inside: avoid; }
tr { page-break-inside: avoid; }
.lead { background: #F4F6FB; border-left: 4px solid #2F41BF; padding: 10px 14px; margin: 0 0 22px; }
table { width: 100%; border-collapse: collapse; margin: 6px 0 10px; font-size: 10pt; }
th { text-align: left; font-weight: 600; color: #5B6475; font-size: 8.8pt; text-transform: uppercase; letter-spacing: .04em; padding: 6px 8px; border-bottom: 1.5px solid #C9D0DC; }
td { padding: 7px 8px; border-bottom: 1px solid #E8EBF1; vertical-align: top; }
.tag { display: inline-block; font-size: 8.5pt; font-weight: 700; padding: 1px 8px; border-radius: 10px; border: 1px solid currentColor; white-space: nowrap; }
.note { color: #5B6475; font-size: 8.8pt; }
.src { color: #5B6475; font-size: 8.5pt; line-height: 1.45; }
.src a { color: #2F41BF; text-decoration: none; }
body.one { font-size: 9.8pt; line-height: 1.45; }
body.one section { margin-bottom: 13px; page-break-inside: avoid; }
body.one .lead { margin-bottom: 14px; }
body.one .top { margin-bottom: 14px; }
body.one td, body.one th { padding: 4px 8px; }
body.one ul { margin: 4px 0; }
"""


def e(x):
    return html.escape(str(x)) if x not in (None, "") else ""


def nice_date(d):
    try:
        return datetime.fromisoformat(str(d)[:10]).strftime("%-d %B %Y")
    except (ValueError, TypeError):
        return str(d or "")


def text(s):
    """Escape, and show a trailing (call) / (news) marker in grey."""
    s = e(s)
    return re.sub(r"\s*\((on the )?(call|news)\)\s*$", lambda m: f" <span class='note'>({m.group(2)})</span>", s)


def src_note(x):
    return f" <span class='note'>({x['src']})</span>" if x.get("src") in ("call", "news") else ""


def tag(word, colors):
    if not word or str(word).lower() in ("n/a", "none", ""):
        return "<span class='note'>—</span>"
    c = colors.get(str(word).lower(), GREY)
    return f"<span class='tag' style='color:{c}'>{e(str(word).capitalize())}</span>"


def ul(items):
    items = [i for i in items if i]
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else ""


def tbl(head, rows, widths):
    if not rows:
        return ""
    th = "".join(f"<th style='width:{w}'>{e(h)}</th>" for h, w in zip(head, widths))
    return "<table><tr>" + th + "</tr>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


def change_word(x):
    c = str(x.get("change") or "").lower()
    return "kept" if c == "reaffirmed" else c


# ------------------------------------------------------------------ sections
def guidance_table(b, short=False):
    rows = []
    for x in b.get("guidance") or []:
        note = f"<br><span class='note'>{e(x.get('note'))}</span>" if x.get("note") and not short else ""
        prev = f" <span class='note'>from {e(x['previous'])}</span>" if short and x.get("previous") and change_word(x) not in ("kept",) else ""
        if short:
            rows.append([e(x.get("metric")) + src_note(x), e(x.get("new")), tag(change_word(x), CHANGE_COLOR) + prev])
        else:
            rows.append([e(x.get("metric")) + src_note(x), e(x.get("new")), e(x.get("previous")) or "<span class='note'>—</span>",
                         tag(change_word(x), CHANGE_COLOR) + note])
    if short:
        return tbl(["Item", "Now", "Status"], rows[:4], ["40%", "28%", "32%"])
    return tbl(["Item", "Now", "Before", "Status"], rows, ["34%", "22%", "22%", "22%"])


def leadership_rows(b):
    return [[f"<b>{e(x.get('person'))}</b>", e(x.get("role")),
             tag(x.get("change"), LEAD_COLOR) + (f" <span class='note'>{e(x.get('detail'))}</span>" if x.get("detail") else "") + src_note(x)]
            for x in b.get("leadership") or []]


def doc_links(b):
    out = []
    for d in b.get("documents") or []:
        if d.get("url"):
            kind = "Official" if d.get("official") else "Earnings call (third-party transcript)"
            out.append(f"{kind}: <a href='{e(d['url'])}'>{e(d.get('title') or 'document')}</a>")
    if b.get("news_used"):
        out.append("Leadership and technology items marked (news): recent news headlines")
    return out


def header(b, kind):
    meta = " · ".join(x for x in [e(b.get("document_type")), e(b.get("period")),
                                  f"released {e(nice_date(b.get('release_date')))}" if b.get("release_date") else ""] if x)
    return (f"<div class='top'><div class='kicker'>Account update · {kind}</div><h1>{e(b.get('name') or b.get('company'))}</h1>"
            f"<div class='meta'>{meta}</div></div>")


def full_html(b):
    out, n = [header(b, "full detail")], 0

    def sec(title, body, flow=True):
        nonlocal n
        if not body:
            return
        n += 1
        out.append(f"<section><h2><span class='n'>{n}</span>{e(title)}</h2>{body}</section>")

    if b.get("headline"):
        out.append(f"<div class='lead'>{text(b['headline'])}</div>")
    sec("Results at a glance", ul([text(x) for x in b.get("at_a_glance") or []]))

    g = guidance_table(b)
    if g or b.get("unit_outlook") or b.get("medium_term"):
        body = (f"<h3 style='margin-top:0'>Guidance — {e(b.get('guidance_verdict') or 'None given')}</h3>" + g if g else "")
        if b.get("guidance_notes"):
            body += "<p class='note'>" + " ".join(text(x) for x in b["guidance_notes"]) + "</p>"
        if b.get("unit_outlook"):
            body += "<h3>Outlook by business</h3>" + ul([f"<b>{e(x['unit'])}:</b> {text(x['outlook'])}" for x in b["unit_outlook"]])
        if b.get("medium_term"):
            body += "<h3>Medium-term targets</h3>" + ul([text(x) for x in b["medium_term"]])
        sec("Guidance", body)

    units = "".join(f"<h3>{e(u['unit'])}{' — ' + e(u['numbers']) if u.get('numbers') else ''}</h3>" + ul([text(p) for p in u.get("points") or []])
                    for u in b.get("units") or [])
    sec("How each business is doing", units.replace("<h3>", "<h3 style='margin-top:0'>", 1))

    org = b.get("organisation") or {}
    if org.get("summary") or org.get("units") or org.get("points"):
        body = f"<p>{text(org.get('summary'))}</p>" if org.get("summary") else ""
        body += tbl(["Unit", "Size", "What it includes", "Leader"],
                    [[f"<b>{e(u.get('unit'))}</b>", e(u.get("size")) or "—", e(u.get("includes")) or "—",
                      (e(u.get("leader")) or "—") + src_note(u)] for u in org.get("units") or []], ["26%", "16%", "34%", "24%"])
        body += ul([text(p) for p in org.get("points") or []])
        sec("Organisation changes" + (f" (from {org['effective']})" if org.get("effective") else ""), body)

    lr = leadership_rows(b)
    body = tbl(["Person", "Role", "Change"], lr, ["26%", "40%", "34%"]) if lr else "<p class='note'>No leadership changes in the documents.</p>"
    if b.get("unchanged"):
        body += f"<p class='note'>Unchanged: {e('; '.join(b['unchanged']))}</p>"
    sec("Leadership changes", body)

    tech = "".join(f"<h3>{e(t['topic'])}</h3>" + ul([text(p) for p in t.get("points") or []]) for t in b.get("technology") or [])
    sec("Technology & IT spending", tech.replace("<h3>", "<h3 style='margin-top:0'>", 1)
        or "<p class='note'>Nothing on technology or IT spending in the documents.</p>")

    sec("Contracts & partnerships", tbl(["Name", "Type", "Detail"],
                                        [[f"<b>{e(x.get('name'))}</b>", tag(x.get("type"), DEAL_COLOR), text(x.get("detail")) + src_note(x)]
                                         for x in b.get("deals") or []], ["30%", "18%", "52%"]))
    sec("Pressures & risks", ul([text(x) for x in b.get("risks") or []]))
    sec("In management's words", ul([f"“{e(q.get('quote'))}” <span class='note'>— {e(q.get('speaker'))}</span>" for q in b.get("quotes") or []]))
    sec("Key dates", tbl(["Date", "Event"], [[e(x.get("date")) or "—", text(x.get("event"))] for x in b.get("dates") or []], ["28%", "72%"]))
    links = doc_links(b)
    out.append("<section><h2>Sources</h2><div class='src'>" + "<br>".join(links)
               + "<br>Read automatically from public documents. Numbers, names and quotes not found in the sources were removed."
               + " Items marked (call) or (news) are not from the company's official documents.</div></section>")
    return page("full", "".join(out), b)


def summary_html(b):
    sm = b.get("summary") or {}
    happening = sm.get("happening") or (b.get("at_a_glance") or [])[:4]
    tech = sm.get("technology") or [p for t in (b.get("technology") or [])[:5] for p in (t.get("points") or [])[:1]]
    lead = [f"<b>{e(x.get('person'))}</b>, {e(x.get('role'))} — "
            f"<span style='color:{LEAD_COLOR.get(str(x.get('change')).lower(), GREY)}'>{e(str(x.get('change') or '').lower())}</span>"
            + (f" ({e(x.get('detail'))})" if x.get("detail") else "") + src_note(x) for x in (b.get("leadership") or [])[:6]]
    dates = [x for x in b.get("dates") or [] if x.get("date")][:5]
    out = [header(b, "summary")]
    if b.get("headline"):
        out.append(f"<div class='lead'>{text(b['headline'])}</div>")
    for title, body in [("What's happening", ul([text(x) for x in happening])),
                        (f"Guidance — {b.get('guidance_verdict') or 'None given'}", guidance_table(b, short=True)),
                        ("Leadership changes", ul(lead) or "<p class='note'>None in the documents.</p>"),
                        ("Technology & IT spending", ul([text(x) for x in tech]) or "<p class='note'>Nothing in the documents.</p>"),
                        ("Key dates", tbl(["Date", "Event"], [[f"<b>{e(x['date'])}</b>", text(x.get("event"))] for x in dates], ["30%", "70%"]))]:
        if body:
            out.append(f"<section><h2>{e(title)}</h2>{body}</section>")
    official = next((d for d in b.get("documents") or [] if d.get("official") and d.get("url")), None)
    out.append("<p class='src'>Source: " + (f"<a href='{e(official['url'])}'>{e(official.get('title'))}</a>" if official else "official documents")
               + ". Full detail in the companion document.</p>")
    return page("one", "".join(out), b)


def page(cls, body, b):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{e(b.get('name'))} account update</title>"
            f"<style>{CSS}</style></head><body class='{cls}'>{body}</body></html>")


# ------------------------------------------------------------------ PDFs
def pdf_names(b):
    d = str(b.get("release_date") or date.today().isoformat())[:10]
    stem = re.sub(r"[^A-Za-z0-9]+", "-", b.get("name") or b.get("company") or "client").strip("-")
    return REPORTS / f"{stem}-summary-{d}.pdf", REPORTS / f"{stem}-full-{d}.pdf"


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
        for html_text, path in ((summary_html(b), summ), (full_html(b), full)):
            pg.set_content(html_text, wait_until="load")
            pg.pdf(path=str(path), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
    return [summ, full]


# ------------------------------------------------------------------ e-mail (inline styles)
EMAIL_STYLE = {
    "lead": f"background:{SOFT};border-left:4px solid {BLUE};padding:10px 14px;margin:0 0 18px",
    "h2": f"font-size:16px;margin:20px 0 6px;padding-bottom:4px;border-bottom:1px solid #DCE1EA;color:{INK}",
    "th": f"text-align:left;color:{MUTED};font-size:11px;text-transform:uppercase;padding:5px 8px;border-bottom:1.5px solid #C9D0DC",
    "td": f"padding:6px 8px;border-bottom:1px solid {LINE};vertical-align:top;font-size:14px",
    "note": f"color:{MUTED};font-size:12px",
    "tag": "display:inline-block;font-size:11px;font-weight:bold;padding:0 8px;border-radius:10px;border:1px solid",
}


def inline(html_text):
    """Swap the PDF's CSS classes for inline styles that e-mail apps keep."""
    s = html_text
    s = s.replace("<div class='lead'>", f"<div style='{EMAIL_STYLE['lead']}'>")
    s = re.sub(r"<h2>", f"<h2 style='{EMAIL_STYLE['h2']}'>", s)
    s = s.replace("<table>", "<table style='border-collapse:collapse;width:100%;margin:4px 0 8px'>")
    s = re.sub(r"<th style='width:([^']+)'>", lambda m: f"<th style='{EMAIL_STYLE['th']};width:{m.group(1)}'>", s)
    s = s.replace("<td>", f"<td style='{EMAIL_STYLE['td']}'>")
    s = s.replace("<span class='note'>", f"<span style='{EMAIL_STYLE['note']}'>").replace("<p class='note'>", f"<p style='{EMAIL_STYLE['note']}'>")
    s = re.sub(r"<span class='tag' style='color:([^']+)'>", lambda m: f"<span style='{EMAIL_STYLE['tag']};color:{m.group(1)}'>", s)
    s = s.replace("<ul>", "<ul style='margin:4px 0 8px;padding-left:20px'>").replace("<li>", "<li style='margin:3px 0'>")
    s = s.replace("<section>", "<div>").replace("</section>", "</div>")
    return s


def summary_email(b, color=BLUE):
    """The one-page summary for one client, as an e-mail block."""
    body = summary_html(b)
    body = body[body.index("<div class='top'>"):body.rindex("<p class='src'>")]
    body = body.replace("<div class='top'><div class='kicker'>Account update · summary</div>", "<div>")
    body = re.sub(r"<h1>(.*?)</h1>", lambda m: f"<div style='font-family:Georgia,serif;font-size:22px;color:{INK}'><b>{m.group(1)}</b></div>", body)
    body = body.replace("<div class='meta'>", f"<div style='color:{MUTED};font-size:13px;margin:2px 0 14px'>")
    return (f"<div style='border-top:5px solid {color};padding:14px 0 6px;margin:18px 0 26px'>" + inline(body) + "</div>")


if __name__ == "__main__":
    import json
    briefs = json.loads((ROOT / "data" / "briefs.json").read_text(encoding="utf-8"))
    for co in sys.argv[1:] or list(briefs):
        print(co, [str(p) for p in make_pdfs(briefs[co])])
