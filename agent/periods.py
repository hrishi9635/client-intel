"""Period labels. Companies here have different fiscal years (Disney ends ~30 Sep, Scholastic 31 May), so the
dashboard labels every quarter by the CALENDAR quarter its last day falls in: a quarter ending 28 Jun 2026 is
'Q2 2026'. The deep-dive page also shows each company's own fiscal label when the release states it."""
from datetime import date, timedelta


def _d(x):
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def calendar_end(d):
    """Snap 52/53-week period ends (e.g. 3 Jan, 28 Jun) to the calendar month they belong to."""
    d = _d(d)
    if d.day <= 7:  # a period ending in the first week of a month belongs to the month before
        d = d.replace(day=1) - timedelta(days=1)
    return d


def period_label(end, months=3):
    d = calendar_end(end)
    if months >= 6 and months < 12:
        return f"H{1 if d.month <= 6 else 2} {d.year}"
    if months >= 12:
        return f"FY {d.year}"
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


def label_key(label):
    """Sort key for 'Q3 2026', 'H1 2026', 'FY 2025'."""
    try:
        a, y = str(label).split()
        order = {"Q1": 3, "Q2": 6, "H1": 6, "Q3": 9, "Q4": 12, "H2": 12, "FY": 12}.get(a, 0)
        return (int(y), order)
    except Exception:  # noqa: BLE001
        return (0, 0)


def quarter_start_end(label):
    """'Q3 2026' -> (2026-07-01, 2026-09-30)."""
    a, y = label.split()
    q, y = int(a[1]), int(y)
    start = date(y, 3 * (q - 1) + 1, 1)
    end = (date(y + (q == 4), (3 * q) % 12 + 1, 1) - timedelta(days=1))
    return start, end
