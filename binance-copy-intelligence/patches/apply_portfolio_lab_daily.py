from pathlib import Path
p=Path('/app/app.py')
s=p.read_text()
if 'PORTFOLIO_LAB_DAILY_OUTLOOK_V1' not in s:
    s += r'''

# PORTFOLIO_LAB_DAILY_OUTLOOK_V1
# Persist a once-daily $250/10%-allocation historical bootstrap outlook, without placing orders.
import threading as _pl_threading
import time as _pl_time
import json as _pl_json
from datetime import datetime as _pl_dt, timezone as _pl_tz

def _pl_daily_outlook_once(market, today):
    with SessionLocal() as db:
        old=db.scalar(select(ScanRun).where(
            ScanRun.kind=="PORTFOLIO_OUTLOOK", ScanRun.market_type==market,
            ScanRun.started_at >= _pl_dt.combine(today, _pl_dt.min.time()),
            ScanRun.status.in_(["COMPLETED","EMPTY"])
        ).order_by(ScanRun.id.desc()).limit(1))
        if old:
            return
    now=utcnow()
    try:
        if market=="SPOT":
            with SessionLocal() as db:
                n=db.scalar(select(func.count(Trader.id)).where(
                    Trader.exchange=="BINANCE",Trader.market_type=="SPOT")) or 0
            if not n:
                details={"investment_usd":250,"forecast_status":"EMPTY","reason":"No Binance Spot profiles are stored; Spot performance was not inferred from Futures."}
                with SessionLocal() as db:
                    db.add(ScanRun(kind="PORTFOLIO_OUTLOOK",market_type=market,status="EMPTY",started_at=now,finished_at=utcnow(),
                        found_count=0,updated_count=0,error_count=0,message="Daily outlook skipped: no Spot portfolios have been collected.",details_json=_pl_json.dumps(details)))
                    db.commit()
                return
        path='/api/portfolio-lab/forecast?market_type='+market+'&investment=250&allocation_pct=10&extra_cost_bps=5&days=7'
        with app.test_request_context(path):
            response=pl_forecast()
            if isinstance(response,tuple):
                response=response[0]
            data=response.get_json() if hasattr(response,'get_json') else {}
        if not isinstance(data,dict) or data.get("error"):
            raise RuntimeError(str(data.get("error") if isinstance(data,dict) else "forecast did not return a JSON object"))
        ranked=data.get("ranked",[])
        concise=[]
        for row in ranked[:20]:
            concise.append({k:row.get(k) for k in (
                "forecast_rank","id","nickname","portfolio_id","profile_url","forecast_status",
                "forecastable_trades","observed_median_leverage","historical_modelled_profit_usd",
                "historical_modelled_return_pct","historical_modelled_max_drawdown_usd",
                "expected_horizon_profit_usd","median_horizon_profit_usd","p10_horizon_profit_usd",
                "p90_horizon_profit_usd","forecast_days")})
        details={"model":"DAILY_BOOTSTRAP_OUTLOOK","recorded_at_utc":_pl_dt.now(_pl_tz.utc).isoformat(),
            "investment_usd":data.get("investment_usd",250),"allocation_per_position_pct":data.get("allocation_per_position_pct",10),
            "extra_copy_cost_bps":data.get("extra_copy_cost_bps",5),"horizon_days":data.get("horizon_days",7),
            "forecastable_count":data.get("forecastable_count",0),"insufficient_history_count":data.get("insufficient_history_count",0),
            "ranked_top_20":concise,"forecast_method":data.get("forecast_method"),
            "limitations":data.get("limitations",[])}
        status="COMPLETED" if data.get("forecastable_count",0)>0 else "EMPTY"
        message=("Daily hypothetical outlook computed for $250; " + str(data.get("forecastable_count",0)) +
            " forecastable portfolios, " + str(data.get("insufficient_history_count",0)) +
            " lacking minimum evidence. This is not actual copier PnL or a guaranteed return.")
        with SessionLocal() as db:
            db.add(ScanRun(kind="PORTFOLIO_OUTLOOK",market_type=market,status=status,started_at=now,finished_at=utcnow(),
                found_count=int(data.get("forecastable_count",0))+int(data.get("insufficient_history_count",0)),
                updated_count=int(data.get("forecastable_count",0)),error_count=0,message=message,
                details_json=_pl_json.dumps(details,ensure_ascii=False,default=str)))
            db.commit()
        app.logger.info("portfolio_daily_outlook_saved market=%s status=%s forecastable=%s insufficient=%s capital_usd=250",
            market,status,data.get("forecastable_count",0),data.get("insufficient_history_count",0))
    except Exception as exc:
        app.logger.exception("portfolio_daily_outlook_failed market=%s",market)
        with SessionLocal() as db:
            db.add(ScanRun(kind="PORTFOLIO_OUTLOOK",market_type=market,status="FAILED",started_at=now,finished_at=utcnow(),
                found_count=0,updated_count=0,error_count=1,message="Daily hypothetical outlook failed: "+str(exc)[:900],
                details_json=_pl_json.dumps({"error":str(exc)[:1200],"investment_usd":250})))
            db.commit()

def _pl_daily_outlook_loop():
    # Runs only when the real monitor is requested and the DB URL is durable PostgreSQL.
    # One recorded forecast per market per UTC day; retries failed attempts on later checks.
    _pl_time.sleep(45)
    while True:
        try:
            url=__import__("os").getenv("DATABASE_URL","").strip()
            enabled=__import__("os").getenv("ENABLE_SCHEDULER","false").lower() in ("1","true","yes")
            if enabled and url.startswith(("postgres://","postgresql://","postgresql+")):
                day=_pl_dt.now(_pl_tz.utc).date()
                _pl_daily_outlook_once("FUTURES",day)
                _pl_daily_outlook_once("SPOT",day)
        except Exception:
            app.logger.exception("portfolio_daily_outlook_loop_failed")
        _pl_time.sleep(300)

if (__import__("os").getenv("ENABLE_SCHEDULER","false").lower() in ("1","true","yes")
    and __import__("os").getenv("DATABASE_URL","").strip().startswith(("postgres://","postgresql://","postgresql+"))):
    _pl_threading.Thread(target=_pl_daily_outlook_loop,name="portfolio-daily-outlook",daemon=True).start()
'''
    p.write_text(s)
print('Daily persistence loop installed')


# Expose saved once-per-day forecasts in the dashboard; only persisted runs are returned.
s=p.read_text()
if "@app.get('/api/portfolio-lab/daily-history')" not in s:
    s += r'''

@app.get('/api/portfolio-lab/daily-history')
def pl_daily_history():
    market=str(pl_request.args.get("market_type","FUTURES")).upper()
    if market not in ("FUTURES","SPOT"):
        return pl_jsonify({"error":"invalid market_type"}),400
    with SessionLocal() as db:
        runs=list(db.scalars(select(ScanRun).where(
            ScanRun.kind=="PORTFOLIO_OUTLOOK",ScanRun.market_type==market
        ).order_by(ScanRun.started_at.desc(),ScanRun.id.desc()).limit(30)))
        out=[]
        for r in runs:
            try: details=_pl_json.loads(r.details_json or "{}")
            except Exception: details={}
            out.append({"id":r.id,"market_type":r.market_type,"status":r.status,
                "started_at":r.started_at.isoformat() if r.started_at else None,
                "finished_at":r.finished_at.isoformat() if r.finished_at else None,
                "found_count":r.found_count,"updated_count":r.updated_count,"error_count":r.error_count,
                "message":r.message,"investment_usd":details.get("investment_usd"),
                "forecastable_count":details.get("forecastable_count"),
                "insufficient_history_count":details.get("insufficient_history_count"),
                "ranked_top_20":details.get("ranked_top_20",[]),
                "forecast_method":details.get("forecast_method"),
                "limitations":details.get("limitations",[])})
    return pl_jsonify({"market_type":market,"items":out,"count":len(out),
        "note":"Snapshots are the default $250 daily research scenario and do not represent real copier account equity."})
'''
    p.write_text(s)
