# G7 Weekly Market Report

Automated weekly market report generator. Fetches live market data, 
macroeconomic data and news headlines, generates AI narratives via 
Claude, and outputs a self-contained HTML report with embedded charts.

## Instruments Covered
S&P 500, Nasdaq, Dow Jones, Dollar Index, DAX, FTSE 100,
Euro Stoxx 50, Euro, Sterling, Nikkei, Yen, Gold, Silver, Crude Oil

## Setup

1. Clone this repository
2. Install dependencies:
   pip3 install -r requirements.txt
3. Create a .env file in the project root with your API keys:
   ANTHROPIC_API_KEY=your-key-here
   FRED_API_KEY=your-key-here
4. Run:
   python3 report.py
5. Open the localhost URL printed in the terminal
6. In Chrome: Cmd+P → Save as PDF → tick Background Graphics → Save

## Data Sources
- Yahoo Finance (market data)
- FRED API (macroeconomic data)
- CNBC & BBC RSS feeds (news headlines)
- Claude API (AI narratives)