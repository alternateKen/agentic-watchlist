# Agentic Watchlist Dashboard

A web page that refreshes itself during US market hours with your stock baskets: basket averages,
relative strength vs the S&P 500, RSI 14, 50/200-day trend, 52-week range, unusual volume, headlines,
a live TradingView price box, and a "Copy brief for Claude" button.

Companion repository: [macro-updates](https://github.com/alternateKen/macro-updates) (macro dashboard).

## Switch-on (one time)
1. Settings, Pages, Source: **GitHub Actions**.
2. Actions tab, "Update agentic watchlist", **Run workflow**.
3. Open the link shown on the finished run and bookmark it.

## Change your stocks
Open `watchlist.txt` on GitHub, click the pencil, edit, press **Commit changes**. The page rebuilds itself.
Bloomberg style codes work (`SHOP US`, `2345 TT`, `6809 HK`, `6723 JP`, `300394 CH`, `NAPA NO`).
Share tickers only, never position sizes: this repository and its page may be public.

## Refresh times
About 6:15am New York time and every 30 minutes from about 9:05am to 4:35pm New York time on weekdays
(the schedule handles summer/winter time), plus whenever `watchlist.txt` changes or you press **Run workflow**.

Files: `scripts/fetch_watchlist.py` (collects data), `docs/index.html` (the page), `watchlist.txt` (your stocks),
`.github/workflows/update.yml` (the schedule).
