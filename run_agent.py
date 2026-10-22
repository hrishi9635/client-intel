"""
Client Intelligence agent
-------------------------
Everything:              python run_agent.py
Only one part:           python run_agent.py --part results     (or pulse, or industry)
Re-analyse everything:   python run_agent.py --force
Only some companies:     python run_agent.py --only "Disney,Pearson"
No AI (data only):       python run_agent.py --skip-ai
Save a key on a laptop:  python run_agent.py --set-key LLM_API_KEY   (also TMDB_KEY, OMDB_KEY, SEC_CONTACT ...)

On GitHub it runs by itself (see .github/workflows/agent.yml):
  results part   4 times a day   prices, financials, official results releases, news, AI analysis, sector view
  pulse part     once a day      what audiences say about recent and upcoming movies and shows
  industry part  once a day      education, publishing, lottery and gaming industry news

The AI only runs when something new has happened, to stay inside the free daily allowance.
"""
import argparse
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone

from agent import news as newsmod
from agent import overrides as ovr
from agent import results as resmod
from agent.llm import LLM, AIError, BudgetExhausted
from agent.periods import calendar_end, period_label
from agent.settings import (SECRET_NAMES, load_companies, load_settings, read_csv, read_json, save_secret,
                            write_csv, write_json)

MARKET_FIELDS = ["company", "name", "ticker", "price", "price_currency", "price_date", "market_cap_m", "currency",
                 "market_cap_usd_m", "return_1m", "return_3m", "return_1y", "high_52w", "low_52w", "pe_ttm", "next_results"]
BENCH_NAMES = {"^GSPC": "S&P 500", "^STOXX": "STOXX Europe 600"}


def scorecard(fin_rows):
    """Latest period per company: revenue, growth vs a year earlier, operating margin (for the AI's sector view)."""
    by = {}
    for r in fin_rows:
        try:
            v = float(r["value"])
        except (TypeError, ValueError):
            continue
        by.setdefault(r["company"], {}).setdefault((r["period_end"], int(float(r.get("months") or 3))), {})[r["metric"]] = v
    out = {}
    for c, periods in by.items():
        ps = sorted(periods)
        (pe, months), last = ps[-1], periods[ps[-1]]
        row = {"period": period_label(pe, months), "revenue_m": last.get("revenue")}
        if last.get("revenue") and last.get("operating_income") is not None:
            row["op_margin_pct"] = round(last["operating_income"] / last["revenue"] * 100, 1)
        step = 12 // months
        same = [p for p in ps if p[1] == months]
        if len(same) > step and last.get("revenue") and periods[same[-1 - step]].get("revenue"):
            row["revenue_yoy_pct"] = round((last["revenue"] / periods[same[-1 - step]]["revenue"] - 1) * 100, 1)
        out[c] = row
    return out


# ------------------------------------------------------------------------------------------------ results part
def part_results(args, settings, companies, llm, log):
    try:
        import yfinance as yf
    except ImportError:
        print("The add-ons aren't installed yet: python -m pip install -r requirements.txt")
        log["errors"].append("yfinance not installed")
        return
    from agent import market
    from agent import sec as secmod

    print("Step 1 of 5 · Share prices and financials (Yahoo Finance), checked for plausibility")
    fx = market.fx_months(yf) or read_csv("fx.csv")
    if fx:
        write_csv("fx.csv", fx, ["currency", "month", "usd_per_unit"])
    old_fin = read_csv("financials.csv")
    yahoo_rows, mkt_rows, prices, refreshed = [], [], [], set()
    for c in companies:
        if c["type"] == "private" or not c["tickers"]:
            continue
        print(f"   {c['short']}...", end=" ", flush=True)
        try:
            t = market.resolve_ticker(yf, c["tickers"])
            if not t:
                raise RuntimeError(f"no price data for {'/'.join(c['tickers'])}")
            rows, info = market.financial_rows(yf, c, t, fx, log["errors"])
            snap, pr = market.snapshot(yf, c, t, info, rows or [r for r in old_fin if r["company"] == c["short"]], fx)
            yahoo_rows += rows
            mkt_rows.append(snap)
            prices += pr
            refreshed.add(c["short"])
            print(f"ok ({t}, {len(rows) // 3} periods)")
        except Exception as e:  # noqa: BLE001
            print(f"skipped ({e})")
            log["errors"].append(f"market {c['short']}: {e}")
        time.sleep(1.2)
    bench = []
    for b in {c["benchmark"] for c in companies if c["benchmark"]}:
        bench += market.benchmark_prices(yf, b, BENCH_NAMES.get(b, b))
    log["steps"].append(f"market data for {len(refreshed)} listed companies")

    print("\nStep 2 of 5 · Official results (SEC EDGAR; company sites for non-US filers)")
    status = read_json("status.json", {})
    filed = read_csv("filed_financials.csv")
    sec = secmod.SEC(settings.get("SEC_CONTACT"))
    if not sec.ok:
        print("   SEC_CONTACT secret missing: the SEC needs a contact e-mail. Skipping EDGAR this time.")
        log["errors"].append("SEC_CONTACT missing; official SEC results skipped")
    seen = secmod.load_seen()
    for c in companies:
        st = status.setdefault(c["short"], {})
        if not c["cik"] or not sec.ok:
            continue
        try:
            _, fl = sec.filings(c["cik"])
            rel = sec.latest_release(c, fl, seen)
            if rel:
                rel["published"] = rel["filed"]
                st["release"] = rel
                print(f"   {c['short']}: official release {rel['form']} filed {rel['filed']}")
            else:
                print(f"   {c['short']}: no results release in the last 120 days")
            periodic = [f for f in fl if f["form"] in ("10-Q", "10-K", "20-F", "10-Q/A", "10-K/A", "20-F/A")]
            newest = periodic[0]["accession"] if periodic else None
            have = any(r["company"] == c["short"] and "xbrl" in r["source"].lower() for r in filed)
            if newest != st.get("xbrl_accession") or not have:
                rows = sec.quarterly_facts(c)
                if rows:
                    filed = [r for r in filed if not (r["company"] == c["short"] and "xbrl" in r["source"].lower())] + rows
                    print(f"      exact XBRL numbers: {len({r['period_end'] for r in rows})} quarters")
                st["xbrl_accession"] = newest
        except Exception as e:  # noqa: BLE001
            print(f"   {c['short']}: EDGAR problem ({type(e).__name__}: {str(e)[:100]})")
            log["errors"].append(f"sec {c['short']}: {type(e).__name__}: {str(e)[:150]}")
    secmod.save_seen(seen)

    print("\nStep 3 of 5 · News (Google News + Bing News, incl. Bloomberg/Reuters and technology signals)")
    all_news = read_json("news.json", {})
    days = settings["NEWS_DAYS"]
    for c in companies:
        s = c["search"]
        queries = [f"{s}", f"{s} (site:bloomberg.com OR site:reuters.com)",
                   f'{s} technology OR AI OR "digital transformation" OR outsourcing OR layoffs OR "cost-cutting"']
        if c["type"] != "private":
            queries.insert(1, f"{s} results OR earnings OR \"trading update\"")
        items = []
        for q in queries:
            items += newsmod.search(q, c["aliases"], days)
        site_items = []
        if c["type"] == "listed_other":  # results published on the company's own site or newswire (last 120 days)
            for d in c["official_domains"][:2]:
                site_items += newsmod.search(f"{s} results OR \"trading update\" site:{d}", c["aliases"], 120, bing=False)
        uniq = newsmod.dedupe(items + [i for i in site_items if i.get("published", "") >= (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()])
        if uniq:
            all_news[c["short"]] = uniq[:45]
        st = status.setdefault(c["short"], {})
        # companies outside the SEC system: a results release on their own site / newswire counts as official
        if c["type"] == "listed_other" and (st.get("release") or {}).get("form", "company release") == "company release":
            off = sorted(resmod.official_news(c, site_items + uniq), key=lambda x: x.get("published") or "", reverse=True)
            if off and (off[0].get("published") or "")[:10] > (st.get("release") or {}).get("filed", ""):
                o = off[0]
                st["release"] = {"form": "company release", "filed": (o.get("published") or "")[:10], "url": o["link"],
                                 "title": o["title"], "accession": o["link"], "published": o.get("published")}
        print(f"   {c['short']}: {len(uniq)} articles")
    write_json("news.json", all_news)
    for snap in mkt_rows:
        status.setdefault(snap["company"], {})["next_results"] = snap.get("next_results")
    log["steps"].append("news updated")

    # combine financials: Yahoo history, then official numbers, then your overrides
    fin_all = ovr.merge([r for r in old_fin if r["company"] not in refreshed or "yahoo" not in r.get("source", "").lower()],
                        yahoo_rows, filed, ovr.read_overrides())

    print("\nStep 4 of 5 · AI analysis")
    insights = read_json("insights.json", {})
    analysed = []
    if args.skip_ai:
        print("   Skipped (you used --skip-ai).")
    elif not llm.available():
        print("   Skipped: no AI key. Add the LLM_API_KEY secret (see the guide).")
        log["errors"].append("no AI key (LLM_API_KEY)")
    else:
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        jobs = []  # results first (most important), then weekly signal refreshes
        for c in companies:
            st, ins = status.get(c["short"], {}), insights.get(c["short"]) or {}
            rel = st.get("release")
            if c["type"] != "private" and rel and (args.force or ins.get("release_key") != rel.get("accession")):
                jobs.append(("results", c))
            elif args.force or not ins or ins.get("signals_at", ins.get("analysed_at", "")) < week_ago:
                new_items = [i for i in all_news.get(c["short"], []) if (i.get("published") or "") > ins.get("signals_at", "")]
                if args.force or not ins or len(new_items) >= 3:
                    jobs.append(("signals", c))
        print(f"   {sum(j[0] == 'results' for j in jobs)} results to read, {sum(j[0] == 'signals' for j in jobs)} "
              f"signal refreshes. AI allowance left today: ~{llm.left_today():,} tokens")
        for mode, c in jobs:
            name, st = c["short"], status.get(c["short"], {})
            items = all_news.get(name, [])
            try:
                if mode == "results":
                    rel = st["release"]
                    text = ""
                    try:
                        if rel["form"] != "company release":
                            text = secmod.release_excerpt(sec.doc_text(rel["url"]), c["segment"])
                        else:
                            text = newsmod.page_text(rel["url"], 3500)
                    except Exception as e:  # noqa: BLE001
                        log["errors"].append(f"release text {name}: {type(e).__name__}")
                    official = [{"title": rel.get("title"), "link": rel["url"], "source": rel["form"],
                                 "published": rel.get("filed"), "text": text}]
                    known = scorecard([r for r in fin_all if r["company"] == name]).get(name, {})
                    print(f"   {name}: reading the official release ({rel['form']}, {rel['filed']}) + {min(len(items), 20)} news items")
                    res = resmod.analyse_results(llm, c, [i for i in items if i.get("link") != rel["url"]], official, known, days)
                    why = resmod.results_check(res, rel)
                    if why:
                        print(f"      -> not counted as results: {why}")
                        res["results_found"] = False
                    res["release"] = rel
                    res["release_key"] = rel.get("accession")
                    res["results_date"] = res.get("results_date") or rel.get("filed")
                    res["signals_at"] = res["analysed_at"]
                    insights[name] = res
                    analysed.append(name)
                    if res.get("results_found") and res.get("period_end"):
                        pe = str(res["period_end"])[:10]
                        lab = res.get("period_label") or period_label(pe)
                        months = 6 if str(lab).upper().startswith("H") else (12 if str(lab).upper().startswith("FY") else 3)
                        if months < 12:
                            label = period_label(calendar_end(pe), months)
                            src = f"Official release ({rel['form']}, read by the agent)"
                            new = ovr.rows_from_release(name, c["currency"], pe, label, months, res.get("metrics") or {}, src)
                            filed = ovr.merge(filed, new)
                    note = f" (dropped unverified: {', '.join(res['unverified_dropped'][:6])})" if res.get("unverified_dropped") else ""
                    print(f"      -> {'results' if res.get('results_found') else 'no results'} · mood {res.get('sentiment')} · "
                          f"IT spend {res.get('it_spend_outlook')}{note}")
                else:
                    if not items:
                        continue
                    print(f"   {name}: refreshing technology signals from {min(len(items), 30)} news items")
                    res = resmod.analyse_signals(llm, c, items)
                    ins = insights.get(name) or {}
                    if ins.get("mode") == "results" and ins.get("results_found"):
                        for k in ("it_signals", "it_spend_outlook", "it_spend_reason", "talking_points"):
                            ins[k] = res.get(k)
                        ins["signals_at"] = res["analysed_at"]
                        ins["signal_sources"] = res.get("sources")
                        insights[name] = ins
                    else:
                        res["signals_at"] = res["analysed_at"]
                        insights[name] = res
                    analysed.append(name)
                    print(f"      -> IT spend {res.get('it_spend_outlook')} · {len(res.get('it_signals') or [])} signals")
            except BudgetExhausted as e:
                print(f"   {e}")
                log["errors"].append(str(e))
                break
            except AIError as e:
                print(f"      AI problem: {e}")
                log["errors"].append(f"ai {name}: {e}")
                if "refused" in str(e):
                    break
            except Exception as e:  # noqa: BLE001
                print(f"      Unexpected problem: {e}")
                log["errors"].append(f"ai {name}: {traceback.format_exc(limit=2)[-400:]}")
        write_json("insights.json", insights)
    write_json("status.json", status)
    write_csv("filed_financials.csv", filed, ovr.FIELDS)
    fin_all = ovr.merge([r for r in old_fin if r["company"] not in refreshed or "yahoo" not in r.get("source", "").lower()],
                        yahoo_rows, filed, ovr.read_overrides())
    write_csv("financials.csv", fin_all, ovr.FIELDS)
    if mkt_rows:
        old_m = {r["company"]: r for r in read_csv("market.csv")}
        for r in mkt_rows:
            old_m[r["company"]] = r
        write_csv("market.csv", list(old_m.values()), MARKET_FIELDS)
    if prices or bench:
        names = {p["company"] for p in prices + bench}
        keep = [r for r in read_csv("prices.csv") if r["company"] not in names]
        write_csv("prices.csv", keep + prices + bench, ["date", "company", "close"])
    log["steps"].append(f"AI analysed: {', '.join(analysed) or 'none'}")

    print("\nAccount updates · reading each new official release in depth (guidance, organisation, leadership, technology)")
    if args.skip_ai or not llm.available():
        print("   Skipped (no AI this run).")
    else:
        from agent import brief as briefmod
        try:
            briefmod.run(llm, sec, companies, status, log, force=args.force)
        except Exception as e:  # noqa: BLE001
            print(f"   Problem: {type(e).__name__}: {e}")
            log["errors"].append(f"briefs: {str(e)[:200]}")

    print("\nStep 5 of 5 · Sector view by industry")
    sector = read_json("sector.json", {})
    stale = sector.get("written_at", "") < (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    if not args.skip_ai and llm.available() and insights and (analysed or stale or args.force):
        try:
            sector = resmod.sector_view(llm, insights, companies, scorecard(fin_all))
            write_json("sector.json", sector)
            print(f"   Written: {sector.get('headline')}")
        except AIError as e:
            print(f"   AI problem: {e}")
            log["errors"].append(f"sector: {e}")
    else:
        print("   Nothing new to summarise.")


# ------------------------------------------------------------------------------------------------ other parts
def part_pulse(args, settings, llm, log):
    from agent import audience
    print("Audience Pulse · movies & shows (TMDB, OMDb, Reddit, trade press)")
    titles, status = audience.run(settings, llm, log, force=args.force, skip_ai=args.skip_ai)
    if titles is not None:
        write_json("pulse_titles.json", {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "titles": titles})
        log["steps"].append(f"audience pulse: {len(titles)} titles, {sum(1 for t in titles if t.get('ai'))} with AI notes")
    return status


def part_industry(args, settings, companies, llm, log):
    from agent import industry
    print("Industry News · education, publishing, lottery, gaming")
    old = read_json("industry_news.json", {})
    history = read_json("industry_history.json", {})
    out, status = industry.run(settings, llm, companies, old, history, log, force=args.force, skip_ai=args.skip_ai)
    write_json("industry_news.json", out)
    write_json("industry_history.json", history)
    log["steps"].append(f"industry news: {len(out['items'])} stories")
    return status


def main():
    ap = argparse.ArgumentParser(description="Client Intelligence agent")
    ap.add_argument("--part", default="all", choices=["all", "results", "pulse", "industry", "daily"],
                    help="which part to run (daily = pulse + industry)")
    ap.add_argument("--force", action="store_true", help="re-analyse everything with AI")
    ap.add_argument("--only", default="", help="comma-separated short names, e.g. Disney,Pearson")
    ap.add_argument("--skip-ai", action="store_true", help="update data and news only")
    ap.add_argument("--set-key", default="", help="save a key on this computer, e.g. --set-key LLM_API_KEY")
    args = ap.parse_args()

    if args.set_key:
        name = args.set_key.strip().upper()
        if name not in SECRET_NAMES:
            print(f"Unknown key name. Use one of: {', '.join(SECRET_NAMES)}")
            return 1
        value = input(f"Paste your {name} and press Enter:\n> ").strip()
        if len(value) < 5:
            print("That looks too short. Nothing saved.")
            return 1
        print(f"Saved on this computer only (not in the project folder): {save_secret(name, value)}")
        return 0

    settings = load_settings()
    companies = load_companies()
    if args.only:
        wanted = {x.strip().lower() for x in args.only.split(",")}
        companies = [c for c in companies if c["short"].lower() in wanted or c["name"].lower() in wanted]
    started = datetime.now(timezone.utc)
    log = {"started": started.isoformat(timespec="seconds"), "part": args.part, "steps": [], "errors": []}
    llm = LLM(settings)
    print(f"\n=== Client Intelligence agent · {date.today().isoformat()} · part: {args.part} ===")
    print(f"Keys found: " + ", ".join(f"{k} {'yes' if settings.get(k) else 'NO'}" for k in SECRET_NAMES) + "\n")

    feed_status = {s["area"] + "|" + s["name"]: s for s in read_json("feed_status.json", [])}
    if args.part in ("all", "results"):
        part_results(args, settings, companies, llm, log)
    if args.part in ("all", "pulse", "daily"):
        print()
        for s in part_pulse(args, settings, llm, log) or []:
            feed_status[s["area"] + "|" + s["name"]] = s
    if args.part in ("all", "industry", "daily"):
        print()
        for s in part_industry(args, settings, load_companies(), llm, log) or []:
            feed_status[s["area"] + "|" + s["name"]] = s
    write_json("feed_status.json", list(feed_status.values()))

    log["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log["ai_calls"] = llm.calls
    log["ai_tokens"] = llm.tokens
    runs = read_json("run_log.json", [])
    write_json("run_log.json", ([log] + runs)[:40])
    print(f"\nDone in {int((datetime.now(timezone.utc) - started).total_seconds())}s. AI calls: {llm.calls} "
          f"({llm.tokens:,} tokens). Problems noted: {len(log['errors'])}.")
    for e in log["errors"][:15]:
        print(f"   - {e}")
    print("AGENT FINISHED OK\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
