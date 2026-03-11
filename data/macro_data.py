# ============================================================
# macro_data.py
# Pulls macroeconomic data from the FRED API
# Covers US, Europe and Japan fundamental indicators
# Used by report.py to populate the macro sections
# ============================================================

# ── Imports ─────────────────────────────────────────────────
import os
from fredapi import Fred
import pandas as pd
import ssl
import certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

# ── API Key ──────────────────────────────────────────────────
# Replace with your FRED API key from:
# https://fred.stlouisfed.org/docs/api/api_key.html
from dotenv import load_dotenv
load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")
fred = Fred(api_key=FRED_API_KEY)


# ── Helper: Get Latest Value ─────────────────────────────────
# Fetches a series and returns the most recent non-null value
# Returns None if the series fails to load
def get_latest(series_id, label):
    try:
        series = fred.get_series(series_id)
        series = series.dropna()
        value  = round(float(series.iloc[-1]), 2)
        date   = series.index[-1].strftime("%b %Y")
        print(f"  ✓ {label}: {value} ({date})")
        return value
    except Exception as e:
        print(f"  ✗ {label}: Failed — {e}")
        return None


# ── Helper: Get YoY % Change ─────────────────────────────────
# Fetches a raw index series and calculates the
# year-over-year percentage change from the last two readings
# 12 months apart. Used for CPI and GDP index series.
def get_yoy_change(series_id, label):
    try:
        series = fred.get_series(series_id).dropna()
        latest = series.iloc[-1]
        prev   = series.iloc[-13]   # 12 months ago
        change = round(((latest - prev) / prev) * 100, 2)
        date   = series.index[-1].strftime("%b %Y")
        print(f"  ✓ {label}: {change}% ({date})")
        return change
    except Exception as e:
        print(f"  ✗ {label}: Failed — {e}")
        return None


# ── Helper: Get Monthly Change ───────────────────────────────
# Returns the difference between the last two readings
# Used for Nonfarm Payrolls (monthly jobs added)
def get_monthly_change(series_id, label, divisor=1):
    try:
        series  = fred.get_series(series_id).dropna()
        latest  = series.iloc[-1]
        prev    = series.iloc[-2]
        change  = round((latest - prev) / divisor, 1)
        date    = series.index[-1].strftime("%b %Y")
        print(f"  ✓ {label}: {change} ({date})")
        return change
    except Exception as e:
        print(f"  ✗ {label}: Failed — {e}")
        return None


# ── US Macro Data ─────────────────────────────────────────────
# Pulls key Federal Reserve and US economic indicators
def fetch_us_macro():
    print("\n🇺🇸  Fetching US Macro Data...")
    return {
        # Monetary Policy
        "fed_funds_rate":    get_latest("FEDFUNDS",          "Fed Funds Rate"),

        # Inflation — YoY % change calculated from index
        "cpi_yoy":           get_yoy_change("CPIAUCSL",      "CPI YoY %"),
        "core_pce":          get_yoy_change("PCEPILFE",      "Core PCE YoY %"),

        # Labour Market
        # UNRATE = unemployment rate (already a %)
        # PAYEMS = total nonfarm payrolls in thousands — we take monthly change
        "unemployment":      get_latest("UNRATE",            "Unemployment Rate"),
        "nonfarm_payrolls":  get_monthly_change("PAYEMS",    "NFP Monthly Change (000s)", divisor=1),

        # Growth — already a % QoQ figure
        "gdp_growth":        get_latest("A191RL1Q225SBEA",   "GDP Growth QoQ %"),

        # Treasury Yields — already in %
        "yield_10yr":        get_latest("DGS10",             "10yr Treasury Yield"),
        "yield_2yr":         get_latest("DGS2",              "2yr Treasury Yield"),

        # Manufacturing Activity — ISM not available on FRED
        # Using Federal Reserve alternatives instead
        "industrial_production": get_latest("INDPRO",        "US Industrial Production Index"),
        "capacity_utilization":  get_latest("TCU",           "US Capacity Utilization %"),
    }


# ── Europe Macro Data ────────────────────────────────────────
# Pulls Eurozone and UK economic indicators
def fetch_europe_macro():
    print("\n🇪🇺  Fetching Europe Macro Data...")
    return {
        # ── ECB / Eurozone ───────────────────────────────
        # Monetary Policy
        "ecb_rate":           get_latest("ECBDFR",                   "ECB Deposit Rate"),

        # Inflation — YoY % change
        "ez_cpi":             get_yoy_change("CP0000EZ19M086NEST",   "Eurozone CPI YoY %"),

        # Growth — YoY % change
        "ez_gdp_growth":      get_yoy_change("CLVMNACSCAB1GQEA19",  "Eurozone GDP YoY %"),

        # Labour Market
        "ez_unemployment":    get_latest("LRHUTTTTEZM156S",          "Eurozone Unemployment"),

        # ── Bank of England / UK ─────────────────────────
        # Monetary Policy — BoE Official Bank Rate
        "boe_rate":           get_latest("IUDSOIA",                  "BoE Bank Rate"),

        # Inflation — UK CPI YoY %
        "uk_cpi":             get_yoy_change("GBRCPIALLMINMEI",      "UK CPI YoY %"),

        # Growth — UK Real GDP YoY %
        "uk_gdp_growth":      get_yoy_change("NGDPRSAXDCGBQ",       "UK GDP YoY %"),

        # Labour Market
        "uk_unemployment":    get_latest("LRHUTTTTGBM156S",          "UK Unemployment"),

        # Public Finances
        "uk_debt_gdp":        get_latest("DEBTTLGBA188A",            "UK Debt to GDP %"),
    }


# ── Japan Macro Data ─────────────────────────────────────────
# Pulls Bank of Japan and Japanese economic indicators
def fetch_japan_macro():
    print("\n🇯🇵  Fetching Japan Macro Data...")
    return {
        # Monetary Policy — already in %
        "boj_rate":           get_latest("IRSTCI01JPM156N",          "BoJ Policy Rate"),

        # Inflation — Japan CPI YoY % direct series
        "japan_cpi":          get_latest("FPCPITOTLZGJPN",           "Japan CPI YoY %"),

        # Growth — YoY % change calculated from index
        "japan_gdp_growth":   get_yoy_change("JPNRGDPEXP",           "Japan GDP YoY %"),

        # Trade Balance — in billions USD
        "japan_trade":        get_monthly_change("XTIMVA01JPM667S",  "Japan Trade Balance (monthly)", divisor=1e9),

        # Labour Market — already in %
        "japan_unemployment": get_latest("LRUNTTTTJPM156S",          "Japan Unemployment"),
    }


# ── Yield Curve Spread ───────────────────────────────────────
# Calculates the US 10yr minus 2yr spread
# Negative = inverted yield curve = recession warning signal
def calculate_yield_spread(us_data):
    print("\n📈  Calculating Yield Curve Spread...")
    try:
        spread = round(us_data["yield_10yr"] - us_data["yield_2yr"], 3)
        status = "Normal" if spread > 0 else "INVERTED ⚠"
        print(f"  ✓ 10yr-2yr Spread: {spread}% — {status}")
        return spread
    except Exception as e:
        print(f"  ✗ Yield spread calculation failed — {e}")
        return None


# ── Fetch All Macro Data ─────────────────────────────────────
# Master function called by report.py
# Returns a single dictionary with all regional macro data
def fetch_all_macro():
    us_data = fetch_us_macro()
    eu_data = fetch_europe_macro()
    jp_data = fetch_japan_macro()

    # Add yield spread to US data
    us_data["yield_spread"] = calculate_yield_spread(us_data)

    return {
        "us": us_data,
        "eu": eu_data,
        "jp": jp_data,
    }


# ── Main: Print All Macro Data ───────────────────────────────
# Runs when macro_data.py is executed directly
# Useful for verifying all series load correctly
if __name__ == "__main__":
    macro = fetch_all_macro()

    print("\n" + "=" * 55)
    print(" MACRO DATA SUMMARY")
    print("=" * 55)

    print("\n🇺🇸  US:")
    for k, v in macro["us"].items():
        print(f"  {k:25} {v}")

    print("\n🇪🇺  Europe:")
    for k, v in macro["eu"].items():
        print(f"  {k:25} {v}")

    print("\n🇯🇵  Japan:")
    for k, v in macro["jp"].items():
        print(f"  {k:25} {v}")