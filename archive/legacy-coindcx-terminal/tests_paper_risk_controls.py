"""Regression tests for paper-trade risk exits and cost hurdle."""
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name
os.environ["SECRET_KEY"] = "risk-controls-test-secret"
os.environ["ADMIN_PASSWORD"] = "risk-controls-test-password"

from app.db import Base, engine, SessionLocal, ConfigKV, MarketSnapshot, PaperPosition, Trade, utcnow
from app.core import mark_paper_positions, _entry_cost_hurdle_pct

Base.metadata.create_all(bind=engine)


def _position(db, pair, price, side="buy", opened_minutes=10):
    now = utcnow()
    trade = Trade(
        run_mode="paper", product="futures", pair=pair, side=side,
        quantity=10, entry_price=100, leverage=1, gross_pnl_inr=0,
        fees_inr=0, slippage_inr=0, funding_inr=0, net_pnl_inr=0,
        status="open", strategy="test", reason="test entry", metadata_json="{}",
        created_at=now - timedelta(minutes=opened_minutes),
    )
    db.add(trade)
    db.flush()
    pos = PaperPosition(
        product="futures", pair=pair, side=side, quantity=10, entry_price=100,
        notional_usdt=1000, leverage=1, opened_at=now - timedelta(minutes=opened_minutes),
        strategy="test", trade_id=trade.id, last_mark_price=100,
        last_unrealized_pnl_inr=0, is_open=True,
    )
    db.add(pos)
    snap = MarketSnapshot(
        product="futures", pair=pair, last_price=price,
        bid=price - 0.01, ask=price + 0.01, quote_turnover_usdt=1000000,
        liquidity_source="test", active=True, exit_only=False,
        updated_at=now, raw_json="{}",
    )
    db.add_all([pos, snap])
    db.flush()
    return trade, pos, snap


def run():
    with SessionLocal() as db:
        # A move beyond the hard stop must close immediately, on the executable bid for a long.
        trade, pos, snap = _position(db, "B-STOP_USDT", 99.20)
        db.commit()
        result = mark_paper_positions(db)
        db.refresh(trade)
        db.refresh(pos)
        assert result["protective_exits"] == 1, result
        assert trade.status == "closed", trade.status
        assert "hard stop" in trade.reason, trade.reason
        assert pos.is_open is False

        # Three consecutive fresh observations at -0.35% trigger an earlier loss exit.
        trade2, pos2, snap2 = _position(db, "B-PERSIST_USDT", 99.60)
        db.commit()
        for _ in range(3):
            snap2.updated_at = utcnow()
            db.commit()
            mark_paper_positions(db)
        db.refresh(trade2)
        db.refresh(pos2)
        assert trade2.status == "closed", trade2.status
        assert "persistent loss" in trade2.reason, trade2.reason
        assert pos2.is_open is False

    snap = SimpleNamespace(bid=99.90, ask=100.10)
    hurdle = _entry_cost_hurdle_pct(
        "futures",
        {"futures_fee_pct": 0.075, "normal_slippage_pct": 0.05, "paper_cost_case": "NORMAL"},
        snap,
    )
    assert abs(hurdle - 0.45) < 1e-6, hurdle
    print("PAPER RISK REGRESSION PASSED: hard stop, persistent-loss exit, and round-trip cost hurdle.")


if __name__ == "__main__":
    try:
        run()
    finally:
        try:
            Path(_tmp.name).unlink()
        except OSError:
            pass
