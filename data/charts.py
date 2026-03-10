# ============================================================
# charts.py
# Generates candlestick charts with technical indicators
# for all instruments defined in config.py
# Saves charts as PNG files to the charts/ folder
# ============================================================

# ── Imports ─────────────────────────────────────────────────
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
import pandas as pd
import numpy as np
import os
from fetch_data import fetch_all_data
from indicators import calculate_indicators, calculate_pivot_points
from config import instruments

# ── Setup ────────────────────────────────────────────────────
# Create charts folder if it doesn't exist
os.makedirs("charts", exist_ok=True)

# Fetch all instrument data
all_data = fetch_all_data()


# ── Chart Generator ──────────────────────────────────────────
# Generates a 4-panel chart for a single instrument:
#   Panel 1 — Candlesticks + SMAs + Bollinger Bands + Pivots
#   Panel 2 — RSI
#   Panel 3 — MACD
#   Panel 4 — Stochastic Oscillator
def generate_chart(ticker, df, name):

    # --- Flatten MultiIndex columns if present ---
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # --- Calculate all indicators ---
    df = calculate_indicators(df)

    # --- Use last 60 days for chart ---
    df_chart = df.tail(60).copy()

    # --- Y-axis bounds ---
    # Include SMA 200 in y_min so it's always fully visible
    q_high     = df_chart["High"].quantile(0.98)
    q_low      = df_chart["Low"].quantile(0.02)
    sma200_min = df_chart["SMA_200"].dropna().min()
    y_max      = q_high * 1.005
    y_min      = min(q_low * 0.995, sma200_min * 0.995)

    # --- Reset index to integers — removes weekend/holiday gaps ---
    df_chart = df_chart.reset_index()
    df_chart.rename(columns={"index": "Date"}, inplace=True)
    df_chart["x"] = range(len(df_chart))

    # --- Calculate pivot points from full dataset ---
    pivots = calculate_pivot_points(df)
    pp  = float(pivots["PP"])
    r1  = float(pivots["R1"])
    r2  = float(pivots["R2"])
    s1  = float(pivots["S1"])
    s2  = float(pivots["S2"])

    # --- Only draw pivot lines within visible y range ---
    def in_range(level):
        return y_min <= level <= y_max

    # ── Figure Layout ────────────────────────────────────────
    # 4 panels: Price (tall), RSI, MACD, Stochastic
    fig = plt.figure(figsize=(14, 12))
    fig.patch.set_facecolor("#0a0c10")

    gs = gridspec.GridSpec(4, 1, height_ratios=[4, 1.2, 1.2, 1.2], hspace=0.08)

    ax1 = fig.add_subplot(gs[0])  # Price + SMAs + Bollinger Bands + Pivots
    ax2 = fig.add_subplot(gs[1])  # RSI
    ax3 = fig.add_subplot(gs[2])  # MACD
    ax4 = fig.add_subplot(gs[3])  # Stochastic

    x_start = df_chart["x"].iloc[0]
    x_end   = df_chart["x"].iloc[-1]

    # ── Panel 1: Candlesticks ────────────────────────────────
    for _, row in df_chart.iterrows():
        color = "#2ecc71" if row["Close"] >= row["Open"] else "#e74c3c"
        # Candle body
        ax1.bar(row["x"], abs(row["Close"] - row["Open"]),
                bottom=min(row["Open"], row["Close"]),
                color=color, width=0.6, alpha=0.9)
        # Candle wick
        ax1.plot([row["x"], row["x"]], [row["Low"], row["High"]],
                 color=color, linewidth=0.8)

    # --- Bollinger Bands — shaded region between upper and lower ---
    ax1.fill_between(df_chart["x"],
                     df_chart["BB_Upper"],
                     df_chart["BB_Lower"],
                     color="#3d7fff", alpha=0.07)
    ax1.plot(df_chart["x"], df_chart["BB_Upper"],
             color="#3d7fff", linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.plot(df_chart["x"], df_chart["BB_Lower"],
             color="#3d7fff", linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.plot(df_chart["x"], df_chart["BB_Mid"],
             color="#3d7fff", linewidth=0.6, linestyle=":", alpha=0.4,
             label="BB Mid")

    # --- SMA Lines ---
    ax1.plot(df_chart["x"], df_chart["SMA_20"],
             color="#3498db", linewidth=1.2, label="SMA 20")
    ax1.plot(df_chart["x"], df_chart["SMA_50"],
             color="#f39c12", linewidth=1.2, label="SMA 50")
    ax1.plot(df_chart["x"], df_chart["SMA_200"],
             color="#e74c3c", linewidth=1.8, label="SMA 200")

    # --- Y-axis limits ---
    ax1.set_ylim(y_min, y_max)

    # --- Pivot Point Lines ---
    pivot_levels = [
        (r2, "#27ae60", "R2"),
        (r1, "#2ecc71", "R1"),
        (pp, "#f1c40f", "PP"),
        (s1, "#e74c3c", "S1"),
        (s2, "#c0392b", "S2"),
    ]

    for level, color, label in pivot_levels:
        if in_range(level):
            ax1.hlines(level, x_start, x_end,
                       colors=color, linewidth=0.9,
                       linestyles="dashed", alpha=0.7)
            ax1.text(x_end + 0.5, level,
                     f" {label} {level:.6f}" if level < 0.1
                     else f" {label} {level:.4f}" if level < 10
                     else f" {label} {level:.2f}",
                     color=color, fontsize=7,
                     va="center", ha="left", alpha=0.9)

    # --- Panel 1 styling ---
    ax1.set_facecolor("#0a0c10")
    ax1.tick_params(colors="white")
    ax1.yaxis.label.set_color("white")
    ax1.legend(loc="upper left", facecolor="#1a1a2e",
               labelcolor="white", fontsize=7)
    ax1.set_title(f"{name} ({ticker}) — Daily Chart",
                  color="white", fontsize=13, pad=10)
    ax1.xaxis.set_visible(False)
    ax1.set_xlim(x_start - 0.5, x_end + 8)

    # ── Panel 2: RSI ─────────────────────────────────────────
    ax2.plot(df_chart["x"], df_chart["RSI"],
             color="#9b59b6", linewidth=1.2)
    ax2.axhline(70, color="#e74c3c", linewidth=0.8, linestyle="--")
    ax2.axhline(30, color="#2ecc71", linewidth=0.8, linestyle="--")
    ax2.axhline(50, color="gray",    linewidth=0.5, linestyle="--")
    ax2.fill_between(df_chart["x"], df_chart["RSI"], 70,
                     where=(df_chart["RSI"] >= 70),
                     color="#e74c3c", alpha=0.3)
    ax2.fill_between(df_chart["x"], df_chart["RSI"], 30,
                     where=(df_chart["RSI"] <= 30),
                     color="#2ecc71", alpha=0.3)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI", color="white", fontsize=9)
    ax2.set_facecolor("#0a0c10")
    ax2.tick_params(colors="white")
    ax2.xaxis.set_visible(False)
    ax2.set_xlim(x_start - 0.5, x_end + 8)

    # ── Panel 3: MACD ────────────────────────────────────────
    ax3.plot(df_chart["x"], df_chart["MACD"],
             color="#2ecc71", linewidth=1.2, label="MACD")
    ax3.plot(df_chart["x"], df_chart["MACD_Signal"],
             color="#e74c3c", linewidth=1.2, label="Signal")

    for _, row in df_chart.iterrows():
        color = "#2ecc71" if row["MACD_Hist"] >= 0 else "#e74c3c"
        ax3.bar(row["x"], row["MACD_Hist"],
                color=color, width=0.6, alpha=0.6)

    ax3.axhline(0, color="gray", linewidth=0.5)
    ax3.set_ylabel("MACD", color="white", fontsize=9)
    ax3.set_facecolor("#0a0c10")
    ax3.tick_params(colors="white")
    ax3.legend(loc="upper left", facecolor="#1a1a2e",
               labelcolor="white", fontsize=7)
    ax3.set_xlim(x_start - 0.5, x_end + 8)
    ax3.xaxis.set_visible(False)

    # Fix scientific notation on MACD y-axis (e.g. Yen)
    ax3.yaxis.set_major_formatter(mticker.ScalarFormatter(useOffset=False))
    ax3.ticklabel_format(style="plain", axis="y")

    # ── Panel 4: Stochastic ──────────────────────────────────
    ax4.plot(df_chart["x"], df_chart["Stoch_K"],
             color="#f1c40f", linewidth=1.2, label="%K")
    ax4.plot(df_chart["x"], df_chart["Stoch_D"],
             color="#e67e22", linewidth=1.0, linestyle="--", label="%D")
    ax4.axhline(80, color="#e74c3c", linewidth=0.8, linestyle="--")
    ax4.axhline(20, color="#2ecc71", linewidth=0.8, linestyle="--")
    ax4.axhline(50, color="gray",    linewidth=0.5, linestyle="--")
    ax4.fill_between(df_chart["x"], df_chart["Stoch_K"], 80,
                     where=(df_chart["Stoch_K"] >= 80),
                     color="#e74c3c", alpha=0.3)
    ax4.fill_between(df_chart["x"], df_chart["Stoch_K"], 20,
                     where=(df_chart["Stoch_K"] <= 20),
                     color="#2ecc71", alpha=0.3)
    ax4.set_ylim(0, 100)
    ax4.set_ylabel("Stoch", color="white", fontsize=9)
    ax4.set_facecolor("#0a0c10")
    ax4.tick_params(colors="white")
    ax4.legend(loc="upper left", facecolor="#1a1a2e",
               labelcolor="white", fontsize=7)
    ax4.set_xlim(x_start - 0.5, x_end + 8)

    # ── X-axis Date Labels ───────────────────────────────────
    # Only shown on bottom panel (Stochastic)
    # Maps integer positions back to real calendar dates
    tick_spacing = max(1, len(df_chart) // 8)
    tick_positions = df_chart["x"].iloc[::tick_spacing].tolist()
    tick_labels = [
        pd.to_datetime(df_chart["Date"].iloc[i]).strftime("%b %d")
        for i in range(0, len(df_chart), tick_spacing)
    ]
    ax4.set_xticks(tick_positions)
    ax4.set_xticklabels(tick_labels, rotation=45,
                        color="white", fontsize=8)

    # ── Save Chart ───────────────────────────────────────────
    filename = ticker.replace("=", "_").replace("^", "")
    filepath = f"charts/{filename}_chart.png"
    plt.savefig(filepath, dpi=150, bbox_inches="tight",
                facecolor="#0a0c10")
    plt.close()
    print(f"  ✓ Chart saved: {filepath}")


# ── Generate All Charts ──────────────────────────────────────
# Loops through all instruments and generates one chart each
print("\nGenerating charts...")
for ticker, df in all_data.items():
    name = next(i["name"] for i in instruments if i["ticker"] == ticker)
    generate_chart(ticker, df, name)

print("\n✓ All charts generated successfully")