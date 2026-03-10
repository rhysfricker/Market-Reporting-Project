# Import Instruments From Config.py
from config import instruments, ATH_TICKERS

# Import Yfinance and Pandas
import yfinance as yf
import pandas as pd

# Fetch Data Function
def fetch_data(ticker, name):
    print(f"Fetching data for {name}")
    df = yf.download(ticker, period="3y", auto_adjust=True, progress=False)
    if df.empty:
        print(f"No Data Found for {name}")
        return None
    print(f"Data for {name} fetched successfully with {len(df)} rows.")
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