"""
calendar_data.py
----------------
Fetches next week's high-impact economic calendar events from the
ForexFactory XML feed and returns them as a structured list of dicts.

Feed URLs (no API key required):
  This week : https://nfs.faireconomy.media/ff_calendar_thisweek.xml
  Next week : https://nfs.faireconomy.media/ff_calendar_nextweek.xml

Each <event> in the feed contains:
  <title>      — event name
  <country>    — two-letter country code (USD, EUR, GBP, JPY, CAD, etc.)
  <date>       — ISO 8601 datetime string
  <impact>     — High / Medium / Low / Holiday
  <forecast>   — analyst consensus estimate (may be empty)
  <previous>   — prior reading (may be empty)

This module:
  1. Fetches next week's XML feed (with a User-Agent header FF requires)
  2. Falls back to this week's feed if next week returns nothing
  3. Filters to HIGH-impact events for G7 currencies only
  4. Optionally includes MEDIUM-impact events (toggle via INCLUDE_MEDIUM)
  5. Returns a clean list of dicts ready for the HTML report
  6. Falls back to a hardcoded list if the live feed is completely unavailable
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Toggle whether medium-impact events are included alongside high-impact ones
INCLUDE_MEDIUM = False

# G7 currency codes as used by ForexFactory
G7_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "CHF"}

# Request headers — ForexFactory requires a browser-like User-Agent
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml, text/xml, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.forexfactory.com/",
}

FEED_NEXT_WEEK = "https://nfs.faireconomy.media/ff_calendar_nextweek.xml"
FEED_THIS_WEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

REQUEST_TIMEOUT = 15  # seconds

# ---------------------------------------------------------------------------
# CURRENCY → FLAG / COUNTRY LABEL MAPPING
# ---------------------------------------------------------------------------

CURRENCY_LABELS = {
    "USD": "🇺🇸 USD",
    "EUR": "🇪🇺 EUR",
    "GBP": "🇬🇧 GBP",
    "JPY": "🇯🇵 JPY",
    "CAD": "🇨🇦 CAD",
    "CHF": "🇨🇭 CHF",
    "AUD": "🇦🇺 AUD",
    "NZD": "🇳🇿 NZD",
    "CNY": "🇨🇳 CNY",
}

# ---------------------------------------------------------------------------
# FALLBACK DATA (used only if the live feed is completely unavailable)
# These are illustrative placeholders — update before each release if needed
# ---------------------------------------------------------------------------

FALLBACK_EVENTS = [
    {
        "date": "Mon",
        "time": "—",
        "currency": "USD",
        "currency_label": "🇺🇸 USD",
        "event": "ISM Services PMI",
        "impact": "High",
        "forecast": "52.8",
        "previous": "52.8",
    },
    {
        "date": "Tue",
        "time": "—",
        "currency": "EUR",
        "currency_label": "🇪🇺 EUR",
        "event": "German ZEW Economic Sentiment",
        "impact": "High",
        "forecast": "12.0",
        "previous": "26.0",
    },
    {
        "date": "Wed",
        "time": "—",
        "currency": "USD",
        "currency_label": "🇺🇸 USD",
        "event": "FOMC Meeting Minutes",
        "impact": "High",
        "forecast": "—",
        "previous": "—",
    },
    {
        "date": "Wed",
        "time": "—",
        "currency": "USD",
        "currency_label": "🇺🇸 USD",
        "event": "CPI m/m",
        "impact": "High",
        "forecast": "0.3%",
        "previous": "0.2%",
    },
    {
        "date": "Thu",
        "time": "—",
        "currency": "GBP",
        "currency_label": "🇬🇧 GBP",
        "event": "GDP m/m",
        "impact": "High",
        "forecast": "0.1%",
        "previous": "0.4%",
    },
    {
        "date": "Thu",
        "time": "—",
        "currency": "USD",
        "currency_label": "🇺🇸 USD",
        "event": "Unemployment Claims",
        "impact": "High",
        "forecast": "215K",
        "previous": "221K",
    },
    {
        "date": "Fri",
        "time": "—",
        "currency": "USD",
        "currency_label": "🇺🇸 USD",
        "event": "Core Retail Sales m/m",
        "impact": "High",
        "forecast": "0.4%",
        "previous": "-0.6%",
    },
    {
        "date": "Fri",
        "time": "—",
        "currency": "USD",
        "currency_label": "🇺🇸 USD",
        "event": "UoM Consumer Sentiment",
        "impact": "High",
        "forecast": "64.5",
        "previous": "64.7",
    },
]


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _parse_ff_datetime(raw: str) -> datetime | None:
    """
    Parse a ForexFactory datetime string.
    FF uses ISO 8601 with a timezone offset, e.g. '2025-03-17T08:30:00-04:00'
    Falls back gracefully if the format differs.
    """
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",   # standard ISO with offset
        "%Y-%m-%dT%H:%M:%S",     # no timezone
        "%m-%d-%Y",              # date only (older FF format)
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _format_day(dt: datetime | None) -> str:
    """Return short day name, e.g. 'Mon', 'Tue'."""
    if dt is None:
        return "—"
    return dt.strftime("%a")


def _format_time(dt: datetime | None) -> str:
    """Return HH:MM in local time (no tz conversion — FF times are already local)."""
    if dt is None:
        return "—"
    # If the datetime has no meaningful time component (midnight), return All Day
    if dt.hour == 0 and dt.minute == 0:
        return "All Day"
    return dt.strftime("%H:%M")


def _safe_text(element, tag: str) -> str:
    """Safely extract text from an XML child element."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return "—"


# ---------------------------------------------------------------------------
# CORE FETCH & PARSE
# ---------------------------------------------------------------------------

def _fetch_xml(url: str) -> str | None:
    """Fetch raw XML from a URL. Returns None on any error."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.warning(f"[calendar_data] Failed to fetch {url}: {e}")
        return None


def _parse_events(xml_text: str) -> list[dict]:
    """
    Parse a ForexFactory XML string and return a filtered list of event dicts.
    Filters to G7 currencies and HIGH (+ optionally MEDIUM) impact only.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logging.error(f"[calendar_data] XML parse error: {e}")
        return []

    events = []

    for event in root.findall("event"):
        # --- impact filter ---
        impact = _safe_text(event, "impact")
        if impact == "Holiday":
            continue
        if impact == "Low":
            continue
        if impact == "Medium" and not INCLUDE_MEDIUM:
            continue

        # --- currency filter ---
        currency = _safe_text(event, "country")
        if currency not in G7_CURRENCIES:
            continue

        # --- parse datetime ---
        raw_date = _safe_text(event, "date")
        dt = _parse_ff_datetime(raw_date) if raw_date != "—" else None

        title   = _safe_text(event, "title")
        forecast = _safe_text(event, "forecast")
        previous = _safe_text(event, "previous")

        # Blank forecast/previous → display dash
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
            # Keep raw dt for sorting
            "_dt":            dt,
        })

    # Sort chronologically (None datetimes go last)
    events.sort(key=lambda e: (e["_dt"] is None, e["_dt"] or datetime.max))

    # Remove internal sort key before returning
    for e in events:
        e.pop("_dt", None)

    return events


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def get_economic_calendar() -> list[dict]:
    """
    Main entry point. Returns a list of dicts for next week's high-impact
    G7 economic events, falling back gracefully at each stage.

    Each dict contains:
        date           — short day name, e.g. 'Mon'
        time           — HH:MM or 'All Day'
        currency       — e.g. 'USD'
        currency_label — e.g. '🇺🇸 USD'
        event          — event title
        impact         — 'High' or 'Medium'
        forecast       — analyst estimate or '—'
        previous       — prior reading or '—'
    """

    # --- 1. Try next week's feed ---
    logging.info("[calendar_data] Fetching next week's ForexFactory XML feed...")
    xml = _fetch_xml(FEED_NEXT_WEEK)

    if xml:
        events = _parse_events(xml)
        if events:
            logging.info(f"[calendar_data] Got {len(events)} events from next week feed.")
            return events
        else:
            logging.warning("[calendar_data] Next week feed returned no matching events.")

    # --- 2. Fall back to this week's feed ---
    logging.info("[calendar_data] Falling back to this week's ForexFactory XML feed...")
    xml = _fetch_xml(FEED_THIS_WEEK)

    if xml:
        events = _parse_events(xml)
        if events:
            logging.info(f"[calendar_data] Got {len(events)} events from this week feed.")
            return events
        else:
            logging.warning("[calendar_data] This week feed returned no matching events.")

    # --- 3. Final fallback — hardcoded placeholder list ---
    logging.warning("[calendar_data] Both feeds failed. Using hardcoded fallback events.")
    return FALLBACK_EVENTS


# ---------------------------------------------------------------------------
# STANDALONE TEST
# Run: python3 calendar_data.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("\n=== G7 Economic Calendar — Next Week ===\n")
    calendar = get_economic_calendar()

    if not calendar:
        print("No events returned.")
    else:
        col_w = [5, 8, 12, 35, 8, 10, 10]
        header = (
            f"{'Day':<{col_w[0]}} "
            f"{'Time':<{col_w[1]}} "
            f"{'Currency':<{col_w[2]}} "
            f"{'Event':<{col_w[3]}} "
            f"{'Impact':<{col_w[4]}} "
            f"{'Forecast':<{col_w[5]}} "
            f"{'Previous':<{col_w[6]}}"
        )
        print(header)
        print("-" * len(header))

        for ev in calendar:
            print(
                f"{ev['date']:<{col_w[0]}} "
                f"{ev['time']:<{col_w[1]}} "
                f"{ev['currency_label']:<{col_w[2]}} "
                f"{ev['event']:<{col_w[3]}} "
                f"{ev['impact']:<{col_w[4]}} "
                f"{ev['forecast']:<{col_w[5]}} "
                f"{ev['previous']:<{col_w[6]}}"
            )

    print(f"\nTotal events: {len(calendar)}")