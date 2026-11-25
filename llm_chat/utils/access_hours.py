"""CLOZE-Guard v0 — access-hours window evaluation.

Determines whether the current moment falls inside a provider-configured
daily availability window. All evaluation happens in the configured IANA
timezone (e.g. "America/New_York"), which follows daylight saving so a
"9:00 Eastern" window stays 9:00 wall-clock year-round.
"""

from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None

DEFAULT_TZ = "America/New_York"
_SHORT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def within_access_window(start_hhmm, end_hhmm, tz_name=None, days=None):
    """Return True if "now" is inside the configured window.

    Args:
        start_hhmm: window open time, "HH:MM" (24h).
        end_hhmm:   window close time, "HH:MM" (24h).
        tz_name:    IANA timezone name; defaults to America/New_York.
        days:       optional iterable of allowed weekday ints (0=Mon..6=Sun).
                    Falsy/empty means every day is allowed.

    The weekday is evaluated at the moment of the call. For an overnight
    window (start > end) combined with day restrictions, the post-midnight
    slice counts as the next day — a documented rule, not special-cased.
    """
    if not start_hhmm or not end_hhmm:
        return True  # incomplete config = no restriction

    tz = ZoneInfo(tz_name or DEFAULT_TZ) if ZoneInfo else None
    now = datetime.now(tz)

    if days and now.weekday() not in days:
        return False

    hhmm = now.strftime("%H:%M")
    if start_hhmm <= end_hhmm:
        return start_hhmm <= hhmm <= end_hhmm
    # overnight window, e.g. 21:00–06:00
    return hhmm >= start_hhmm or hhmm <= end_hhmm


def _fmt12(hhmm):
    """'09:00' -> '9:00 AM'."""
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        return hhmm
    suffix = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{m:02d} {suffix}"


def _days_label(days):
    """Human-readable day set: 'Every day', 'Mon–Fri', 'Weekends', or a list."""
    if not days:
        return "Every day"
    s = sorted({int(d) for d in days})
    if s == [0, 1, 2, 3, 4]:
        return "Mon–Fri"
    if s == [5, 6]:
        return "Weekends"
    if len(s) > 2 and s == list(range(s[0], s[-1] + 1)):
        return f"{_SHORT_DAYS[s[0]]}–{_SHORT_DAYS[s[-1]]}"
    return ", ".join(_SHORT_DAYS[d] for d in s)


def next_open(start_hhmm, tz_name=None, days=None):
    """Datetime of the next time the window opens (next allowed weekday at start)."""
    if not start_hhmm:
        return None
    tz = ZoneInfo(tz_name or DEFAULT_TZ) if ZoneInfo else None
    now = datetime.now(tz)
    try:
        sh, sm = (int(x) for x in start_hhmm.split(":"))
    except ValueError:
        return None
    allowed = {int(d) for d in days} if days else set(range(7))
    for offset in range(8):
        cand = (now + timedelta(days=offset)).replace(hour=sh, minute=sm, second=0, microsecond=0)
        if cand.weekday() in allowed and cand > now:
            return cand
    return None


def window_status(start_hhmm, end_hhmm, tz_name=None, days=None):
    """Full status for the participant UI: open flag + friendly schedule/reopen text."""
    is_open = within_access_window(start_hhmm, end_hhmm, tz_name, days)
    tz = ZoneInfo(tz_name or DEFAULT_TZ) if ZoneInfo else None
    now = datetime.now(tz)
    tz_abbr = now.strftime("%Z") or (tz_name or DEFAULT_TZ)
    schedule = f"{_days_label(days)}, {_fmt12(start_hhmm)} – {_fmt12(end_hhmm)} {tz_abbr}"

    reopen = None
    reopens_at = None
    if not is_open:
        nxt = next_open(start_hhmm, tz_name, days)
        if nxt:
            reopens_at = nxt.timestamp()
            if nxt.date() == now.date():
                when = "today"
            elif nxt.date() == (now + timedelta(days=1)).date():
                when = "tomorrow"
            else:
                when = nxt.strftime("%A")
            reopen = f"Opens {when} at {_fmt12(start_hhmm)}"
    return {"open": is_open, "schedule": schedule, "reopen": reopen, "reopens_at": reopens_at}
