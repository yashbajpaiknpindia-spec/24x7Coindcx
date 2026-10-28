"""Build-time isolated smoke tests for critical Binance Intel pages.

This script MUST use a temporary SQLite database; it intentionally fails if app/model
configuration points at any database other than the temporary local test DB.
It never calls Binance, Render, or a live/private endpoint.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force every known application DB env variable to a disposable local SQLite DB
# before importing the app or its SQLAlchemy models.
tmp = tempfile.TemporaryDirectory(prefix="bi-page-smoke-")
db_path = Path(tmp.name) / "page-smoke.sqlite3"
sqlite_url = "sqlite:///" + str(db_path)
for key in (
    "DATABASE_URL",
    "POSTGRES_URL",
    "POSTGRESQL_URL",
    "RENDER_DATABASE_URL",
    "SQLALCHEMY_DATABASE_URI",
    "APP_DATABASE_URL",
):
    os.environ[key] = sqlite_url
for key in (
    "DATABASE_BACKEND",
    "DB_BACKEND",
    "DB_TYPE",
):
    os.environ[key] = "sqlite"
for key in (
    "ENABLE_SCHEDULER",
    "SCHEDULER_ENABLED",
    "BINANCE_SCHEDULER_ENABLED",
    "ENABLE_BINANCE_SCHEDULER",
):
    os.environ[key] = "false"
os.environ.pop("BINANCE_API_KEY", None)
os.environ.pop("BINANCE_API_SECRET", None)
os.environ.setdefault("APP_PASSWORD", "isolated-page-smoke-password")

sys.path.insert(0, "/app")
from models import SessionLocal, Trader, Position, TraderSnapshot  # noqa: E402

engine = SessionLocal.kw.get("bind") if hasattr(SessionLocal, "kw") else None
if engine is None:
    with SessionLocal() as db:
        engine = db.get_bind()
if engine.dialect.name != "sqlite":
    raise RuntimeError(
        "SAFETY STOP: page smoke test resolved database dialect "
        + engine.dialect.name
        + " instead of the temporary local SQLite database"
    )
Trader.metadata.create_all(bind=engine)

# Importing the app happens only after the disposable SQLite env vars are set.
import app as app_module  # noqa: E402

flask_app = getattr(app_module, "app", None)
if flask_app is None:
    raise RuntimeError("Could not find Flask app instance in app module")

# Some apps create a fresh DB engine at import; re-assert the database boundary.
with SessionLocal() as db:
    if db.get_bind().dialect.name != "sqlite":
        raise RuntimeError("SAFETY STOP: SQLAlchemy switched away from local SQLite")

now = datetime.now(timezone.utc).replace(tzinfo=None)
now_ms = int(time.time() * 1000)
periods = {
    "7D": {"roi": 4.2, "mdd": 3.1},
    "30D": {"roi": 12.5, "mdd": 5.8},
    "90D": {"roi": 27.4, "mdd": 8.7},
    "365D": {"roi": 61.1, "mdd": 12.4},
}
trader = Trader(
    exchange="BINANCE",
    market_type="FUTURES",
    portfolio_id="LOCAL-SMOKE-PORTFOLIO",
    nickname="Local page smoke trader",
    profile_url="https://www.binance.com/en/copy-trading/futures/lead-details/LOCAL-SMOKE-PORTFOLIO",
    portfolio_status="ACTIVE",
    data_source="LOCAL_SMOKE_TEST",
    roi=12.5,
    metrics_period="30D",
    period_metrics=json.dumps(periods),
    pnl=1250.0,
    mdd=5.8,
    sharpe=1.2,
    win_rate=66.7,
    win_positions=10,
    total_positions=15,
    aum=10000.0,
    copier_pnl=25.0,
    copiers=100,
    total_copiers=100,
    min_copy_usd=10.0,
    start_time_ms=now_ms - 200 * 86400000,
    last_trade_ms=now_ms - 1000,
    first_seen=now - timedelta(days=200),
    last_seen=now,
    last_snapshot_at=now,
    history_synced_at=now,
    history_status="SYNCED",
    history_count=15,
    watchlisted=False,
    raw_json="{}",
)
with SessionLocal() as db:
    db.add(trader)
    db.commit()
    db.refresh(trader)
    trader_id = trader.id
    for i in range(15):
        closed = now_ms - (i * 86400000) - 5000
        opened = closed - 3600000
        # 11 winning days and 4 losing days: enough genuine local test outcomes
        # for the forecast bootstrap gate, without touching live or remote data.
        pnl = 3.0 if i % 4 else -1.0
        roi = 1.2 if i % 4 else -0.4
        db.add(
            Position(
                trader_id=trader_id,
                external_key=f"LOCAL-SMOKE-{i}",
                symbol="BTCUSDT" if i % 2 == 0 else "ETHUSDT",
                side="LONG" if i % 2 == 0 else "SHORT",
                leverage=3.0,
                margin_mode="CROSS",
                entry_price=100.0,
                exit_price=101.2 if pnl > 0 else 99.6,
                close_pnl=pnl,
                roi_pct=roi,
                size=100.0,
                opened_ms=opened,
                closed_ms=closed,
                source_kind="CLOSED_POSITION_HISTORY",
                path_status="ANALYZED",
                path_interval="1m",
                candles_covered=60,
                coverage_pct=100.0,
                mae_pct=0.3 if pnl > 0 else 0.7,
                mfe_pct=1.0 if pnl > 0 else 0.2,
                adverse_price=99.7,
                favorable_price=101.0,
                time_to_mae_min=5.0,
                time_to_mfe_min=20.0,
                max_peak_to_close_retrace_pct=0.2,
                went_adverse_first=(i % 2 == 0),
                raw_json="{}",
                added_at=now,
                path_analyzed_at=now,
            )
        )
    db.add(
        TraderSnapshot(
            trader_id=trader_id,
            captured_at=now,
            time_range="30D",
            roi=12.5,
            pnl=1250.0,
            mdd=5.8,
            win_rate=66.7,
            aum=10000.0,
            copier_pnl=25.0,
            raw_json="{}",
        )
    )
    db.commit()

def response_payload(result):
    status = 200
    if isinstance(result, tuple):
        result, status = result[0], result[1]
    response = flask_app.make_response(result)
    status = int(status or response.status_code)
    payload = response.get_json(silent=True)
    return status, payload, response.get_data(as_text=True)

def call_view(path: str, method: str = "GET", body=None):
    clean_path = path.split("?", 1)[0]
    adapter = flask_app.url_map.bind("localhost")
    endpoint, values = adapter.match(clean_path, method=method)
    with flask_app.test_request_context(
        path,
        method=method,
        json=body,
        headers={"Accept": "application/json"},
    ):
        return response_payload(flask_app.view_functions[endpoint](**values))

checks = []
def check(name, path, method="GET", body=None, status_wanted=200, predicate=None):
    status, payload, raw = call_view(path, method, body)
    if status != status_wanted:
        raise AssertionError(
            f"{name}: expected HTTP {status_wanted}, got {status}; "
            f"payload={(payload if payload is not None else raw[:500])}"
        )
    if predicate and not predicate(payload or {}):
        raise AssertionError(f"{name}: response assertion failed: {str(payload)[:900]}")
    checks.append((name, status, "PASS"))

check(
    "Portfolio Lab portfolio list",
    "/api/portfolio-lab/portfolios?market_type=FUTURES",
    predicate=lambda d: any(int(x.get("id", -1)) == trader_id for x in d.get("items", [])),
)
check(
    "Portfolio Lab historical forecast",
    "/api/portfolio-lab/forecast?market_type=FUTURES&investment=250&allocation_pct=10&extra_cost_bps=5&days=7",
    predicate=lambda d: "forecastable_count" in d and "insufficient_history_count" in d,
)
check(
    "Portfolio Lab portfolio detail",
    f"/api/portfolio-lab/portfolio/{trader_id}?offset=0&limit=50",
    predicate=lambda d: int(d.get("trade_total", 0)) >= 15 and bool(d.get("behavior")),
)
check(
    "Multi-Trader candidates",
    "/api/multi-trader/candidates?market_type=FUTURES&evaluation_period=30D&min_win_rate_pct=0&max_selected=5",
    predicate=lambda d: "candidates" in d and int(d.get("monitored_count", -1)) >= 1,
)
check(
    "Multi-Trader save evaluation",
    "/api/multi-trader/evaluate",
    method="POST",
    body={
        "market_type": "FUTURES",
        "min_closed_trades": 1,
        "min_profit_factor": 0.5,
        "max_mdd_pct": 20,
        "min_roi_7d": -5,
        "evaluation_period": "30D",
        "min_win_rate_pct": 0,
        "ranking_priority": "STABILITY",
        "max_selected": 5,
    },
    predicate=lambda d: "evaluation_id" in d and "candidates" in d,
)
check(
    "Multi-Trader evaluation history",
    "/api/multi-trader/history",
    predicate=lambda d: int(d.get("count", 0)) >= 1,
)
check(
    "Trade Behaviour ranking",
    "/api/trade-behaviour?market_type=FUTURES&period_days=30&min_win_rate_pct=0&sort_by=STABILITY&limit=250",
    predicate=lambda d: int(d.get("profile_count", 0)) >= 1 and int(d.get("verified_closed_trades", 0)) >= 15 and len(d.get("items", [])) >= 1,
)
check(
    "Profit & Tax Centre ledger summary",
    "/api/profit-tax/summary",
    predicate=lambda d: "summary" in d and "has_personal_records" in d,
)
check(
    "Strategy Tax Watch uses same summary",
    "/api/profit-tax/summary",
    predicate=lambda d: isinstance(d.get("by_strategy", []), list),
)
check(
    "Personal account sync status diagnostics",
    "/api/profit-tax/sync-status",
    predicate=lambda d: "status" in d and "api_key_configured" in d and "credentials_validated_by_binance" in d,
)
check(
    "Server-managed tax sync refuses missing env safely",
    "/api/profit-tax/sync",
    method="POST",
    body={"lookback_days": 30},
    status_wanted=503,
    predicate=lambda d: d.get("credentials_saved") is False,
)

html_path = Path("/app/templates/index.html")
js_path = Path("/app/static/app.js")
html = html_path.read_text()
js = js_path.read_text()
for view in ("portfolio-lab", "multi-trader", "profit-tax", "strategy-watch", "history"):
    if f'id="view-{view}"' not in html:
        raise AssertionError(f"UI smoke failed: missing view section {view}")
    if f'data-view="{view}"' not in html:
        raise AssertionError(f"UI smoke failed: missing navigation link {view}")
if 'id="pt-api-key"' in html or 'id="pt-api-secret"' in html:
    raise AssertionError("UI smoke failed: manual API credential inputs remain")
if "pt-env-status" not in html or "Configured on the server" not in js:
    raise AssertionError("UI smoke failed: server-managed credential status is missing")
if "personal Futures sync" not in js or "Spot per-symbol fills" not in html:
    raise AssertionError("UI smoke failed: personal account sync status/scope diagnostics are missing")
if 'await itLoadProfitTax(true);' in html or 'function(){return itLoadProfitTax(true)}' in html:
    raise AssertionError("UI smoke failed: page navigation can trigger a duplicate signed account sync")
if '"profit-tax":"Profit & Tax Centre"' not in html or '"strategy-watch":"Strategy Tax Watch"' not in html:
    raise AssertionError("UI smoke failed: tax pages missing from navigation failsafe")
for function_name in ("loadPortfolioLab", "loadMultiTrader", "loadTradeBehaviour", "itLoadProfitTax", "itCheckEnvCredentials"):
    if f"function {function_name}" not in js:
        raise AssertionError(f"UI smoke failed: missing JavaScript loader {function_name}")
checks.append(("Static UI navigation and no secret-entry controls", 0, "PASS"))

print("LOCAL SQLITE ISOLATION: PASS (" + engine.dialect.name + ")")
for name, status, state in checks:
    print(f"{state} [{status}] {name}")
print(f"PAGE SMOKE TESTS PASSED: {len(checks)}/{len(checks)}")
tmp.cleanup()
