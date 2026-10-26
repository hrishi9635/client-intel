"""
Sends the client-by-client account update by e-mail (one-page summary in the body, summary + full PDFs
attached; see report.py), and short Telegram alerts.

When it sends:
  * as soon as a company's results are out and its official documents have been read in depth
    (each release is announced once; the e-mail waits up to a day for the account update)
  * a weekly round-up on Mondays
  * NOTIFY_FORCE=yes sends a round-up right now (the "Run workflow" button can set it)
  * NOTIFY_RESEND=Pearson,Disney sends those companies' latest account update again
The very first time a channel is switched on it sends one "alerts are on" message with the current
status, instead of announcing every company that already reported.

Each channel is skipped quietly if its secrets are missing, and a problem with one channel never
stops the other.
  E-mail:   GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_TO (comma-separated for several people)
  Telegram: TELEGRAM_BOT_TOKEN (TELEGRAM_CHAT_ID is optional: found automatically after you
            send your bot any message)
"""
import html
import json
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

from agent.brief import FORMAT
from backup_summary import DATA, build, done_keys, money, new_results, pct, pulse_groups, site_links

STATE = DATA / "notify_state.json"


def e(x):
    return html.escape(str(x)) if x is not None else ""


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(st):
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def links(settings=None):
    return site_links()


def result_line(r):
    i = r["insight"] or {}
    m = i.get("metrics") or {}
    cur = i.get("currency") or r["currency"]
    bits = []
    if m.get("revenue_m"):
        bits.append(f"revenue {money(m['revenue_m'], cur)}")
    g = m.get("revenue_growth_yoy_pct") if m.get("revenue_growth_yoy_pct") is not None else m.get("organic_growth_pct")
    if g is not None:
        bits.append(f"{pct(g)} {'YoY' if m.get('revenue_growth_yoy_pct') is not None else 'organic'}")
    if m.get("operating_margin_pct") is not None:
        bits.append(f"operating margin {pct(m['operating_margin_pct'], False)}")
    if m.get("net_income_m") is not None:
        bits.append(f"net income {money(m['net_income_m'], cur)}")
    if i.get("guidance_change") not in (None, "unknown", "none"):
        bits.append(f"guidance {i['guidance_change']}")
    bits.append(f"IT outlook {r['it_outlook']}")
    return ", ".join(bits)


def status(r):
    return {"private": "news only", "out": f"results out {r['filed']}", "out-unread": f"filed {r['filed']}, being read",
            "due": f"due {r['due']}"}.get(r["state"], "awaiting date")


# ------------------------------------------------------------------ PDF
def make_pdf(s, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    small = ss["Normal"].clone("small", fontSize=7.5, leading=9)
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm, title="Client Intelligence snapshot")
    k = s["kpi"]
    story = [Paragraph(f"Client Intelligence · snapshot", ss["Title"]),
             Paragraph(f"Generated {e(s['generated'])} · last agent run {e(s['last_run'])}", ss["Normal"]), Spacer(1, 4)]
    if (s["sector"] or {}).get("headline"):
        story += [Paragraph(f"<b>{e(s['sector']['headline'])}</b>", ss["Normal"]), Spacer(1, 4)]
    o = k["outlooks"]
    kt = Table([["Results out (last 60 days)", "Median operating margin", "Median revenue growth (YoY)", "IT spend outlook"],
                [f"{k['reported']}/{k['listed']}", pct(k["median_margin"], False), pct(k["median_yoy"]),
                 f"{o['Expanding']} expanding · {o['Stable']} stable · {o['Tightening']} tightening"]],
               colWidths=[50 * mm, 60 * mm, 60 * mm, 100 * mm])
    kt.setStyle(TableStyle([("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5B6475")), ("FONTSIZE", (0, 0), (-1, 0), 8),
                            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("FONTSIZE", (0, 1), (-1, 1), 12),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4E7EC")), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4E7EC")),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [kt, Spacer(1, 6)]
    head = ["Company", "Industry", "Status", "Quarter", "Revenue", "YoY", "Op. margin", "Mood", "IT outlook", "Market value"]
    data = [head]
    for r in s["rows"]:
        data.append([r["company"], r["industry"], status(r), r["period"] or "—", money(r["revenue"], r["currency"]),
                     pct(r["rev_yoy"]), pct(r["op_margin"], False), r["sentiment"] or "—", r["it_outlook"],
                     money(r["mcap_usd"], "USD") if r["mcap_usd"] else "—"])
    t = Table(data, repeatRows=1)
    style = [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F5F9")), ("ALIGN", (4, 1), (6, -1), "RIGHT"),
             ("ALIGN", (9, 1), (9, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4E7EC")),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for idx, r in enumerate(s["rows"], 1):
        style += [("TEXTCOLOR", (0, idx), (0, idx), colors.HexColor(r["color"])), ("FONTNAME", (0, idx), (0, idx), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    story += [t, Spacer(1, 6)]
    extras = []
    for x in ((s["sector"] or {}).get("industries") or [])[:4]:
        extras.append(f"<b>{e(x.get('industry'))}</b> (mood {e(x.get('mood'))}, IT spend {e(x.get('it_outlook'))}): {e(x.get('summary'))}")
    ind = (s.get("industry") or {}).get("areas") or {}
    if ind:
        extras.append("<b>Industry news mood:</b> " + " · ".join(f"{e(n)} {e(x.get('mood') or '—')}" for n, x in ind.items()))
    if (s.get("pulse") or {}).get("titles"):
        g = pulse_groups(s["pulse"])
        extras.append("<b>Audience Pulse:</b> " + " · ".join(
            f"{e(n)}: avg score {e(v['avg_score'] if v['avg_score'] is not None else '—')}, {e(v['positive'] if v['positive'] is not None else '—')}% positive"
            for n, v in g.items()))
    for x in extras:
        story.append(Paragraph(x, small))
    story += [Spacer(1, 4), Paragraph("AI-extracted figures should be checked against company releases. Public information only. "
                                      "Not investment advice.", small)]
    doc.build(story)
    return path


# ------------------------------------------------------------------ email
def email_html(s, settings, new, weekly):
    k = s["kpi"]
    td = "padding:6px 8px;border-bottom:1px solid #eee"
    rows = "".join(
        f"<tr><td style='{td}'><b style='color:{r['color']}'>●</b> {e(r['company'])}</td><td style='{td}'>{e(status(r))}</td>"
        f"<td style='{td};text-align:right'>{e(money(r['revenue'], r['currency']))}</td>"
        f"<td style='{td};text-align:right'>{e(pct(r['rev_yoy']))}</td>"
        f"<td style='{td}'>{e(r['sentiment'] or '—')}</td><td style='{td}'>{e(r['it_outlook'])}</td></tr>" for r in s["rows"])
    newhtml = "".join(
        f"<div style='border-left:4px solid {r['color']};padding:8px 12px;margin:10px 0;background:#F7F8FB'>"
        f"<b>{e(r['name'])}</b> – results{' (filed ' + e(r['filed']) + ')' if r['filed'] else ''}<br>"
        f"{e(result_line(r))}<br><i>{e(r['headline'])}</i>"
        + ("<br>Talking points: " + e("; ".join(r["talking_points"][:3])) if r["talking_points"] else "") + "</div>" for _, r in new)
    ind = (s.get("industry") or {}).get("areas") or {}
    indhtml = "".join(f"<li><b>{e(n)}</b> – mood {e(x.get('mood') or '—')}: {e(x.get('mood_reason') or '')}</li>" for n, x in ind.items())
    lk = " · ".join(f"<a href='{e(u)}'>{e(n)}</a>" for n, u in links(settings))
    head = (s["sector"] or {}).get("headline")
    return f"""<div style='font-family:Arial,sans-serif;color:#16213E;max-width:720px'>
<h2 style='margin:0 0 4px'>Client Intelligence</h2>
<p style='color:#5B6475;margin:0 0 12px'>{'Weekly round-up' if weekly else 'New results'} · {e(s['generated'])}</p>
{f"<p><b>{e(head)}</b></p>" if head else ''}
{('<h3>Just reported</h3>' + newhtml) if new else ''}
<p><b>{k['reported']}/{k['listed']}</b> listed companies reported in the last 60 days · median growth <b>{e(pct(k['median_yoy']))}</b>
· median operating margin <b>{e(pct(k['median_margin'], False))}</b></p>
<table style='border-collapse:collapse;font-size:13px;width:100%'><tr style='background:#F3F5F9;text-align:left'>
<th style='padding:6px 8px'>Organisation</th><th style='padding:6px 8px'>Status</th><th style='padding:6px 8px;text-align:right'>Revenue</th>
<th style='padding:6px 8px;text-align:right'>YoY</th><th style='padding:6px 8px'>Mood</th><th style='padding:6px 8px'>IT outlook</th></tr>{rows}</table>
{f"<h3>Industry news</h3><ul>{indhtml}</ul>" if indhtml and weekly else ''}
<p>Full dashboard: {lk or '—'}</p><p style='color:#5B6475;font-size:12px'>A one-page PDF snapshot is attached. Sent automatically by your agent.</p></div>"""


def load_briefs():
    try:
        return json.loads((DATA / "briefs.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def brief_ready(r, briefs):
    """Wait for the account update (up to a day after the release) so the e-mail carries the full analysis."""
    b = briefs.get(r["company"]) or {}
    if b.get("release_key") == r.get("release_key") and b.get("format") == FORMAT:
        return True
    try:
        filed = datetime.fromisoformat(str(r.get("filed"))[:10]).date()
        return (datetime.now(timezone.utc).date() - filed).days >= 1
    except ValueError:
        return True


def send_email(s, settings, new, weekly, intro=False):
    """Client-by-client account update. Returns True when sent."""
    import brief_email
    import report
    user, pw, to = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD"), os.environ.get("EMAIL_TO")
    if not (user and pw and to):
        print("Email: skipped (GMAIL_USER / GMAIL_APP_PASSWORD / EMAIL_TO not set)")
        return False
    briefs = load_briefs()
    by = {r["company"]: r for r in s["rows"]}
    new_cos = [r["company"] for _, r in new]
    pdfs = []
    for c in new_cos:
        b = briefs.get(c)
        if brief_email.is_current(b, by.get(c)):
            try:
                pdfs += report.make_pdfs(b)
            except Exception as ex:  # noqa: BLE001  # the e-mail still goes, without that PDF
                print(f"Email: PDF for {c} skipped ({type(ex).__name__}: {str(ex)[:150]})")
    if new:
        tags = []
        for c in new_cos:
            b = briefs.get(c) or {}
            name = (by.get(c) or {}).get("name") or c
            tags.append(name + (f" (guidance {str(b.get('guidance_verdict')).lower()})" if b.get("guidance_verdict") else ""))
        subject = f"Account update · {'; '.join(tags)}"
    elif intro:
        subject = "Client Intelligence account updates are on"
    else:
        subject = f"Weekly account round-up · {datetime.now(timezone.utc):%d %b %Y}"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content("Your email app shows the HTML version of this message.")
    msg.add_alternative(brief_email.email_html(s["rows"], briefs, new_cos, weekly or intro, links(settings), s.get("generated"),
                                               attached=bool(pdfs)), subtype="html")
    for p in pdfs:
        msg.add_attachment(p.read_bytes(), maintype="application", subtype="pdf", filename=p.name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as smtp:
        smtp.login(user, pw)
        smtp.send_message(msg)
    print(f"Email: sent '{subject}'" + (f" with {len(pdfs)} PDFs" if pdfs else ""))
    return True


# ------------------------------------------------------------------ Telegram
def telegram_chat(token):
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if cid:
        return cid
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
    chats = [u.get("message", {}).get("chat", {}).get("id") for u in r.get("result", []) if u.get("message")]
    return str(chats[-1]) if chats else None


def send_telegram(s, settings, new, weekly, intro=False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Telegram: skipped (TELEGRAM_BOT_TOKEN not set)")
        return False
    chat = telegram_chat(token)
    if not chat:
        print("Telegram: no chat found yet – open your bot in Telegram and send it any message (e.g. 'hi')")
        return False
    k = s["kpi"]
    parts = []
    if intro:
        parts.append("🔔 <b>Client Intelligence alerts are on.</b> You'll get a message as soon as a company reports.")
    for _, r in new:
        parts.append(f"📊 <b>{e(r['name'])}</b> results out\n{e(result_line(r))}\n<i>{e(r['headline'])}</i>")
    if weekly or intro:
        waiting = [r["company"] + (f" ({r['due']})" if r["due"] else "") for r in s["rows"] if r["type"] != "private" and not r["reported"]]
        parts.append(f"🗓 <b>{k['reported']}/{k['listed']}</b> listed companies reported in the last 60 days. "
                     f"Median growth {e(pct(k['median_yoy']))}."
                     + (f"\nStill to report: {e(', '.join(waiting))}" if waiting else ""))
        ind = (s.get("industry") or {}).get("areas") or {}
        if ind:
            parts.append("📰 Industry mood: " + " · ".join(f"{e(n)} {e(x.get('mood') or '—')}" for n, x in ind.items()))
    lk = links(settings)
    if lk:
        parts.append(" · ".join(f"<a href='{e(u)}'>{e(n)}</a>" for n, u in lk))
    text = "\n\n".join(parts)[:4000]
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    r.raise_for_status()
    print("Telegram: message sent")
    return True


# ------------------------------------------------------------------ main
def main():
    settings = None
    s = build()
    state = load_state()
    force = os.environ.get("NOTIFY_FORCE", "").lower() in ("yes", "true", "1")
    today = datetime.now(timezone.utc)
    briefs = load_briefs()
    for channel, sender in (("email", send_email), ("telegram", send_telegram)):
        st = state.setdefault(channel, {})
        intro = "announced" not in st
        new = [] if intro else new_results(s, st)  # first time: one "alerts are on" message, not a flood
        if channel == "email":
            new = [(k, r) for k, r in new if brief_ready(r, briefs)]
            # "Run workflow" -> "Send again" box: e-mail these companies' latest update again (e.g. Pearson)
            again = {x.strip().lower() for x in os.environ.get("NOTIFY_RESEND", "").split(",") if x.strip()}
            have = {r["company"] for _, r in new}
            new += [(f"{r['company']}|{r['release_key']}", r) for r in s["rows"]
                    if r["reported"] and r["company"] not in have
                    and (r["company"].lower() in again or str(r.get("name") or "").lower() in again)]
        weekly = force or (today.weekday() == 0 and st.get("last_weekly") != today.date().isoformat())
        if not (new or weekly or intro):
            print(f"{channel.title()}: nothing new")
            continue
        try:
            sent = sender(s, settings, new, weekly, intro=intro)
        except Exception as ex:  # noqa: BLE001
            print(f"{channel.title()}: problem – {type(ex).__name__}: {str(ex)[:200]}")
            continue
        if sent:
            # only what was actually announced (e-mails may wait for the in-depth brief)
            sent_keys = done_keys(s) if (intro or channel != "email") else {k for k, _ in new}
            st["announced"] = sorted(set(st.get("announced", [])) | sent_keys)
            if weekly or intro:
                st["last_weekly"] = today.date().isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
