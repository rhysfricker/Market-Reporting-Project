# G7 Weekly Market Report

Automated weekly market report generator. Fetches live market data, 
macroeconomic data and news headlines, generates AI narratives via 
Anthropic's Claude, and outputs a self-contained HTML report with embedded charts.

## Instruments Covered
S&P 500, Nasdaq, Dow Jones, Dollar Index, DAX, FTSE 100,
Euro Stoxx 50, Euro, Sterling, Nikkei, Yen, Gold, Silver, Crude Oil

## Setup

1. Clone this repository
2. Install dependencies:
   pip3 install -r requirements.txt
3. Copy `.env.example` to `.env` and add your API keys:
   cp .env.example .env
   # Then edit .env with your keys (Anthropic, FRED, e-Stat)
4. Run:
   python3 report.py
5. Open the localhost URL printed in the terminal
6. In Chrome: Cmd+P → Save as PDF → tick Background Graphics → Save

## Data Sources
- Yahoo Finance (market data)
- FRED API (macroeconomic data)
- CNBC & BBC RSS feeds (news headlines)
- Claude API (AI narratives)
- Forex Factory (Economic Calendar)