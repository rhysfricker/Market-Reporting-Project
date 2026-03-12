# ============================================================
# macro_data.py  —  G7 Weekly Market Report
#
# Fetches macroeconomic data for the report's macro sections.
# Returns DataPoint dicts:  { value, date, released_this_week }
#
# FRED SERIES STATUS (verified March 2026):
#   ✅ DFEDTARU          — Fed Funds upper target  (live, Mar 2026)
#   ✅ CPIAUCNS           — US CPI index NSA        (live, Feb 2026)
#   ✅ PCEPILFE           — Core PCE index          (live, Feb 2026)
#   ✅ UNRATE             — US Unemployment         (live, Feb 2026)
#   ✅ PAYEMS             — US NFP                  (live, Feb 2026)
#   ✅ A191RL1Q225SBEA    — US GDP QoQ              (live, Q4 2025)
#   ✅ INDPRO             — Industrial Production   (live, Jan 2026)
#   ✅ TCU                — Capacity Utilization    (live, Jan 2026)
#   ✅ DGS10 / DGS2       — Treasury yields         (live, daily)
#   ✅ ECBDFR             — ECB Deposit Rate        (live, Mar 2026)
#   ✅ IUDSOIA            — BoE Bank Rate           (live, Mar 2026)
#   ✅ CP0000EZ19M086NEST — EA HICP index (26-char) (live, Dec 2025)
#                          → must compute YoY manually (units=pc1 rejected)
#   ✅ CLVMNACSCAB1GQEA19 — EZ GDP index            (live, Q3 2025)
#   ⛔ LRHUTTTTEZM156S   — EZ Unemployment OECD    DEAD Jan 2023
#   ⛔ EURUNEMPEA20       — EZ Unemployment Eurostat DOES NOT EXIST on FRED
#      → use Eurostat JSON API (no key needed), fallback to hardcoded
#   ✅ NGDPRSAXDCGBQ      — UK GDP index            (live, Q3 2025)
#   ✅ LRHUTTTTGBM156S    — UK Unemployment         (live, Oct 2025)
#   ✅ DEBTTLGBA188A      — UK Debt/GDP             (live, 2024)
#   ⛔ GBRCPIALLMINMEI   — UK CPI OECD index       STALE Mar 2025
#      → fetch directly from ONS API (no key required), series D7G7
#   ✅ IRSTCI01JPM156N    — BoJ Policy Rate         (live, Jan 2026)
#   ⛔ JPNCPIALLMINMEI   — Japan CPI OECD index    DEAD Jun 2021
#      → fetch from Japan e-Stat API (no key required), fallback to hardcoded
#   ✅ JPNRGDPEXP         — Japan GDP               (live, Q3 2025)
#   ✅ XTIMVA01JPM667S    — Japan Trade Balance     (live, Dec 2025)
#   ✅ LRUNTTTTJPM156S    — Japan Unemployment      (live, Dec 2025)
# ============================================================
 
import os
import requests
from datetime import datetime, timedelta
from fredapi import Fred
import ssl, certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
 
from dotenv import load_dotenv
load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")
fred = Fred(api_key=FRED_API_KEY)
 
from calendar_data import get_this_week_events
 
TODAY = datetime.today()
 
 
# ── ForexFactory → FRED key mapping ──────────────────────────
FF_TO_FRED = {
    "fed_funds_rate":        {"currency": "USD", "keywords": ["fed funds", "fomc rate", "interest rate", "federal reserve rate", "ffr"]},
    "cpi_yoy":               {"currency": "USD", "keywords": ["cpi y/y", "cpi m/m", "consumer price index"], "exclude": ["core"]},
    "core_pce":              {"currency": "USD", "keywords": ["pce", "core pce", "personal consumption expenditure"]},
    "unemployment":          {"currency": "USD", "keywords": ["unemployment rate", "jobless rate"]},
    "nonfarm_payrolls":      {"currency": "USD", "keywords": ["nonfarm", "non-farm", "payroll"]},
    "gdp_growth":            {"currency": "USD", "keywords": ["gdp", "gross domestic product"]},
    "industrial_production": {"currency": "USD", "keywords": ["industrial production"]},
    "capacity_utilization":  {"currency": "USD", "keywords": ["capacity utilization"]},
    "ecb_rate":              {"currency": "EUR", "keywords": ["ecb", "deposit facility", "interest rate", "monetary policy", "main refinancing"]},
    "ez_cpi":                {"currency": "EUR", "keywords": ["cpi", "consumer price", "hicp", "inflation"], "exclude": ["core"]},
    "ez_gdp_growth":         {"currency": "EUR", "keywords": ["gdp", "gross domestic product"]},
    "ez_unemployment":       {"currency": "EUR", "keywords": ["unemployment"]},
    "boe_rate":              {"currency": "GBP", "keywords": ["boe", "bank rate", "mpc", "interest rate", "monetary policy"]},
    "uk_cpi":                {"currency": "GBP", "keywords": ["cpi", "consumer price", "inflation"], "exclude": ["core"]},
    "uk_gdp_growth":         {"currency": "GBP", "keywords": ["gdp", "gross domestic product"]},
    "uk_unemployment":       {"currency": "GBP", "keywords": ["unemployment", "claimant", "employment change"]},
    "boj_rate":              {"currency": "JPY", "keywords": ["boj", "policy rate", "interest rate", "monetary policy", "bank of japan"]},
    "japan_cpi":             {"currency": "JPY", "keywords": ["cpi", "consumer price", "inflation"], "exclude": ["core"]},
    "japan_gdp_growth":      {"currency": "JPY", "keywords": ["gdp", "gross domestic product"]},
    "japan_trade":           {"currency": "JPY", "keywords": ["trade balance", "trade deficit", "trade surplus"]},
    "japan_unemployment":    {"currency": "JPY", "keywords": ["unemployment"]},
}
 
 
# ── Released-this-week set ─────────────────────────────────────
def _build_released_set(ff_events):
    released = set()
    for event in ff_events:
        currency = event.get("currency", "").upper()
        title    = event.get("event", "").lower()
        for fred_key, cfg in FF_TO_FRED.items():
            if currency != cfg["currency"]:
                continue
            if any(ex.lower() in title for ex in cfg.get("exclude", [])):
                continue
            if any(kw.lower() in title for kw in cfg["keywords"]):
                if fred_key not in released:
                    released.add(fred_key)
                    print(f"  ✅ FF verified release: {fred_key} ← '{event['event']}' ({event['date']})")
    return released
 
 
# ── DataPoint helpers ─────────────────────────────────────────
def _dp(value, date, label, released):
    date_str = date.strftime("%b %Y") if hasattr(date, "strftime") else str(date)
    flag = "🆕" if released else "  "
    print(f"  {flag} {label}: {value} ({date_str})")
    return {"value": value, "date": date_str, "released_this_week": released}
 
def _fail(label):
    print(f"  ✗ {label}: Failed — no data available")
    return {"value": None, "date": None, "released_this_week": False}
 
 
# ── FRED: latest value ────────────────────────────────────────
def get_latest(series_id, label, released=False):
    try:
        s = fred.get_series(series_id).dropna()
        return _dp(round(float(s.iloc[-1]), 2), s.index[-1], label, released)
    except Exception as e:
        print(f"  ✗ {label}: Failed — {e}")
        return _fail(label)
 
 
# ── FRED: YoY via units=pc1 ───────────────────────────────────
def get_yoy_change(series_id, label, released=False):
    try:
        s = fred.get_series(series_id, units="pc1").dropna()
        return _dp(round(float(s.iloc[-1]), 2), s.index[-1], label, released)
    except Exception as e:
        print(f"  ✗ {label}: Failed — {e}")
        return _fail(label)
 
 
# ── FRED: Manual YoY from raw index ──────────────────────────
# Use when series ID > 25 chars (units=pc1 fails on long IDs)
def get_yoy_manual(series_id, label, released=False):
    try:
        s = fred.get_series(series_id).dropna()
        latest_val  = s.iloc[-1]
        latest_date = s.index[-1]
        target = latest_date - timedelta(days=365)
        candidates = s.index[
            (s.index >= target - timedelta(days=20)) &
            (s.index <= target + timedelta(days=50))
        ]
        if len(candidates) == 0:
            raise ValueError("No prior-year data point found")
        prior_val = s.loc[candidates[0]]
        yoy = round((float(latest_val) / float(prior_val) - 1) * 100, 2)
        return _dp(yoy, latest_date, label, released)
    except Exception as e:
        print(f"  ✗ {label}: Failed — {e}")
        return _fail(label)
 
 
# ── FRED: Monthly change ──────────────────────────────────────
def get_monthly_change(series_id, label, divisor=1, released=False):
    try:
        s      = fred.get_series(series_id).dropna()
        change = round((float(s.iloc[-1]) - float(s.iloc[-2])) / divisor, 1)
        return _dp(change, s.index[-1], label, released)
    except Exception as e:
        print(f"  ✗ {label}: Failed — {e}")
        return _fail(label)
 
 
# ── UK CPI: ONS website JSON API (series D7G7 = CPI all items YoY %) ─
# FRED GBRCPIALLMINMEI lags ~9 months behind ONS — DO NOT USE for YoY.
# The ONS website exposes JSON by appending /data to the timeseries page URL.
# Confirmed working URL:
#   https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data
# The old api.ons.gov.uk v0 endpoint is retired and returns 404.
def get_uk_cpi(released=False):
    label = "UK CPI YoY %"
    # Two URLs to try: primary is the www.ons.gov.uk /data endpoint,
    # fallback is the api.beta.ons.gov.uk search endpoint.
    urls = [
        "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data",
        "https://api.beta.ons.gov.uk/v1/datasets/mm23/timeseries/d7g7/data",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=10, headers={"Accept": "application/json"})
            r.raise_for_status()
            data = r.json()
            months = data.get("months", [])
            if not months:
                continue
            latest = months[-1]
            val = round(float(latest["value"]), 2)
            raw_date = latest.get("label", "")
            # ONS label format: "2026 JAN"
            dt = TODAY
            for fmt in ("%Y %b", "%b %Y", "%Y-%m"):
                try:
                    dt = datetime.strptime(raw_date, fmt)
                    break
                except Exception:
                    pass
            return _dp(val, dt, label, released)
        except Exception as e:
            print(f"  ⚠ ONS URL failed ({url[-50:]}: {e})")
            continue
 
    # Fallback: hardcoded from ONS bulletin released 18 Feb 2026
    # UK CPI Jan 2026 = 3.0% (ONS Consumer price inflation, UK: January 2026)
    print(f"  ⚠ All ONS URLs failed — using hardcoded fallback (Jan 2026 = 3.0%)")
    return _dp(3.0, datetime(2026, 1, 1), label, released)
 
 
# ── Japan CPI: e-Stat API ─────────────────────────────────────
# statsDataId 0003427113 = "CPI All Japan, 2020=100, All items (monthly)"
# FRED JPNCPIALLMINMEI ended Jun 2021 — DO NOT USE.
def get_japan_cpi(released=False):
    label = "Japan CPI YoY %"
    try:
        url = (
            "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
            "?appId=guest"
            "&statsDataId=0003427113"
            "&cdCat01=0000"
            "&limit=25"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
 
        values = (
            data.get("GET_STATS_DATA", {})
                .get("STATISTICAL_DATA", {})
                .get("DATA_INF", {})
                .get("VALUE", [])
        )
        if not values:
            raise ValueError("Empty e-Stat response")
 
        obs = {}
        for v in values:
            t   = v.get("@time", "")
            val = v.get("$", "")
            if t and val:
                try:
                    obs[t] = float(val)
                except ValueError:
                    pass
 
        if not obs:
            raise ValueError("No usable observations in e-Stat response")
 
        sorted_keys = sorted(obs.keys())
        latest_key  = sorted_keys[-1]
        latest_val  = obs[latest_key]
 
        year  = int(latest_key[:4])
        month = latest_key[4:]
        prior_key = f"{year - 1}{month}"
 
        if prior_key not in obs:
            raise ValueError(f"Prior-year key {prior_key} not in data")
 
        yoy = round((latest_val / obs[prior_key] - 1) * 100, 2)
        try:
            dt = datetime.strptime(latest_key, "%Y%m")
        except Exception:
            dt = TODAY
        return _dp(yoy, dt, label, released)
 
    except Exception as e:
        print(f"  ⚠ e-Stat API failed ({e}), using hardcoded fallback")
        # Japan Stats Bureau released Jan 2026 CPI on 21 Feb 2026: 1.5% YoY
        return _dp(1.5, datetime(2026, 1, 1), label, released)
 
 
# ── EZ Unemployment: Eurostat JSON API ───────────────────────
# FRED has no live series. Eurostat provides a free JSON-stat REST API.
# Response structure (JSON-stat):
#   data["id"]        = ["freq","unit","age","sex","geo","time"]  (dimension order)
#   data["size"]      = [1, 1, 1, 1, 1, 3]                       (positions per dim)
#   data["value"]     = {"0": 6.3, "1": 6.2, "2": 6.1}          (flat index → value)
#   data["dimension"]["time"]["category"]["index"] = {"2025-11":0,"2025-12":1,"2026-01":2}
# Flat index = sum of (dim_position × stride), with stride = product of later dim sizes.
# Since all non-time dims are filtered to 1, flat_index == time_position.
def get_ez_unemployment(released=False):
    label = "Eurozone Unemployment %"
    try:
        url = (
            "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m"
            "?geo=EA20&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT&lastTimePeriod=3&format=JSON&lang=en"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
 
        # JSON-stat: values keyed by flat string integer index
        values = data.get("value", {})
        if not values:
            raise ValueError(f"No value field in response. Keys: {list(data.keys())}")
 
        # The "id" array gives the dimension order; time is always the last one
        dim_ids   = data.get("id", [])
        time_key  = dim_ids[-1] if dim_ids else "time"   # e.g. "time" or "TIME_PERIOD"
        dim_sizes = data.get("size", [])
 
        # Get time dimension category index: {"2025-11": 0, "2025-12": 1, "2026-01": 2}
        time_cat_index = (
            data.get("dimension", {})
                .get(time_key, {})
                .get("category", {})
                .get("index", {})
        )
 
        if not time_cat_index:
            raise ValueError(
                f"No time category index found. dim_ids={dim_ids}, "
                f"dimension keys={list(data.get('dimension', {}).keys())}"
            )
 
        # Find the time period with the highest position index → most recent
        latest_period = max(time_cat_index, key=lambda k: time_cat_index[k])
        latest_pos    = time_cat_index[latest_period]  # position within time dimension
 
        # Compute flat index: stride for time dimension = product of sizes of later dims
        # Since time is last, stride = 1. flat_index = (other dims all pos 0) * their strides + latest_pos
        # With all non-time dims filtered to 1 value, flat_index == latest_pos.
        time_stride = 1
        for sz in dim_sizes[len(dim_ids):]:   # dims after time (none) — just future-proofing
            time_stride *= sz
        flat_index = latest_pos * time_stride
 
        val = values.get(str(flat_index)) or values.get(flat_index)
        if val is None:
            # Try iterating all value keys to find the last one as a fallback
            all_vals = {int(k): v for k, v in values.items() if v is not None}
            if all_vals:
                val = all_vals[max(all_vals.keys())]
            else:
                raise ValueError(f"No value at flat index {flat_index}. Values: {values}")
 
        try:
            dt = datetime.strptime(latest_period, "%Y-%m")
        except Exception:
            dt = TODAY
        return _dp(round(float(val), 2), dt, label, released)
 
    except Exception as e:
        print(f"  ⚠ Eurostat API failed ({e})")
        # Hardcoded: Eurostat press release 4 Mar 2026 — EA21 Jan 2026 = 6.1%
        return _dp(6.1, datetime(2026, 1, 1), label, released)
 
 
# ── US Macro ──────────────────────────────────────────────────
def fetch_us_macro(released):
    print("\n🇺🇸  Fetching US Macro Data...")
    us = {
        "fed_funds_rate":        get_latest("DFEDTARU",        "Fed Funds Rate",            released=("fed_funds_rate"        in released)),
        "yield_10yr":            get_latest("DGS10",           "10yr Treasury Yield",       released=False),
        "yield_2yr":             get_latest("DGS2",            "2yr Treasury Yield",        released=False),
        "cpi_yoy":               get_yoy_change("CPIAUCNS",    "CPI YoY %",                 released=("cpi_yoy"               in released)),
        "core_pce":              get_yoy_change("PCEPILFE",    "Core PCE YoY %",            released=("core_pce"              in released)),
        "unemployment":          get_latest("UNRATE",          "Unemployment Rate",         released=("unemployment"          in released)),
        "nonfarm_payrolls":      get_monthly_change("PAYEMS",  "NFP Monthly Change (000s)", released=("nonfarm_payrolls"      in released)),
        "gdp_growth":            get_latest("A191RL1Q225SBEA", "GDP Growth QoQ %",          released=("gdp_growth"            in released)),
        "industrial_production": get_latest("INDPRO",          "Industrial Production",     released=("industrial_production" in released)),
        "capacity_utilization":  get_latest("TCU",             "Capacity Utilization %",    released=("capacity_utilization"  in released)),
    }
    try:
        spread = round(us["yield_10yr"]["value"] - us["yield_2yr"]["value"], 3)
        status = "Normal" if spread > 0 else "INVERTED ⚠"
        print(f"     Yield Spread: {spread}% — {status}")
    except Exception:
        spread = None
    us["yield_spread"] = {"value": spread, "date": TODAY.strftime("%b %Y"), "released_this_week": False}
    return us
 
 
# ── Europe Macro ──────────────────────────────────────────────
def fetch_europe_macro(released):
    print("\n🇪🇺  Fetching Europe Macro Data...")
    return {
        "ecb_rate":        get_latest("ECBDFR",                  "ECB Deposit Rate",        released=("ecb_rate"        in released)),
        "boe_rate":        get_latest("IUDSOIA",                 "BoE Bank Rate",            released=("boe_rate"        in released)),
        "ez_cpi":          get_yoy_manual("CP0000EZ19M086NEST",  "Eurozone CPI YoY %",      released=("ez_cpi"          in released)),
        "ez_gdp_growth":   get_yoy_change("CLVMNACSCAB1GQEA19", "Eurozone GDP YoY %",       released=("ez_gdp_growth"   in released)),
        "ez_unemployment": get_ez_unemployment(                   released=("ez_unemployment" in released)),
        "uk_cpi":          get_uk_cpi(                            released=("uk_cpi"          in released)),
        "uk_gdp_growth":   get_yoy_change("NGDPRSAXDCGBQ",      "UK GDP YoY %",             released=("uk_gdp_growth"   in released)),
        "uk_unemployment": get_latest("LRHUTTTTGBM156S",         "UK Unemployment",          released=("uk_unemployment" in released)),
        "uk_debt_gdp":     get_latest("DEBTTLGBA188A",           "UK Debt to GDP %",         released=False),
    }
 
 
# ── Japan Macro ───────────────────────────────────────────────
def fetch_japan_macro(released):
    print("\n🇯🇵  Fetching Japan Macro Data...")
    return {
        "boj_rate":           get_latest("IRSTCI01JPM156N",          "BoJ Policy Rate",      released=("boj_rate"           in released)),
        "japan_cpi":          get_japan_cpi(                          released=("japan_cpi"          in released)),
        "japan_gdp_growth":   get_yoy_change("JPNRGDPEXP",           "Japan GDP YoY %",      released=("japan_gdp_growth"   in released)),
        "japan_trade":        get_monthly_change("XTIMVA01JPM667S",  "Japan Trade Balance",  released=("japan_trade"        in released), divisor=1e9),
        "japan_unemployment": get_latest("LRUNTTTTJPM156S",          "Japan Unemployment",   released=("japan_unemployment" in released)),
    }
 
 
# ── Master fetch ──────────────────────────────────────────────
def fetch_all_macro(ff_this_week=None):
    if ff_this_week is None:
        ff_this_week = get_this_week_events()
 
    print("\n📋  Verifying this week's releases against ForexFactory...")
    released = _build_released_set(ff_this_week)
    if not released:
        print("     No matching FF events found — no FRED series flagged.")
 
    return {
        "us": fetch_us_macro(released),
        "eu": fetch_europe_macro(released),
        "jp": fetch_japan_macro(released),
    }
 
 
# ── This week's releases for Claude prompts ───────────────────
def get_this_weeks_releases(macro):
    LABELS = {
        "fed_funds_rate": "Fed Funds Rate", "cpi_yoy": "US CPI YoY",
        "core_pce": "US Core PCE YoY", "unemployment": "US Unemployment Rate",
        "nonfarm_payrolls": "US Nonfarm Payrolls", "gdp_growth": "US GDP Growth QoQ",
        "yield_10yr": "US 10yr Treasury Yield", "yield_2yr": "US 2yr Treasury Yield",
        "industrial_production": "US Industrial Production",
        "capacity_utilization": "US Capacity Utilization",
        "yield_spread": "US Yield Spread (10yr-2yr)",
        "ecb_rate": "ECB Deposit Rate", "ez_cpi": "Eurozone CPI YoY",
        "ez_gdp_growth": "Eurozone GDP YoY", "ez_unemployment": "Eurozone Unemployment",
        "boe_rate": "BoE Bank Rate", "uk_cpi": "UK CPI YoY",
        "uk_gdp_growth": "UK GDP YoY", "uk_unemployment": "UK Unemployment",
        "uk_debt_gdp": "UK Debt to GDP", "boj_rate": "BoJ Policy Rate",
        "japan_cpi": "Japan CPI YoY", "japan_gdp_growth": "Japan GDP YoY",
        "japan_trade": "Japan Trade Balance", "japan_unemployment": "Japan Unemployment",
    }
    UNITS = {
        "fed_funds_rate": "%", "cpi_yoy": "%", "core_pce": "%",
        "unemployment": "%", "nonfarm_payrolls": "k", "gdp_growth": "%",
        "yield_10yr": "%", "yield_2yr": "%", "industrial_production": "",
        "capacity_utilization": "%", "yield_spread": "%", "ecb_rate": "%",
        "ez_cpi": "%", "ez_gdp_growth": "%", "ez_unemployment": "%",
        "boe_rate": "%", "uk_cpi": "%", "uk_gdp_growth": "%",
        "uk_unemployment": "%", "uk_debt_gdp": "%", "boj_rate": "%",
        "japan_cpi": "%", "japan_gdp_growth": "%", "japan_trade": "bn",
        "japan_unemployment": "%",
    }
 
    def _fmt(key, dp):
        if not dp or dp.get("value") is None:
            return None
        v    = dp["value"]
        sign = "+" if isinstance(v, (float, int)) and v > 0 else ""
        return f"{LABELS.get(key, key)}: {sign}{v}{UNITS.get(key, '')} ({dp.get('date', '')})"
 
    us_r, eu_r, jp_r = [], [], []
    for key, dp in macro["us"].items():
        if dp and dp.get("released_this_week"):
            l = _fmt(key, dp)
            if l: us_r.append(l)
    for key, dp in macro["eu"].items():
        if dp and dp.get("released_this_week"):
            l = _fmt(key, dp)
            if l: eu_r.append(l)
    for key, dp in macro["jp"].items():
        if dp and dp.get("released_this_week"):
            l = _fmt(key, dp)
            if l: jp_r.append(l)
 
    return {"us": us_r, "eu": eu_r, "jp": jp_r, "any": bool(us_r or eu_r or jp_r)}
 
 
# ── Convenience extractor ─────────────────────────────────────
def val(datapoint):
    return datapoint.get("value") if datapoint else None
 
 
# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
 
    macro = fetch_all_macro()
 
    print("\n" + "=" * 55)
    print(" MACRO DATA SUMMARY")
    print("=" * 55)
    for region, label in [("us", "🇺🇸  US"), ("eu", "🇪🇺  Europe"), ("jp", "🇯🇵  Japan")]:
        print(f"\n{label}:")
        for k, dp in macro[region].items():
            if isinstance(dp, dict):
                flag = "🆕" if dp.get("released_this_week") else "  "
                print(f"  {flag} {k:25} {dp.get('value')}  ({dp.get('date')})")
 
    print("\n" + "=" * 55)
    print(" THIS WEEK'S VERIFIED RELEASES")
    print("=" * 55)
    releases = get_this_weeks_releases(macro)
    if not releases["any"]:
        print("\n  Nothing verified as released this week.")
    else:
        for region, label in [("us", "🇺🇸  US"), ("eu", "🇪🇺  Europe"), ("jp", "🇯🇵  Japan")]:
            if releases[region]:
                print(f"\n{label}:")
                for line in releases[region]:
                    print(f"  • {line}")