# Update v1.4.5 — Prevent stablecoin momentum false positives

## Live evidence
The first paper cycle on the expanded market list opened eight simulated positions. Two were USDC/USDT and USD1/USDT. These are pegged stablecoins, where tiny price noise divided by near-zero volatility can inflate momentum/volatility scores.

## Changes
- Stablecoin pairs stay visible in the market scanner, but their score rows are labeled `EXCLUDED` with an explicit reason and they are removed before building the strategy liquidity shortlist, longs and shorts.
- Introduce a paper-engine version marker. The worker runs once against updated strategy rules after deployment and records the new version to avoid repeating on each poll.
- Existing paper positions are reconciled by the usual paper cycle at current fresh market marks. Any immediate closed-trade statistics form a tiny implementation-transition sample, not meaningful evidence of strategy performance.
- Live trading remains disabled; this migration only changes the paper simulator.

## Verification
- Offline tests cover stablecoin exclusion from the shortlist even when candle-derived turnover is very high, scan row visibility, and one-time paper cycle after strategy version changes.
- After deployment, check that stablecoin rows are labeled EXCLUDED and the paper cycle completes. Do not interpret paper P&L as guaranteed real profit.
