# v1.4.1 paper execution and UI hotfix

## Root cause addressed

- Previously, pressing Start only set `paper_enabled`; it did not request a cycle. The worker also refused to run a second cycle once `paper_last_cycle` was already dated today, so Start could appear to do nothing until the next UTC day.
- If the candle fetch was empty, the daily guard stayed open and the worker could repeat a costly strategy fetch on every polling loop without useful diagnostics.
- The discovery step populated live market snapshots beyond the seed watchlist, but the strategy candle scorer still fetched candles from only the configured legacy seed pairs.

## Changes

- Paper Start now persists a unique immediate-cycle request which overrides the daily cycle guard.
- The worker consumes each request once and applies a configurable retry cooldown (default 15 minutes) to skipped cycles.
- Strategy scoring uses the dynamically discovered market list plus the legacy seed watchlist. Actual candle-ready counts and fetch errors are persisted; no mock prices are added.
- Added authenticated `/api/paper-status` diagnostics and a Paper Trading panel that polls scan count, fresh snapshots, candle coverage, worker heartbeat, refresh errors, and cycle status every 10 seconds.
- Updated Strategy Lab, Overview, login version labels, and Blueprint environment variables to reflect the dynamic universe and scheduler.
- Fixed the open-position table headers to match the liquidation estimate cells.

## Verification

Passed compilation and offline tests: web/UI smoke and paper request persistence, missing-password startup, futures reconciliation idempotency, scheduler trigger/backoff logic, and dynamic candle-scoring universe. These tests do not prove the external CoinDCX API will return sufficient candle history or that a deployment has a running worker/database.
