# ============================================================
# indicators.py
# Calculates all technical indicators for each instrument
# Called by charts.py and report.py
# ============================================================

# ── Imports ─────────────────────────────────────────────────
import pandas as pd
import ta
from fetch_data import fetch_all_data, fetch_ath_data
from config import instruments, ATH_TICKERS


# ── Price Formatting Helper ──────────────────────────────────
# Adjusts decimal places based on instrument price magnitude
# e.g. Yen (0.006xxx) needs 6dp, FX needs 4dp, indices need 2dp
def format_price(value):
    if value < 0.1:
        return f"{value:.6f}"
    elif value < 10:
        return f"{value:.4f}"
    else:
        return f"{value:.2f}"


# ── Technical Indicators ─────────────────────────────────────
# Calculates all indicators and appends them as new columns
# to the DataFrame. Called once per instrument before charting.
def calculate_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # --- Trend: Moving Averages ---
    df["SMA_20"]      = ta.trend.sma_indicator(df["Close"], window=20)
    df["SMA_50"]      = ta.trend.sma_indicator(df["Close"], window=50)
    df["SMA_200"]     = ta.trend.sma_indicator(df["Close"], window=200)

    # --- Volatility: Bollinger Bands (20 period, 2 std dev) ---
    bb                = ta.volatility.BollingerBands(df["Close"], window=20, window_dev=2)
    df["BB_Upper"]    = bb.bollinger_hband()
    df["BB_Lower"]    = bb.bollinger_lband()
    df["BB_Mid"]      = bb.bollinger_mavg()

    # --- Momentum: RSI (14 period) ---
    df["RSI"]         = ta.momentum.rsi(df["Close"], window=14)

    # --- Momentum: Stochastic Oscillator (14, 3, 3) ---
    stoch             = ta.momentum.StochasticOscillator(
                            df["High"], df["Low"], df["Close"],
                            window=14, smooth_window=3)
    df["Stoch_K"]     = stoch.stoch()
    df["Stoch_D"]     = stoch.stoch_signal()

    # --- Momentum: MACD (12, 26, 9) ---
    df["MACD"]        = ta.trend.macd(df["Close"], window_fast=12, window_slow=26)
    df["MACD_Signal"] = ta.trend.macd_signal(df["Close"], window_fast=12, window_slow=26, window_sign=9)
    df["MACD_Hist"]   = ta.trend.macd_diff(df["Close"], window_fast=12, window_slow=26)

    # --- Volatility: ATR (14 period) — used in report text, not charts ---
    df["ATR"]         = ta.volatility.average_true_range(
                            df["High"], df["Low"], df["Close"], window=14)

    return df


# ── Pivot Points ─────────────────────────────────────────────
# Classic floor trader pivot points calculated from
# the previous day's High, Low, Close
def calculate_pivot_points(df):
    prev  = df.iloc[-2]
    high  = prev["High"]
    low   = prev["Low"]
    close = prev["Close"]

    pp = (high + low + close) / 3      # Pivot Point
    r1 = (2 * pp) - low                # Resistance 1
    r2 = pp + (high - low)             # Resistance 2
    s1 = (2 * pp) - high               # Support 1
    s2 = pp - (high - low)             # Support 2

    return {"PP": pp, "R1": r1, "R2": r2, "S1": s1, "S2": s2}


# ── Swing Levels & All Time High ─────────────────────────────
# Calculates short (5d), medium (20d) and long (60d) swing
# highs and lows. ATH pulled from ath_data if available.
def calculate_swing_levels(df, ticker, ath_data=None):
    short  = df.tail(5)
    medium = df.tail(20)
    long   = df.tail(60)

    # Use verified ATH from fetch_data if available
    if ath_data and ticker in ath_data:
        ath = ath_data[ticker]
    else:
        ath = df["High"].max()

    return {
        "ST_High": short["High"].max(),
        "ST_Low":  short["Low"].min(),
        "MT_High": medium["High"].max(),
        "MT_Low":  medium["Low"].min(),
        "LT_High": long["High"].max(),
        "LT_Low":  long["Low"].min(),
        "ATH":     ath,
    }


# ── Main: Print All Indicators for All Instruments ───────────
# Runs when indicators.py is executed directly.
# Useful for verifying indicator output before building charts.
if __name__ == "__main__":
    all_data = fetch_all_data()
    ath_data = fetch_ath_data()

    for ticker, df in all_data.items():

        # Calculate all indicators
        df = calculate_indicators(df)

        # Extract latest and previous row values
        latest      = df.iloc[-1]
        prev        = df.iloc[-2]
        close       = latest["Close"]
        rsi         = latest["RSI"]
        sma200      = latest["SMA_200"]
        macd        = latest["MACD"]
        signal      = latest["MACD_Signal"]
        hist        = latest["MACD_Hist"]
        macd_prev   = prev["MACD"]
        signal_prev = prev["MACD_Signal"]
        stoch_k     = latest["Stoch_K"]
        stoch_d     = latest["Stoch_D"]
        bb_upper    = latest["BB_Upper"]
        bb_lower    = latest["BB_Lower"]
        atr         = latest["ATR"]

        pivots = calculate_pivot_points(df)
        swings = calculate_swing_levels(df, ticker, ath_data)

        # --- Trend Signal ---
        above_200 = "Above 200 SMA" if close > sma200 else "Below 200 SMA"

        # --- RSI Signal ---
        if rsi >= 70:   rsi_signal = "Overbought"
        elif rsi <= 30: rsi_signal = "Oversold"
        else:           rsi_signal = "Neutral"

        # --- Stochastic Signal ---
        if stoch_k >= 80:   stoch_signal = "Overbought"
        elif stoch_k <= 20: stoch_signal = "Oversold"
        else:               stoch_signal = "Neutral"

        # --- MACD Signal ---
        if macd_prev < signal_prev and macd > signal:
            macd_signal = "Golden Cross - Bullish crossover, potential buy signal"
        elif macd_prev > signal_prev and macd < signal:
            macd_signal = "Death Cross - Bearish crossover, potential sell signal"
        elif macd > signal and hist > 0:
            macd_signal = "Bullish - MACD above signal, momentum building"
        elif macd > signal and hist < 0:
            macd_signal = "Weakening Bullish - MACD above signal but momentum fading"
        elif macd < signal and hist < 0:
            macd_signal = "Bearish - MACD below signal, momentum building"
        elif macd < signal and hist > 0:
            macd_signal = "Weakening Bearish - MACD below signal but losing steam"
        else:
            macd_signal = "Flat"

        # --- Print Output ---
        print(f"{'-' * 55}")
        print(f" {ticker}")
        print(f" Close:         {format_price(close)}")
        print(f" RSI:           {rsi:>10.1f}  — {rsi_signal}")
        print(f" Stochastic K:  {stoch_k:>10.1f}  — {stoch_signal}")
        print(f" MACD:          {macd_signal}")
        print(f" Trend:         {above_200}")
        print(f" BB Upper:      {format_price(bb_upper)}")
        print(f" BB Lower:      {format_price(bb_lower)}")
        print(f" ATR:           {format_price(atr)}")
        print(f" Pivots:        PP={format_price(pivots['PP'])}  R1={format_price(pivots['R1'])}  R2={format_price(pivots['R2'])}  S1={format_price(pivots['S1'])}  S2={format_price(pivots['S2'])}")
        print(f" Week:          High={format_price(swings['ST_High'])}  Low={format_price(swings['ST_Low'])}")
        print(f" Month:         High={format_price(swings['MT_High'])}  Low={format_price(swings['MT_Low'])}")
        print(f" 60 Days:       High={format_price(swings['LT_High'])}  Low={format_price(swings['LT_Low'])}")
        print(f" All Time High: {format_price(swings['ATH'])}")