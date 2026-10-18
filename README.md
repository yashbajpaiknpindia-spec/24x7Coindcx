# CoinDCX Strategy Terminal (v1.4.4)

## Reported ticker-volume correction (v1.4.4)

- The live API emitted BTC spot 24h `volume` around 721 million with a last price around 81,000. Multiplying these values generated a fictitious turnover around 58 trillion. The scanner now preserves the exchange-reported 24h volume value for the USDT-quoted spot/futures ticker as its turnover proxy; it does not multiply ticker volume by last price again.
- The universe is ranked by the reported 24h volume on the USDT pair, not by volume × price and not by market capitalization. This is still a screening proxy; always check order-book spread/depth and current freshness before treating a pair as executable.
- Candle-derived strategy turnover is distinct: hourly candle volumes represent traded quantity and are still multiplied by candle close for the historical turnover proxy.
- The liquidity gate compares the ticker-reported proxy against the configured threshold. CoinDCX field semantics can change; the UI calls this a proxy rather than a guaranteed fill or verified profitability metric.

## Live scan / response parsing / UI fix (v1.4.3)

- The exchange-discovered market universe is ranked by reported 24h ticker volume and capped at 60 unique USDT pairs by default (configurable up to 150). It is not a market-cap ranking; liquidity and turnover are screening proxies.
- Spot ticker symbols are normalized from the concatenated CoinDCX format (for example, `BTCUSDT`) to the canonical app pair (for example, `B-BTC_USDT`) using market-details metadata where available.
- Futures current prices now unwrap the documented `prices` map, and futures candles unwrap the `{s, data}` response.
- Candle scoring uses the same discovered, capped universe that the scan UI displays. It refreshes opportunities every 15 minutes while portfolio rebalancing remains daily.
- The Paper Trading page shows scanned product/pair rows, price / turnover proxy / spread, candle readiness, score / momentum, strategy signal and reason, liquidity gate, and paper position/trade state. It also shows counts and explicit worker/API/stale-data errors.
- The market list is based on exchange data; it does not invent mock market prices. Futures liquidation remains a simplified estimate, not an exchange-verified historical liquidation event.
- Live orders remain disabled by default. The scan and paper-trading page do not submit live orders.

## Paper scheduler and scanner fix (v1.4.1)

- Paper Start writes a unique immediate-cycle request; the worker executes it even if a daily rebalance already occurred today.
- Skipped daily cycles persist a diagnostic and retry on a 15-minute cooldown rather than every worker minute.
- The strategy now fetches hourly candles for the live exchange-discovered USDT universe plus the original seed pairs, and stores candle-ready counts and fetch errors.
- Paper Trading UI polls worker, refresh, candle coverage, and cycle state every 10 seconds. If the worker heartbeat is stale, queued cycles will remain queued until the worker is running.

## Render startup password fix (v1.3.1)

- Startup no longer crashes if `ADMIN_PASSWORD` is absent or weak. `/health` stays available, while the login page remains locked until a strong password is configured.
- The Blueprint now declares `ADMIN_PASSWORD` with `generateValue: true` for a new/synced Blueprint deployment. After applying the Blueprint, open the web service's Render Environment page, locate the generated value and save it in your password manager. If the existing service does not populate it during Blueprint sync, set a private value of at least 14 characters manually and redeploy.
- `SECRET_KEY` remains generated separately. Keep `COOKIE_SECURE=true` for the public HTTPS service.
- Check `/health` for `admin_auth_configured: true` after deployment. Never share or commit the generated admin password.

A Render-ready research and trading operations dashboard for the user's CoinDCX hourly cross-sectional momentum strategy over a dynamic USDT-market discovery universe. The application includes a persistent PostgreSQL ledger, a background market/paper worker, historical backtest snapshots, a paper-trading engine, an exchange market screener, current order-book/trade views, an account snapshot, an audit journal, exports, and a separately gated manual live-order ticket.

## Current status and important limitations

- **Paper trading:** the app's hourly CSM strategy can run automatically when enabled in Paper Trading. The worker refreshes current public market data, marks positions, consumes immediate paper-cycle requests, and normally rebalances once per UTC day; a new Start request can trigger an extra immediate cycle.
- **Live mode:** the UI supports manually submitted, explicitly confirmed spot/futures orders. It is disabled by default with `LIVE_TRADING_ENABLED=false`, requires API credentials in Render environment variables, a successful account check, an explicit `ARM LIVE TRADING` phrase, and a second `SUBMIT LIVE ORDER` phrase on each order. App-level caps default to $25 USDT per order, 2x maximum futures leverage, and $100 USDT rolling 24-hour order notional. A web-service restart disarms live mode.
- **Automated live strategy trading is implemented behind explicit deployment gates and typed UI arming, but is disabled by default.** The worker only runs a daily UTC rebalance when both `LIVE_TRADING_ENABLED=true` and `AUTO_LIVE_TRADING_ENABLED=true` are set for both web and worker, credentials are present, reconciliation is clean, and an administrator arms it in the UI. Worker/web restarts disarm it. This is not a guarantee of profitability.
- Reconciliation imports spot account trade history, app-order-linked futures trade history, and futures transaction rows with exchange-reported P&L/fees/funding where returned. Entries are idempotent and unknown orders block automation. The account-wide futures trade sync uses a configurable rolling lookback (default 3 days), not a lifetime archive. API pagination ceilings, incomplete order history, and field/venue limitations are surfaced as warnings. This cannot guarantee complete accounting of external orders; verify discrepancies against CoinDCX before trading.
- The liquid-market gate fails closed when the app lacks a fresh snapshot, best bid/ask, turnover proxy, active status, or acceptable spread. The ticker-reported 24h volume is used directly as a turnover proxy for the USDT pair, without multiplying by last price again. It is not a verified guarantee of fillability or complete order-book depth. Do not assume it guarantees fillability.
- Paper-trading P&L and fees/slippage/funding are modelled estimates, not actual account results. Stress funding is hypothetical. Paper futures liquidation/maintenance-margin simulation is not exchange-exact.
- Seeded backtest rows are snapshots of previous results supplied during research. They are not recomputed by this application, cannot be merged across differing strategy versions, and aren't a genuine blind test. The newest run's 3x return (+828.85%) differed from a previous variant (+451.72%); both are labelled as separate snapshots.
- API names/fields can change; test on a separate API key with the minimum required permissions first. Never put API secrets into source files, Colab output, chat, the database, or Git.

## Strategy identifier

`CSM14D_VOL14D_LIQ7D_DAILY` — up to 60 dynamically discovered USDT candidates by default (configurable up to 150; seed pairs are fallback only); 14-day price momentum divided by 14-day hourly return volatility; prior 7-day close-times-volume turnover proxy used for the top-eight liquidity shortlist; once-per-UTC-day rebalance. Futures select up to three long leaders and three short laggards. Cash spot is long-only and selects up to three positive-score leaders. This is a practical app-side reproduction of the current research description, not proof it matches every historical notebook implementation. Historical variant discrepancies must be reconciled before treating results as reproducible.

## UI pages

- **Overview:** summary cards, market freshness, open paper positions and recent trades/events.
- **Markets & liquidity:** spot/futures market snapshots, eligibility reasons, order-book snapshots, recent trade tape and refresh action.
- **Strategy lab:** product selection, research leverage choices, cost case, capital and liquidity gates.
- **Paper trading:** start/pause, manual cycle, simulated positions, trade ledger and CSV export.
- **Live execution:** manual, gated live order ticket, typed confirmations, current order request log and per-order/rolling notional caps.
- **Positions:** paper positions plus current external futures positions and spot balances when API credentials are present.
- **Orders & fills:** app-recorded orders and trade history.
- **Analytics:** paper-trade P&L, win rate, profit factor and cumulative equity chart.
- **Backtest archive:** seeded historical snapshots, CSV/JSON imports and cost/product filters.
- **Audit journal:** action, worker, data, integration and error events.
- **Connections & settings:** database/credential readiness, worker heartbeat, market refresh and last cycle status.

## Local setup

Python 3.12 is recommended.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and replace local passwords/secrets. Keep live trading disabled. Example development settings:

```dotenv
SECRET_KEY=<use-a-long-random-secret>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<use-a-long-random-password>
DATABASE_URL=sqlite:///./coindcx_terminal.db
COOKIE_SECURE=false
LIVE_TRADING_ENABLED=false
AUTO_LIVE_TRADING_ENABLED=false
```

Run the web UI:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Sign in with the configured admin credentials. `/health` reports web/database reachability; `/api/docs` is an authenticated API helper only for endpoints that require session auth.

Run the paper market worker in a second terminal:

```bash
python -m app.worker
```

Do not launch multiple workers against the same database unless you've designed for leader election: market snapshots and rebalance cycles should have one scheduler.

## Render deployment

The included `render.yaml` Blueprint provisions a web service, a separate always-running worker, and PostgreSQL. The selected `starter` compute plans and `basic-256mb` database may incur charges; review Render's current dashboard pricing and plans before applying. Both services should be in the same region as the database.

1. Create an empty GitHub repository and upload/push this folder, including `render.yaml`.
2. Open Render and create a new Blueprint from that repository.
3. Review all resources and current prices before applying.
4. Enter a strong `ADMIN_PASSWORD` (14+ characters). Keep `LIVE_TRADING_ENABLED=false`, `AUTO_LIVE_TRADING_ENABLED=false`.
5. Deploy and check `/health`, then confirm the Settings page sees the worker heartbeat.
6. Optionally add `COINDCX_API_KEY` and `COINDCX_API_SECRET` as Render secret environment variables for authenticated account snapshots. Start with read-only permissions if possible.
7. Keep live trading locked until market mapping, precision, order semantics, fill polling/reconciliation and paper behavior are independently verified. Never use a key with withdrawal permissions. For auto-live, both environment flags must be true on web and worker and the UI phrase must be explicitly confirmed; a restart disarms automation.

The Render Blueprint requires the repo to be pushed first; a zip file itself is not a direct Blueprint deployment source. There is no deployment action or account credential baked into this package.

## Environment variables

See `.env.example`. Live safety defaults are deliberately restrictive. `LIVE_MAX_ORDER_NOTIONAL_USDT`, `LIVE_MAX_LEVERAGE`, and `LIVE_MAX_GROSS_EXPOSURE_USDT` apply to manual live tickets. These are app-side checks only and cannot replace exchange limits or account-level risk management.

## Tests and verification

Version 1.4.1 fixes immediate paper scheduling, dynamic market candle scoring, and live runtime diagnostics. Version 1.3.1 added account-wide rolling futures fill sync and tighter live-order status normalization. Run `python -m py_compile app/*.py tests_*.py`, then `python tests_smoke.py`, `python tests_reconciliation.py`, `python tests_missing_admin_password.py`, `python tests_paper_scheduler.py`, and `python tests_dynamic_market_scoring.py`. The package passes these offline checks using SQLite. Smoke tests do not prove API endpoints will be available or that any order can be filled. Live trading is never tested with real order submission as part of a smoke test.


## Existing Render service deployment checklist

- Push the updated `coindcx_strategy_terminal` folder, including `render.yaml`, to the repository connected to the Render Blueprint; then sync/apply the Blueprint. If your Render services were created manually, set environment variables in each service explicitly instead.
- Web **and worker** must point to the same Postgres database and have the CoinDCX API secret group attached. To use automatic live execution, `LIVE_TRADING_ENABLED=true` and `AUTO_LIVE_TRADING_ENABLED=true` must be present on both services. In this package these values remain `false` by default.
- Keep live execution off until a least-privilege API key, market mapping, actual fill reconciliation, fees, funding, balance checks and margin/liquidation behaviour have been verified. Once purposely enabled, the worker makes strategy decisions on its configured daily cycle; live orders can be rejected, partially filled, or ambiguous and must reconcile before new risk is allowed. The app is not a profitability guarantee.
- The ledger records exchange-sourced fills, fee currency, futures transactions/P&L/funding where returned, order status and reconciliation warnings. CoinDCX API history limits and missing/external activity can still leave gaps; review the audit/ledger pages and exchange account before relying on reports.
