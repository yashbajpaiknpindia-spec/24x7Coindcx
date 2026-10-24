> **Volume semantics superseded by v1.4.4:** the exchange ticker's 24h `volume`/futures `v` is used directly as a screening proxy for a USDT pair. Do not multiply it by the latest price again. See `UPDATE_v1.4.4.md` for the correction and test coverage.

# Update v1.4.3 — Live scanner and paper opportunity visibility

## Fixes
- Parse standard concatenated CoinDCX spot ticker names into canonical app market pairs.
- Unwrap futures price `prices` responses and futures candle `{s,data}` payloads.
- Discover and cap the default USDT scan universe at 60 unique pairs (configurable to 150); rank by reported spot base volume × last price, not market capitalization.
- Keep candle scoring on the same capped discovered market list shown in the UI.
- Refresh strategy opportunity scores on a 15-minute schedule independently of once-per-day portfolio rebalance.
- Show scan rows, quality/readiness, strategy score, signal reason, liquidity gate and paper trade state on Paper Trading.
- Add offline regression tests for ticker normalization, market cap, public futures response shapes, and visible scan UI.

## Deploy safety
- The existing Render Blueprint declares both web and background worker, one shared PostgreSQL database, `SCAN_UNIVERSE_LIMIT=60`, `AUTO_START_PAPER=true`, and `LIVE_TRADING_ENABLED=false` / `AUTO_LIVE_TRADING_ENABLED=false`. This update does not alter deployed environment variables or enable real trading.
- Render auto-deploys web and worker from the `main` branch after merge. Monitor both deploys and `/health` after merge; verify the database contains up to 120 spot/futures snapshots for 60 unique pairs and candle diagnostics cover the discovered list.
- No API secrets are read or printed by this update.

## Test commands
```bash
python -m py_compile app/*.py tests_*.py
python tests_smoke.py
python tests_reconciliation.py
python tests_missing_admin_password.py
python tests_paper_scheduler.py
python tests_dynamic_market_scoring.py
python tests_scan_ui.py
python tests_coindcx_public_shapes.py
python tests_paper_scan_ui.py
```

Fixture tests use mock responses exclusively for deterministic testing; they do not claim live API verification or make real orders.
