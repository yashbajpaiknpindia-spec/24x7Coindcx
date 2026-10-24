"""Keep stablecoin/USDT markets visible but exclude them from momentum entries."""
import os, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name

from app.db import Base, engine, SessionLocal
import app.core as core

PAIRS = [
    "B-USDC_USDT", "B-USD1_USDT", "B-BTC_USDT", "B-ETH_USDT",
    "B-SOL_USDT", "B-ZEC_USDT", "B-NEAR_USDT", "B-XRP_USDT",
    "B-DOGE_USDT", "B-BNB_USDT",
]

class FixtureCoinDCX:
    def spot_candles(self, pair, interval="1h", limit=500):
        idx = PAIRS.index(pair)
        base = 1.0 if pair in ("B-USDC_USDT", "B-USD1_USDT") else 10.0 + idx
        rows=[]
        start=int((datetime.now(timezone.utc)-timedelta(hours=400)).timestamp()*1000)
        for i in range(400):
            # Stablecoins get very high turnover with tiny positive price drift, the
            # exact case that can create a false momentum/volatility score.
            close = base * (1 + (i*0.000001 if pair in ("B-USDC_USDT","B-USD1_USDT") else i*0.0005))
            volume = 10_000_000 if pair in ("B-USDC_USDT","B-USD1_USDT") else 100_000
            rows.append({"time": start+i*3_600_000, "close": close, "volume": volume})
        return rows

def run():
    Base.metadata.create_all(engine)
    original_client = core.CoinDCXClient
    core.CoinDCXClient = FixtureCoinDCX
    try:
        with SessionLocal() as db:
            core.initialize_defaults(db)
            cfg = core.read_config(db, "strategy_config", {})
            cfg.update({"product_mode":"spot", "liquid_universe_size":8, "long_count":3, "short_count":3})
            core.write_config(db, "strategy_config", cfg)
            runtime=core.read_config(db,"runtime",{})
            runtime.update({"scan_universe_pairs":PAIRS,"scan_universe_count":len(PAIRS),"scan_universe_limit":60})
            core.write_config(db,"runtime",runtime)
            scored=core.calculate_scores(db,cfg)
            product=scored["spot"]
            allowed={x["pair"] for x in product["liquid_universe"]}
            assert "B-USDC_USDT" not in allowed and "B-USD1_USDT" not in allowed, allowed
            assert len(allowed)==8, allowed
            persisted=core.read_config(db,"runtime",{})["paper_strategy_scan"]["products"]["spot"]
            excluded={x["pair"]:x for x in persisted if x.get("signal")=="EXCLUDED"}
            assert excluded["B-USDC_USDT"]["liquid_shortlist"] is False
            assert excluded["B-USD1_USDT"]["liquid_shortlist"] is False
            assert "Stablecoin" in excluded["B-USDC_USDT"]["signal_reason"]
            assert not any(x["pair"] in ("B-USDC_USDT","B-USD1_USDT") for x in product["longs"]+product["shorts"])
            print("PASS: high-volume USDC/USDT and USD1/USDT remain visible but cannot enter momentum shortlist.")
    finally:
        core.CoinDCXClient = original_client
        try: Path(_tmp.name).unlink()
        except OSError: pass

if __name__ == "__main__": run()
