"""
Client-by-client e-mail, built from data/briefs.json (written by agent/brief.py) and report.py.

 - New release: the one-page summary (key numbers, revenue by segment, area of focus, key changes, leadership) for each client that just reported, in the body.
   The full and summary PDFs are attached by notify.py.
 - Weekly round-up: one short card per client, grouped by industry.
Plain inline styles only, so it renders the same in Outlook, Gmail and on phones.
"""
import html
from datetime import date

import report
from agent.brief import FORMAT

INK, MUTED, LINE, SOFT, ACCENT = "#1B2333", "#5B6475", "#E4E7EC", "#F4F6FB", "#2F41BF"
INDUSTRY_ORDER = ["Media & Entertainment", "Gaming & Lottery", "Publishing & Information", "Education"]
VERDICT = {"Raised": "#0B7A0B", "Introduced": "#0B7A0B", "Reaffirmed": "#A86400", "Narrowed": "#A86400", "Mixed": "#A86400",
           "Lowered": "#B42318", "Withdrawn": "#B42318", "None given": MUTED}


def e(x):
    return html.escape(str(x)) if x not in (None, "") else ""


def pill(t):
    if not t:
        return ""
    c = VERDICT.get(t, MUTED)
    return (f"<span style='display:inline-block;color:{c};border:1px solid {c};border-radius:10px;padding:0 8px;"
            f"font-size:11px;font-weight:bold;white-space:nowrap'>Guidance {e(t.lower())}</span>")


def compact(b, color):
    """Short weekly card: headline, top spending focus and leadership changes."""
    m = report.Money()
    focus = [f"{x.get('area')}: {x.get('plan')}" for x in (b.get("focus") or [])[:2]]
    lead = [f"{e(x.get('person'))} ({e(str(x.get('change') or '').lower())})" for x in (b.get("leadership") or [])[:3]]
    lines = []
    if focus:
        lines.append(f"<b>Focus:</b> {e(m.text(' · '.join(focus)))}")
    if lead:
        lines.append(f"<b>Leadership:</b> {'; '.join(lead)}")
    return (f"<div style='border-left:4px solid {color};padding:8px 12px;margin:8px 0;background:{SOFT}'>"
            f"<b>{e(b.get('name') or b.get('company'))}</b> <span style='color:{MUTED};font-size:12px'>{e(b.get('period'))} · "
            f"released {e(report.nice_date(b.get('release_date')))}</span>"
            f"<div style='margin-top:4px'>{e(m.text(b.get('headline')))}</div>"
            + "".join(f"<div style='font-size:13px;margin-top:3px'>{x}</div>" for x in lines) + "</div>")


def status_card(r, color):
    st = {"private": "Private / non-profit · news only", "out-unread": f"Release filed {r.get('filed')} · update being prepared",
          "due": f"Next results due {r.get('due')}"}.get(r.get("state"), "Awaiting next results date")
    return (f"<div style='border-left:4px solid {color};padding:6px 12px;margin:6px 0'><b>{e(r.get('name') or r.get('company'))}</b>"
            f" · <span style='color:{MUTED}'>{e(st)}</span></div>")


def is_current(b, r):
    return bool(b) and b.get("format") == FORMAT and b.get("release_key") == (r or {}).get("release_key")


def email_html(rows, briefs, new_companies, weekly, links=None, generated="", attached=None):
    """rows: summary rows (company, name, industry, color, state, filed, due, release_key)."""
    by = {r["company"]: r for r in rows}
    out = [f"<div style='font-family:Segoe UI,Arial,sans-serif;color:{INK};max-width:780px;font-size:14px;line-height:1.5'>",
           f"<div style='color:{ACCENT};font-size:12px;font-weight:bold;letter-spacing:.08em;text-transform:uppercase'>"
           f"{'Weekly account round-up' if weekly and not new_companies else 'Account update'}</div>",
           f"<div style='color:{MUTED};font-size:12.5px;margin-bottom:6px'>{e(generated or date.today().isoformat())} · from official company documents</div>"]
    if new_companies:
        if attached:
            out.append(f"<p style='margin:6px 0 0;color:{MUTED};font-size:13px'>Attached for each company: a one-page summary and the full update (PDF).</p>")
        for c in new_companies:
            r, b = by.get(c) or {}, briefs.get(c)
            color = r.get("color", ACCENT)
            if is_current(b, r):
                out.append(report.summary_email(b, color))
            else:
                out.append(f"<div style='border-left:4px solid {color};padding:8px 12px;margin:14px 0;background:{SOFT}'>"
                           f"<b>{e(r.get('name') or c)}</b>: results are out; the full update follows after the next run.</div>")
    if weekly:
        out.append(f"<h2 style='font-size:16px;margin:24px 0 6px;padding-bottom:4px;border-bottom:1px solid #DCE1EA'>All companies, by industry</h2>")
        industries = INDUSTRY_ORDER + sorted({r["industry"] for r in rows} - set(INDUSTRY_ORDER))
        for ind in industries:
            members = [r for r in rows if r["industry"] == ind and r["company"] not in (new_companies or [])]
            if not members:
                continue
            out.append(f"<div style='font-weight:bold;color:{MUTED};text-transform:uppercase;font-size:12px;letter-spacing:.05em;margin:16px 0 2px'>{e(ind)}</div>")
            for r in members:
                b = briefs.get(r["company"])
                out.append(compact(b, r.get("color", ACCENT)) if b and b.get("format") == FORMAT else status_card(r, r.get("color", ACCENT)))
    lk = " · ".join(f"<a href='{e(u)}' style='color:{ACCENT}'>{e(n)}</a>" for n, u in (links or []))
    out.append(f"<p style='color:{MUTED};font-size:12px;margin-top:18px;border-top:1px solid {LINE};padding-top:8px'>"
               + (f"Dashboard: {lk}. " if lk else "")
               + "Sent automatically. Public information only; items marked (call) or (news) are not from the company's official documents.</p></div>")
    return "".join(out)
