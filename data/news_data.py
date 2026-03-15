# ============================================================
# news_data.py
# Pulls headline news from CNBC, BBC, and Reuters RSS feeds
# No API key required — free and open source friendly
# Used by report.py to populate the news/events section
#
# Feed categories and what they drive in the report:
#   GEOPOLITICAL  → all sections (wars, sanctions, crises)
#   BREAKING      → all sections (major world events)
#   SUPPLY/DEMAND → commodities (oil supply, OPEC, shipping)
#   EARNINGS      → equities (company results, guidance)
#   RATES/CBanks  → currencies (Fed, ECB, BoE, BoJ decisions)
#   REGIONAL      → the relevant geographic section
# ============================================================
 
# ── Imports ─────────────────────────────────────────────────
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import certifi
 
 
# ── Feed Configuration ───────────────────────────────────────
# MAX_HEADLINES per feed. Geopolitical/Breaking fetch more
# because a single major event can affect every section.
MAX_HEADLINES_DEFAULT     = 5
MAX_HEADLINES_GEOPOLITICAL = 8   # Wars, sanctions, crises affect every market
MAX_HEADLINES_BREAKING     = 8   # Same — major world events permeate everything
 
FEEDS = {
    # ── CNBC Regional / Macro ────────────────────────────────
    "Markets":        ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",  MAX_HEADLINES_DEFAULT),
    "Business":       ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147",  MAX_HEADLINES_DEFAULT),
    "US Economy":     ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069",  MAX_HEADLINES_DEFAULT),
    "Europe Markets": ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19794221",  MAX_HEADLINES_DEFAULT),
    "Asia Markets":   ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19832390",  MAX_HEADLINES_DEFAULT),
 
    # ── BBC World / Geopolitical ─────────────────────────────
    # Fetches more headlines — a war or crisis in the Middle East
    # belongs in commodities, equities, currencies AND the exec summary
    "Geopolitical":   ("https://feeds.bbci.co.uk/news/world/rss.xml",    MAX_HEADLINES_GEOPOLITICAL),
    "Breaking News":  ("https://feeds.bbci.co.uk/news/rss.xml",          MAX_HEADLINES_BREAKING),
    "World Business": ("https://feeds.bbci.co.uk/news/business/rss.xml", MAX_HEADLINES_DEFAULT),
 
    # ── Energy & Commodities Supply/Demand ───────────────────
    # CNBC Energy — OPEC cuts, oil supply shocks, shipping disruptions
    "Energy":         ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", MAX_HEADLINES_DEFAULT),

    # ── Oil & Commodities / Middle East ────────────────────────
    # Reuters business news for oil/commodities context;
    # BBC Middle East for war/conflict headlines that drive oil prices
    "Oil & Commodities": ("https://oilprice.com/rss/main",                                   MAX_HEADLINES_GEOPOLITICAL),
    "Middle East":       ("https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",         MAX_HEADLINES_GEOPOLITICAL),

    # ── Earnings ─────────────────────────────────────────────
    # CNBC Earnings — company results that move equity indices
    "Earnings":       ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069", MAX_HEADLINES_DEFAULT),
 
    # ── Central Banks / Rates ────────────────────────────────
    # CNBC Fed/Policy feed — rate decisions that move currencies
    "Central Banks":  ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", MAX_HEADLINES_DEFAULT),
}
 
# ── Feed routing — which feeds belong to which report section
# report.py uses these keys in format_headlines() calls
SECTION_FEEDS = {
    # Every section gets geopolitical + breaking as a baseline
    "geopolitical":  ["Geopolitical", "Breaking News"],
 
    # Section-specific feeds layered on top
    "us":            ["Markets", "US Economy", "Business", "Earnings"],
    "europe":        ["Europe Markets", "World Business", "Business"],
    "japan":         ["Asia Markets"],
    "commodities":   ["Energy", "World Business", "Middle East", "Oil & Commodities"],
    "currencies":    ["Central Banks", "Markets"],
    "earnings":      ["Earnings", "Business"],
}
 
 
# ── Helper: Parse Single RSS Feed ───────────────────────────
# Collects ALL headlines from the feed published in the last 7 days.
# No arbitrary item cap — we want full week coverage, not just the
# most recent few. max_items is kept as a safety ceiling only.
def parse_feed(category, url, max_items=200):
    try:
        from datetime import timezone, timedelta
        headers  = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10, verify=certifi.where())
        response.raise_for_status()
 
        root    = ET.fromstring(response.content)
        channel = root.find("channel")
 
        cutoff   = datetime.now(timezone.utc) - timedelta(days=7)
        headlines = []
 
        for item in channel.findall("item")[:max_items]:
            title    = item.findtext("title", "").strip()
            pub_date = item.findtext("pubDate", "")
            link     = item.findtext("link", "").strip()
 
            if not title:
                continue
 
            # Parse publish date — try the standard RSS format first,
            # then fall back to storing the raw string for display
            dt       = None
            date_str = pub_date
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
                try:
                    dt       = datetime.strptime(pub_date, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    date_str = dt.strftime("%d %b %Y %H:%M")
                    break
                except Exception:
                    continue
 
            # Drop anything older than 7 days; keep if date unparseable
            # (better to include than silently drop)
            if dt is not None and dt < cutoff:
                continue
 
            # Tag as weekday (Mon-Fri) or weekend (Sat-Sun)
            # Weekday headlines can explain market moves; weekend ones are forward context only
            is_weekend = dt.weekday() >= 5 if dt is not None else False

            headlines.append({
                "category": category,
                "title":    title,
                "date":     date_str,
                "dt":       dt,   # kept for sorting; not used in prompts
                "link":     link,
                "is_weekend": is_weekend,
            })
 
        print(f"  ✓ {category}: {len(headlines)} headlines (last 7 days)")
        return headlines
 
    except Exception as e:
        print(f"  ✗ {category}: Failed — {e}")
        return []
 
 
# ── Fetch All News ───────────────────────────────────────────
# Passes a generous safety ceiling (100) to parse_feed.
# The 7-day date filter is the real gate — not item count.
def fetch_all_news():
    print("\n📰  Fetching News Headlines (last 7 days)...")
    all_news = {}
    for category, (url, _) in FEEDS.items():
        all_news[category] = parse_feed(category, url, max_items=100)
    return all_news
 
 
# ── Get Headlines for a Report Section ───────────────────────
# Returns a flat list of headlines for a given section,
# ALWAYS prepending geopolitical/breaking headlines first
# so world-affecting events are never silently dropped.
#
# Usage in report.py:
#   get_section_headlines(news, "commodities", limit=12)
#   get_section_headlines(news, "us",          limit=10)
def get_section_headlines(all_news, section, limit=20):
    """
    Returns headlines for a report section covering the full past 7 days.
    Geopolitical + Breaking are ALWAYS included first —
    they are the most likely to explain market moves.
    Section-specific feeds are appended after.
    Results are sorted newest-first within each priority group.
    """
    from datetime import timezone
 
    def sort_key(h):
        if h.get("dt") is not None:
            return h["dt"]
        try:
            return datetime.strptime(h["date"], "%d %b %Y %H:%M").replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)
 
    seen   = set()
    geo    = []
    specific = []
 
    # 1. Geopolitical + Breaking — always first
    for cat in SECTION_FEEDS["geopolitical"]:
        for h in all_news.get(cat, []):
            key = h["title"].strip().lower()
            if key not in seen:
                seen.add(key)
                geo.append(h)
 
    # 2. Section-specific feeds
    for cat in SECTION_FEEDS.get(section, []):
        for h in all_news.get(cat, []):
            key = h["title"].strip().lower()
            if key not in seen:
                seen.add(key)
                specific.append(h)
 
    # Sort each group newest-first, then combine
    # Sort: weekday headlines first (they drove market moves),
    # then weekend headlines (forward context only). Newest-first within each.
    all_hl = geo + specific
    weekday_hl = [h for h in all_hl if not h.get("is_weekend", False)]
    weekend_hl = [h for h in all_hl if h.get("is_weekend", False)]
    weekday_hl.sort(key=sort_key, reverse=True)
    weekend_hl.sort(key=sort_key, reverse=True)

    return (weekday_hl + weekend_hl)[:limit]
 
 
# ── Format Headlines for a Prompt ────────────────────────────
# Returns a plain-text bullet list ready to paste into a prompt.
# Headlines are split into WEEKDAY (Mon-Fri, when markets were open)
# and WEEKEND (Sat-Sun, after market close) so the AI knows which
# headlines could have driven market moves vs. which are forward context.
def format_section_headlines(all_news, section, limit=12):
    headlines = get_section_headlines(all_news, section, limit=limit)
    if not headlines:
        return "No headlines available."

    weekday = [h for h in headlines if not h.get("is_weekend", False)]
    weekend = [h for h in headlines if h.get("is_weekend", False)]

    lines = []
    if weekday:
        lines.append("WEEKDAY HEADLINES (Mon-Fri, markets open — these drove this week's moves):")
        for h in weekday:
            lines.append(f"- [{h['category']}] {h['title']}")
    if weekend:
        if weekday:
            lines.append("")
        lines.append("WEEKEND HEADLINES (Sat-Sun, after market close — context only, did NOT cause this week's moves):")
        for h in weekend:
            lines.append(f"- [{h['category']}] {h['title']}")

    return "\n".join(lines)
 
 
# ── Helper: Get Top Headlines Across All Categories ──────────
def get_top_headlines(all_news, limit=10):
    combined = []
    for category, headlines in all_news.items():
        combined.extend(headlines)
    # Sort by parsed datetime if available, fall back to string date
    def sort_key(h):
        if h.get("dt") is not None:
            return h["dt"]
        try:
            from datetime import timezone
            return datetime.strptime(h["date"], "%d %b %Y %H:%M").replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=__import__("datetime").timezone.utc)
    combined.sort(key=sort_key, reverse=True)
    return combined[:limit]
 
 
# ── Main: Print All Headlines ────────────────────────────────
if __name__ == "__main__":
    news = fetch_all_news()
 
    print("\n" + "=" * 65)
    print(" HEADLINES BY SECTION")
    print("=" * 65)
 
    for section in ["us", "europe", "japan", "commodities", "currencies", "earnings"]:
        print(f"\n── {section.upper()} SECTION ──")
        print(format_section_headlines(news, section, limit=10))
 
    print("\n" + "=" * 65)
    print(" TOP 10 MOST RECENT ACROSS ALL FEEDS")
    print("=" * 65)
    for h in get_top_headlines(news, limit=10):
        print(f"\n  [{h['date']}] {h['category']}")
        print(f"   {h['title']}")