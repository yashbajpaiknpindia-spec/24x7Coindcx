# v1.4.0 update notes

- Paper mode auto-starts by default (`AUTO_START_PAPER=true`) and stays separate from live order execution.
- Market refresh dynamically expands beyond the legacy 14-pair watchlist, ranking active-looking CoinDCX USDT tickers by volume × last price. Configure `SCAN_UNIVERSE_LIMIT` (20–150, default 60). API coverage/eligibility still depends on exchange responses and the quality page.
- Research paper signals use a fixed notional per signal rather than the configured account capital, so the paper trade sample is not capped by the capital-mode balance. The Capital page remains a separate account-sized view. Configure `PAPER_RESEARCH_NOTIONAL_USDT` (default 1000) for the intended paper notional.
- Paper dashboard includes closed-trade count, net win rate, profit factor and net P&L, plus a simplified futures liquidation-price estimate for open positions.
- Added previously reported exploratory 1-year CoinDCX results for ZEC/SOL/ETH/BNB to the backtest archive. They are labelled as prior results, not reruns or blind tests. Existing databases add missing scorecards on startup.
- API secrets are intentionally not collected in ChatGPT or written into the application database. Add `COINDCX_API_KEY` and `COINDCX_API_SECRET` in the deployment environment. Public market scanning can work without account credentials; authenticated account endpoints cannot.
- No mock market data is introduced. Failed/stale API data should be treated as unavailable. Historical liquidation verification is not claimed: it requires intrabar candle history and exchange-specific maintenance-margin tiers, which this version does not yet reconstruct.

Live order execution remains disabled by default. Paper simulation is not a guarantee of real fills, profitability, or exchange liquidation behavior.
