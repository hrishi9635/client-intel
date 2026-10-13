"""Free market data and financials from Yahoo Finance (via the open-source yfinance library).

Yahoo is free but imperfect, so every number is checked before it is used:
 - the currency label is compared with the company's known reporting currency (companies.csv)
 - yearly revenue must make sense against the company's market value (a business is not worth 0.01x or 500x its sales)
 - single quarters that are wildly out of line with the company's other quarters are dropped
 - missing quarters are reported in the run log (official SEC numbers fill the gaps)
"""
import time
from datetime import date

import pandas as pd

from .periods import period_label

METRICS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported", "EBIT"],
    "net_income": ["Net Income Common Stockholders", "Net Income",
                   "Net Income From Continuing Operation Net Minority Interest"],
}
FX_TICKERS = {"EUR": "EURUSD=X", "GBP": "GBPUSD=X", "AUD": "AUDUSD=X"}


def _retry(fn, tries=3, wait=6):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(wait * (i + 1))
    raise last


def resolve_ticker(yf, tickers):
    for t in tickers:
        try:
            h = _retry(lambda: yf.Ticker(t).history(period="1mo"), tries=2, wait=4)
            if h is not None and not h.empty:
                return t
        except Exception:  # noqa: BLE001
            continue
    return None


def fx_months(yf):
    """Monthly average US-dollar value of one EUR, GBP and AUD (for the 'convert to USD' toggle)."""
    rows = []
    for cur, t in FX_TICKERS.items():
        try:
            h = _retry(lambda: yf.Ticker(t).history(period="5y"))["Close"].dropna()
            h.index = pd.to_datetime(h.index).tz_localize(None)
            m = h.groupby(h.index.to_period("M")).mean()
            rows += [{"currency": cur, "month": str(p), "usd_per_unit": round(float(v), 5)} for p, v in m.items()]
        except Exception as e:  # noqa: BLE001
            print(f"   (exchange rate {cur} unavailable: {type(e).__name__})")
    return rows


def usd_rate(fx_rows, currency, month=None):
    if currency == "USD":
        return 1.0
    vals = [r for r in fx_rows if r["currency"] == currency]
    if not vals:
        return None
    if month:
        m = [r for r in vals if r["month"] <= month]
        if m:
            return float(max(m, key=lambda r: r["month"])["usd_per_unit"])
    return float(max(vals, key=lambda r: r["month"])["usd_per_unit"])


def _info(tk):
    out = {}
    try:
        fi = tk.fast_info
        for k, names in (("currency", ("currency",)), ("market_cap", ("market_cap", "marketCap")),
                         ("last_price", ("last_price", "lastPrice"))):
            for n in names:
                try:
                    v = getattr(fi, n) if hasattr(fi, n) else fi[n]
                except Exception:  # noqa: BLE001
                    v = None
                if v:
                    out[k] = v
                    break
    except Exception:  # noqa: BLE001
        pass
    try:
        info = tk.get_info() or {}
        out.setdefault("currency", info.get("currency"))
        out["financial_currency"] = info.get("financialCurrency")
        out.setdefault("market_cap", info.get("marketCap"))
    except Exception:  # noqa: BLE001
        pass
    return out


def price_unit(currency):
    """Yahoo quotes London shares in pence ('GBp' / 'GBX'). Returns (currency, divide_by)."""
    if currency in ("GBp", "GBX", "GBx"):
        return "GBP", 100.0
    if currency in ("ZAc", "ILA"):
        return currency[:2] + ("R" if currency == "ZAc" else "S"), 100.0
    return (currency or "").upper(), 1.0


def market_cap_in(info, report_cur, fx_rows):
    """Market value in millions of the company's reporting currency."""
    mcap = info.get("market_cap")
    if not mcap:
        return None
    cur, div = price_unit(info.get("currency") or report_cur)
    mcap = float(mcap) / div
    if cur == report_cur:
        return mcap / 1e6
    a, b = usd_rate(fx_rows, cur), usd_rate(fx_rows, report_cur)
    if a and b:
        return mcap * a / b / 1e6
    return None


def financial_rows(yf, company, ticker, fx_rows, log):
    """One row per period and metric, values in millions of the reporting currency."""
    tk = yf.Ticker(ticker)
    stmt = None
    for attr in ("quarterly_income_stmt", "quarterly_financials"):
        try:
            stmt = _retry(lambda: getattr(tk, attr))
            if stmt is not None and not stmt.empty:
                break
        except Exception:  # noqa: BLE001
            stmt = None
    info = _info(tk)
    if stmt is None or stmt.empty:
        return [], info
    expected = company["currency"]
    label_cur = (info.get("financial_currency") or expected).upper()
    note = ""
    factor = 1.0
    if label_cur != expected:
        # Yahoo sometimes mislabels the currency. Decide with the market-value test below.
        note = f" (Yahoo said {label_cur}; checked)"
    cols = sorted(stmt.columns)
    ends = [pd.Timestamp(c).date() for c in cols]
    # half-yearly reporters (Wolters Kluwer, Pearson): Yahoo's "quarters" are 6-month periods
    gaps = [(b - a).days for a, b in zip(ends, ends[1:])]
    months = 6 if gaps and min(gaps) > 150 else 3
    rev = None
    for n in METRICS["revenue"]:
        if n in stmt.index:
            rev = pd.to_numeric(stmt.loc[n], errors="coerce").dropna()
            break
    mcap = market_cap_in(info, expected, fx_rows)
    if rev is not None and not rev.empty and mcap:
        # median, not mean: one glitchy period must not make the whole history look wrong
        yearly = float(rev.sort_index().iloc[-4 if months == 3 else -2:].median()) * (12 / months) / 1e6
        ratio = mcap / yearly if yearly > 0 else None

        def sensible(r):
            return r is not None and 0.05 <= r <= 60

        if not sensible(ratio):
            a, b = usd_rate(fx_rows, label_cur), usd_rate(fx_rows, expected)
            alt = (mcap / (yearly * a / b)) if a and b and yearly > 0 else None
            if label_cur != expected and sensible(alt):
                factor, note = a / b, f" (converted from {label_cur})"
            else:
                log.append(f"yahoo {company['short']}: revenue looks implausible vs market value "
                           f"(ratio {ratio and round(ratio, 2)}); Yahoo financials skipped")
                return [], info
    rows = []
    for col in cols:
        e = pd.Timestamp(col).date()
        for metric, names in METRICS.items():
            val = None
            for n in names:
                if n in stmt.index:
                    v = stmt.loc[n, col]
                    if pd.notna(v):
                        val = float(v)
                        break
            if val is None:
                continue
            rows.append({"company": company["short"], "ticker": ticker, "period_end": e.isoformat(),
                         "period_label": period_label(e, months), "months": months, "metric": metric,
                         "value": round(val * factor / 1e6, 2), "currency": expected,
                         "source": "Yahoo Finance" + note})
    # drop single quarters wildly out of line with the rest (a known Yahoo glitch)
    revs = {r["period_end"]: r["value"] for r in rows if r["metric"] == "revenue" and r["value"] > 0}
    if len(revs) >= 3:
        med = sorted(revs.values())[len(revs) // 2]
        bad = {p for p, v in revs.items() if v > med * 3 or v < med / 3}
        if bad:
            log.append(f"yahoo {company['short']}: dropped out-of-line period(s) {', '.join(sorted(bad))}")
            rows = [r for r in rows if r["period_end"] not in bad]
    ps = sorted({r["period_end"] for r in rows})
    for a, b in zip(ps, ps[1:]):
        if (date.fromisoformat(b) - date.fromisoformat(a)).days > months * 31 + 40:
            log.append(f"yahoo {company['short']}: a period seems missing between {a} and {b}")
    return rows, info


def snapshot(yf, company, ticker, info, fin_rows, fx_rows):
    tk = yf.Ticker(ticker)
    hist = _retry(lambda: tk.history(period="2y"))
    close_all = hist["Close"].dropna()
    out = {"company": company["short"], "name": company["name"], "ticker": ticker}
    if close_all.empty:
        return out, []
    close = close_all[close_all.index >= close_all.index[-1] - pd.Timedelta(days=365)]
    pcur, div = price_unit(info.get("currency") or company["currency"])
    last = float(close.iloc[-1]) / div

    def ret(days):
        past = close_all[close_all.index <= close.index[-1] - pd.Timedelta(days=days)]
        return round((float(close.iloc[-1]) / float(past.iloc[-1]) - 1) * 100, 2) if not past.empty else None

    mcap = market_cap_in(info, company["currency"], fx_rows)
    ni = sorted([r for r in fin_rows if r["metric"] == "net_income" and r.get("months", 3) == 3],
                key=lambda r: r["period_end"])
    ttm = sum(float(r["value"]) for r in ni[-4:]) if len(ni) >= 4 else None
    if ttm is None:  # half-yearly reporters
        nh = sorted([r for r in fin_rows if r["metric"] == "net_income" and r.get("months") == 6], key=lambda r: r["period_end"])
        ttm = sum(float(r["value"]) for r in nh[-2:]) if len(nh) >= 2 else None
    rate = usd_rate(fx_rows, company["currency"]) or None
    nxt = None
    try:
        cal = tk.calendar
        ed = (cal or {}).get("Earnings Date") if isinstance(cal, dict) else None
        if ed:
            future = [d for d in (ed if isinstance(ed, list) else [ed]) if d and pd.Timestamp(d).date() >= date.today()]
            nxt = min(future).isoformat() if future else None
    except Exception:  # noqa: BLE001
        pass
    out.update({
        "price": round(last, 2), "price_currency": pcur, "price_date": close.index[-1].date().isoformat(),
        "market_cap_m": round(mcap, 0) if mcap else None, "currency": company["currency"],
        "market_cap_usd_m": round(mcap * rate, 0) if mcap and rate else None,
        "return_1m": ret(30), "return_3m": ret(91), "return_1y": ret(364),
        "high_52w": round(float(close.max()) / div, 2), "low_52w": round(float(close.min()) / div, 2),
        "pe_ttm": round(mcap / ttm, 1) if mcap and ttm and ttm > 0 else None,
        "next_results": nxt,
    })
    prices = [{"date": d.date().isoformat(), "company": company["short"], "close": round(float(v) / div, 4)}
              for d, v in close.items()]
    return out, prices


def benchmark_prices(yf, ticker, name):
    try:
        close = _retry(lambda: yf.Ticker(ticker).history(period="1y"))["Close"].dropna()
        return [{"date": d.date().isoformat(), "company": name, "close": round(float(v), 2)} for d, v in close.items()]
    except Exception:  # noqa: BLE001
        return []
