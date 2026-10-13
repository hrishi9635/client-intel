"""Official results from the US regulator's free EDGAR system (www.sec.gov).

 - submissions JSON: the list of a company's filings. An 8-K with "Item 2.02" is an earnings release;
   foreign companies (Pearson, Brightstar) file 6-K reports, which we read to see whether they are results.
 - the release itself (Exhibit 99.1 of the 8-K, or the 6-K document): read as text for the AI.
 - companyfacts JSON (XBRL): exact revenue, operating income and net income for every quarter the company
   has reported in a 10-Q / 10-K. Restated numbers replace older ones automatically.

The SEC asks every program to send a contact e-mail in its User-Agent. It comes from the SEC_CONTACT secret.
"""
import re
import time
from datetime import date, datetime, timedelta

import requests

from .periods import period_label
from .settings import read_json, write_json

RESULTS_WORDS = re.compile(
    r"(interim|half[- ]year|full[- ]year|preliminary|annual|quarterly|financial) results|results for the|"
    r"trading (update|statement)|(first|second|third|fourth)[- ]quarter( and (full|fiscal)[- ]year)?( (fiscal )?20\d\d)?"
    r"( financial| operating)?( and operating)? results|reports? (first|second|third|fourth)|nine[- ]month|"
    r"q[1-4] (20\d\d )?(results|trading)|earnings release", re.I)
NOT_RESULTS = re.compile(
    r"transaction in own shares|total voting rights|director|pdmr|major holding|block listing|"
    r"conference call|to host|will (report|announce|release)|date of (its|the)|notice of|agm|annual general meeting|"
    r"dividend reinvestment|form 20-f filed|share buyback programme", re.I)

CONCEPTS = {
    "revenue": [("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"), ("us-gaap", "SalesRevenueNet"),
                ("ifrs-full", "Revenue")],
    "operating_income": [("us-gaap", "OperatingIncomeLoss"), ("ifrs-full", "ProfitLossFromOperatingActivities")],
    "net_income": [("us-gaap", "NetIncomeLoss"), ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic"),
                   ("us-gaap", "ProfitLoss"), ("ifrs-full", "ProfitLossAttributableToOwnersOfParent"),
                   ("ifrs-full", "ProfitLoss")],
}


class SEC:
    def __init__(self, contact):
        self.ok = bool(contact and "@" in contact)
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": f"ClientDashboard {contact or 'contact-not-set@example.com'}",
                               "Accept-Encoding": "gzip, deflate"})
        self._last = 0.0

    def get(self, url, as_json=True):
        wait = 0.15 - (time.time() - self._last)  # the SEC allows 10 requests a second; we stay well below
        if wait > 0:
            time.sleep(wait)
        for attempt in range(3):
            r = self.s.get(url, timeout=30)
            self._last = time.time()
            if r.status_code == 200:
                return r.json() if as_json else r.text
            if r.status_code in (403, 429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
        r.raise_for_status()

    # ------------------------------------------------------------------ filings
    def filings(self, cik, days=120):
        sub = self.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        rec = sub.get("filings", {}).get("recent", {})
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        out = []
        for i, form in enumerate(rec.get("form", [])):
            fdate = rec["filingDate"][i]
            if fdate < cutoff:
                continue
            out.append({"form": form, "filed": fdate, "accession": rec["accessionNumber"][i],
                        "accepted": (rec.get("acceptanceDateTime") or [""] * (i + 1))[i],
                        "items": (rec.get("items") or [""] * (i + 1))[i] or "",
                        "primary": rec["primaryDocument"][i],
                        "description": (rec.get("primaryDocDescription") or [""] * (i + 1))[i] or ""})
        return sub.get("name", ""), out

    def folder(self, cik, accession):
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"

    def release_doc(self, cik, f):
        """URL of the press release inside a filing: Exhibit 99.1 if there is one, else the main document."""
        base = self.folder(cik, f["accession"])
        try:
            idx = self.get(f"{base}/index.json")
            names = [x["name"] for x in idx.get("directory", {}).get("item", [])]
        except Exception:  # noqa: BLE001
            names = []
        ex = [n for n in names if re.search(r"(ex|exhibit|dex)[-_]?99", n, re.I) and n.lower().endswith((".htm", ".html", ".txt"))]
        ex.sort(key=lambda n: (0 if re.search(r"99[-_.]?0?1(?!\d)", n) else 1, n))
        return f"{base}/{ex[0] if ex else f['primary']}"

    def doc_text(self, url):
        from bs4 import BeautifulSoup
        raw = self.get(url, as_json=False)
        soup = BeautifulSoup(raw, "html.parser")
        for t in soup(["script", "style"]):
            t.decompose()
        text = soup.get_text("\n")
        text = re.sub(r"[ \t\xa0]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return text.strip()

    def latest_release(self, company, fl, seen, max_reads=8):
        """The newest official results release filed with the SEC in the last 120 days, or None.

        fl: the company's recent filings (from filings()).
        seen: cache of 6-K accession numbers already read (so each is read only once)."""
        reads = 0
        for f in fl:  # newest first
            form = f["form"].upper()
            if form in ("8-K", "8-K/A") and "2.02" in f["items"]:
                url = self.release_doc(company["cik"], f)
                return {"form": form, "filed": f["filed"], "accepted": f["accepted"], "accession": f["accession"],
                        "url": url, "title": f"{company['name']} {form} earnings release (Item 2.02)",
                        "index": self.folder(company["cik"], f["accession"])}
            if form in ("6-K", "6-K/A"):
                key = f["accession"]
                if key not in seen:
                    if reads >= max_reads:
                        continue
                    reads += 1
                    try:
                        url = self.release_doc(company["cik"], f)
                        head = self.doc_text(url)[:2000]
                    except Exception:  # noqa: BLE001
                        continue
                    first = " ".join(head.split()[:120])
                    is_res = bool(RESULTS_WORDS.search(first)) and not NOT_RESULTS.search(" ".join(head.split()[:40]))
                    title = next((l.strip() for l in head.splitlines() if len(l.strip()) > 25
                                  and not re.search(r"form 6-k|securities and exchange|commission file|washington", l, re.I)), "")
                    seen[key] = {"results": is_res, "url": url, "title": title[:160], "filed": f["filed"]}
                s = seen[key]
                if s.get("results"):
                    return {"form": form, "filed": f["filed"], "accepted": f["accepted"], "accession": key,
                            "url": s["url"], "title": s.get("title") or f"{company['name']} results (6-K)",
                            "index": self.folder(company["cik"], key)}
        return None

    # ------------------------------------------------------------------ XBRL numbers
    def quarterly_facts(self, company):
        """Exact quarterly figures from XBRL: list of rows (values in millions of the reporting currency)."""
        facts = self.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(company['cik']):010d}.json").get("facts", {})
        rows = []
        for metric, concepts in CONCEPTS.items():
            per = {}  # (start, end) -> (filed, value, unit) ; first concept in the list wins for each period
            for taxonomy, concept in concepts:
                units = (facts.get(taxonomy, {}).get(concept) or {}).get("units", {})
                for unit, vals in units.items():
                    if not re.fullmatch(r"[A-Z]{3}", unit):
                        continue
                    found = {}
                    for v in vals:
                        if not v.get("start") or not v.get("end") or v.get("val") is None:
                            continue
                        k = (v["start"], v["end"])
                        if k not in found or v.get("filed", "") > found[k][0]:  # newest filing wins (restatements)
                            found[k] = (v.get("filed", ""), float(v["val"]), unit, v.get("form", ""))
                    for k, val in found.items():
                        per.setdefault(k, val)
            rows += _to_quarters(company, metric, per)
        return rows


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days + 1


def _to_quarters(company, metric, per):
    quarters = {}
    for (s, e), (filed, val, unit, form) in per.items():
        if 80 <= _days(s, e) <= 100:
            quarters[e] = (val, unit, f"SEC XBRL {form}".strip())
    # Q4 is usually only in the annual report: Q4 = full year minus the first nine months
    for (s, e), (filed, val, unit, form) in per.items():
        if 350 <= _days(s, e) <= 380 and e not in quarters:
            nine = [(e9, v9) for (s9, e9), (_, v9, u9, _) in per.items() if s9 == s and 250 <= _days(s9, e9) <= 290 and u9 == unit]
            if nine:
                e9, v9 = max(nine)
                if 80 <= _days((date.fromisoformat(e9) + timedelta(days=1)).isoformat(), e) <= 100:
                    quarters[e] = (val - v9, unit, f"SEC XBRL {form} (full year minus 9 months)")
    out = []
    for e, (val, unit, src) in quarters.items():
        out.append({"company": company["short"], "period_end": e, "period_label": period_label(e), "months": 3, "metric": metric,
                    "value": round(val / 1e6, 2), "currency": unit, "source": src})
    return out


def release_excerpt(text, segments="", max_chars=5000):
    """The parts of a long press release the AI needs: the opening, plus paragraphs with key words."""
    if len(text) <= max_chars:
        return text
    head = text[:2600]
    words = ["revenue", "operating income", "net income", "guidance", "outlook", "expect", "segment", "margin",
             "technology", "digital", "ai ", "artificial intelligence", "cloud", "restructur", "cost", "layoff",
             "workforce", "efficien", "acquisi", "streaming", "parks", "casino", "igaming", "lottery", "enrol"]
    words += [w.strip().lower() for w in re.split(r"[;,()]", segments) if len(w.strip()) > 3][:10]
    picked, used = [], len(head)
    for line in text[2600:].split("\n"):
        l = line.strip()
        if 60 < len(l) < 900 and any(w in l.lower() for w in words):
            if used + len(l) > max_chars:
                break
            picked.append(l)
            used += len(l)
    return head + "\n...\n" + "\n".join(picked)


def load_seen():
    seen = read_json("sec_seen.json", {})
    cutoff = (date.today() - timedelta(days=150)).isoformat()
    return {k: v for k, v in seen.items() if v.get("filed", "") >= cutoff}


def save_seen(seen):
    write_json("sec_seen.json", seen)


def accepted_iso(accepted):
    try:
        return datetime.fromisoformat(accepted.replace("Z", "+00:00")).isoformat(timespec="minutes")
    except Exception:  # noqa: BLE001
        return accepted or ""
