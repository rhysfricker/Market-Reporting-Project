# ============================================================
# news_data.py
# Pulls headline news from CNBC and BBC RSS feeds
# No API key required — free and open source friendly
# Used by report.py to populate the news/events section
# ============================================================

# ── Imports ─────────────────────────────────────────────────
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import certifi


# ── News Feed Configuration ──────────────────────────────────
# Two sources combined for maximum coverage:
#   CNBC — markets, earnings, Fed, macro, regional markets
#   BBC  — geopolitical, breaking news, world business
# All feeds are free RSS — no API key or signup required
# Ideal for open source / public GitHub distribution
MAX_HEADLINES = 5

FEEDS = {
    # ── CNBC Feeds ───────────────────────────────────────────
    "Markets":        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "Business":       "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147",
    "US Economy":     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069",
    "Europe Markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19794221",
    "Asia Markets":   "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19832390",

    # ── BBC Feeds ────────────────────────────────────────────
    "Geopolitical":   "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Breaking News":  "https://feeds.bbci.co.uk/news/rss.xml",
    "World Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
}


# ── Helper: Parse Single RSS Feed ───────────────────────────
# Fetches and parses one RSS feed URL
# Returns a list of headline dicts with title, date and link
# Returns empty list if feed fails so report can continue
def parse_feed(category, url):
    try:
        # Set browser-like headers to avoid being blocked
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url,
                                headers=headers,
                                timeout=10,
                                verify=certifi.where())
        response.raise_for_status()

        # Parse XML response from RSS feed
        root    = ET.fromstring(response.content)
        channel = root.find("channel")

        headlines = []
        for item in channel.findall("item")[:MAX_HEADLINES]:

            # --- Extract headline title ---
            title = item.findtext("title", "").strip()

            # --- Extract and format publication date ---
            pub_date = item.findtext("pubDate", "")
            try:
                dt       = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
                date_str = dt.strftime("%d %b %Y %H:%M")
            except Exception:
                date_str = pub_date

            # --- Extract article link ---
            link = item.findtext("link", "").strip()

            if title:
                headlines.append({
                    "category": category,
                    "title":    title,
                    "date":     date_str,
                    "link":     link,
                })

        print(f"  ✓ {category}: {len(headlines)} headlines fetched")
        return headlines

    except Exception as e:
        print(f"  ✗ {category}: Failed — {e}")
        return []


# ── Fetch All News ───────────────────────────────────────────
# Loops through all configured feeds and returns a combined
# dictionary of headlines organised by category
# Called by report.py to populate the news section
def fetch_all_news():
    print("\n📰  Fetching News Headlines...")
    all_news = {}
    for category, url in FEEDS.items():
        all_news[category] = parse_feed(category, url)
    return all_news


# ── Helper: Get Top Headlines Across All Categories ──────────
# Returns a flat list of the most recent headlines
# across all categories sorted by date
# Useful for the executive summary section of the report
def get_top_headlines(all_news, limit=10):
    combined = []
    for category, headlines in all_news.items():
        combined.extend(headlines)

    # Sort by date descending — most recent first
    try:
        combined.sort(
            key=lambda x: datetime.strptime(x["date"], "%d %b %Y %H:%M"),
            reverse=True
        )
    except Exception:
        pass

    return combined[:limit]


# ── Main: Print All Headlines ────────────────────────────────
# Runs when news_data.py is executed directly
# Useful for verifying all feeds load correctly
# before integrating into the full report
if __name__ == "__main__":
    news = fetch_all_news()

    print("\n" + "=" * 65)
    print(" HEADLINES SUMMARY")
    print("=" * 65)

    # --- Print headlines by category ---
    for category, headlines in news.items():
        print(f"\n── {category} ──")
        if headlines:
            for h in headlines:
                print(f"  [{h['date']}]")
                print(f"   {h['title']}")
        else:
            print("  No headlines available")

    # --- Print top 10 most recent across all feeds ---
    print("\n" + "=" * 65)
    print(" TOP 10 MOST RECENT HEADLINES")
    print("=" * 65)
    top = get_top_headlines(news, limit=10)
    for h in top:
        print(f"\n  [{h['date']}] {h['category']}")
        print(f"   {h['title']}")