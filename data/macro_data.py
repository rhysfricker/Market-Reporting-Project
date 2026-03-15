# ============================================================
# macro_data.py  --  G7 Weekly Market Report
#
# Fetches macroeconomic data for the report's macro sections.
# Returns DataPoint dicts:  { value, date, released_this_week }
#
# FRED SERIES STATUS (verified March 2026):
#   OK DFEDTARU          -- Fed Funds upper target  (live, Mar 2026)
#   OK CPIAUCNS           -- US CPI index NSA        (live, Feb 2026)
#   OK PCEPILFE           -- Core PCE index          (live, Feb 2026)
#   OK UNRATE             -- US Unemployment         (live, Feb 2026)
#   OK PAYEMS             -- US NFP                  (live, Feb 2026)
#   OK A191RL1Q225SBEA    -- US GDP QoQ              (live, Q4 2025)
#   OK INDPRO             -- Industrial Production   (live, Jan 2026)
#   OK TCU                -- Capacity Utilization    (live, Jan 2026)
#   OK DGS10 / DGS2       -- Treasury yields         (live, daily)
#   OK ECBDFR             -- ECB Deposit Rate        (live, Mar 2026)
#   OK IUDSOIA            -- BoE Bank Rate           (live, Mar 2026)
#   OK CP0000EZ19M086NEST -- EA HICP index (26-char) (live, Dec 2025)
#                          -> must compute YoY manually (units=pc1 rejected)
#   OK CLVMNACSCAB1GQEA19 -- EZ GDP index            (live, Q3 2025)
#   XX LRHUTTTTEZM156S   -- EZ Unemployment OECD    DEAD Jan 2023
#   XX EURUNEMPEA20       -- EZ Unemployment Eurostat DOES NOT EXIST on FRED
#      -> use Eurostat JSON API (no key needed), fails loudly if unavailable
#   XX GBRCPIALLMINMEI   -- UK CPI OECD index       STALE Mar 2025
#      -> fetch directly from ONS API (no key required), series D7G7
#   OK IRSTCI01JPM156N    -- BoJ Overnight Call Rate  (live, Jan 2026)
#      -> this is the overnight call rate, NOT the policy target
#      -> snap to nearest 0.25% to get the policy rate (like BoE/SONIA)
#   XX JPNCPIALLMINMEI   -- Japan CPI OECD index    DEAD Jun 2021
#      -> multi-source: e-Stat API -> OECD SDMX API fallback
#      -> set ESTAT_APP_ID env var for reliable e-Stat access
#   OK JPNRGDPEXP         -- Japan GDP               (live, Q3 2025)
#   OK XTEXVA01JPM667S    -- Japan Exports (OECD)    (live, Dec 2025)
#   OK XTIMVA01JPM667S    -- Japan Imports (OECD)    (live, Dec 2025)
#      -> trade balance = exports - imports (no single FRED series)
#   XX LRUNTTTTJPM156S    -- Japan Unemployment OECD  lags e-Stat
#      -> use e-Stat API table 0003005865 for latest unemployment rate
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


# -- ForexFactory -> FRED key mapping --
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


# -- Released-this-week set --
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
                    print(f"  \u2705 FF verified release: {fred_key} \u2190 '{event['event']}' ({event['date']})")
    return released


# -- DataPoint helpers --
def _dp(value, date, label, released):
    date_str = date.strftime("%b %Y") if hasattr(date, "strftime") else str(date)
    flag = "\U0001f195" if released else "  "
    print(f"  {flag} {label}: {value} ({date_str})")
    return {"value": value, "date": date_str, "released_this_week": released}

def _fail(label):
    print(f"  \u2717 {label}: Failed -- no data available")
    return {"value": None, "date": None, "released_this_week": False}

def _quarter_date(dp):
    """Convert a DataPoint's date from 'Oct 2025' -> 'Q4 2025'.
    FRED quarterly GDP series use the first month of the quarter as the date,
    which causes the AI to write 'in October' instead of 'in Q4'."""
    try:
        dt = datetime.strptime(dp["date"], "%b %Y")
        q = (dt.month - 1) // 3 + 1
        dp["date"] = f"Q{q} {dt.year}"
    except Exception:
        pass
    return dp


# -- FRED: latest value --
def get_latest(series_id, label, released=False):
    try:
        s = fred.get_series(series_id).dropna()
        return _dp(round(float(s.iloc[-1]), 2), s.index[-1], label, released)
    except Exception as e:
        print(f"  \u2717 {label}: Failed -- {e}")
        return _fail(label)


# -- FRED: YoY via units=pc1 --
def get_yoy_change(series_id, label, released=False):
    try:
        s = fred.get_series(series_id, units="pc1").dropna()
        return _dp(round(float(s.iloc[-1]), 2), s.index[-1], label, released)
    except Exception as e:
        print(f"  \u2717 {label}: Failed -- {e}")
        return _fail(label)


# -- FRED: Manual YoY from raw index --
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
        print(f"  \u2717 {label}: Failed -- {e}")
        return _fail(label)


# -- FRED: Monthly change --
def get_monthly_change(series_id, label, divisor=1, released=False):
    try:
        s      = fred.get_series(series_id).dropna()
        change = round((float(s.iloc[-1]) - float(s.iloc[-2])) / divisor, 1)
        return _dp(change, s.index[-1], label, released)
    except Exception as e:
        print(f"  \u2717 {label}: Failed -- {e}")
        return _fail(label)


# -- UK CPI: ONS website JSON API (series D7G7 = CPI all items YoY %) --
def get_uk_cpi(released=False):
    label = "UK CPI YoY %"
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
            dt = TODAY
            for fmt in ("%Y %b", "%b %Y", "%Y-%m"):
                try:
                    dt = datetime.strptime(raw_date, fmt)
                    break
                except Exception:
                    pass
            return _dp(val, dt, label, released)
        except Exception as e:
            print(f"  \u26a0 ONS URL failed ({url[-50:]}: {e})")
            continue

    print(f"  \u2717 UK CPI: All ONS URLs failed -- no data available")
    return _fail(label)


# -- UK GDP YoY: ONS website JSON API --
# KGQ5 (GDP YoY monthly %) is discontinued on ONS -- all pgdp/mgdp URLs 404.
# Instead: fetch ECY2/mgdp (GVA monthly index, CVM SA) and compute YoY
# manually by comparing the latest month to 12 months prior.
def get_uk_gdp(released=False):
    label = "UK GDP YoY %"
    url = "https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries/ecy2/mgdp/data"
    try:
        r = requests.get(url, timeout=10, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
        months = data.get("months", [])
        if len(months) < 13:
            raise ValueError(f"Need 13+ months for YoY, got {len(months)}")
        latest_val = float(months[-1]["value"])
        prior_val  = float(months[-13]["value"])
        yoy = round((latest_val / prior_val - 1) * 100, 2)
        raw_date = months[-1].get("label", "")
        dt = TODAY
        for fmt in ("%Y %b", "%b %Y", "%Y-%m"):
            try:
                dt = datetime.strptime(raw_date, fmt)
                break
            except Exception:
                pass
        print(f"     UK GDP via ECY2 index: {prior_val} -> {latest_val} = {yoy}% YoY")
        return _dp(yoy, dt, label, released)
    except Exception as e:
        print(f"  \u26a0 ONS GDP URL failed: {e}")

    print(f"  \u2717 UK GDP: ONS ECY2/mgdp failed -- no data available")
    return _fail(label)


# -- BoJ Policy Rate: snap overnight call rate to nearest 0.25% --
# IRSTCI01JPM156N is the overnight call rate, which trades slightly
# below the BoJ's policy rate target.  Recent BoJ target rates:
# -0.1%, 0%, 0.25%, 0.5%, 0.75% -- all multiples of 0.25%.
# Snapping to nearest 0.25% recovers the correct policy target.
def get_boj_rate(released=False):
    label = "BoJ Policy Rate"
    try:
        s = fred.get_series("IRSTCI01JPM156N").dropna()
        raw = round(float(s.iloc[-1]), 4)
        snapped = round(round(raw / 0.25) * 0.25, 2)
        print(f"     BoJ overnight call rate raw: {raw}% -> snapped to {snapped}%")
        return _dp(snapped, s.index[-1], label, released)
    except Exception as e:
        print(f"  \u2717 {label}: Failed -- {e}")
        return _fail(label)


# -- Japan Unemployment: e-Stat API --
# Table 0003005865 = Labor Force Survey
# cdTab=02 (rate %), cdCat02=08 (unemployment rate), cdCat03=0 (total)
def get_japan_unemployment_estat(released=False):
    label = "Japan Unemployment"
    estat_app_id = os.getenv("ESTAT_APP_ID", "guest")
    try:
        url = (
            f"https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
            f"?appId={estat_app_id}"
            f"&statsDataId=0003005865"
            f"&cdTab=02"
            f"&cdCat02=08"
            f"&cdCat03=0"
            f"&limit=500"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        result = data.get("GET_STATS_DATA", {}).get("RESULT", {})
        status = result.get("STATUS", 0)
        if int(status) != 0:
            msg = result.get("ERROR_MSG", "unknown error")
            raise ValueError(f"e-Stat API error {status}: {msg}")

        values = (
            data.get("GET_STATS_DATA", {})
                .get("STATISTICAL_DATA", {})
                .get("DATA_INF", {})
                .get("VALUE", [])
        )
        if not values:
            raise ValueError("e-Stat returned empty VALUE array")

        obs = {}
        for v in values:
            t = v.get("@time", "")
            val = v.get("$", "")
            if t and val:
                try:
                    obs[t] = float(val)
                except ValueError:
                    pass

        if not obs:
            raise ValueError("No numeric observations from e-Stat")

        latest_key = sorted(obs.keys())[-1]
        rate = round(obs[latest_key], 2)

        try:
            dt = datetime.strptime(latest_key, "%Y-%m")
        except Exception:
            dt = TODAY
        print(f"    e-Stat unemployment: {rate}% ({dt.strftime('%b %Y')})")
        return _dp(rate, dt, label, released)

    except Exception as e:
        print(f"  \u26a0 e-Stat unemployment failed: {e}")
        print(f"    Falling back to FRED LRUNTTTTJPM156S...")
        return get_latest("LRUNTTTTJPM156S", label, released)


# -- Japan Trade Balance: exports minus imports from FRED --
# No single FRED series provides Japan's trade balance directly.
# XTEXVA01JPM667S = Exports of goods (OECD, USD, SA)
# XTIMVA01JPM667S = Imports of goods (OECD, USD, SA)
# Raw values are in USD (e.g. 60,926,820,000 = ~$60.9B).
# Trade balance = exports - imports, divided by 1e9 -> billions USD.
def get_japan_trade_balance(released=False):
    label = "Japan Trade Balance"
    try:
        exports = fred.get_series("XTEXVA01JPM667S").dropna()
        imports = fred.get_series("XTIMVA01JPM667S").dropna()

        common_idx = exports.index.intersection(imports.index)
        if len(common_idx) == 0:
            raise ValueError("No overlapping dates between exports and imports series")

        latest_date = common_idx[-1]
        exp_val = float(exports.loc[latest_date])
        imp_val = float(imports.loc[latest_date])
        balance = round((exp_val - imp_val) / 1e9, 2)

        print(f"     Japan trade: exports=${exp_val/1e9:.1f}B - imports=${imp_val/1e9:.1f}B = ${balance:.2f}B")
        return _dp(balance, latest_date, label, released)
    except Exception as e:
        print(f"  \u2717 {label}: Failed -- {e}")
        return _fail(label)


# -- Japan CPI: e-Stat API with proper API key --
# statsDataId 0003427113, cdTab=3 (YoY% directly), cdCat01=0001 (All items),
# cdArea=00000 (All Japan). Uses ESTAT_APP_ID from .env.
def get_japan_cpi(released=False):
    label = "Japan CPI YoY %"
    estat_app_id = os.getenv("ESTAT_APP_ID", "guest")
    print(f"  Trying e-Stat API for Japan CPI...")
    try:
        url = (
            f"https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
            f"?appId={estat_app_id}"
            f"&statsDataId=0003427113"
            f"&cdTab=3"
            f"&cdCat01=0001"
            f"&cdArea=00000"
            f"&limit=5"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        result = data.get("GET_STATS_DATA", {}).get("RESULT", {})
        status = result.get("STATUS", 0)
        if int(status) != 0:
            msg = result.get("ERROR_MSG", "unknown error")
            raise ValueError(f"e-Stat API error {status}: {msg}")

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

        latest_key = sorted(obs.keys())[-1]
        yoy = round(obs[latest_key], 2)

        # Extract date: "2025000303" -> year=2025, month=03
        year_str  = latest_key[:4]
        month_str = latest_key[4:6]
        if month_str == "00":
            month_str = latest_key[6:8]
        try:
            dt = datetime.strptime(f"{year_str}{month_str}", "%Y%m")
        except Exception:
            dt = TODAY
        print(f"    e-Stat: success -- {yoy}% ({dt.strftime('%b %Y')})")
        return _dp(yoy, dt, label, released)

    except Exception as e:
        print(f"  \u2717 Japan CPI: e-Stat API failed ({e})")
        print(f"    -> Set ESTAT_APP_ID env var for reliable access")
        return _fail(label)


# -- EZ Unemployment: Eurostat JSON API --
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

        values = data.get("value", {})
        if not values:
            raise ValueError(f"No value field in response. Keys: {list(data.keys())}")

        dim_ids   = data.get("id", [])
        time_key  = dim_ids[-1] if dim_ids else "time"
        dim_sizes = data.get("size", [])

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

        latest_period = max(time_cat_index, key=lambda k: time_cat_index[k])
        latest_pos    = time_cat_index[latest_period]

        time_stride = 1
        for sz in dim_sizes[len(dim_ids):]:
            time_stride *= sz
        flat_index = latest_pos * time_stride

        val = values.get(str(flat_index)) or values.get(flat_index)
        if val is None:
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
        print(f"  \u2717 EZ Unemployment: Eurostat API failed ({e})")
        return _fail(label)


# -- BoE Rate: SONIA snapped to nearest 0.25% --
def get_boe_rate(released=False):
    label = "BoE Bank Rate"
    try:
        s = fred.get_series("IUDSOIA").dropna()
        raw = float(s.iloc[-1])
        snapped = round(round(raw / 0.25) * 0.25, 2)
        print(f"     BoE SONIA raw: {raw}% -> snapped to {snapped}%")
        return _dp(snapped, s.index[-1], label, released)
    except Exception as e:
        print(f"  \u2717 {label}: Failed -- {e}")
        return _fail(label)


# -- US Macro --
def fetch_us_macro(released):
    print("\n\U0001f1fa\U0001f1f8  Fetching US Macro Data...")
    us = {
        "fed_funds_rate":        get_latest("DFEDTARU",        "Fed Funds Rate",            released=("fed_funds_rate"        in released)),
        "yield_10yr":            get_latest("DGS10",           "10yr Treasury Yield",       released=False),
        "yield_2yr":             get_latest("DGS2",            "2yr Treasury Yield",        released=False),
        "cpi_yoy":               get_yoy_change("CPIAUCNS",    "CPI YoY %",                 released=("cpi_yoy"               in released)),
        "core_pce":              get_yoy_change("PCEPILFE",    "Core PCE YoY %",            released=("core_pce"              in released)),
        "unemployment":          get_latest("UNRATE",          "Unemployment Rate",         released=("unemployment"          in released)),
        "nonfarm_payrolls":      get_monthly_change("PAYEMS",  "NFP Monthly Change (000s)", released=("nonfarm_payrolls"      in released)),
        "gdp_growth":            _quarter_date(get_latest("A191RL1Q225SBEA", "US GDP annualised rate -- THIS VALUE IS ALREADY ANNUALISED. Write ONLY as: the economy grew at an annualised rate of X%. NEVER say quarter-over-quarter. NEVER multiply by 4.", released=("gdp_growth" in released))),
        "industrial_production": get_latest("INDPRO",          "Industrial Production",     released=("industrial_production" in released)),
        "capacity_utilization":  get_latest("TCU",             "Capacity Utilization %",    released=("capacity_utilization"  in released)),
    }
    try:
        spread = round(us["yield_10yr"]["value"] - us["yield_2yr"]["value"], 3)
        status = "Normal" if spread > 0 else "INVERTED \u26a0"
        print(f"     Yield Spread: {spread}% -- {status}")
    except Exception:
        spread = None
    us["yield_spread"] = {"value": spread, "date": TODAY.strftime("%b %Y"), "released_this_week": False}
    return us


# -- Europe Macro --
def fetch_europe_macro(released):
    print("\n\U0001f1ea\U0001f1fa  Fetching Europe Macro Data...")
    return {
        "ecb_rate":        get_latest("ECBDFR",                  "ECB Deposit Rate",        released=("ecb_rate"        in released)),
        "boe_rate":        get_boe_rate(released=("boe_rate" in released)),
        "ez_cpi":          get_yoy_manual("CP0000EZ19M086NEST",  "Eurozone CPI YoY %",      released=("ez_cpi"          in released)),
        "ez_gdp_growth":   _quarter_date(get_yoy_change("CLVMNACSCAB1GQEA19", "Eurozone GDP YoY %", released=("ez_gdp_growth" in released))),
        "ez_unemployment": get_ez_unemployment(released=("ez_unemployment" in released)),
        "uk_cpi":          get_uk_cpi(released=("uk_cpi" in released)),
        "uk_gdp_growth":   get_uk_gdp(released=("uk_gdp_growth" in released)),
        "uk_unemployment": get_latest("LRHUTTTTGBM156S",         "UK Unemployment",          released=("uk_unemployment" in released)),
        "uk_debt_gdp":     get_latest("DEBTTLGBA188A",           "UK Debt to GDP %",         released=False),
    }


# -- Japan Macro --
def fetch_japan_macro(released):
    print("\n\U0001f1ef\U0001f1f5  Fetching Japan Macro Data...")
    return {
        "boj_rate":           get_boj_rate(released=("boj_rate" in released)),
        "japan_cpi":          get_japan_cpi(released=("japan_cpi" in released)),
        "japan_gdp_growth":   _quarter_date(get_yoy_change("JPNRGDPEXP", "Japan GDP YoY %", released=("japan_gdp_growth" in released))),
        "japan_trade":        get_japan_trade_balance(released=("japan_trade" in released)),
        "japan_unemployment": get_japan_unemployment_estat(released=("japan_unemployment" in released)),
    }


# -- Master fetch --
def fetch_all_macro(ff_this_week=None):
    if ff_this_week is None:
        ff_this_week = get_this_week_events()

    print("\n\U0001f4cb  Verifying this week's releases against ForexFactory...")
    released = _build_released_set(ff_this_week)
    if not released:
        print("     No matching FF events found -- no FRED series flagged.")

    return {
        "us": fetch_us_macro(released),
        "eu": fetch_europe_macro(released),
        "jp": fetch_japan_macro(released),
    }


# -- This week's releases for Claude prompts --
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


# -- Convenience extractor --
def val(datapoint):
    return datapoint.get("value") if datapoint else None


# -- Main --
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    macro = fetch_all_macro()

    print("\n" + "=" * 55)
    print(" MACRO DATA SUMMARY")
    print("=" * 55)
    for region, label in [("us", "\U0001f1fa\U0001f1f8  US"), ("eu", "\U0001f1ea\U0001f1fa  Europe"), ("jp", "\U0001f1ef\U0001f1f5  Japan")]:
        print(f"\n{label}:")
        for k, dp in macro[region].items():
            if isinstance(dp, dict):
                flag = "\U0001f195" if dp.get("released_this_week") else "  "
                print(f"  {flag} {k:25} {dp.get('value')}  ({dp.get('date')})")

    print("\n" + "=" * 55)
    print(" THIS WEEK'S VERIFIED RELEASES")
    print("=" * 55)
    releases = get_this_weeks_releases(macro)
    if not releases["any"]:
        print("\n  Nothing verified as released this week.")
    else:
        for region, label in [("us", "\U0001f1fa\U0001f1f8  US"), ("eu", "\U0001f1ea\U0001f1fa  Europe"), ("jp", "\U0001f1ef\U0001f1f5  Japan")]:
            if releases[region]:
                print(f"\n{label}:")
                for line in releases[region]:
                    print(f"  \u2022 {line}")
