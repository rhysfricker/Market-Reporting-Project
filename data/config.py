# Define Assets, Tickers, and Regions
instruments = [
    {"name": "S&P500",       "ticker": "ES=F",      "region": "US"},
    {"name": "Nasdaq",       "ticker": "NQ=F",       "region": "US"},
    {"name": "Dollar Index", "ticker": "DX-Y.NYB",  "region": "US"},
    {"name": "Dow Jones",    "ticker": "YM=F",       "region": "US"},
    {"name": "DAX",          "ticker": "^GDAXI",     "region": "EU"},
    {"name": "FTSE100",      "ticker": "^FTSE",      "region": "UK"},
    {"name": "Euro Stoxx50", "ticker": "^STOXX50E",  "region": "EU"},
    {"name": "Nikkei",       "ticker": "NKD=F",      "region": "JP"},
    {"name": "Yen",          "ticker": "6J=F",       "region": "JP"},
    {"name": "Sterling",     "ticker": "6B=F",       "region": "UK"},
    {"name": "Euro",         "ticker": "6E=F",       "region": "EU"},
    {"name": "Gold",         "ticker": "GC=F",       "region": "Commodity"},
    {"name": "Silver",       "ticker": "SI=F",       "region": "Commodity"},
    {"name": "Crude Oil",    "ticker": "CL=F",       "region": "Commodity"},
]

# ATH Tickers — maps futures tickers to best Yahoo Finance source for true ATH
ATH_TICKERS = {
    "ES=F":      "ES=F",      # S&P 500 cash index
    "NQ=F":      "NQ=F",      # Nasdaq cash index
    "YM=F":      "YM=F",       # Dow Jones cash index
    "^GDAXI":    "^GDAXI",     # DAX
    "^FTSE":     "^FTSE",      # FTSE 100
    "^STOXX50E": "^STOXX50E",  # Euro Stoxx 50
    "NKD=F":     "NKD=F",      # Nikkei cash index
    "GC=F":      "GC=F",       # Gold futures
    "SI=F":      "SI=F",       # Silver futures
    "CL=F":      "CL=F",       # Crude Oil futures
    "6B=F":      "6B=F",   # Sterling spot
    "6E=F":      "6E=F",   # Euro spot
    "6J=F":      "6J=F",   # Yen spot
    "DX-Y.NYB":  "DX-Y.NYB",  # Dollar Index
}


# Only print when running config.py directly
if __name__ == "__main__":
    
    # Print Each Instrument
    for instrument in instruments:
        print(f"{instrument['name']} ({instrument['ticker']}) - Region: {instrument['region']}")

    # Group Instruments by Region and Print
    region_list = ["US", "EU", "UK", "JP", "Commodity"]
    for r in region_list:
        print(f"\n- {r} -")
        for instrument in instruments:
            if instrument["region"] == r:
                print(f" {instrument['name']:15} {instrument['ticker']}")