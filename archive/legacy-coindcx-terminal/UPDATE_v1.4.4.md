# Update v1.4.4 — Correct ticker-volume units

## Root cause
Live Render market snapshots showed values such as BTC spot last price near 81,000 and reported 24-hour `volume` near 721 million. The previous implementation multiplied these fields and displayed a turnover near 58 trillion, which is not credible. Futures `v` was treated the same way and similarly inflated.

## Fix
- Preserve the exchange-reported 24h volume value on USDT-quoted spot and futures markets as the turnover proxy; do not multiply by last price a second time.
- Rank the 60-market scan universe by reported 24h ticker volume.
- Keep the distinct candle-based strategy turnover calculation (candle close × base-quantity volume) unchanged.
- Update the Paper Trading explanation and add fixtures where a high last price must not overpower the raw 24h volume rank.

## Validation
- Use `python tests_scan_ui.py` and the existing offline regression suite before treating this as final.
- Render's worker and web deploy from `main`; after deployment verify that DB ticker volume values persist without price multiplication, the universe remains capped at 60, and live-order environment gates remain false.
- This is a data-unit correction, not evidence that any strategy is profitable or that every pair can be filled.
