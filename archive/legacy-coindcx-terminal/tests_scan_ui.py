"""Offline regression for dynamic CoinDCX spot discovery and 60-pair scan cap."""
import os, tempfile
from pathlib import Path

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name

from app.db import Base, engine, SessionLocal, MarketSnapshot
import app.core as core

class FixtureCoinDCX:
    def __init__(self):
        self.pairs = [f"B-COIN{i:03d}_USDT" for i in range(80)]
    def spot_tickers(self):
        return [
            {"market": p.removeprefix("B-").replace("_", ""),
             "last_price": str(i+1), "volume": str(1_000_000-i)}
            for i, p in enumerate(self.pairs)
        ]
    def spot_market_details(self):
        return [
            {"coindcx_name": p.removeprefix("B-").replace("_", ""),
             "target_currency_short_name": p[2:].split("_")[0],
             "base_currency_short_name": "USDT", "status": "active"}
            for p in self.pairs
        ]
    def futures_prices(self):
        return [{"mkt": p, "ls": str(i+1), "v": str(1_000_000-i)}
                for i, p in enumerate(self.pairs)]
    def futures_active_instruments(self, margin="USDT"):
        return list(self.pairs)
    def spot_orderbook(self, pair, depth=20):
        return {"bids": {"0.9999": "1000"}, "asks": {"1.0001": "1000"}}
    def futures_orderbook(self, pair, depth=20):
        return {"bids": {"0.9999": "1000"}, "asks": {"1.0001": "1000"}}

def run():
    Base.metadata.create_all(engine)
    old_client = core.CoinDCXClient
    old_limit = os.environ.get("SCAN_UNIVERSE_LIMIT")
    os.environ["SCAN_UNIVERSE_LIMIT"] = "60"
    core.CoinDCXClient = FixtureCoinDCX
    try:
        with SessionLocal() as db:
            core.initialize_defaults(db)
            result = core.refresh_markets(db)
            runtime = core.read_config(db, "runtime", {})
            pairs = runtime["scan_universe_pairs"]
            assert result["updated"] == 120, result
            assert len(pairs) == 60, len(pairs)
            assert pairs[0] == "B-COIN000_USDT", pairs[:3]
            assert len(set(pairs)) == 60
            rows = db.query(MarketSnapshot).all()
            assert len(rows) == 120, len(rows)
            assert sum(1 for x in rows if x.product == "spot" and x.last_price is not None) == 60
            assert sum(1 for x in rows if x.product == "futures" and x.last_price is not None) == 60
            spot_by_pair = {x.pair: x for x in rows if x.product == "spot"}
            fut_by_pair = {x.pair: x for x in rows if x.product == "futures"}
            # The higher price on COIN059 must not overpower its lower reported
            # 24h ticker volume; no second multiplication by last price is valid.
            assert spot_by_pair["B-COIN059_USDT"].last_price == 60
            assert spot_by_pair["B-COIN059_USDT"].quote_turnover_usdt == 999_941
            assert fut_by_pair["B-COIN059_USDT"].last_price == 60
            assert fut_by_pair["B-COIN059_USDT"].quote_turnover_usdt == 999_941
            print("PASS: concatenated symbols normalize, the 60-market cap persists, and ticker volume remains unmultiplied by last price.")
    finally:
        core.CoinDCXClient = old_client
        if old_limit is None:
            os.environ.pop("SCAN_UNIVERSE_LIMIT", None)
        else:
            os.environ["SCAN_UNIVERSE_LIMIT"] = old_limit
        try: Path(_tmp.name).unlink()
        except OSError: pass

if __name__ == "__main__": run()
