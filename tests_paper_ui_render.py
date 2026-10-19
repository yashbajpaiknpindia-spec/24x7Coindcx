"""Render smoke tests for pages whose failures only appear during Jinja rendering."""
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent
env = Environment(loader=FileSystemLoader(str(ROOT / "app" / "templates")), autoescape=True)

def ist(value, fmt="%d %b %Y %H:%M IST"):
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Kolkata")).strftime(fmt)

env.filters["ist"] = ist
base = {
    "request": object(), "page": "paper", "title": "Smoke test",
    "app_name": "CoinDCX Test", "summary": {"config": {"paper_enabled": True},
    "fresh_markets": 0, "market_count": 0}, "events": [],
    "live_trading_enabled": False, "auto_live_trading_enabled": False,
    "api_key_configured": False, "api_secret_configured": False,
    "admin_password_configured": True, "csrf_token": "",
    "now_utc": "2026-01-01 00:00 UTC", "now_ist": "01 Jan 2026 05:30:00 AM IST",
}
empty_audit = {
    "decisions": 0, "rejected": 0, "accepted": 0, "reasons": {},
    "1h": {"would_win": 0, "likely_correct": 0, "false_rejection_rate_pct": None},
    "4h": {"would_win": 0, "likely_correct": 0, "false_rejection_rate_pct": None},
    "24h": {"would_win": 0, "likely_correct": 0, "false_rejection_rate_pct": None},
}
cfg = {
    "paper_enabled": True, "research_notional_usdt": 1000,
    "starting_capital_inr": 30000, "capital_allocation_pct_per_position": 10,
    "paper_last_cycle": None, "scalper_enabled": True,
    "scalper_max_open_positions": 3, "scalper_notional_usdt": 100,
}
runtime = {
    "paper_candle_diagnostics": {"candle_ready_total": 0, "fetch_error_count": 0, "fetch_errors": []},
    "last_strategy_cycle": {"status": "ok", "selected_signals": 0, "eligible_signals": 0},
    "scan_universe_count": 0, "paper_cycle_status": "waiting",
}
equity = {"equity_inr": 30000, "starting_capital_inr": 30000,
          "realized_pnl_inr": 0, "unrealized_pnl_inr": 0}
paper_stats = {"closed": 0, "wins": 0, "losses": 0, "win_rate": None,
               "profit_factor": None, "net_pnl_inr": 0}
capital_stats = {"closed": 0, "wins": 0, "losses": 0, "win_rate": None,
                 "profit_factor": None, "net_pnl_inr": 0, "open": 0,
                 "reserved_margin_inr": 0, "capital_inr": 30000,
                 "available_margin_inr": 30000}
paper_context = {
    **base, "cfg": cfg, "runtime": runtime, "equity": equity,
    "positions": [], "trades": [], "paper_stats": paper_stats,
    "capital_positions": [], "capital_trades": [], "capital_stats": capital_stats,
    "observation_count": 0, "audit_stats": {"unrestricted": empty_audit,
    "capital_constrained": empty_audit}, "recent_audits": [],
}
ledger_context = {
    **base, "page": "ledger", "entries": [], "fills": [], "status_counts": {},
    "needs_review": 0, "runtime": {}, "paper_trades": [],
    "paper_positions": [], "capital_positions": [],
}
lane_stats = {
    "research": {"open": 0, "closed": 0, "wins": 0, "losses": 0, "net": 0,
                 "open_net": 0, "pf": None},
    "capital": {"open": 0, "closed": 0, "wins": 0, "losses": 0, "net": 0,
                "open_net": 0, "pf": None},
}
scalper_context = {
    **base, "page": "scalper", "cfg": cfg, "runtime": {}, "lane_stats": lane_stats,
    "candidates": [], "trades": [],
    "scalper_stats": {"open": 0, "closed": 0, "wins": 0, "losses": 0,
    "profit_factor": None, "net_after_tax": 0, "open_net": 0, "eligible": 0,
    "scanned": 0, "sample_target": 50, "pf_validated": False},
}
scalper_review_context = {
    **base, "page": "scalper_review", "cfg": cfg, "lane_stats": lane_stats,
    "model_stats": [
        {"label": "Legacy v0.1 · research", "closed": 0, "wins": 0, "losses": 0,
         "win_rate": None, "net": 0, "pf": None},
        {"label": "Model v0.2 · research", "closed": 0, "wins": 0, "losses": 0,
         "win_rate": None, "net": 0, "pf": None},
        {"label": "Model v0.2 · capital", "closed": 0, "wins": 0, "losses": 0,
         "win_rate": None, "net": 0, "pf": None},
    ],
    "loss_trades": [], "rejected": [],
    "review_meta": {"snapshots": 0, "candidates": 0, "episodes": 0, "sampled": 0,
                    "positive_rejected": 0, "positive_samples": 0,
                    "full_coverage_snapshots": 0, "legacy_truncated_snapshots": 0,
                    "relaxed_reversal_episodes": 0, "relaxed_reversal_target_first": 0,
                    "relaxed_reversal_stop_first": 0, "scan_start": None},
}
review_stats = {h: {"evaluated": 0, "held_better": 0, "exit_better": 0, "potential_recovery": 0, "avg_delta": None}
                for h in ("1h", "4h", "24h", "72h", "7d")}
loss_context = {**base, "page": "loss_review", "trades": [],
                "review_stats": review_stats, "fetch_info": {}, "fetch_message": "Not run", "candle_count": 0, "observation_start": None,
                "observation_end": None, "observation_count": 0, "tax_pct": 30, "spot_tax_pct": 31.2, "futures_tax_pct": 31.2,
                "runtime": {}}

for name, context in (
    ("paper.html", paper_context),
    ("ledger.html", ledger_context),
    ("scalper.html", scalper_context),
    ("scalper_review.html", scalper_review_context),
    ("loss_review.html", loss_context),
):
    template = env.get_template(name)
    rendered = template.render(**context)
    assert "<html" in rendered.lower() and "</html>" in rendered.lower(), name
    print(f"RENDERED {name}: {len(rendered)} bytes")

# This specifically prevents regression to a Python built-in call in a Jinja expression.
assert env.from_string("{{ (t.quantity * t.entry_price)|abs }}").render(
    t={"quantity": -2, "entry_price": 5}
) == "10"
now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
assert ist(now, "%H:%M") == "05:30", ist(now, "%H:%M")
print("PAPER UI RENDER REGRESSION PASSED: paper, ledger, scalper and loss-review templates render; IST and abs filter work.")
