"""Regression: the strategy candle scorer includes markets discovered by the live scanner."""
import os, tempfile
from pathlib import Path
_tmp=tempfile.NamedTemporaryFile(suffix='.db',delete=False); _tmp.close()
os.environ['DATABASE_URL']='sqlite:///'+_tmp.name
from app.db import Base, engine, SessionLocal
import app.core as core

class FakeCoinDCX:
    seen=[]
    def spot_candles(self,pair,interval,limit):
        self.seen.append((pair,interval,limit))
        return [{'time':1700000000+i*3600,'close':100+i*0.02,'volume':50+i%5} for i in range(400)]
    def futures_candles(self,*args): raise AssertionError('futures should not be requested in spot-only mode')

def run():
    Base.metadata.create_all(engine)
    old=core.CoinDCXClient; core.CoinDCXClient=FakeCoinDCX
    try:
        with SessionLocal() as db:
            core.initialize_defaults(db)
            cfg=core.read_config(db,'strategy_config',{})
            cfg.update({'product_mode':'spot','pair_universe':['B-OLD_USDT'],'liquid_universe_size':2})
            core.write_config(db,'strategy_config',cfg)
            runtime=core.read_config(db,'runtime',{})
            runtime['scan_universe_pairs']=['B-NEW_USDT']
            core.write_config(db,'runtime',runtime); db.commit()
            scores=core.calculate_scores(db,cfg)
            fetched={x[0] for x in FakeCoinDCX.seen}
            assert fetched=={'B-OLD_USDT','B-NEW_USDT'}, fetched
            assert scores['_diagnostics']['requested_pairs']==2, scores['_diagnostics']
            assert scores['_diagnostics']['candle_ready_total']==2, scores['_diagnostics']
            assert 'spot' in scores and len(scores['spot']['all_scored'])==2
            print('DYNAMIC UNIVERSE REGRESSION PASSED: candle scorer fetched both legacy and discovered pairs and exposed coverage diagnostics.')
    finally:
        core.CoinDCXClient=old
        try: Path(_tmp.name).unlink()
        except OSError: pass

if __name__=='__main__': run()
