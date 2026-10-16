"""
Builds a static copy of the dashboard (docs/index.html) from the data the agent saved.
Cloudflare Pages publishes the "docs" folder after every agent run. It never sleeps, loads fast,
and keeps working even if the Streamlit site is down.
"""
import html
import json
from pathlib import Path

from backup_summary import build, money, pct, pulse_groups, site_links

OUT = Path(__file__).parent / "docs"


def e(x):
    return html.escape(str(x)) if x is not None else ""


def pill(word):
    w = (word or "").lower()
    cls = "pos" if w in ("positive", "raised", "introduced", "expanding", "hit") else \
        "neg" if w in ("negative", "cut", "tightening", "under-performing") else \
        "mid" if w in ("neutral", "mixed", "retained", "on track") else "blu" if w == "stable" else "na"
    return f"<span class='pill {cls}'>{e(word or 'n/a')}</span>" if word else ""


def ul(items):
    items = [x for x in (items or []) if x]
    return "<ul>" + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>" if items else "<p class='sub'>—</p>"


def status_html(r):
    if r["state"] == "private":
        return "<span class='na'>private · news only</span>"
    if r["state"] == "out":
        return f"<span class='pos'>results out {e(r['filed'])}</span>"
    if r["state"] == "out-unread":
        return f"<span class='mid'>release filed {e(r['filed'])} · being read</span>"
    if r["state"] == "due":
        return f"<span class='na'>due {e(r['due'])}</span>"
    return "<span class='na'>awaiting date</span>"


def company_card(r):
    i = r["insight"] or {}
    tiles = ""
    if r["type"] != "private":
        tl = [("Revenue " + (r["period"] or ""), money(r["revenue"], r["currency"])), ("Revenue YoY", pct(r["rev_yoy"])),
              ("Op. margin", pct(r["op_margin"], False)), ("Net income", money(r["net_income"], r["currency"])),
              ("Market value", money(r["mcap_usd"], "USD") if r["mcap_usd"] else "—"), ("1-yr return", pct(r["ret_1y"]))]
        tiles = "<div class='minis'>" + "".join(f"<div class='mini'><span>{e(a)}</span><b>{e(v)}</b></div>" for a, v in tl) + "</div>"
    rel = i.get("release") or {}
    res = ((f"<p class='lead'>{e(i.get('headline'))} {pill(i.get('sentiment'))}</p>" if i.get("headline") else "")
           + (f"<p class='sub'>📄 <a href='{e(rel.get('url'))}' target='_blank' rel='noopener'>{e(rel.get('title'))}</a></p>" if rel.get("url") else "")
           + (f"<h4>Guidance {pill(i.get('guidance_change'))}</h4><p>{e(i.get('guidance'))}</p>" if i.get("guidance") else "")
           + ("<h4>Highlights</h4>" + ul(i.get("highlights")) if i.get("highlights") else "")
           + ("<h4>Risks</h4>" + ul(i.get("risks")) if i.get("risks") else ""))
    sigs = [f"{x.get('type')}: {x.get('detail')}" if isinstance(x, dict) else str(x) for x in r["it_signals"]]
    signals = (f"<h4>IT services signals {pill(r['it_outlook'])}</h4><p class='sub'>{e(r['it_reason'] or '')}</p>" + ul(sigs)
               + "<h4>Talking points</h4>" + ul(r["talking_points"]))
    srcs, seen = [], set()
    for s_ in i.get("sources") or []:
        if s_.get("link") not in seen:
            seen.add(s_.get("link"))
            srcs.append(s_)
    src_html = "<h4>Sources</h4><ul class='src'>" + "".join(
        f"<li>{'📄 ' if s.get('official') else ''}<a href='{e(s.get('link'))}' target='_blank' rel='noopener'>{e(s.get('title'))}</a>"
        f" <span class='sub'>{e(s.get('source'))} · {e((s.get('published') or '')[:10])}</span></li>" for s in srcs[:12]) + "</ul>" if srcs else ""
    return f"""<details class='card co' style='border-left-color:{r["color"]}'>
<summary><b>{e(r['name'])}</b> <span class='sub'>· {e(r['industry'])}</span> · {status_html(r)} · IT {pill(r['it_outlook'])}</summary>
{f"<p class='sub'>{e(r['note'])}</p>" if r.get('note') else ''}{tiles}{res}{signals}{src_html}</details>"""


def audience_html(s):
    aud = s.get("pulse") or {}
    titles = aud.get("titles") or []
    if not titles:
        return "<p class='sub'>Audience Pulse appears after the first daily run (needs the TMDB_KEY secret).</p>"
    stats = pulse_groups(aud)
    k = "".join(f"<div class='kpi'><span>{e(g)}</span><b>{e(v['avg_score'] if v['avg_score'] is not None else '—')}</b>"
                f"<div class='sub'>avg audience score · {v['titles']} titles · {e(v['positive'] if v['positive'] is not None else '—')}% positive</div></div>"
                for g, v in stats.items())
    cols = ""
    for g in ("Tracked companies", "Rest of industry"):
        rows = ""
        for t in sorted([t for t in titles if t.get("group") == g], key=lambda t: -(t.get("popularity") or 0))[:12]:
            a = t.get("ai") if isinstance(t.get("ai"), dict) else {}
            rows += (f"<li><b>{e(t['title'])}</b> <span class='sub'>{e({'movie': 'Movie', 'tv': 'Show'}.get(t.get('kind'), t.get('kind')))} · {e(t.get('parent'))} · {e(t.get('release_date'))}"
                     f"{' · upcoming' if t.get('upcoming') else ''}</span> {pill(a.get('audience_sentiment'))}<br>"
                     f"<span class='sub'>{e(a.get('summary') or '')}</span></li>")
        cols += f"<div class='card'><h4>{e(g)}</h4><ul class='plain'>{rows or '<li>—</li>'}</ul></div>"
    return (f"<p class='sub'>Online audience opinion, not a representative survey. Sources: TMDB, OMDb, Reddit, trade press.</p>"
            f"<div class='kpis'>{k}</div><div class='grid2'>{cols}</div>")


def industry_html(s):
    ind = (s.get("industry") or {}).get("areas") or {}
    if not ind:
        return "<p class='sub'>Industry News appears after the first daily run.</p>"
    out = ""
    for name, x in ind.items():
        h = (s.get("industry_hist") or {}).get(name) or []
        prev = h[-2]["mood"] if len(h) >= 2 else None
        stories = "".join(f"<li><a href='{e(t.get('link'))}' target='_blank' rel='noopener'>{e(t.get('title'))}</a>"
                          f" <span class='sub'>{e(t.get('source'))} · {e((t.get('published') or '')[:10])}</span><br>{e(t.get('why'))}</li>"
                          for t in x.get("top_stories") or [])
        themes = ", ".join(e(t if isinstance(t, str) else t.get("theme")) for t in x.get("themes") or [])
        ment = "".join(f"<li><b>{e(m.get('company'))}</b>: {e(m.get('note'))}</li>" for m in x.get("tracked_mentions") or [] if isinstance(m, dict))
        out += (f"<div class='card'><h4>{e(name)} {pill(x.get('mood'))}</h4><p class='sub'>{e(x.get('mood_reason') or '')}"
                + (f" · previous reading: {e(prev)}" if prev else "") + "</p>"
                + (f"<p><b>Themes:</b> {themes}</p>" if themes else "")
                + (f"<p><b>For technology vendors:</b> {e(x.get('it_implications'))}</p>" if x.get("it_implications") else "")
                + (f"<p><b>Tracked organisations in the news</b></p><ul>{ment}</ul>" if ment else "")
                + f"<ul class='src'>{stories}</ul></div>")
    return f"<div class='grid2'>{out}</div>"


def page(s):
    k = s["kpi"]
    sec = s["sector"] or {}
    rows = s["rows"]
    chips = "".join(
        f"<span class='chip' style='border-color:{r['color']}'><i style='background:{r['color']}'></i>{e(r['company'])} · "
        + status_html(r) + "</span>" for r in rows)
    cols = [("Company", "company", None), ("Industry", "industry", None), ("Quarter", "period", None),
            ("Revenue", "revenue", "m"), ("Revenue (US$)", "revenue_usd", "usd"), ("YoY", "rev_yoy", "s"),
            ("Op. margin", "op_margin", "p"), ("Guidance", "guidance_change", None), ("Mood", "sentiment", None),
            ("IT outlook", "it_outlook", None), ("Market value", "mcap_usd", "usd"), ("1Y return", "ret_1y", "s"), ("P/E", "pe", "n")]

    def cell(r, key, kind):
        v = r[key]
        if v is None or v == "":
            return "<td data-v=''>—</td>"
        if kind == "m":
            return f"<td data-v='{r.get('revenue_usd') or v}' class='num'>{money(v, r['currency'])}</td>"
        if kind == "usd":
            return f"<td data-v='{v}' class='num'>{money(v, 'USD')}</td>"
        if kind == "s":
            return f"<td data-v='{v}' class='num'>{pct(v)}</td>"
        if kind == "p":
            return f"<td data-v='{v}' class='num'>{pct(v, False)}</td>"
        if kind == "n":
            return f"<td data-v='{v}' class='num'>{v:,.1f}</td>"
        if key == "company":
            return f"<td data-v='{e(v)}'><i class='dot' style='background:{r['color']}'></i>{e(v)}</td>"
        return f"<td data-v='{e(v)}'>{e(v)}</td>"

    table = "<table id='sc'><thead><tr>" + "".join(f"<th class='{'num' if kind else ''}'>{c}</th>" for c, _, kind in cols) + \
        "</tr></thead><tbody>" + "".join("<tr>" + "".join(cell(r, key, kind) for _, key, kind in cols) + "</tr>" for r in rows) + "</tbody></table>"
    industries = "".join(
        f"<div class='card ind'><h4>{e(x.get('industry'))} <span>IT spend {pill(x.get('it_outlook'))}</span></h4>"
        f"<p>Mood {pill(x.get('mood'))}</p><p>{e(x.get('summary'))}</p>"
        f"<p><b>Doing well:</b> {e('; '.join(str(l.get('company')) + ' – ' + str(l.get('why')) for l in x.get('leaders') or []) or '—')}</p>"
        f"<p><b>Under pressure:</b> {e('; '.join(str(l.get('company')) + ' – ' + str(l.get('why')) for l in x.get('laggards') or []) or '—')}</p>"
        f"<p><b>For technology vendors:</b> {e(x.get('it_note') or '—')}</p></div>"
        for x in sec.get("industries") or [])
    if sec.get("watch_next"):
        industries += f"<div class='card'><h4>Watch next</h4>{ul(sec.get('watch_next'))}</div>"
    sig_rows = "".join(
        f"<tr><td><i class='dot' style='background:{r['color']}'></i>{e(r['company'])}</td><td>{e(r['industry'])}</td>"
        f"<td>{pill(r['it_outlook'])}</td><td class='tw'>{e(r['it_reason'] or '—')}</td>"
        f"<td class='tw'>{e('; '.join(r['talking_points']) or '—')}</td></tr>" for r in rows)
    news = "".join(f"<li><a href='{e(n.get('link'))}' target='_blank' rel='noopener'>{e(n.get('title'))}</a> "
                   f"<span class='sub'>{e(n.get('company'))} · {e(n.get('source'))} · {e((n.get('published') or '')[:10])}</span></li>"
                   for n in s["news"][:40])
    links = " · ".join(f"<a href='{u}' target='_blank' rel='noopener'>{e(t)}</a>" for t, u in site_links()) or "—"
    cards = "".join(company_card(r) for r in rows)
    data = json.dumps({"rows": [{k2: r[k2] for k2 in ("company", "color", "revenue_usd", "rev_yoy", "op_margin", "type")} for r in rows],
                       "history": s["history"]}, ensure_ascii=False, default=str)

    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Client Intelligence</title>
<meta name='description' content='Results, IT-services signals, audience opinion and industry news for media, gaming, publishing and education organisations.'>
<link rel='preconnect' href='https://fonts.googleapis.com'>
<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:wght@600&display=swap' rel='stylesheet'>
<script src='https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js'></script>
<style>
:root{{--bg:#F6F7FB;--panel:#fff;--ink:#16213E;--muted:#5B6475;--line:#E4E7EC;--pos:#0A7F0A;--neg:#C62828;--mid:#9A6700;--blu:#2A78D6;--accent:#2A78D6}}
@media (prefers-color-scheme:dark){{:root:not([data-theme='light']){{--bg:#121417;--panel:#1B1E23;--ink:#ECEDEF;--muted:#A3A9B4;--line:#2B3038;--pos:#4CC24C;--neg:#F07171;--mid:#E0B341;--blu:#5A9BE6;--accent:#5A9BE6}}}}
:root[data-theme='dark']{{--bg:#121417;--panel:#1B1E23;--ink:#ECEDEF;--muted:#A3A9B4;--line:#2B3038;--pos:#4CC24C;--neg:#F07171;--mid:#E0B341;--blu:#5A9BE6;--accent:#5A9BE6}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}}
.wrap{{max-width:1240px;margin:0 auto;padding:24px 16px 60px}}
h1{{font-family:'Source Serif 4',Georgia,serif;font-size:2rem;margin:0 0 4px}} h2{{margin:34px 0 12px;font-size:1.3rem}}
h4{{margin:10px 0 4px}} a{{color:var(--accent)}} .sub{{color:var(--muted);font-size:.84rem}}
.lead{{font-size:1.05rem;margin:8px 0 12px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:16px 0}}
.kpi,.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}}
.kpi span{{color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.04em}}
.kpi b{{display:block;font-family:'Source Serif 4',Georgia,serif;font-size:1.8rem;margin-top:4px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px}} .chip{{background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:10px;padding:5px 10px;font-size:.82rem}}
.chip i,.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .mid{{color:var(--mid)}} .na{{color:var(--muted)}} .blu{{color:var(--blu)}}
.pill{{border:1px solid currentColor;border-radius:999px;padding:1px 9px;font-size:.72rem;font-weight:600;white-space:nowrap}}
.scroll{{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px}}
table{{border-collapse:collapse;width:100%;font-size:.86rem}} th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap;vertical-align:top}}
td.tw{{white-space:normal;min-width:220px}} .card h4{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}} .ind h4>span:last-child{{margin-left:auto}}
th{{cursor:pointer;color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel)}} td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr));gap:12px}}
.chart{{background:var(--panel);border:1px solid var(--line);border-radius:14px;min-height:380px}}
details.co{{border-left:5px solid var(--accent);margin-bottom:10px}} details.co summary{{cursor:pointer;font-size:1rem}}
.minis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}}
.mini{{border:1px solid var(--line);border-radius:10px;padding:8px 10px}} .mini span{{color:var(--muted);font-size:.72rem;display:block}}
ul{{margin:4px 0 8px;padding-left:20px}} ul.src li,.news li{{margin:6px 0}} .news,ul.plain{{list-style:none;padding:0}}
ul.plain li{{padding:6px 0;border-bottom:1px solid var(--line)}}
.news li{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px}}
header .sub a{{white-space:nowrap}}
</style></head><body><div class='wrap'>
<header><h1>Client Intelligence</h1>
<p class='sub'>Last agent run {e(s['last_run'])} · page built {e(s['generated'])}<br>
Other copies: {links}</p>
{f"<p class='lead'>{e(sec.get('headline'))}</p>" if sec.get('headline') else ''}</header>
<div class='kpis'>
<div class='kpi'><span>Results out (last 60 days)</span><b>{k['reported']}/{k['listed']}</b><div class='sub'>listed companies, official releases only</div></div>
<div class='kpi'><span>Median operating margin</span><b>{pct(k['median_margin'], False)}</b><div class='sub'>latest period</div></div>
<div class='kpi'><span>Median revenue growth</span><b>{pct(k['median_yoy'])}</b><div class='sub'>year on year</div></div>
<div class='kpi'><span>IT spend outlook</span><b>{k['outlooks']['Expanding']}↑ {k['outlooks']['Tightening']}↓</b><div class='sub'>{k['outlooks']['Expanding']} expanding · {k['outlooks']['Stable']} stable · {k['outlooks']['Tightening']} tightening</div></div>
</div>
<div class='chips'>{chips}</div>
<h2>Scorecard</h2><p class='sub'>Click a column to sort. Official numbers (SEC filings, company releases) win over Yahoo Finance. Periods are calendar quarters (or half-years for European companies).</p>
<div class='scroll'>{table}</div>
<div class='grid2' style='margin-top:12px'><div id='bubble' class='chart'></div><div id='rev' class='chart'></div></div>
<div class='grid2' style='margin-top:12px'><div id='trend' class='chart'></div><div id='margin' class='chart'></div></div>
<h2>Industry view</h2>{f"<div class='grid2'>{industries}</div>" if industries else "<p class='sub'>Appears after the first AI run.</p>"}
<h2>IT opportunity signals</h2>
<div class='scroll'><table><thead><tr><th>Company</th><th>Industry</th><th>Outlook</th><th>Why</th><th>Talking points</th></tr></thead><tbody>{sig_rows}</tbody></table></div>
<h2>Audience Pulse</h2>{audience_html(s)}
<h2>Industry News</h2>{industry_html(s)}
<h2>Organisations</h2><p class='sub'>Click one to open its details.</p>{cards}
<h2>Latest news</h2><ul class='news'>{news}</ul>
<p class='sub' style='margin-top:30px'>Backup copy, rebuilt automatically after every agent run from SEC EDGAR, company releases, Yahoo Finance, TMDB, OMDb and news.
AI-extracted figures should be checked against company releases. Public information about industry players only. Not investment advice.</p>
</div>
<script>
const D={data};
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const L=(t,extra)=>Object.assign({{title:{{text:t,font:{{size:15}}}},paper_bgcolor:css('--panel'),plot_bgcolor:css('--panel'),
 font:{{family:'Inter, sans-serif',color:css('--ink'),size:12}},margin:{{l:60,r:20,t:48,b:48}},showlegend:false,
 xaxis:{{gridcolor:css('--line'),zerolinecolor:css('--line')}},yaxis:{{gridcolor:css('--line'),zerolinecolor:css('--line')}}}},extra||{{}});
const cfg={{displayModeBar:false,responsive:true}};
if(window.Plotly){{
 const b=D.rows.filter(r=>r.op_margin!=null&&r.rev_yoy!=null);
 const mx=Math.max(...b.map(r=>r.revenue_usd||1));
 Plotly.newPlot('bubble',[{{x:b.map(r=>r.rev_yoy),y:b.map(r=>r.op_margin),text:b.map(r=>r.company),mode:'markers+text',textposition:'top center',
  marker:{{size:b.map(r=>12+40*Math.sqrt((r.revenue_usd||mx*0.1)/mx)),color:b.map(r=>r.color),opacity:.85,line:{{color:'white',width:2}}}},
  hovertemplate:'<b>%{{text}}</b><br>Growth %{{x:+.1f}}%<br>Margin %{{y:.1f}}%<extra></extra>'}}],
  L('Growth vs margin (bubble = revenue)',{{xaxis:{{title:'Revenue growth YoY (%)',ticksuffix:'%',gridcolor:css('--line')}},yaxis:{{title:'Operating margin (%)',ticksuffix:'%',gridcolor:css('--line')}}}}),cfg);
 const r=D.rows.filter(r=>r.revenue_usd).sort((a,b)=>a.revenue_usd-b.revenue_usd);
 const fmt=v=>v>=1000?'$'+(v/1000).toFixed(1)+'bn':'$'+Math.round(v)+'m';
 Plotly.newPlot('rev',[{{type:'bar',orientation:'h',x:r.map(x=>x.revenue_usd),y:r.map(x=>x.company),marker:{{color:r.map(x=>x.color)}},
  text:r.map(x=>fmt(x.revenue_usd)),textposition:'outside',cliponaxis:false,hovertemplate:'%{{y}}: $%{{x:,.0f}}m<extra></extra>'}}],
  L('Latest quarterly revenue (US$)',{{xaxis:{{showticklabels:false,gridcolor:css('--line')}},margin:{{l:120,r:70,t:48,b:30}}}}),cfg);
 const tr=[],mg=[];
 for(const row of D.rows){{ if(row.type==='private')continue; const h=D.history[row.company]||[];const base=(h.find(p=>p.revenue)||{{}}).revenue;
  tr.push({{x:h.map(p=>p.period),y:h.map(p=>p.revenue&&base?p.revenue/base*100:null),name:row.company,mode:'lines+markers',line:{{color:row.color,width:2}},marker:{{size:6}},
   hovertemplate:row.company+' · %{{x}}: %{{y:.1f}}<extra></extra>'}});
  mg.push({{x:h.map(p=>p.period),y:h.map(p=>p.op_margin),name:row.company,mode:'lines+markers',line:{{color:row.color,width:2}},marker:{{size:6}},
   hovertemplate:row.company+' · %{{x}}: %{{y:.1f}}%<extra></extra>'}});}}
 const leg={{showlegend:true,legend:{{orientation:'h',y:-0.2}}}};
 Plotly.newPlot('trend',tr,L('Revenue, indexed (first quarter shown = 100)',leg),cfg);
 Plotly.newPlot('margin',mg,L('Operating margin by quarter',Object.assign({{yaxis:{{ticksuffix:'%',gridcolor:css('--line')}}}},leg)),cfg);
}} else {{ for(const id of ['bubble','rev','trend','margin']) document.getElementById(id).innerHTML="<p class='sub' style='padding:16px'>Charts need an internet connection.</p>"; }}
document.querySelectorAll('#sc th').forEach((th,i)=>th.addEventListener('click',()=>{{
 const tb=th.closest('table').tBodies[0];const asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 [...tb.rows].sort((a,b)=>{{const x=a.cells[i].dataset.v,y=b.cells[i].dataset.v;const nx=parseFloat(x),ny=parseFloat(y);
  if(x==='')return 1;if(y==='')return -1;return (!isNaN(nx)&&!isNaN(ny)?nx-ny:x.localeCompare(y))*(asc?1:-1);}}).forEach(tr=>tb.appendChild(tr));}}));
</script></body></html>"""


def main():
    s = build()
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(page(s), encoding="utf-8")
    (OUT / "_headers").write_text("/*\n  Cache-Control: public, max-age=300\n", encoding="utf-8")  # Cloudflare: refresh within 5 min
    print(f"Static dashboard written: {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
