"""Paper-only scalper regression coverage: candidate gates, quote-side execution, costs, and exits."""
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name
os.environ["SECRET_KEY"] = "scalper-test-secret"
os.environ["ADMIN_PASSWORD"] = "scalper-regression-test-password"

from app.db import Base, engine, SessionLocal, ConfigKV, MarketSnapshot, MarketObservation, ScalpTrade, ScalpScanSnapshot, utcnow
from app.core import build_scalper_scan, run_scalper_cycle, _scalp_calculate

Base.metadata.create_all(bind=engine)

CFG = {
    "inr_per_usdt": 94.75,
    "scalper_enabled": True,
    "scalper_notional_usdt": 100,
    "scalper_max_open_positions": 3,
    "scalper_min_turnover_usdt": 1_000_000,
    "scalper_max_spread_bps": 5,
    "scalper_min_cost_multiple": 1.5,
    "scalper_min_signal_move_pct": 0.05,
    "scalper_spot_tax_pct": 31.2,
    "scalper_futures_tax_pct": 31.2,
    "scalper_research_enabled": True,
    "scalper_capital_enabled": False,
    "scalper_target_net_pct": 0.10,
    "scalper_stop_net_pct": 0.40,
    "scalper_max_hold_minutes": 15,
    "scalper_pair_cooldown_minutes": 5,
    "scalper_research_notional_usdt": 100,
    "scalper_research_max_open_positions": 3,
    "scalper_capital_notional_usdt": 30,
    "scalper_capital_max_open_positions": 3,
    "scalper_spot_fee_pct": 0.15,
    "scalper_futures_fee_pct": 0.075,
    "scalper_fee_gst_pct": 18.0,
    "scalper_normal_slippage_pct": 0.05,
    "scalper_stress_slippage_pct": 0.12,
    "scalper_tds_pct": 1,
    "futures_fee_pct": 0.075,
    "spot_fee_pct": 0.15,
    "scalper_cost_case": "NORMAL",
    "normal_slippage_pct": 0.05,
    "stress_slippage_pct": 0.12,
    "paper_cost_case": "NORMAL",
    "funding_stress_pct_per_8h": 0.01,
}

def run():
    try:
        with SessionLocal() as db:
            now = utcnow()
            db.add(ConfigKV(key="strategy_config", value=json.dumps(CFG)))
            snap = MarketSnapshot(
                product="futures", pair="B-BTC_USDT", last_price=100.75,
                bid=100.74, ask=100.76, quote_turnover_usdt=50_000_000,
                liquidity_source="test", active=True, exit_only=False,
                updated_at=now, raw_json=json.dumps({"futures_orderbook":{"bids":{"100.74":"10","100.73":"9"},"asks":{"100.76":"5","100.77":"5"}}}),
            )
            db.add(snap)
            for observed_at, price in (
                (now - timedelta(minutes=10), 100.0),
                (now - timedelta(minutes=5), 100.48),
                (now - timedelta(seconds=10), 101.00),
            ):
                db.add(MarketObservation(
                    observed_at=observed_at, product="futures", pair="B-BTC_USDT",
                    last_price=price, bid=price - 0.01, ask=price + 0.01,
                    active=True, source_updated_at=observed_at,
                ))
            db.add(MarketSnapshot(
                product="futures", pair="B-REV_USDT", last_price=100.20,
                bid=100.18, ask=100.22, quote_turnover_usdt=50_000_000,
                liquidity_source="test", active=True, exit_only=False,
                updated_at=now, raw_json=json.dumps({"futures_orderbook":{"bids":{"100.18":"10"},"asks":{"100.22":"10"}}}),
            ))
            for observed_at, price in (
                (now - timedelta(minutes=10), 100.0),
                (now - timedelta(minutes=5), 100.50),
                (now - timedelta(seconds=10), 100.20),
            ):
                db.add(MarketObservation(
                    observed_at=observed_at, product="futures", pair="B-REV_USDT",
                    last_price=price, bid=price - 0.01, ask=price + 0.01,
                    active=True, source_updated_at=observed_at,
                ))
            # This spot setup has enough momentum, liquidity and depth to pass
            # signal gates, but its round-trip fee + GST + slippage + spread
            # exceeds the configured 0.40% net-stop budget.
            db.add(MarketSnapshot(
                product="spot", pair="B-ETH_USDT", last_price=102.01,
                bid=102.00, ask=102.02, quote_turnover_usdt=50_000_000,
                liquidity_source="test", active=True, exit_only=False,
                updated_at=now, raw_json=json.dumps({"spot_orderbook":{
                    "bids":{"102.00":"20","101.99":"20"},
                    "asks":{"102.02":"20","102.03":"20"}}}),
            ))
            for observed_at, price in (
                (now - timedelta(minutes=10), 100.0),
                (now - timedelta(minutes=5), 101.0),
                (now - timedelta(seconds=10), 102.01),
            ):
                db.add(MarketObservation(
                    observed_at=observed_at, product="spot", pair="B-ETH_USDT",
                    last_price=price, bid=price-0.01, ask=price+0.01,
                    active=True, source_updated_at=observed_at,
                ))
            db.commit()
    
            candidates = build_scalper_scan(db, CFG, now)
            candidate = next(x for x in candidates if x["pair"] == "B-BTC_USDT")
            assert candidate["eligible"], candidate
            assert candidate["side"] == "buy", candidate
            assert candidate["cost_hurdle_pct"] > 0, candidate
            assert candidate["required_move_pct"] > candidate["cost_hurdle_pct"], candidate
            assert candidate["expected_continuation_pct"] > 0, candidate
            assert candidate["return_previous_5m_pct"] > 0, candidate
            reversal = next(x for x in candidates if x["pair"] == "B-REV_USDT")
            assert not reversal["eligible"] and "Reversal" in reversal["reason"], reversal
            spot_cost_block = next(x for x in candidates if x["pair"] == "B-ETH_USDT")
            assert not spot_cost_block["eligible"], spot_cost_block
            assert "round-trip cost hurdle" in spot_cost_block["reason"].lower(), spot_cost_block
            assert spot_cost_block["cost_hurdle_pct"] >= CFG["scalper_stop_net_pct"], spot_cost_block
            assert candidate["bid_depth_10_usdt"] is not None and candidate["ask_depth_10_usdt"] is not None, candidate
            opened = run_scalper_cycle(db, now)
            assert opened["opened"] == 1, opened
            # New bounded audit snapshots must retain the full candidate list and
            # scan-time settings, not only a top-25 subset of rejected signals.
            scan_rows = db.scalars(__import__("sqlalchemy").select(ScalpScanSnapshot)).all()
            assert len(scan_rows) >= 2, scan_rows
            for scan_row in scan_rows:
                saved_candidates = json.loads(scan_row.candidates_json or "[]")
                assert saved_candidates, scan_row.mode
                assert all(c.get("_audit_coverage") == "full-universe-v1" for c in saved_candidates), scan_row.mode
                assert all("_audit_settings" in c for c in saved_candidates), scan_row.mode
            trade = db.scalar(__import__("sqlalchemy").select(ScalpTrade).where(ScalpTrade.status == "open"))
            assert trade is not None
            assert trade.entry_price >= snap.ask - 1e-9, (trade.entry_price, snap.ask)
    
            # Move executable bid up by >1%; paper position should close at bid,
            # with positive fees/slippage/tax reserve and target-based exit reason.
            snap.last_price = 101.80
            snap.bid = 101.79
            snap.ask = 101.81
            snap.updated_at = now + timedelta(seconds=20)
            db.commit()
            closed = run_scalper_cycle(db, now + timedelta(seconds=20))
            db.refresh(trade)
            assert closed["closed"] == 1, closed
            assert trade.status == "closed"
            assert trade.exit_price == snap.bid, (trade.exit_price, snap.bid)
            assert trade.fees_inr > 0 and trade.slippage_inr > 0 and trade.tax_reserve_inr > 0
            assert trade.net_after_tax_inr > 0
            assert "take profit" in trade.exit_reason.lower(), trade.exit_reason
            assert trade.tds_estimate_inr == 0, "Futures must not show spot transfer TDS"
            assert closed["opened"] == 0, "The same pair must not re-open immediately after a close"

            # Track identity and mode isolation: enable capital paper lane only;
            # the previously closed research lane trade must not count as its cooldown.
            cfg_capital = dict(CFG)
            cfg_capital["scalper_research_enabled"] = False
            cfg_capital["scalper_capital_enabled"] = True
            db.get(ConfigKV, "strategy_config").value = json.dumps(cfg_capital)
            db.commit()
            capital_cycle = run_scalper_cycle(db, now + timedelta(seconds=25))
            capital_trades = db.scalars(__import__("sqlalchemy").select(ScalpTrade).where(ScalpTrade.status == "open")).all()
            assert any(json.loads(t.metadata_json or "{}").get("mode") == "capital" for t in capital_trades), capital_cycle
            assert capital_cycle["lanes"]["capital"]["opened"] == 1, capital_cycle
    
            # Verify taxable assumptions are product-aware and TDS stays display-only.
            spot = type("TradeLike", (), {
                "side": "buy", "quantity": 1.0, "entry_price": 100.0,
                "product": "spot",
            })()
            mark = _scalp_calculate(spot, 101.0, CFG, 94.75)
            assert mark["tax"] > 0 and mark["tds"] > 0, mark
            assert abs(mark["fees"] - (201 * 0.0015 * 1.18 * 94.75)) < 1e-6, mark
            assert abs(mark["slippage"] - (201 * 0.0005 * 94.75)) < 1e-6, mark
            assert mark["net_after_tax"] == mark["gross"] - mark["fees"] - mark["slippage"] - mark["tax"], mark
            futures = type("TradeLike", (), {
                "side": "buy", "quantity": 1.0, "entry_price": 100.0,
                "product": "futures",
            })()
            futures_mark = _scalp_calculate(futures, 101.0, CFG, 94.75)
            assert futures_mark["tax"] > 0 and futures_mark["tds"] == 0, futures_mark
            print("SCALPER REGRESSION PASSED: net-target gate, book depth, dual-track isolation, bid/ask execution, fee GST, fees/slippage, tax reserve, target exit and no futures TDS.")
    finally:
        try:
            Path(_tmp.name).unlink()
        except OSError:
            pass

if __name__ == "__main__":
    run()
