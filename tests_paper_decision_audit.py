"""Regression checks for persisted paper-decision counterfactual outcomes."""
import os
import tempfile
from datetime import timedelta
from pathlib import Path

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name
os.environ["SECRET_KEY"] = "paper-audit-test-secret"
os.environ["ADMIN_PASSWORD"] = "paper-audit-test-password"

from app.db import Base, engine, SessionLocal, MarketObservation, PaperDecisionAudit, PaperModePosition, PaperPosition, utcnow
from app.core import evaluate_paper_decision_audits

Base.metadata.create_all(bind=engine)


def run():
    now = utcnow()
    with SessionLocal() as db:
        audit = PaperDecisionAudit(
            decision_at=now - timedelta(hours=5), product="futures", pair="B-TEST_USDT",
            proposed_side="buy", mode="unrestricted", decision="rejected",
            rejection_reason="cost gate", reference_price=100.0, entry_bid=99.9,
            entry_ask=100.1, expected_move_pct=0.4, estimated_cost_pct=0.2,
            score=1.2, momentum_24h_pct=0.3, momentum_72h_pct=0.5,
        )
        db.add_all([
            audit,
            MarketObservation(observed_at=now-timedelta(hours=4), product="futures",
                pair="B-TEST_USDT", last_price=101.0, bid=100.9, ask=101.1,
                turnover_usdt=100000, active=True),
            MarketObservation(observed_at=now-timedelta(hours=1), product="futures",
                pair="B-TEST_USDT", last_price=99.0, bid=98.9, ask=99.1,
                turnover_usdt=100000, active=True),
        ])
        db.commit()
        updated = evaluate_paper_decision_audits(db, {})
        db.commit()
        db.refresh(audit)
        assert audit.evaluated_1h is True, audit.evaluated_1h
        assert audit.evaluated_4h is True, audit.evaluated_4h
        assert audit.net_outcome_1h_pct is not None and audit.net_outcome_1h_pct > 0, audit.net_outcome_1h_pct
        assert audit.net_outcome_4h_pct is not None and audit.net_outcome_4h_pct < 0, audit.net_outcome_4h_pct
        assert audit.evaluated_24h is False
        assert updated == 2, updated
        # The two modes are distinct tables; a shared pair cannot collide across ledgers.
        assert PaperModePosition.__tablename__ != PaperPosition.__tablename__
        print("PAPER DECISION AUDIT PASSED: 1h/4h shadow outcomes, net costs, and separate ledgers.")


if __name__ == "__main__":
    try:
        run()
    finally:
        try:
            Path(_tmp.name).unlink()
        except OSError:
            pass
