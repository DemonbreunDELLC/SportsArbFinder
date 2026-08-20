# SportsArbFinder Pro ⚡

A modern, real-time **sports betting arbitrage & +EV finder** — built in the spirit of
today's odds platforms (OddsJam, ProfitDuel): a live dark-mode dashboard with an
arbitrage finder, a positive-EV tool, an odds-comparison screen, betting calculators,
browser alerts, and multi-market scanning — all powered by [The Odds API](https://the-odds-api.com/).

![stack](https://img.shields.io/badge/Python_3.10+-FastAPI-blue) ![stack](https://img.shields.io/badge/UI-vanilla_JS,_no_build-green)

## What it does

| Feature | Description |
|---|---|
| **Arbitrage Finder** | Scans every event × market for guaranteed-profit combinations across bookmakers, with optimal stake splits and guaranteed return per outcome |
| **+EV / Value Bets** | Computes consensus no-vig (devigged) fair probabilities from every book, then flags prices that beat fair value (the same core approach +EV tools use) |
| **Odds Screen** | Per-event comparison of every book's moneyline, spread and total — best prices highlighted, low-hold markets badged |
| **Back/Lay (Exchange) Arbs** | Matched-betting style arbs: back at a book, lay at an exchange (Betfair etc.), commission-aware |
| **Real-time updates** | WebSocket push on every scan; refresh from the UI (respects your API quota) |
| **Alerts** | Browser notifications when a new arb above your threshold appears |
| **Calculators** | Arbitrage/dutching, EV, odds converter (decimal/American/fractional), hedge calculator |
| **Works everywhere** | Live API *or* built-in deterministic sample data — the app always runs, even with no key or no network |

## Quick start

```bash
pip install -r requirements.txt

# 1) put YOUR OWN key in a .env file (or export ODDS_API_KEY)
echo "ODDS_API_KEY=your_key_here" > .env

# 2) launch the dashboard (auto-scans on start, refreshes every 5 min)
python app.py
# → http://localhost:8000
```

Open the dashboard, watch arbs stream in, filter by sport/market/margin, set your stake,
and hit **🔔 Alerts** to get pinged on new opportunities.

> **No API key?** The app falls back to realistic built-in sample data and labels it
> clearly in the header, so you can try every feature immediately.

## Command line

```bash
python main.py                            # scan once from the terminal (CLI)
python main.py -r uk --markets h2h,totals --min-ev 2 -c 1
python main.py --sports basketball_nba,baseball_mlb --serve   # scan, then open the dashboard
python app.py --region uk --markets h2h,spreads,totals --refresh 120
python easy_run.py                        # same as `python app.py`
python viewer.py [results.json]           # view saved results without rescanning
python main.py -o response_data.json      # analyze a previously saved API response
python test_engine.py                     # run the test suite
```

All options: `python main.py --help`.

## Markets

`h2h` (moneyline, 2-way and 3-way), `spreads`, `totals`, `outrights` (futures),
`h2h_lay` / `outrights_lay` (exchange back/lay). Player props are a natural next step —
the engine's market layer is built to add them without touching the UI.

## How the math works

- **Arbitrage**: best price per outcome across all books; require at least two
  *different* bookmakers; opportunity exists when `Σ 1/odds < 1`.
  Profit margin = `1/Σ(1/odds) − 1`. Stakes are split so every outcome returns the same amount.
- **Fair probability (devig)**: implied probabilities are averaged across every book
  pricing the market, then renormalized to sum to 1 (no-vig consensus).
- **+EV**: `EV = fair_probability × best_decimal_odds − 1`. A book offering `+128`
  where fair value is `+100` shows up as a ~12% EV bet.
- **Back/lay**: balanced stakes with `lay_stake = back_stake × back_odds / (lay_odds − commission)`;
  profit guaranteed when `back_odds > lay_odds − commission`.

## API credits (free tier = 500/month)

Each scan costs `sports × markets × regions` credits. Defaults are tuned to be cheap
(`h2h,spreads,totals`, 1 region, ≤10 sports) — the header shows your remaining credits
from The Odds API response headers, and the scanner backs off automatically when the
quota runs low. Raise the refresh interval in **Settings** to save credits.

## Project layout

```
main.py               CLI scanner
app.py                FastAPI + WebSocket dashboard server
web/                  dashboard UI (index.html / styles.css / app.js — no build step)
arbitrage_finder.py   detection engine (arbs, +EV, odds screen, lay arbs)
odds_api.py           The Odds API client (caching, quota tracking, sample fallback)
calculators.py        devig / arbitrage / EV / odds-conversion math
sample_data.py        deterministic demo dataset (mirrors the API response shape)
config.py             shared configuration
easy_run.py           `python easy_run.py` → dashboard
viewer.py             `python viewer.py [results.json]` → saved-results view
test_engine.py        test suite (no dependencies beyond the project's own)
```

## Security note

The repository originally shipped an API key in `.env.txt` (committed to git).
That file has been **removed from the repo and deleted** — the app no longer
uses or references it. However, the key still exists in the git history of the
original commit, so **rotate/revoke that key** at https://the-odds-api.com/ if
this repo has ever been public or shared. Keys are only ever read from
`ODDS_API_KEY`, `.env` or `.env.txt` (all git-ignored) — never hard-coded.

## Disclaimer

Educational tool. Odds move fast and books can limit accounts — always verify live
prices before betting, and be aware of the legal status of sports betting in your
jurisdiction. The authors are not responsible for any financial losses. Gamble responsibly.
