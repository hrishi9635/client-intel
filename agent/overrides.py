"""Which number wins when sources disagree.

  1. data/overrides.csv        typed in by you, hand-checked from the company's own release   (always wins)
  2. SEC XBRL                   exact numbers from the 10-Q / 10-K, read by the agent
  3. official press release    numbers the AI read from the company's own results release
  4. Yahoo Finance              free feed, checked for plausibility

Columns everywhere: company, period_end, period_label, months, metric, value, currency, source
(value is in MILLIONS of the currency; metric is revenue, operating_income or net_income)
"""
from .periods import period_label as _label
from .settings import read_csv

FIELDS = ["company", "ticker", "period_end", "period_label", "months", "metric", "value", "currency", "source"]
METRICS = ("revenue", "operating_income", "net_income")


def rank(source):
    s = (source or "").lower()
    if s.startswith("override") or "hand-checked" in s:
        return 4
    if "xbrl" in s:
        return 3
    if "release" in s or "filing" in s or "6-k" in s or "8-k" in s or "official" in s:
        return 2
    return 1


def read_overrides():
    out = []
    for r in read_csv("overrides.csv"):
        try:
            float(r.get("value") or "")
        except ValueError:
            continue
        if not r.get("company") or not r.get("period_end") or r.get("metric") not in METRICS:
            continue
        out.append({"company": r["company"].strip(), "period_end": r["period_end"].strip()[:10],
                    "period_label": (r.get("period_label") or "").strip() or _label(r["period_end"].strip()[:10]),
                    "months": 6 if (r.get("period_label") or "").strip().upper().startswith("H") else 3,
                    "metric": r["metric"].strip(), "value": float(r["value"]),
                    "currency": (r.get("currency") or "").strip().upper(),
                    "source": "Override: " + ((r.get("source") or "").strip() or "hand-checked")})
    return out


def merge(*row_sets):
    """Keep one row per (company, period, metric): the highest-ranked source; among equals, the later set."""
    keep = {}
    for rows in row_sets:
        for r in rows:
            # the same quarter can carry slightly different end dates (27 Jun vs 30 Jun), so match on the label
            months = int(float(r.get("months") or 3))
            label = r.get("period_label") or _label(str(r["period_end"])[:10], months)
            k = (r["company"], months, label, r["metric"])
            old = keep.get(k)
            if old is None or rank(r.get("source")) >= rank(old.get("source")):
                new = {f: r.get(f, "") for f in FIELDS}
                new["period_end"] = str(r["period_end"])[:10]
                new["months"] = months
                new["period_label"] = label
                new["ticker"] = new["ticker"] or (old or {}).get("ticker", "")
                keep[k] = new
    return sorted(keep.values(), key=lambda r: (r["company"], r["period_end"], r["metric"]))


def rows_from_release(company, currency, period_end, label, months, metrics, source):
    """Turn the AI's reading of an official results release into financial rows (millions)."""
    out = []
    rev = metrics.get("revenue_m")
    vals = {"revenue": rev, "net_income": metrics.get("net_income_m"), "operating_income": metrics.get("operating_income_m")}
    if vals["operating_income"] is None and rev and metrics.get("operating_margin_pct") is not None:
        vals["operating_income"] = round(rev * metrics["operating_margin_pct"] / 100, 1)
    for m, v in vals.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and (v > 0 or m != "revenue"):
            out.append({"company": company, "period_end": period_end, "period_label": label, "months": months,
                        "metric": m, "value": v, "currency": currency, "source": source})
    return out
