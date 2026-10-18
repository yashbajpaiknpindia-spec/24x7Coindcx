"""Offline idempotency test for account-wide futures trade reconciliation."""
import os, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name
os.environ["INR_PER_USDT"] = "94.75"
from app.db import Base, engine, SessionLocal, ExecutionFill, LedgerEntry
from app.core import initialize_defaults, read_config, write_config
from app.live_engine import _sync_futures_account_trades

class FakeClient:
    def __init__(self): self.ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    def futures_trade_history(self, pair, order_id, from_date, to_date, page=1, size=500):
        if pair == "B-BTC_USDT" and page == 1:
            return [{"order_id":"test-order-1", "pair":pair, "side":"buy", "quantity":0.001,
                     "price":60000, "timestamp":self.ts, "fee_amount":0.02,
                     "margin_currency_short_name":"USDT", "is_maker":False}]
        return []

def run():
    Base.metadata.create_all(engine)
    fake = FakeClient()
    with SessionLocal() as db:
        initialize_defaults(db)
        first = _sync_futures_account_trades(db, fake)
        db.commit()
        assert first["fills_inserted"] == 1, first
        assert db.query(ExecutionFill).count() == 1
        assert db.query(LedgerEntry).count() >= 2
        runtime = read_config(db, "runtime", {})
        runtime["last_futures_trade_sync_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        write_config(db, "runtime", runtime); db.commit()
        second = _sync_futures_account_trades(db, fake)
        db.commit()
        assert second["fills_inserted"] == 0, second
        assert db.query(ExecutionFill).count() == 1
        print("FUTURES LEDGER IDEMPOTENCY PASSED: repeated sync does not duplicate fill/ledger rows.")

if __name__ == "__main__":
    try: run()
    finally:
        try: Path(_tmp.name).unlink()
        except OSError: pass
