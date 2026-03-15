# ============================================================
# report.py
# Generates the weekly G7 Market Report as an HTML file
# Focus: this week's news → market effect → why it matters
# Charts appear in technical section only
# ============================================================
 
# ── Imports ─────────────────────────────────────────────────
import os
import re
import json
import urllib.request
import threading
import http.server
import socketserver
from datetime import datetime, timedelta
from fetch_data import fetch_all_data
from indicators import calculate_indicators, calculate_pivot_points, format_price
from macro_data import fetch_all_macro, get_this_weeks_releases, val
from news_data import fetch_all_news, get_top_headlines, format_section_headlines
from config import instruments
from calendar_data import get_this_week_events
import ssl
import certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
 
# ── Configuration ────────────────────────────────────────────
# Anthropic API key required — get yours at https://console.anthropic.com
from dotenv import load_dotenv
load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OUTPUT_DIR = "reports"
os.makedirs(OUTPUT_DIR, exist_ok=True)
CHARTS_DIR = "charts"
CHART_SERVER_PORT = 8765
 
# ── Date Helpers ─────────────────────────────────────────────
today      = datetime.today()
week_start = today - timedelta(days=today.weekday())
week_end   = week_start + timedelta(days=4)
WEEK_LABEL = f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"
TODAY_STR  = today.strftime("%d %B %Y")
 
 
# ── Local HTTP Server for Charts ─────────────────────────────
# Chrome blocks file:// image paths during print. Serving charts
# over localhost:8765 removes that restriction instantly.
 
def start_chart_server(directory, port=CHART_SERVER_PORT):
    """Spin up a background HTTP server to serve chart images."""
    original_dir = os.getcwd()
    os.chdir(directory)
 
    handler = http.server.SimpleHTTPRequestHandler
    # Silence the default request logs
    handler.log_message = lambda *args: None
 
    try:
        httpd = socketserver.TCPServer(("", port), handler)
    except OSError:
        # Port already in use — server likely already running, that's fine
        os.chdir(original_dir)
        return None
 
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True  # Dies automatically when main script exits
    thread.start()
    os.chdir(original_dir)
    print(f"  ✓ Chart server running at http://localhost:{port}")
    return httpd
 
 
# ── Helper: Get Chart URL ─────────────────────────────────────
def encode_chart(ticker):
    """Return a localhost URL for the chart image (not file://)."""
    filename = ticker.replace("=", "_").replace("^", "")
    filepath = os.path.abspath(os.path.join(CHARTS_DIR, f"{filename}_chart.png"))
    if os.path.exists(filepath):
        return f"http://localhost:{CHART_SERVER_PORT}/{CHARTS_DIR}/{filename}_chart.png"
    return None
 
 
# ── Helper: Call Claude API ───────────────────────────────────
def call_claude(prompt, max_tokens=500):
    try:
        payload = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["content"][0]["text"]
    except Exception as e:
        print(f"  ✗ Claude API call failed — {e}")
        return "Narrative unavailable."
 
 
# ── Helper: Determine Bias ────────────────────────────────────
def get_bias(latest, prev):
    try:
        rsi    = float(latest["RSI"])
        macd   = float(latest["MACD"])
        signal = float(latest["MACD_Signal"])
        macd_p = float(prev["MACD"])
        sig_p  = float(prev["MACD_Signal"])
        close  = float(latest["Close"])
        sma200 = float(latest["SMA_200"])
        above_200 = close > sma200
        if macd_p < sig_p and macd > signal and above_200:
            return "🟢 Bullish"
        elif macd_p > sig_p and macd < signal and not above_200:
            return "🔴 Bearish"
        elif rsi > 60 and macd > signal:
            return "🟢 Bullish"
        elif rsi < 40 and macd < signal:
            return "🔴 Bearish"
        else:
            return "🟡 Neutral"
    except Exception:
        return "🟡 Neutral"
 
 
# ── Helper: Get Weekly Price Change ──────────────────────────
# Calculates Friday close → Friday close weekly change, matching
# what Yahoo Finance shows as the 5-day change.
# yfinance includes Sunday overnight sessions as extra rows for
# futures tickers (ES=F, NQ=F etc), which would push iloc[-6] onto
# Sunday instead of the prior Friday. We strip Sunday rows only
# for this calculation — the raw df passed in is left untouched.
def get_weekly_change(df):
    try:
        import pandas as pd

        # Flatten MultiIndex columns (yfinance quirk with some tickers)
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)

        df = df.dropna(subset=["Close"])
        if df.empty:
            return None

        # Normalise index to tz-naive for consistent weekday detection
        idx = pd.to_datetime(df.index)
        if idx.tz is not None:
            idx = idx.tz_convert("America/New_York").tz_localize(None)
        df = df.copy()
        df.index = idx

        # Drop Sunday rows only — keeps all Mon-Fri sessions intact
        # so iloc[-1] = this Friday, iloc[-6] = prior Friday, always
        df = df[df.index.dayofweek != 6]

        if len(df) < 6:
            return None

        close_now  = float(df["Close"].iloc[-1])
        close_week = float(df["Close"].iloc[-6])
        return round(((close_now - close_week) / close_week) * 100, 2)

    except Exception:
        return None
 
 
# format_headlines removed — use format_section_headlines(news, section) from news_data.py
# It always prepends geopolitical + breaking headlines before section-specific ones.
 
 
# ── SYSTEM PROMPT ─────────────────────────────────────────────
SYSTEM_CONTEXT = """You write weekly market report sections for a general audience.
 
CRITICAL DATA RULES — READ FIRST:
1. You must ONLY use the data, figures, and headlines explicitly provided in this prompt.
2. Do NOT use your own knowledge of current events, recent news, or market moves.
3. Do NOT invent, estimate, or assume any figures, events, or market moves not given to you.
4. If the prompt does not tell you a market moved, do not say it moved.
5. If a data point is not in the "Released this week" section, do not present it as new news.
6. If you have insufficient data to fill a paragraph, write fewer paragraphs — do not pad with fabrications.
7. Never reference specific news events, central bank decisions, geopolitical events, or company news
   unless they appear verbatim in the headlines provided to you.
8. If a headline describes a geopolitical event, military conflict, supply shock, or major world event
   that is driving market moves — NAME IT EXPLICITLY. Do not describe the effect (e.g. "oil surged")
   without naming the cause (e.g. "following US-Israeli strikes on Iran and the Strait of Hormuz closure").
9. Headlines tagged [Geopolitical] or [Breaking News] are the highest priority — if they explain a
   market move, they MUST be referenced. Do not bury or omit them.
10. Headlines are split into WEEKDAY (Mon-Fri) and WEEKEND (Sat-Sun) sections.
    WEEKDAY headlines happened while markets were open — use these to explain market moves.
    WEEKEND headlines happened AFTER markets closed — they did NOT cause this week's price action.
    NEVER cite a weekend headline as the reason for a market move this week.
    Weekend headlines may only be mentioned as forward-looking context (e.g. "looking ahead...").

WRITING RULES:
8. Structure every point as: [what happened] → [which market moved] → [why it moved]
9. Plain English only — if you use a financial term, explain it briefly in brackets
10. Maximum 3 short paragraphs per section — fewer if the data does not support more
11. Weave relevant headlines naturally into prose — do not list them
12. Only reference a headline if it directly explains a market move in the data provided
13. End with one sentence about what to watch next week, based only on data provided
14. Do NOT use markdown formatting — no **bold**, no ## headers, no bullet points"""
 
 
# ── Section: Executive Summary ────────────────────────────────
def build_executive_summary(macro, releases, news, all_data):
    print("  Writing executive summary...")
    # Executive summary gets ALL section feeds merged — it covers everything
    headlines_txt = format_section_headlines(news, "us", limit=20)
    changes = {}
    for name, ticker in [("S&P500","ES=F"),("Nasdaq","NQ=F"),("Gold","GC=F"),("Oil","CL=F")]:
        if ticker in all_data:
            df = calculate_indicators(all_data[ticker].copy())
            changes[name] = get_weekly_change(df)
    changes_txt = " | ".join([
        f"{k}: {'+' if v and v>0 else ''}{v}%"
        for k, v in changes.items() if v is not None
    ])
 
    released_txt = ""
    if releases["any"]:
        parts = []
        if releases["us"]:
            parts.append("US: " + " | ".join(releases["us"]))
        if releases["eu"]:
            parts.append("EU/UK: " + " | ".join(releases["eu"]))
        if releases["jp"]:
            parts.append("Japan: " + " | ".join(releases["jp"]))
        released_txt = "\n".join(parts)
    else:
        released_txt = "No major data confirmed released this week."
 
    prompt = f"""{SYSTEM_CONTEXT}
 
REMINDER: Base your writing ONLY on the market moves, data, and headlines listed below.
Do not add any events, figures, or context not explicitly provided.
If a [Geopolitical] or [Breaking News] headline explains market moves this week, name it explicitly.

NO FABRICATION RULES:
- Do NOT add context, reasons, or commentary beyond what the data and headlines explicitly show.
- Do NOT speculate about what might happen or what investors were thinking.
- If insufficient data exists to write 4 sentences, write fewer.

CENTRAL BANK RATE RULE — CRITICAL:
- Do NOT mention the Fed funds rate or any interest rate figure UNLESS a Fed decision or FOMC
  announcement appears in the "Released this week" section below.
- Rates that did not change this week are not news and must not appear in the narrative.

INFLATION DATA RULES — CRITICAL:
- CPI and Core PCE are TWO DIFFERENT measures. NEVER conflate them.
- If referencing inflation, state which measure it is: "CPI came in at X%" or "Core PCE stood at Y%".
- Do NOT blend or average these two figures.
 
Write an executive summary for this week's market report. Maximum 4 sentences.
Start with the single most important story of the week.
Use WEEKDAY headlines only to explain market moves — weekend headlines did NOT drive this week's price action.

OIL MOVE RULE — CRITICAL: If oil moved more than 3% this week, the cause MUST be named explicitly
from the geopolitical/energy headlines. The cause of large oil moves is ALWAYS military conflict,
supply disruption, blockades, or sanctions — NEVER sports events, weather, or unrelated news.
Do NOT cite sports cancellations (F1, football, Olympics etc.) as explanations for oil price moves.
Scan [Geopolitical], [Breaking News], [Middle East] and [Energy] headlines for the real cause.

Use the format: X happened → markets did Y → because Z.
End with the biggest risk to watch next week based only on headlines and data provided.
 
Headlines available this week (geopolitical/breaking listed first — use if market-moving):
{headlines_txt}
 
Key market moves this week:
{changes_txt}
 
Key data released this week:
{released_txt}"""
    return call_claude(prompt, max_tokens=300)
 
 
# ── Section: US Narrative ─────────────────────────────────────
def build_us_narrative(macro, releases, news, all_data):
    print("  Writing US narrative...")
    # Geopolitical + Breaking always prepended; then US-specific feeds (markets, economy, earnings)
    headlines = format_section_headlines(news, "us", limit=20)
    us        = macro["us"]
    changes = {}
    for name, ticker in [("S&P500","ES=F"),("Nasdaq","NQ=F"),("Dow","YM=F"),("Dollar","DX-Y.NYB")]:
        if ticker in all_data:
            df = calculate_indicators(all_data[ticker].copy())
            changes[name] = get_weekly_change(df)
    changes_txt = " | ".join([
        f"{k}: {'+' if v and v>0 else ''}{v}%"
        for k, v in changes.items() if v is not None
    ])
 
    # Split into released this week vs background context
    released_us = releases["us"]
    # Only pass data that genuinely moved this week
    # Yield moves daily so reflects this week's action — include it
    # Yield spread is a standing calculated value — excluded
    background = [
        f"10yr Yield: {val(us.get('yield_10yr'))}% (only mention if bond markets moved this week)",
    ]
 
    prompt = f"""{SYSTEM_CONTEXT}
 
REMINDER: Base your writing ONLY on the market moves, data, and headlines listed below.
Do not add any events, figures, or context not explicitly provided.
If a [Geopolitical] or [Breaking News] headline is driving US market moves, name it explicitly — not just its effect.
If an [Earnings] headline moved equity indices this week, include it.

NO FABRICATION RULES:
- Do NOT speculate about future Fed policy, rate cuts, or rate hikes unless a headline explicitly states this.
- Do NOT invent reasons markets moved beyond what the headlines and data show.
- Do NOT add context about "investors worried about X" unless a headline says so.
- If insufficient data exists to write 3 paragraphs, write fewer — do not pad.

CENTRAL BANK RATE RULE — CRITICAL:
- Do NOT mention the Fed funds rate or any interest rate figure UNLESS a Fed/FOMC decision appears
  in the "Released this week" section below — meaning a rate decision actually happened this week.
- Rates that did not change this week are not news and must not appear in the narrative.

INFLATION DATA RULES — CRITICAL:
- CPI (Consumer Price Index) and Core PCE (Personal Consumption Expenditures) are TWO DIFFERENT measures.
- CPI is the BLS headline inflation figure — what consumers pay for goods and services.
- Core PCE is the Fed's preferred inflation gauge — it strips out food and energy and uses different weights.
- NEVER present the Core PCE figure as a CPI figure or vice versa.
- If both are in the data below, name each explicitly: "CPI came in at X%" and "Core PCE, the Fed's preferred gauge, stood at Y%".
- Do NOT blend, average, or confuse these two numbers.

GDP WORDING RULE — CRITICAL:
- The US GDP figure provided below IS ALREADY AN ANNUALISED RATE. Use it exactly as given.
- NEVER multiply it by 4 or any other number — it is not a raw quarterly figure.
- ALWAYS write it as "the economy grew at an annualised rate of X%" using the exact number provided.
- NEVER write "X% quarter-over-quarter", "X% quarterly growth", or derive any other figure from it.
- Example: if the data shows X%, write "grew at an annualised rate of X%" — do NOT write X*4%, do NOT derive any other figure.

Write the US Economy section. 3 short paragraphs using WEEKDAY headlines only for market moves.
Format: [news event] → [US market that reacted] → [why it reacted]
Only mention data figures if they were released this week and caused a market move.
Weave in specific headlines naturally where they explain a market move — do not list them.
If WEEKEND headlines contain market-relevant news, add one brief sentence at the end noting
what traders should watch on Monday's open — but do NOT attribute any of this week's moves to them.
 
Available headlines (geopolitical/breaking listed first):
{headlines}
 
US market moves this week:
{changes_txt}
 
Released this week (USE THESE — they are confirmed this week's data):
{chr(10).join(released_us) if released_us else 'No major US releases confirmed this week'}
 
Background context (only mention if directly relevant to a market move):
{chr(10).join(background)}"""
    return call_claude(prompt, max_tokens=500)
 
 
# ── Section: Europe & UK Narrative ───────────────────────────
def build_europe_narrative(macro, releases, news, all_data):
    print("  Writing Europe & UK narrative...")
    # Geopolitical + Breaking always prepended; then Europe-specific feeds
    headlines = format_section_headlines(news, "europe", limit=20)
    eu        = macro["eu"]
    changes = {}
    for name, ticker in [("DAX","^GDAXI"),("FTSE100","^FTSE"),("EuroStoxx","^STOXX50E"),("Euro","6E=F"),("Sterling","6B=F")]:
        if ticker in all_data:
            df = calculate_indicators(all_data[ticker].copy())
            changes[name] = get_weekly_change(df)
    changes_txt = " | ".join([
        f"{k}: {'+' if v and v>0 else ''}{v}%"
        for k, v in changes.items() if v is not None
    ])
 
    released_eu = releases["eu"]
    # Only pass CPI figures if they were actually released this week
    # Standing inflation figures are not news and must not appear in narrative
    background = []
    if eu.get("ez_cpi", {}).get("released_this_week"):
        background.append(f"EZ CPI released this week: {val(eu.get('ez_cpi'))}% YoY")
    if eu.get("uk_cpi", {}).get("released_this_week"):
        background.append(f"UK CPI released this week: {val(eu.get('uk_cpi'))}% YoY")

    prompt = f"""{SYSTEM_CONTEXT}

REMINDER: Base your writing ONLY on the market moves, data, and headlines listed below.
Do not add any events, figures, or context not explicitly provided.
If a [Geopolitical] or [Breaking News] headline is driving European market moves, name it explicitly.

CENTRAL BANK RATE RULE — CRITICAL:
- Do NOT mention the BoE Bank Rate, ECB rate, or any central bank rate UNLESS it appears
  in the "Released this week" section below — meaning a rate decision actually happened this week.
- If no rate decision is listed, do NOT reference any central bank rate at all.
- This is a weekly report. Rates that did not change this week are not news.

NO FABRICATION RULES:
- Do NOT invent reasons, speculation, or context not present in the headlines or data below.
- Do NOT reference government policy, energy bill interventions, or political decisions
  unless they appear explicitly in a headline provided.
- If insufficient data exists to write 3 paragraphs, write fewer.

Write the Europe & UK section. Cover Eurozone AND UK separately — they often move differently.
3 short paragraphs using WEEKDAY headlines only for market moves. Format: [news event] → [which market moved] → [why]
Weave in specific headlines naturally where they explain a market move — do not list them.
If WEEKEND headlines contain market-relevant news, add one brief sentence at the end noting what to watch on Monday's open.

Available headlines (geopolitical/breaking listed first):
{headlines}

Market moves this week:
{changes_txt}

Released this week (USE THESE — confirmed this week's data):
{chr(10).join(released_eu) if released_eu else 'No major EU/UK releases confirmed this week'}

Background context (only mention if directly relevant to explaining a move):
{chr(10).join(background)}"""
    return call_claude(prompt, max_tokens=500)
 
 
# ── Section: Japan Narrative ──────────────────────────────────
def build_japan_narrative(macro, releases, news, all_data):
    print("  Writing Japan narrative...")
    # Geopolitical + Breaking always prepended; then Asia/Japan-specific feeds
    headlines = format_section_headlines(news, "japan", limit=15)
    jp        = macro["jp"]
    changes = {}
    for name, ticker in [("Nikkei","NKD=F"),("Yen","6J=F")]:
        if ticker in all_data:
            df = calculate_indicators(all_data[ticker].copy())
            changes[name] = get_weekly_change(df)
    changes_txt = " | ".join([
        f"{k}: {'+' if v and v>0 else ''}{v}%"
        for k, v in changes.items() if v is not None
    ])
 
    released_jp = releases["jp"]
    # BoJ rate removed from background — only mention if a decision happened this week
    # Japan CPI only in background if released this week — otherwise remove it
    background = [
        f"Japan CPI: {val(jp.get('japan_cpi'))}% (only mention if in Released this week above)"
        if jp.get('japan_cpi') and macro.get('jp',{}).get('japan_cpi',{}).get('released_this_week')
        else ""
    ]
    background = [b for b in background if b]  # remove empty strings

    prompt = f"""{SYSTEM_CONTEXT}

REMINDER: Base your writing ONLY on the market moves, data, and headlines listed below.
Do not add any events, figures, or context not explicitly provided.
If a [Geopolitical] or [Breaking News] headline is affecting the Nikkei or Yen, name it explicitly.

CENTRAL BANK RATE RULE — CRITICAL:
- Do NOT mention the BoJ rate or any interest rate UNLESS it appears in the "Released this week"
  section below — meaning a BoJ rate decision actually happened this week.
- If no BoJ decision is listed, do NOT reference the BoJ rate at all.
- You MAY briefly explain the yen carry trade concept if it helps explain a yen move, but only
  reference it as a general mechanism — do not state a specific rate figure.

NO FABRICATION RULES:
- Do NOT invent reasons, speculation, or context beyond what the headlines and data below show.
- Do NOT reference corporate earnings, export demand, or economic outlook unless a headline says so.
- If insufficient data exists to write 2 paragraphs, write one.

Write the Japan section. 2 short paragraphs using WEEKDAY headlines only for market moves.
Format: [news event] → [Nikkei or Yen reaction] → [why]
Weave in specific headlines naturally where they explain a market move — do not list them.
If WEEKEND headlines contain market-relevant news, add one brief sentence noting what to watch on Monday.

Available headlines (geopolitical/breaking listed first):
{headlines}

Japan market moves this week:
{changes_txt}

Released this week (USE THESE — confirmed this week's data):
{chr(10).join(released_jp) if released_jp else 'No major Japan releases confirmed this week'}

Background context (only mention if directly relevant to explaining a move):
{chr(10).join(background)}"""
    return call_claude(prompt, max_tokens=400)
 
 
# ── Section: Commodities Narrative ───────────────────────────
def build_commodities_narrative(macro, news, all_data):
    print("  Writing commodities narrative...")
    # Commodities: geopolitical first (wars, sanctions, Hormuz closures drive oil)
    # then energy/supply-demand feeds (OPEC, shipping, production data)
    headlines = format_section_headlines(news, "commodities", limit=30)
    commodities = {}
    for name, ticker in [("Gold","GC=F"),("Silver","SI=F"),("Oil","CL=F")]:
        if ticker in all_data:
            df = calculate_indicators(all_data[ticker].copy())
            try:
                close_val = df["Close"].iloc[-1]
                if hasattr(close_val, '__len__'):
                    close_val = close_val.iloc[0]
                price  = round(float(close_val), 2)
                change = get_weekly_change(df)
                commodities[name] = {"price": price, "change": change}
            except Exception:
                pass
    prices_txt = " | ".join([
        f"{k}: ${v['price']} ({'+' if v['change'] and v['change']>0 else ''}{v['change']}% this week)"
        for k, v in commodities.items() if v
    ])
    prompt = f"""{SYSTEM_CONTEXT}
 
REMINDER: Base your writing ONLY on the commodity prices, moves, and headlines listed below.
Do not add any events, figures, or context not explicitly provided.
 
COMMODITY-SPECIFIC RULES — CRITICAL:
- Any oil price move above 3% in a week is ALWAYS caused by a supply disruption, geopolitical shock,
  or major demand shift. You MUST name the specific event from the headlines.
- Scan ALL headlines — [Geopolitical], [Breaking News], [Middle East], [Energy] — for the cause.
- If headlines mention military strikes on oil infrastructure, a war, a naval blockade, or sanctions
  on an oil-producing country — that IS the cause. Name the specific location/event: e.g.
  "US strikes on Iran's Kharg Island" or "closure of the Strait of Hormuz". Be specific.
- Do NOT write vague phrases like "geopolitical tensions" or "regional concerns" without naming the event.
- Do NOT cite sports events (F1, football etc.), weather, or unrelated news as oil price drivers.
- NEVER say the cause is unclear if [Geopolitical] or [Middle East] headlines are present.
- Gold moves often reflect investor fear — if a geopolitical event is in the headlines, connect it explicitly.

NO FABRICATION RULES:
- Do NOT invent supply/demand explanations not present in the headlines.
- Do NOT speculate about what investors were thinking unless a headline states it.
- Only reference price implications (e.g. petrol costs) if directly supported by the price data provided.
- NEVER say a price move had "no clear cause" or "no explanation" if there are geopolitical or Middle East
  headlines in the list above — those ARE the cause for commodity price moves. Connect them.

Write the Commodities section. 2 short paragraphs using WEEKDAY headlines only for market moves.
Format: [named news event or supply/demand driver] → [commodity price move] → [what it means for ordinary people]
Connect to real life — e.g. oil rising means petrol costs more, gold rising means investors are nervous.
Weave in specific headlines naturally where they explain a price move — do not list them.
If WEEKEND headlines contain market-relevant news, add one brief sentence noting what to watch on Monday.
 
Available headlines (geopolitical/breaking listed first, then supply/demand):
{headlines}
 
Commodity prices and weekly moves:
{prices_txt}"""
    return call_claude(prompt, max_tokens=400)
 
 
# ── Section: Technical Analysis Narrative ────────────────────
def build_technical_narrative(all_data):
    print("  Writing technical analysis narrative...")
    signals = []
    for inst in instruments:
        ticker = inst["ticker"]
        if ticker not in all_data:
            continue
        try:
            df     = calculate_indicators(all_data[ticker].copy())
            latest = df.iloc[-1]
            prev   = df.iloc[-2]
            close  = format_price(float(df["Close"].iloc[-1]))
            rsi    = round(float(latest["RSI"]), 1)
            bias   = get_bias(latest, prev)
            weekly = get_weekly_change(df)
            w_str  = f"{'+' if weekly and weekly>0 else ''}{weekly}%" if weekly else ""
            signals.append(f"{inst['name']}: Price {close} {w_str} | RSI {rsi} | Bias {bias}")
        except Exception:
            continue
    signals_txt = "\n".join(signals)
    prompt = f"""{SYSTEM_CONTEXT}
 
REMINDER: Base your writing ONLY on the technical readings listed below.
Do not reference any news events, macro data, or context not explicitly provided.
Do NOT output any heading, title or label like "Technical Analysis" — start directly with the first paragraph.
 
Write the Technical Analysis section. 3 short paragraphs:
 
Para 1: Overall market picture — are most markets trending up, down or sideways?
        RSI above 70 = overbought (price likely to pull back).
        RSI below 30 = oversold (price likely to bounce).
        RSI 40-60 = neutral territory.
 
Para 2: The 2-3 most interesting signals this week.
        MACD measures momentum — crossing above its signal line means momentum is turning positive.
        Mention any extreme RSI readings or instruments near key support/resistance.
 
Para 3: What the charts suggest for next week.
        Which instruments look strongest? Weakest?
        ONLY reference price levels that appear in the current readings below (e.g. S1/R1 from pivot points).
        Do NOT invent or estimate price levels not present in the data.

Current readings:
{signals_txt}"""
    return call_claude(prompt, max_tokens=500)
 
 
# ── HTML: Chart Card ──────────────────────────────────────────
def chart_card(ticker, name):
    img_url = encode_chart(ticker)
    if not img_url:
        return ""
    return f"""<div class="chart-card">
        <img src="{img_url}" alt="{name} chart" loading="eager">
        <div class="chart-caption">{name} — Daily Chart</div>
    </div>"""
 
 
# ── HTML: Bias Table Row ──────────────────────────────────────
def bias_row(inst, all_data):
    ticker = inst["ticker"]
    name   = inst["name"]
    if ticker not in all_data:
        return ""
    try:
        df     = calculate_indicators(all_data[ticker].copy())
        latest = df.iloc[-1]
        prev   = df.iloc[-2]
        pivots = calculate_pivot_points(df)
        close  = format_price(float(df["Close"].iloc[-1]))
        rsi    = round(float(latest["RSI"]), 1)
        sma200 = float(latest["SMA_200"])
        trend  = "Above 200 SMA" if float(df["Close"].iloc[-1]) > sma200 else "Below 200 SMA"
        bias   = get_bias(latest, prev)
        weekly = get_weekly_change(df)
        w_str  = f"{'+' if weekly and weekly>0 else ''}{weekly}%" if weekly else "—"
        s1     = format_price(float(pivots["S1"]))
        r1     = format_price(float(pivots["R1"]))
        w_col  = "#2ecc71" if weekly and weekly>0 else "#e74c3c" if weekly and weekly<0 else "#9ca3af"
        return f"""<tr>
            <td><strong>{name}</strong></td>
            <td style="font-family:'IBM Plex Mono',monospace">{close}</td>
            <td style="color:{w_col};font-family:'IBM Plex Mono',monospace">{w_str}</td>
            <td style="font-family:'IBM Plex Mono',monospace">{rsi}</td>
            <td>{trend}</td>
            <td>{bias}</td>
            <td style="font-family:'IBM Plex Mono',monospace;font-size:12px">S1: {s1} / R1: {r1}</td>
        </tr>"""
    except Exception:
        return ""
 
 
# ── HTML: Narrative Paragraphs ────────────────────────────────
def narrative_html(text):
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'^#{1,4}\s+', '', line)
        line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
        line = re.sub(r'__(.+?)__',     r'\1', line)
        line = re.sub(r'\*(.+?)\*',     r'\1', line)
        line = re.sub(r'_(.+?)_',       r'\1', line)
        lines.append(line)
    return "".join(f"<p>{p}</p>" for p in lines if p)
 
 
# ── Build Full HTML Report ────────────────────────────────────
def build_report():
    print("\n📊  Building Weekly G7 Market Report...")
    print("─" * 55)
 
    print("\n[1/6] Fetching market data...")
    all_data = fetch_all_data()
 
    print("\n[2/6] Fetching calendar & macro data...")
    this_week = get_this_week_events()
    macro    = fetch_all_macro(this_week)
    releases = get_this_weeks_releases(macro)
 
    print("\n[3/6] Fetching news headlines...")
    news = fetch_all_news()
 
    print("\n[4/6] Generating AI narratives...")
    exec_summary     = build_executive_summary(macro, releases, news, all_data)
    us_narrative     = build_us_narrative(macro, releases, news, all_data)
    europe_narrative = build_europe_narrative(macro, releases, news, all_data)
    japan_narrative  = build_japan_narrative(macro, releases, news, all_data)
    commodities_narr = build_commodities_narrative(macro, news, all_data)
    technical_narr   = build_technical_narrative(all_data)
 
    print("\n[5/6] Building bias table...")
    bias_rows = "".join(bias_row(inst, all_data) for inst in instruments)
 
    print("\n[6/6] Starting chart server & assembling HTML...")
 
    # Start local server so Chrome can load charts during print
    # (Chrome blocks file:// image paths in its print renderer)
    server = start_chart_server(os.getcwd(), port=CHART_SERVER_PORT)
 
    us_charts = "".join([
        chart_card("ES=F",     "S&P 500"),
        chart_card("NQ=F",     "Nasdaq"),
        chart_card("YM=F",     "Dow Jones"),
        chart_card("DX-Y.NYB", "Dollar Index"),
    ])
    eu_charts = "".join([
        chart_card("^GDAXI",    "DAX"),
        chart_card("^FTSE",     "FTSE 100"),
        chart_card("^STOXX50E", "Euro Stoxx 50"),
        chart_card("6E=F",      "Euro"),
        chart_card("6B=F",      "Sterling"),
    ])
    jp_charts = "".join([
        chart_card("NKD=F", "Nikkei"),
        chart_card("6J=F",  "Japanese Yen"),
    ])
    cm_charts = "".join([
        chart_card("GC=F", "Gold"),
        chart_card("SI=F", "Silver"),
        chart_card("CL=F", "Crude Oil"),
    ])
 
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>G7 Weekly Market Report | {WEEK_LABEL}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Source+Sans+3:wght@300;400;600&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
    --navy:#0d1b2a;--navy-mid:#112236;--navy-light:#1a3050;
    --gold:#c9a84c;--gold-dim:rgba(201,168,76,0.12);
    --text:#e8eaf0;--text-mid:#9ca3af;--text-dim:#5a6473;
    --green:#2ecc71;--red:#e74c3c;--border:rgba(201,168,76,0.18);
}}
body{{background:var(--navy);color:var(--text);font-family:'Source Sans 3',sans-serif;font-weight:300;line-height:1.75}}
 
/* Header */
.report-header{{background:linear-gradient(160deg,#080f18 0%,#0f1e30 50%,#0d1b2a 100%);border-bottom:2px solid var(--gold);padding:70px 40px 55px;text-align:center;position:relative;overflow:hidden}}
.report-header::before{{content:'';position:absolute;inset:0;background:radial-gradient(ellipse at 50% -20%,rgba(201,168,76,0.1) 0%,transparent 65%);pointer-events:none}}
.header-eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:6px;color:var(--gold);text-transform:uppercase;margin-bottom:22px}}
.report-title{{font-family:'Playfair Display',serif;font-size:clamp(36px,6vw,64px);font-weight:900;color:var(--text);letter-spacing:-1px;line-height:1.05;margin-bottom:18px}}
.report-title span{{color:var(--gold)}}
.report-dates{{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--gold);letter-spacing:3px;margin-bottom:24px}}
.report-disclaimer{{font-size:12px;color:var(--text-dim);max-width:560px;margin:0 auto;font-style:italic;line-height:1.6}}
 
/* Layout */
.container{{max-width:1160px;margin:0 auto;padding:0 28px}}
.section{{padding:64px 0;border-bottom:1px solid var(--border)}}
.section-eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:5px;color:var(--gold);text-transform:uppercase;margin-bottom:10px;opacity:.8}}
.section-title{{font-family:'Playfair Display',serif;font-size:clamp(24px,3.5vw,36px);font-weight:700;color:var(--text);margin-bottom:6px;line-height:1.2}}
.section-rule{{width:48px;height:2px;background:var(--gold);margin:18px 0 34px;opacity:.5}}
 
/* Exec box */
.exec-box{{background:linear-gradient(135deg,var(--navy-mid),#16293f);border:1px solid var(--border);border-left:3px solid var(--gold);border-radius:3px;padding:30px 36px;font-size:16px;line-height:1.85;color:var(--text)}}
.exec-box p{{margin-bottom:14px}}
.exec-box p:last-child{{margin-bottom:0}}
 
/* Narrative */
.narrative p{{font-size:15px;line-height:1.85;color:var(--text-mid);margin-bottom:18px}}
.narrative p:last-child{{margin-bottom:0}}
 
/* Charts */
.charts-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:12px 0 0}}
.chart-card{{background:var(--navy-mid);border:1px solid var(--border);border-radius:4px;overflow:hidden}}
.chart-card img{{width:100%;display:block;max-height:280px;object-fit:contain}}
.chart-caption{{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--gold);padding:7px 14px;letter-spacing:1.5px;border-top:1px solid var(--border);text-transform:uppercase}}
.chart-region{{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:4px;color:var(--text-dim);text-transform:uppercase;margin:24px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--border)}}
.chart-group{{margin-bottom:6px}}
 
/* Bias table */
.bias-wrap{{overflow-x:auto;margin-top:8px}}
.bias-table{{width:100%;border-collapse:collapse;font-size:13px}}
.bias-table th{{font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--gold);text-transform:uppercase;letter-spacing:1.5px;padding:12px 14px;border-bottom:1px solid var(--border);text-align:left;background:var(--navy-mid);white-space:nowrap}}
.bias-table td{{padding:11px 14px;border-bottom:1px solid rgba(255,255,255,0.035);color:var(--text-mid);vertical-align:middle}}
.bias-table tr:hover td{{background:rgba(201,168,76,0.03)}}
.bias-table td:first-child{{color:var(--text);font-weight:600}}
 
/* Events */
.events-table{{width:100%;border-collapse:collapse;font-size:14px;margin-top:24px}}
.events-table th{{font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:2px;padding:10px 16px;border-bottom:1px solid var(--border);text-align:left}}
.events-table td{{padding:13px 16px;border-bottom:1px solid rgba(255,255,255,0.04);color:var(--text-mid)}}
.events-table td:first-child{{font-family:'IBM Plex Mono',monospace;color:var(--gold);font-size:12px;white-space:nowrap}}
 
/* Footer */
.report-footer{{background:var(--navy-mid);border-top:1px solid var(--border);padding:44px 40px;text-align:center;font-size:12px;color:var(--text-dim);line-height:2}}
.report-footer strong{{color:var(--gold)}}
 
/* ── Print Styles ───────────────────────────────────────────
   GOLDEN RULES:
   1. ONLY apply page-break-inside:avoid to genuinely small elements
      (single table row, single chart card). Never to sections,
      narratives, grids or any container taller than ~200px.
   2. Crush ALL padding/margin in print — the 64px screen padding
      is the #1 cause of gaps and phantom blank pages.
   3. print-color-adjust:exact is mandatory — without it Chrome
      strips dark backgrounds leaving white voids.
   4. chart-group must NEVER have avoid — even 2-chart groups can
      exceed the page height with padding included.
─────────────────────────────────────────────────────────── */
@media print {{
    @page {{ margin: 10mm 10mm; }}
 
    body {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }}
 
    /* ── Kill all padding/margin that creates phantom gaps ── */
    .section {{
        padding: 12px 0 !important;
        margin: 0 !important;
        border-bottom: 1px solid var(--border);
        page-break-inside: auto;
        break-inside: auto;
    }}
    .section-rule  {{ margin: 8px 0 14px !important; }}
    .chart-region  {{ margin: 10px 0 6px !important; }}
    .chart-group   {{ margin-bottom: 4px !important; }}
    .charts-grid   {{ margin: 4px 0 0 !important; gap: 6px !important; }}
    .narrative p   {{ margin-bottom: 10px !important; }}
    .exec-box      {{ padding: 16px 20px !important; }}
 
    /* ── Headings: keep eyebrow+title+rule together ── */
    .section-eyebrow {{ page-break-after: avoid; break-after: avoid; }}
    .section-title   {{ page-break-after: avoid; break-after: avoid; }}
    .section-rule    {{ page-break-after: avoid; break-after: avoid; }}
 
    /* ── Content containers: always auto (allow breaking) ── */
    .exec-box      {{ page-break-inside: avoid; break-inside: avoid; }}
    .narrative     {{ page-break-inside: auto;  break-inside: auto; }}
    .chart-group   {{ page-break-inside: auto;  break-inside: auto; }}
    .charts-grid   {{ page-break-inside: auto;  break-inside: auto; }}
 
    /* ── Atomic units only: keep these together ── */
    .chart-card         {{ page-break-inside: avoid; break-inside: avoid; }}
    .bias-table tr      {{ page-break-inside: avoid; break-inside: avoid; }}
    .events-table tr    {{ page-break-inside: avoid; break-inside: avoid; }}
 
    /* ── Tables: repeat header, allow body to break ── */
    .bias-wrap      {{ page-break-inside: auto; break-inside: auto; overflow: visible; }}
    .bias-table     {{ page-break-inside: auto; }}
    .bias-table thead {{ display: table-header-group; }}
    .events-table   {{ page-break-inside: auto; }}
 
    /* ── Prevent report header taking whole first page ── */
    .report-header {{ padding: 20px 20px 16px !important; }}
    .report-title  {{ font-size: 36px !important; margin-bottom: 8px !important; }}
    .report-dates  {{ margin-bottom: 10px !important; }}
}}
 
@media(max-width:768px){{
    .report-header{{padding:44px 20px}}
    .section{{padding:44px 0}}
    .exec-box{{padding:22px 20px;font-size:15px}}
    .charts-grid{{grid-template-columns:1fr}}
}}
</style>
</head>
<body>
 
<div class="report-header">
    <div class="header-eyebrow">G7 Markets · Weekly Intelligence Report</div>
    <h1 class="report-title">Weekly <span>Market</span> Report</h1>
    <div class="report-dates">{WEEK_LABEL}</div>
    <p class="report-disclaimer">
        For educational and informational purposes only. Not financial advice.<br>
        Data: FRED API · CNBC · BBC News · Yahoo Finance · Generated {TODAY_STR}
    </p>
</div>
 
<div class="container">
 
<div class="section">
    <div class="section-eyebrow">Overview</div>
    <h2 class="section-title">Executive Summary</h2>
    <div class="section-rule"></div>
    <div class="exec-box">{narrative_html(exec_summary)}</div>
</div>
 
<div class="section">
    <div class="section-eyebrow">United States</div>
    <h2 class="section-title">🇺🇸 US Economy & Markets</h2>
    <div class="section-rule"></div>
    <div class="narrative">{narrative_html(us_narrative)}</div>
</div>
 
<div class="section">
    <div class="section-eyebrow">Europe & United Kingdom</div>
    <h2 class="section-title">🇪🇺 Europe & UK Economy & Markets</h2>
    <div class="section-rule"></div>
    <div class="narrative">{narrative_html(europe_narrative)}</div>
</div>
 
<div class="section">
    <div class="section-eyebrow">Japan</div>
    <h2 class="section-title">🇯🇵 Japan Economy & Markets</h2>
    <div class="section-rule"></div>
    <div class="narrative">{narrative_html(japan_narrative)}</div>
</div>
 
<div class="section">
    <div class="section-eyebrow">Commodities</div>
    <h2 class="section-title">⚡ Commodities</h2>
    <div class="section-rule"></div>
    <div class="narrative">{narrative_html(commodities_narr)}</div>
</div>
 
<div class="section">
    <div class="section-eyebrow">Technical Analysis</div>
    <h2 class="section-title">📈 Technical Analysis</h2>
    <div class="section-rule"></div>
    <div class="narrative">{narrative_html(technical_narr)}</div>
 
    <div class="chart-group">
        <div class="chart-region">United States</div>
        <div class="charts-grid">{us_charts}</div>
    </div>
 
    <div class="chart-group">
        <div class="chart-region">Europe & United Kingdom</div>
        <div class="charts-grid">{eu_charts}</div>
    </div>
 
    <div class="chart-group">
        <div class="chart-region">Japan</div>
        <div class="charts-grid">{jp_charts}</div>
    </div>
 
    <div class="chart-group">
        <div class="chart-region">Commodities</div>
        <div class="charts-grid">{cm_charts}</div>
    </div>
</div>
 
<div class="section">
    <div class="section-eyebrow">Market Summary</div>
    <h2 class="section-title">📊 Trader's Bias Summary</h2>
    <div class="section-rule"></div>
    <div class="bias-wrap">
        <table class="bias-table">
            <thead><tr>
                <th>Instrument</th><th>Price</th><th>Week %</th>
                <th>RSI</th><th>Trend</th><th>Bias</th><th>Key Levels (S1 / R1)</th>
            </tr></thead>
            <tbody>{bias_rows}</tbody>
        </table>
    </div>
</div>
 

</div>
 
<div class="report-footer">
    <strong>G7 Weekly Market Report</strong> · {WEEK_LABEL}<br>
    Data: FRED API · CNBC · BBC News · Yahoo Finance<br>
    Auto-generated for educational purposes only. Not financial advice.<br>
    Built with Python · Open source on GitHub
</div>
 
</body>
</html>"""
 
    filename = f"G7_Market_Report_{today.strftime('%Y_%m_%d')}.html"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
 
    print(f"\n✅  Report saved: {filepath}")
    print(f"\n{'─'*55}")
    print(f"  ⚠️  IMPORTANT: Open the report via localhost, not file://")
    print(f"  👉  http://localhost:{CHART_SERVER_PORT}/{OUTPUT_DIR}/{filename}")
    print(f"{'─'*55}")
    print(f"  Then: Cmd+P → Save as PDF → tick Background Graphics → Save")
    print(f"  Press Ctrl+C in this terminal when done.")
    print(f"{'─'*55}\n")
 
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Server stopped. Goodbye.")
        if server:
            server.shutdown()
 
 
# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    build_report()