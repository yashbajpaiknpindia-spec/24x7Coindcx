"""Historical OHLC fetch persistence and normalization tests."""
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name
os.environ["SECRET_KEY"] = "loss-review-test-secret"
os.environ["ADMIN_PASSWORD"] = "loss-review-test-password"

from app.db import Base, engine, SessionLocal, LossReviewCandle
from app.main import _historical_candle_row, _save_loss_review_candles

Base.metadata.create_all(bind=engine)

class FakeClient:
    def __init__(self):
        self.calls = 0
    def spot_candles(self, pair, interval, limit, start_time_ms, end_time_ms):
        self.calls += 1
        return [
            {"time": start_time_ms, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 5},
            {"time": end_time_ms, "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 7},
        ]
    def futures_candles(self, **kwargs):
        raise AssertionError("futures method should not be called by spot test")

def run():
    try:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        valid = _historical_candle_row(
            {"time": int(now.timestamp()*1000), "open": 100, "high": 103, "low": 98, "close": 101, "volume": 12},
            "spot", "B-BTC_USDT", "15m",
        )
        assert valid and valid["high_price"] == 103
        assert _historical_candle_row(
            {"time": int(now.timestamp()*1000), "open": 100, "high": 99, "low": 98, "close": 101},
            "spot", "B-BTC_USDT", "15m",
        ) is None

        with SessionLocal() as db:
            client = FakeClient()
            result = _save_loss_review_candles(
                db, client, "spot", "B-BTC_USDT",
                now, now + timedelta(minutes=30), max_calls=3,
            )
            db.commit()
            assert result["calls"] == 1, result
            assert result["inserted"] == 2, result
            assert db.query(LossReviewCandle).count() == 2
            again = _save_loss_review_candles(
                db, client, "spot", "B-BTC_USDT",
                now, now + timedelta(minutes=30), max_calls=3,
            )
            db.commit()
            assert again["inserted"] == 0, again
            assert db.query(LossReviewCandle).count() == 2
        print("LOSS REVIEW CANDLES PASSED: OHLC validation, historical request window, persistence and duplicate-safe refresh.")
    finally:
        try:
            Path(_tmp.name).unlink()
        except OSError:
            pass

if __name__ == "__main__":
    run()
