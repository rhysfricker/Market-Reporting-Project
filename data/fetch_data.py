# Import Instruments From Config.py
from config import instruments, ATH_TICKERS
 
# Import Yfinance and Pandas
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
 
 
# ── Settlement guard ─────────────────────────────────────────
# Returns True if the latest row in a DataFrame is likely an
# incomplete intraday bar rather than a final settled close.
# This catches the case where the script runs during Friday
# trading hours and yfinance returns a partial bar.
def _is_incomplete_bar(df):
    """
    Heuristic: if the latest bar's date is TODAY and the current
    time is before 6pm ET (23:00 UTC), the bar may not be final.
    COMEX futures settle ~2:30pm ET; equity close is 4pm ET.
    We give a 2-hour buffer → warn if before 6pm ET.
    """
    try:
        latest_date = pd.to_datetime(df.index[-1]).date()
        today       = datetime.utcnow().date()
        utc_hour    = datetime.utcnow().hour
        if latest_date == today and utc_hour < 23:   # before ~6pm ET
            return True
    except Exception:
        pass
    return False
 
 
# Fetch Data Function
def fetch_data(ticker, name):
    print(f"Fetching data for {name}")
    # prepost=False ensures we never get pre/post-market partial bars.
    # actions=False speeds things up (we don't need dividends/splits here).
    df = yf.download(ticker, period="3y", auto_adjust=True,
                     prepost=False, actions=False, progress=False)
    if df.empty:
        print(f"No Data Found for {name}")
        return None
 
    # Flatten MultiIndex columns that yfinance sometimes returns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
 
    # Drop any rows where Close is NaN (can happen on partial bars)
    df = df.dropna(subset=["Close"])
 
    if df.empty:
        print(f"No valid rows after cleaning for {name}")
        return None
 
    # Warn if the latest bar looks incomplete (script run during market hours)
    if _is_incomplete_bar(df):
        print(f"  ⚠ WARNING: {name} — latest bar may be incomplete (market still open). "
              f"Run after 6pm ET / 11pm UTC for fully settled prices.")
 
    print(f"Data for {name} fetched successfully with {len(df)} rows. "
          f"Latest close: {df['Close'].iloc[-1]:.4f} ({df.index[-1].date()})")
    return df
 
# Fetch Max History for True ATH Calculation
def fetch_ath_data():
    print("\nFetching ATH data...")
    ath_data = {}
    for futures_ticker, ath_ticker in ATH_TICKERS.items():
        df = yf.download(ath_ticker, period="max", auto_adjust=True, progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            ath_data[futures_ticker] = df["High"].max()
            print(f"  ✓ ATH fetched for {futures_ticker}: {ath_data[futures_ticker]:.6f}")
        else:
            print(f"  ⚠ No ATH data for {futures_ticker}")
    return ath_data
 
# Wrap All Data Fetching in a Function
def fetch_all_data():
    all_data = {}
    for instrument in instruments:
        df = fetch_data(instrument["ticker"], instrument["name"])
        if df is not None:
            all_data[instrument["ticker"]] = df
    print(f"\n Successfully fetched {len(all_data)} instruments")
    print(f" Tickers loaded: {list(all_data.keys())}")
    return all_data
 
if __name__ == "__main__":
    fetch_all_data()
    fetch_ath_data()