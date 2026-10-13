"""Protects against made-up numbers: every number the AI writes must appear in the source text it was given."""
import re

NUM = re.compile(r"(?<![\w.])[-+]?\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


def _variants(v):
    """Ways a number may be written in a source: 5.2 / 5.20, 23650 / 23.65 (billion), 2.5 (billion) / 2500."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return []
    v = abs(float(v))
    whole = float(v).is_integer()
    out = {f"{v:g}", f"{v:.2f}"}
    if whole:
        out.add(f"{v:.0f}")
    else:
        out.add(f"{v:.1f}")
    if v >= 1000:  # millions written as billions
        w = v / 1000
        out.update({f"{w:.2f}", f"{w:.1f}" if round(w, 1) == round(w, 2) else f"{w:.2f}"})
    if v < 1000 and round(v, 3) == round(v, 2):  # billions written as millions
        out.add(f"{v * 1000:.0f}")
    clean = set()
    for x in out:
        if "." in x:
            x = x.rstrip("0").rstrip(".")
        if x not in ("0", ""):
            clean.add(x)
    return clean


def flat(corpus):
    return corpus.replace(",", "")


def number_in(v, flat_corpus):
    return any(re.search(rf"(?<![\d.]){re.escape(x)}(?![\d])", flat_corpus) for x in _variants(v))


def text_ok(text, flat_corpus):
    """True if every meaningful number written in the text appears in the sources."""
    if not isinstance(text, str):
        return True
    for m in NUM.finditer(text):
        whole = m.group(1).replace(",", "")
        dec = m.group(2)
        try:
            val = float(whole + ("." + dec if dec else ""))
        except ValueError:
            continue
        if val < 10 and not dec:  # small counts ("3 parks", "2 studios") are not checked
            continue
        if not dec and 1990 <= val <= 2040:  # years
            continue
        token = whole + ("." + dec if dec else "")
        if re.search(rf"(?<![\d.]){re.escape(token)}(?![\d])", flat_corpus):
            continue
        if not number_in(val, flat_corpus):
            return False
    return True


SKIP_KEYS = ("date", "period", "label", "url", "link", "published", "currency", "type", "kind")


def scrub(obj, flat_corpus, dropped, path=""):
    """Walk the AI's answer: remove list items / strings that contain numbers not found in the sources."""
    if isinstance(obj, dict):
        for k in list(obj):
            v = obj[k]
            if any(w in str(k).lower() for w in SKIP_KEYS):
                continue
            if isinstance(v, str):
                if not text_ok(v, flat_corpus):
                    obj[k] = None
                    dropped.append(f"{path}{k}")
            elif isinstance(v, (dict, list)):
                scrub(v, flat_corpus, dropped, f"{path}{k}.")
        return obj
    if isinstance(obj, list):
        keep = []
        for i, v in enumerate(obj):
            if isinstance(v, str) and not text_ok(v, flat_corpus):
                dropped.append(f"{path}{i}")
                continue
            if isinstance(v, dict):
                before = len(dropped)
                scrub(v, flat_corpus, dropped, f"{path}{i}.")
                # a list entry (e.g. a segment or an IT signal) with an unverified number is dropped altogether
                if len(dropped) > before:
                    continue
            keep.append(v)
        obj[:] = keep
        return obj
    return obj


def check_metrics(metrics, flat_corpus, dropped, skip=("currency",)):
    for k, v in list((metrics or {}).items()):
        if k in skip or v is None:
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not number_in(v, flat_corpus):
            metrics[k] = None
            dropped.append(f"metrics.{k}")
    return metrics
