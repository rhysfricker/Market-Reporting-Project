# ============================================================
# calendar_data.py
# Fetches economic calendar data from ForexFactory XML feeds
#
# Returns two separate datasets:
#
#   get_next_week_events()
#     -> List of dicts for the report's "Key Events Next Week"
#       section. Fetches ff_calendar_nextweek.xml.
#       Falls back to ff_calendar_thisweek.xml if next week
#       isn't published yet (before Friday).
#
#   get_this_week_events()
#     -> List of dicts for this week's actual releases.
#       Fetches ff_calendar_thisweek.xml.
#       Used by macro_data.py to verify which economic events
#       genuinely occurred this week before flagging FRED series
#       as released_this_week=True.
#
# Both functions filter to:
#   - High impact events only (toggle INCLUDE_MEDIUM to add Medium)
#   - JPY Low-impact events ARE included (FF rates all Japan events Low)
#   - G7 currencies: USD, EUR, GBP, JPY, CAD, CHF
#
# Report runs Saturday/Sunday so:
#   thisweek feed  = Mon-Fri just gone  -> event verification
#   nextweek feed  = Mon-Fri coming     -> calendar section
#
# Weekend handling:
#   On Sunday, FF rolls "this week" to the coming Mon-Fri.
#   Week-stamped cache (ff_week_YYYY-MM-DD.xml) is the primary
#   fallback — these never expire, so past-week data survives
#   the Sunday rollover permanently. TTL cache (72h) is a
#   secondary fallback.
#
# Date-range queries:
#   get_events_for_week("2026-03-09")       -> events from that week
#   get_events_for_date_range("2026-03-01", "2026-03-15")
#   list_cached_weeks()                     -> all cached week dates
#
#   CLI: python calendar_data.py 2026-03-09
#        python calendar_data.py 2026-03-01 2026-03-15
#        python calendar_data.py cache
# ============================================================

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging

# -- Config ---
INCLUDE_MEDIUM = False

G7_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "CHF"}

FEED_THIS_WEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FEED_NEXT_WEEK = "https://nfs.faireconomy.media/ff_calendar_nextweek.xml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/xml, text/xml, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer":         "https://www.forexfactory.com/",
}

REQUEST_TIMEOUT = 15

# -- Currency Labels --
CURRENCY_LABELS = {
    "USD": "\U0001f1fa\U0001f1f8 USD", "EUR": "\U0001f1ea\U0001f1fa EUR", "GBP": "\U0001f1ec\U0001f1e7 GBP",
    "JPY": "\U0001f1ef\U0001f1f5 JPY", "CAD": "\U0001f1e8\U0001f1e6 CAD", "CHF": "\U0001f1e8\U0001f1ed CHF",
}

# No hardcoded fallback lists -- they go stale every week.
FALLBACK_THIS_WEEK = []

# -- Date Helpers --
def _monday_of_week(dt: datetime) -> datetime:
    """Return the Monday 00:00 of the week containing dt."""
    return (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

# -- Helpers --
def _parse_ff_datetime(raw: str) -> datetime | None:
    for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%m-%d-%Y"]:
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None

def _format_day(dt: datetime | None) -> str:
    return dt.strftime("%a") if dt else "\u2014"

def _format_time(dt: datetime | None) -> str:
    if dt is None:
        return "\u2014"
    return "All Day" if (dt.hour == 0 and dt.minute == 0) else dt.strftime("%H:%M")

def _safe_text(element, tag: str) -> str:
    child = element.find(tag)
    return child.text.strip() if (child is not None and child.text) else "\u2014"


# -- Cache Config --
import os, time, hashlib

_XML_CACHE: dict = {}
CACHE_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_HOURS = 1


def _cache_path(url: str) -> str:
    """Return a filesystem path for caching a given URL."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.md5(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"ff_{key}.xml")


def _load_disk_cache(url: str, max_age_hours: float | None = None) -> str | None:
    """Return cached XML if it exists and is less than max_age_hours old.
    Defaults to CACHE_HOURS if not specified."""
    path = _cache_path(url)
    if os.path.exists(path):
        age_hours = (time.time() - os.path.getmtime(path)) / 3600
        limit = max_age_hours if max_age_hours is not None else CACHE_HOURS
        if age_hours < limit:
            logging.info(f"[calendar_data] Using disk cache ({age_hours:.1f}h old) for {url}")
            return open(path, encoding="utf-8").read()
    return None


def _save_disk_cache(url: str, xml: str) -> None:
    """Save fetched XML to disk cache."""
    try:
        open(_cache_path(url), "w", encoding="utf-8").write(xml)
    except Exception as e:
        logging.warning(f"[calendar_data] Could not save disk cache: {e}")


# -- Week-Stamped Persistent Cache --
# Every time we fetch a week's XML, we also save a permanent copy
# keyed by the Monday date of that week (e.g. ff_week_2026-03-09.xml).
# These NEVER expire — they let us look up any previously-fetched week,
# solving the Sunday rollover problem permanently.

def _week_cache_path(monday: datetime) -> str:
    """Return path for a week-stamped cache file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"ff_week_{monday.strftime('%Y-%m-%d')}.xml")


def _extract_week_monday(xml_text: str) -> datetime | None:
    """Parse event dates from filtered G7 events and return the Monday
    of the week they belong to. Uses the most common Monday among
    weekday (Mon-Fri) events to avoid being skewed by weekend outliers."""
    events = _parse_events_with_dates(xml_text)
    if not events:
        return None
    mondays = {}
    for e in events:
        dt = e.get("_dt")
        if dt is None:
            continue
        dt_naive = dt.replace(tzinfo=None)
        # Only count weekday events (Mon-Fri) — weekend events can belong to either week
        if dt_naive.weekday() < 5:
            m = _monday_of_week(dt_naive)
            key = m.strftime("%Y-%m-%d")
            mondays[key] = mondays.get(key, 0) + 1
    if not mondays:
        return None
    # Return the Monday with the most events
    best = max(mondays, key=mondays.get)
    return datetime.strptime(best, "%Y-%m-%d")


def _save_week_cache(xml_text: str) -> datetime | None:
    """Save XML to a week-stamped file. Returns the Monday date, or None on failure."""
    monday = _extract_week_monday(xml_text)
    if monday is None:
        return None
    path = _week_cache_path(monday)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml_text)
        logging.info(f"[calendar_data] Saved week cache: {path}")
        return monday
    except Exception as e:
        logging.warning(f"[calendar_data] Could not save week cache: {e}")
        return None


def _load_week_cache(monday: datetime) -> str | None:
    """Load XML from week-stamped cache. Never expires."""
    path = _week_cache_path(monday)
    if os.path.exists(path):
        logging.info(f"[calendar_data] Found week cache: {path}")
        return open(path, encoding="utf-8").read()
    return None


# -- Core Fetch --
def _fetch_xml(url: str) -> str | None:
    # 1. In-memory cache (same process)
    if url in _XML_CACHE:
        logging.info(f"[calendar_data] Using in-memory cache for {url}")
        return _XML_CACHE[url]

    # 2. Disk cache (across runs on the same day)
    cached = _load_disk_cache(url)
    if cached:
        _XML_CACHE[url] = cached
        return cached

    # 3. Fetch from ForexFactory with one retry on 429
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            _XML_CACHE[url] = r.text
            _save_disk_cache(url, r.text)
            _save_week_cache(r.text)  # permanent week-stamped copy
            return r.text
        except requests.exceptions.HTTPError as e:
            if r.status_code == 429 and attempt == 0:
                logging.warning(f"[calendar_data] 429 rate limited -- waiting 15s before retry...")
                time.sleep(15)
                continue
            logging.warning(f"[calendar_data] Failed to fetch {url}: {e}")
            return None
        except requests.RequestException as e:
            logging.warning(f"[calendar_data] Failed to fetch {url}: {e}")
            return None
    return None


def _fetch_xml_live(url: str) -> str | None:
    """Fetch XML from ForexFactory WITHOUT saving to disk cache.
    Used on weekends to avoid overwriting valid past-week cache
    with rolled-over next-week data."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.text
        except requests.exceptions.HTTPError as e:
            if r.status_code == 429 and attempt == 0:
                logging.warning(f"[calendar_data] 429 rate limited -- waiting 15s before retry...")
                time.sleep(15)
                continue
            logging.warning(f"[calendar_data] Failed to fetch {url}: {e}")
            return None
        except requests.RequestException as e:
            logging.warning(f"[calendar_data] Failed to fetch {url}: {e}")
            return None
    return None


# -- Core Parser --
def _parse_events(xml_text: str) -> list[dict]:
    """
    Parse FF XML and return filtered list of event dicts.
    Each dict contains: date, time, currency, currency_label,
    event, impact, forecast, previous.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logging.error(f"[calendar_data] XML parse error: {e}")
        return []

    events = []
    for event in root.findall("event"):
        impact   = _safe_text(event, "impact")
        currency = _safe_text(event, "country")
        if impact in ("Holiday",):
            continue
        # ForexFactory rates ALL Japan events as "Low" -- even GDP, CPI, Trade Balance.
        # Allow Low-impact JPY events through; keyword matching in _build_released_set
        # will filter to relevant series only.
        if impact == "Low" and currency != "JPY":
            continue
        if impact == "Medium" and not INCLUDE_MEDIUM:
            continue

        if currency not in G7_CURRENCIES:
            continue

        raw_date = _safe_text(event, "date")
        dt       = _parse_ff_datetime(raw_date) if raw_date != "\u2014" else None
        title    = _safe_text(event, "title")
        forecast = _safe_text(event, "forecast")
        previous = _safe_text(event, "previous")
        forecast = forecast if forecast not in ("", "\u2014", None) else "\u2014"
        previous = previous if previous not in ("", "\u2014", None) else "\u2014"

        events.append({
            "date":           _format_day(dt),
            "time":           _format_time(dt),
            "currency":       currency,
            "currency_label": CURRENCY_LABELS.get(currency, currency),
            "event":          title,
            "impact":         impact,
            "forecast":       forecast,
            "previous":       previous,
            "_dt":            dt,
        })

    events.sort(key=lambda e: (e["_dt"] is None, e["_dt"] or datetime.max))
    for e in events:
        e.pop("_dt", None)

    return events


def _parse_events_with_dates(xml_text: str) -> list[dict]:
    """Like _parse_events but keeps _dt field for date validation.
    Caller must pop _dt after using it."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logging.error(f"[calendar_data] XML parse error: {e}")
        return []

    events = []
    for event in root.findall("event"):
        impact   = _safe_text(event, "impact")
        currency = _safe_text(event, "country")
        if impact in ("Holiday",):
            continue
        if impact == "Low" and currency != "JPY":
            continue
        if impact == "Medium" and not INCLUDE_MEDIUM:
            continue
        if currency not in G7_CURRENCIES:
            continue

        raw_date = _safe_text(event, "date")
        dt       = _parse_ff_datetime(raw_date) if raw_date != "\u2014" else None
        title    = _safe_text(event, "title")
        forecast = _safe_text(event, "forecast")
        previous = _safe_text(event, "previous")
        forecast = forecast if forecast not in ("", "\u2014", None) else "\u2014"
        previous = previous if previous not in ("", "\u2014", None) else "\u2014"

        events.append({
            "date":           _format_day(dt),
            "time":           _format_time(dt),
            "currency":       currency,
            "currency_label": CURRENCY_LABELS.get(currency, currency),
            "event":          title,
            "impact":         impact,
            "forecast":       forecast,
            "previous":       previous,
            "_dt":            dt,
        })

    events.sort(key=lambda e: (e["_dt"] is None, e["_dt"] or datetime.max))
    return events


# -- Public: Next Week Events (for report calendar section) --
def get_next_week_events() -> list[dict]:
    """
    Returns high-impact G7 events for next week.
    Used by report.py for the "Key Events Next Week" section.

    Tries nextweek feed first (live from Friday onwards),
    falls back to thisweek feed mid-week.
    Returns [] if both fail.
    """
    logging.info("[calendar_data] Fetching next week events...")

    xml = _fetch_xml(FEED_NEXT_WEEK)
    if xml:
        events = _parse_events(xml)
        if events:
            logging.info(f"[calendar_data] Next week: {len(events)} events from nextweek feed.")
            return events

    logging.warning("[calendar_data] nextweek feed unavailable -- trying thisweek feed.")
    xml = _fetch_xml(FEED_THIS_WEEK)
    if xml:
        events = _parse_events(xml)
        if events:
            logging.info(f"[calendar_data] Next week: {len(events)} events from thisweek feed.")
            return events

    logging.warning("[calendar_data] Both ForexFactory feeds failed -- returning empty list. "
                    "Check https://nfs.faireconomy.media status.")
    return []

# -- Public: This Week Events (for macro verification) --
def get_this_week_events() -> list[dict]:
    """
    Returns high-impact G7 events that occurred this past week (Mon-Fri).
    Used by macro_data.py to verify which economic releases
    genuinely happened before flagging FRED series as released.

    Weekend handling: On Sat/Sun, FF rolls "this week" to next week.
    We try the disk cache first (extended to 72h on weekends) to get
    the correct past-week data. If no cache and the live feed has
    rolled over (all events in the future), we return [] safely.
    """
    logging.info("[calendar_data] Fetching this week events for macro verification...")

    today = datetime.today()
    is_weekend = today.weekday() >= 5  # Sat=5, Sun=6

    # Calculate the Monday of the past trading week (Mon-Fri just gone)
    if is_weekend:
        # Sat/Sun: "past week" = the Mon-Fri that just ended
        past_monday = _monday_of_week(today)
    else:
        # Weekday: "this week" = current Mon-Fri
        past_monday = _monday_of_week(today)

    # 1. Try week-stamped persistent cache first (never expires)
    week_xml = _load_week_cache(past_monday)
    if week_xml:
        events = _parse_events(week_xml)
        if events:
            logging.info(f"[calendar_data] Using week cache for {past_monday.strftime('%Y-%m-%d')} "
                         f"({len(events)} events)")
            return events

    if is_weekend:
        # 2. Try TTL-based disk cache (72h covers Fri->Sun)
        #    But validate that it actually contains past-week data, not rolled-over next-week
        cached_xml = _load_disk_cache(FEED_THIS_WEEK, max_age_hours=72)
        if cached_xml:
            cached_monday = _extract_week_monday(cached_xml)
            if cached_monday and cached_monday <= past_monday:
                events = _parse_events(cached_xml)
                if events:
                    _save_week_cache(cached_xml)  # permanent copy
                    logging.info(f"[calendar_data] Weekend: using TTL cache "
                                 f"(week of {cached_monday.strftime('%Y-%m-%d')}, {len(events)} events)")
                    return events
            else:
                logging.info(f"[calendar_data] Weekend: TTL cache has rolled over "
                             f"(contains week of {cached_monday.strftime('%Y-%m-%d') if cached_monday else '?'}, "
                             f"need week of {past_monday.strftime('%Y-%m-%d')})")

        # 3. Fetch live but DON'T save to TTL cache (would overwrite good data)
        logging.info("[calendar_data] Weekend: no cache, fetching live feed...")
        xml = _fetch_xml_live(FEED_THIS_WEEK)
        if xml:
            events = _parse_events_with_dates(xml)
            has_past_events = any(
                e.get("_dt") and e["_dt"].replace(tzinfo=None) <= today
                for e in events
            )
            for e in events:
                e.pop("_dt", None)

            if has_past_events:
                logging.info(f"[calendar_data] Weekend: live feed still has past-week events ({len(events)})")
                _save_disk_cache(FEED_THIS_WEEK, xml)
                _save_week_cache(xml)  # permanent copy
                return events
            else:
                logging.warning("[calendar_data] Weekend: feed has rolled to next week -- "
                                "no past-week data available for verification")
                return []

        logging.warning("[calendar_data] Weekend: feed unavailable and no cache -- "
                        "no events flagged for macro.")
        return []

    # Weekday -- normal fetch
    xml = _fetch_xml(FEED_THIS_WEEK)
    if xml:
        events = _parse_events(xml)
        logging.info(f"[calendar_data] This week: {len(events)} events for macro verification.")
        return events

    logging.warning("[calendar_data] thisweek feed unavailable -- no events flagged for macro.")
    return FALLBACK_THIS_WEEK


# -- Convenience: Get Both Feeds at Once --
def get_all_calendar_data() -> dict:
    """
    Fetches both feeds in one call. Returns:
    {
        "next_week": [...],   # for report calendar section
        "this_week": [...],   # for macro_data verification
    }
    """
    this_week = get_this_week_events()
    next_week = get_next_week_events()
    return {"this_week": this_week, "next_week": next_week}


# -- Public: Get Events for a Specific Week --
def get_events_for_week(target_date: datetime | str) -> list[dict]:
    """
    Returns cached events for the week containing target_date.
    target_date can be a datetime or a string like '2026-03-09'.

    Uses week-stamped persistent cache — only works for weeks
    that have been previously fetched (e.g. by a prior report run).
    Returns [] if no cached data exists for that week.
    """
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d")
    monday = _monday_of_week(target_date)

    xml = _load_week_cache(monday)
    if xml:
        events = _parse_events(xml)
        logging.info(f"[calendar_data] Week of {monday.strftime('%Y-%m-%d')}: {len(events)} events from cache")
        return events

    logging.warning(f"[calendar_data] No cached data for week of {monday.strftime('%Y-%m-%d')}")
    return []


def get_events_for_date_range(start: datetime | str, end: datetime | str) -> list[dict]:
    """
    Returns cached events across multiple weeks from start to end (inclusive).
    Merges all week-stamped caches that overlap with the date range.

    start/end can be datetime objects or strings like '2026-03-01'.
    Returns [] if no cached data exists for any week in the range.
    """
    if isinstance(start, str):
        start = datetime.strptime(start, "%Y-%m-%d")
    if isinstance(end, str):
        end = datetime.strptime(end, "%Y-%m-%d")

    all_events = []
    monday = _monday_of_week(start)
    while monday <= end:
        xml = _load_week_cache(monday)
        if xml:
            events = _parse_events_with_dates(xml)
            # Filter to only events within the requested date range
            for e in events:
                dt = e.get("_dt")
                if dt is not None:
                    dt_naive = dt.replace(tzinfo=None)
                    if start <= dt_naive <= end + timedelta(days=1):
                        e.pop("_dt", None)
                        all_events.append(e)
                else:
                    e.pop("_dt", None)
                    all_events.append(e)
        monday += timedelta(weeks=1)

    logging.info(f"[calendar_data] Date range {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}: "
                 f"{len(all_events)} events")
    return all_events


def list_cached_weeks() -> list[str]:
    """Returns a sorted list of Monday dates for which week-stamped caches exist."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    weeks = []
    for f in os.listdir(CACHE_DIR):
        if f.startswith("ff_week_") and f.endswith(".xml"):
            date_str = f[8:-4]  # extract YYYY-MM-DD
            weeks.append(date_str)
    weeks.sort()
    return weeks


# -- Standalone Test --
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    def _print_events(events, label):
        print(f"\n{'='*55}")
        print(f" {label}")
        print(f"{'='*55}")
        if not events:
            print("  No events.")
        else:
            for ev in events:
                print(f"  {ev['date']} {ev['time']:8} {ev['currency_label']:10} "
                      f"{ev['event']:35} {ev['impact']:6} F:{ev['forecast']:8} P:{ev['previous']}")
        print(f"  Total: {len(events)} events")

    # Usage: python calendar_data.py [start_date] [end_date]
    #   No args:                fetch this week + next week (normal mode)
    #   One arg (date):         fetch events for that week
    #   Two args (start end):   fetch events for date range
    #   "cache":                list all cached weeks
    if len(sys.argv) >= 2 and sys.argv[1] == "cache":
        weeks = list_cached_weeks()
        print(f"\nCached weeks ({len(weeks)}):")
        for w in weeks:
            print(f"  {w}")
    elif len(sys.argv) == 3:
        events = get_events_for_date_range(sys.argv[1], sys.argv[2])
        _print_events(events, f"EVENTS: {sys.argv[1]} to {sys.argv[2]}")
    elif len(sys.argv) == 2:
        events = get_events_for_week(sys.argv[1])
        _print_events(events, f"EVENTS FOR WEEK OF {sys.argv[1]}")
    else:
        data = get_all_calendar_data()
        _print_events(data["this_week"], "THIS WEEK (macro verification)")
        _print_events(data["next_week"], "NEXT WEEK (report calendar)")

        weeks = list_cached_weeks()
        if weeks:
            print(f"\nCached weeks: {', '.join(weeks)}")
