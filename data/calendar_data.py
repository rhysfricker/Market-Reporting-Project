# ============================================================
# calendar_data.py
# Fetches economic calendar data from ForexFactory XML feeds
#
# Returns two separate datasets:
#
#   get_next_week_events()
#     → List of dicts for the report's "Key Events Next Week"
#       section. Fetches ff_calendar_nextweek.xml.
#       Falls back to ff_calendar_thisweek.xml if next week
#       isn't published yet (before Friday).
#
#   get_this_week_events()
#     → List of dicts for this week's actual releases.
#       Fetches ff_calendar_thisweek.xml.
#       Used by macro_data.py to verify which economic events
#       genuinely occurred this week before flagging FRED series
#       as released_this_week=True.
#
# Both functions filter to:
#   - High impact events only (toggle INCLUDE_MEDIUM to add Medium)
#   - G7 currencies: USD, EUR, GBP, JPY, CAD, CHF
#
# Report runs every Saturday so:
#   thisweek feed  = Mon–Fri just gone  → event verification
#   nextweek feed  = Mon–Fri coming     → calendar section
# ============================================================
 
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import logging
 
# ── Config ───────────────────────────────────────────────────
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
 
# ── Currency Labels ──────────────────────────────────────────
CURRENCY_LABELS = {
    "USD": "🇺🇸 USD", "EUR": "🇪🇺 EUR", "GBP": "🇬🇧 GBP",
    "JPY": "🇯🇵 JPY", "CAD": "🇨🇦 CAD", "CHF": "🇨🇭 CHF",
}
 
# ── Fallback Events (last resort if both feeds fail) ─────────
FALLBACK_NEXT_WEEK = [
    {"date": "Mon", "time": "—", "currency": "USD", "currency_label": "🇺🇸 USD", "event": "ISM Services PMI",           "impact": "High", "forecast": "—", "previous": "—"},
    {"date": "Tue", "time": "—", "currency": "EUR", "currency_label": "🇪🇺 EUR", "event": "German ZEW Sentiment",       "impact": "High", "forecast": "—", "previous": "—"},
    {"date": "Wed", "time": "—", "currency": "USD", "currency_label": "🇺🇸 USD", "event": "US CPI m/m",                 "impact": "High", "forecast": "—", "previous": "—"},
    {"date": "Wed", "time": "—", "currency": "USD", "currency_label": "🇺🇸 USD", "event": "FOMC Meeting Minutes",       "impact": "High", "forecast": "—", "previous": "—"},
    {"date": "Thu", "time": "—", "currency": "GBP", "currency_label": "🇬🇧 GBP", "event": "UK GDP m/m",                 "impact": "High", "forecast": "—", "previous": "—"},
    {"date": "Thu", "time": "—", "currency": "USD", "currency_label": "🇺🇸 USD", "event": "Unemployment Claims",        "impact": "High", "forecast": "—", "previous": "—"},
    {"date": "Fri", "time": "—", "currency": "USD", "currency_label": "🇺🇸 USD", "event": "Core Retail Sales m/m",      "impact": "High", "forecast": "—", "previous": "—"},
    {"date": "Fri", "time": "—", "currency": "USD", "currency_label": "🇺🇸 USD", "event": "UoM Consumer Sentiment",     "impact": "High", "forecast": "—", "previous": "—"},
]
 
FALLBACK_THIS_WEEK = []   # No fallback for verification — if feed fails, nothing gets flagged
 
 
# ── Helpers ──────────────────────────────────────────────────
def _parse_ff_datetime(raw: str) -> datetime | None:
    for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%m-%d-%Y"]:
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None
 
def _format_day(dt: datetime | None) -> str:
    return dt.strftime("%a") if dt else "—"
 
def _format_time(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return "All Day" if (dt.hour == 0 and dt.minute == 0) else dt.strftime("%H:%M")
 
def _safe_text(element, tag: str) -> str:
    child = element.find(tag)
    return child.text.strip() if (child is not None and child.text) else "—"
 
 
# ── Cache Config ─────────────────────────────────────────────
# In-memory cache: prevents duplicate fetches within same run.
# Disk cache: saves XML to .cache/ folder so repeated runs on
# the same day reuse the saved file instead of hitting FF again.
# Cache expires after CACHE_HOURS hours.
import os, time, hashlib
 
_XML_CACHE: dict = {}
CACHE_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_HOURS = 4   # reuse cached XML for up to 4 hours
 
 
def _cache_path(url: str) -> str:
    """Return a filesystem path for caching a given URL."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.md5(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"ff_{key}.xml")
 
 
def _load_disk_cache(url: str) -> str | None:
    """Return cached XML if it exists and is less than CACHE_HOURS old."""
    path = _cache_path(url)
    if os.path.exists(path):
        age_hours = (time.time() - os.path.getmtime(path)) / 3600
        if age_hours < CACHE_HOURS:
            logging.info(f"[calendar_data] Using disk cache ({age_hours:.1f}h old) for {url}")
            return open(path, encoding="utf-8").read()
    return None
 
 
def _save_disk_cache(url: str, xml: str) -> None:
    """Save fetched XML to disk cache."""
    try:
        open(_cache_path(url), "w", encoding="utf-8").write(xml)
    except Exception as e:
        logging.warning(f"[calendar_data] Could not save disk cache: {e}")
 
 
# ── Core Fetch ───────────────────────────────────────────────
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
            return r.text
        except requests.exceptions.HTTPError as e:
            if r.status_code == 429 and attempt == 0:
                logging.warning(f"[calendar_data] 429 rate limited — waiting 15s before retry...")
                time.sleep(15)
                continue
            logging.warning(f"[calendar_data] Failed to fetch {url}: {e}")
            return None
        except requests.RequestException as e:
            logging.warning(f"[calendar_data] Failed to fetch {url}: {e}")
            return None
    return None
 
 
# ── Core Parser ──────────────────────────────────────────────
def _parse_events(xml_text: str) -> list[dict]:
    """
    Parse FF XML and return filtered list of event dicts.
    Each dict contains: date, time, currency, currency_label,
    event, impact, forecast, previous, _dt (for sorting).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logging.error(f"[calendar_data] XML parse error: {e}")
        return []
 
    events = []
    for event in root.findall("event"):
        impact = _safe_text(event, "impact")
        if impact in ("Holiday", "Low"):
            continue
        if impact == "Medium" and not INCLUDE_MEDIUM:
            continue
 
        currency = _safe_text(event, "country")
        if currency not in G7_CURRENCIES:
            continue
 
        raw_date = _safe_text(event, "date")
        dt       = _parse_ff_datetime(raw_date) if raw_date != "—" else None
        title    = _safe_text(event, "title")
        forecast = _safe_text(event, "forecast")
        previous = _safe_text(event, "previous")
        forecast = forecast if forecast not in ("", "—", None) else "—"
        previous = previous if previous not in ("", "—", None) else "—"
 
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
 
 
# ── Public: Next Week Events (for report calendar section) ───
def get_next_week_events() -> list[dict]:
    """
    Returns high-impact G7 events for next week.
    Used by report.py for the "Key Events Next Week" section.
 
    Tries nextweek feed first (live from Friday onwards),
    falls back to thisweek feed mid-week, then hardcoded list.
    """
    logging.info("[calendar_data] Fetching next week events...")
 
    xml = _fetch_xml(FEED_NEXT_WEEK)
    if xml:
        events = _parse_events(xml)
        if events:
            logging.info(f"[calendar_data] Next week: {len(events)} events from nextweek feed.")
            return events
 
    logging.warning("[calendar_data] nextweek feed unavailable — trying thisweek feed.")
    xml = _fetch_xml(FEED_THIS_WEEK)
    if xml:
        events = _parse_events(xml)
        if events:
            logging.info(f"[calendar_data] Next week: {len(events)} events from thisweek feed (fallback).")
            return events
 
    logging.warning("[calendar_data] Both feeds failed — using hardcoded fallback.")
    return FALLBACK_NEXT_WEEK
 
 
# ── Public: This Week Events (for macro verification) ────────
def get_this_week_events() -> list[dict]:
    """
    Returns high-impact G7 events that occurred this week (Mon–Fri).
    Used by macro_data.py to verify which economic releases
    genuinely happened before flagging FRED series as released.
 
    Only uses thisweek feed — no fallback, because if the feed
    is unavailable we should not falsely flag any FRED series.
    Returns empty list on failure (safe default = nothing flagged).
    """
    logging.info("[calendar_data] Fetching this week events for macro verification...")
 
    xml = _fetch_xml(FEED_THIS_WEEK)
    if xml:
        events = _parse_events(xml)
        logging.info(f"[calendar_data] This week: {len(events)} events for macro verification.")
        return events
 
    logging.warning("[calendar_data] thisweek feed unavailable — no events flagged for macro.")
    return FALLBACK_THIS_WEEK
 
 
# ── Convenience: Get Both Feeds at Once ─────────────────────
def get_all_calendar_data() -> dict:
    """
    Fetches both feeds in one call. Returns:
    {
        "next_week": [...],   # for report calendar section
        "this_week": [...],   # for macro_data verification
    }
    Useful when both are needed (e.g. in report.py) to avoid
    fetching the thisweek feed twice.
    """
    this_week = get_this_week_events()
    next_week = get_next_week_events()
    return {"this_week": this_week, "next_week": next_week}
 
 
# ── Standalone Test ──────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
 
    data = get_all_calendar_data()
 
    for section, label in [("this_week", "THIS WEEK (macro verification)"),
                            ("next_week", "NEXT WEEK (report calendar)")]:
        print(f"\n{'='*55}")
        print(f" {label}")
        print(f"{'='*55}")
        events = data[section]
        if not events:
            print("  No events.")
        else:
            for ev in events:
                print(f"  {ev['date']} {ev['time']:8} {ev['currency_label']:10} {ev['event']:35} {ev['impact']:6} F:{ev['forecast']:8} P:{ev['previous']}")
        print(f"  Total: {len(events)} events")