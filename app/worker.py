"""Long-running Render worker: market polling, paper strategy, exchange reconciliation and gated live automation."""
import os, time, traceback
from datetime import datetime, timezone, timedelta
from .db import Base, engine, SessionLocal
from .core import initialize_defaults, read_config, write_config, refresh_markets, mark_paper_positions, calculate_scores, run_paper_cycle, log_event, PAPER_ENGINE_VERSION
from .coindcx import CoinDCXClient
from .live_engine import reconcile_live_account, collect_market_telemetry, run_auto_live_cycle

POLL_SECONDS=max(20, int(os.getenv('MARKET_DATA_POLL_SECONDS','60')))
RECONCILE_SECONDS=max(120, int(os.getenv('LIVE_RECONCILE_SECONDS','300')))
PAPER_RETRY_SECONDS=max(60, int(os.getenv('PAPER_CYCLE_RETRY_SECONDS','900')))
PAPER_SCORE_REFRESH_SECONDS=max(300, int(os.getenv('PAPER_SCORE_REFRESH_SECONDS','900')))


def _due(value, seconds):
    if not value: return True
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc)-dt).total_seconds()>=seconds
    except Exception:
        return True


def _parse_dt(value):
    if not value: return None
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None


def paper_cycle_due(cfg, runtime, now=None):
    # A fresh Start click bypasses the usual once-per-day rebalance guard.
    now=now or datetime.now(timezone.utc)
    cycle_at=_parse_dt(cfg.get('paper_last_cycle'))
    attempt_at=_parse_dt(runtime.get('paper_cycle_attempted_at'))
    request=cfg.get('paper_cycle_requested_at')
    request_pending=bool(request and request != runtime.get('paper_request_handled_at'))
    daily_due=(cycle_at is None or cycle_at.date() != now.date())
    retry_ready=(attempt_at is None or (now-attempt_at).total_seconds() >= PAPER_RETRY_SECONDS)
    # An expanded discovered universe is new research input. Rebalance paper
    # once against it even if today's earlier run used only the old seed universe;
    # recording the new count in last_strategy_cycle prevents repeat rebalance loops.
    last_cycle=runtime.get('last_strategy_cycle') or {}
    try:
        latest_universe_count=int(runtime.get('scan_universe_count') or 0)
        last_universe_count=int(last_cycle.get('scan_universe_count') or 0)
    except (TypeError, ValueError):
        latest_universe_count=last_universe_count=0
    universe_changed=(latest_universe_count > 0 and latest_universe_count > last_universe_count)
    engine_changed=last_cycle.get('paper_engine_version') != PAPER_ENGINE_VERSION
    return bool(request_pending or ((daily_due or universe_changed or engine_changed) and retry_ready)), (request if request_pending else None)


def main():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        initialize_defaults(db)
        cfg=read_config(db,'strategy_config',{})
        if os.getenv('AUTO_START_PAPER','true').lower() == 'true':
            cfg['paper_enabled']=True; write_config(db,'strategy_config',cfg)
        r=read_config(db,'runtime',{}); r['worker_started']=datetime.now(timezone.utc).isoformat(); write_config(db,'runtime',r)
        # A restarted worker must never inherit an old real-money arm. The operator must
        # explicitly re-arm in the authenticated UI after confirming service health.
        live=read_config(db,'live_state',{})
        if live.get('armed') or live.get('auto_live_armed'):
            live.update({'armed':False,'armed_at':None,'auto_live_armed':False,'auto_live_armed_at':None})
            write_config(db,'live_state',live)
            log_event(db,'Live automation disarmed on worker startup; explicit re-arm required.','WARNING','live_auto')
        log_event(db, 'Background worker started.', 'INFO','worker'); db.commit()
    while True:
        start=time.time()
        try:
            with SessionLocal() as db:
                r=read_config(db,'runtime',{})
                r['worker_last_heartbeat']=datetime.now(timezone.utc).isoformat(); write_config(db,'runtime',r)
                refresh_result=refresh_markets(db)
                mark_paper_positions(db)
                telemetry=collect_market_telemetry(db)
                cfg=read_config(db,'strategy_config',{})
                if cfg.get('paper_enabled'):
                    runtime=read_config(db,'runtime',{})
                    due, queued_request=paper_cycle_due(cfg,runtime)
                    # Keep opportunity scores live while the portfolio rebalance remains daily.
                    if not due and _due(runtime.get('paper_score_refresh_at'), PAPER_SCORE_REFRESH_SECONDS):
                        score_result=calculate_scores(db,cfg)
                        diag=score_result.get('_diagnostics',{}) if isinstance(score_result,dict) else {}
                        refreshed_at=diag.get('as_of') or datetime.now(timezone.utc).isoformat()
                        runtime=read_config(db,'runtime',{})
                        runtime['paper_score_refresh_at']=refreshed_at
                        runtime['paper_score_refresh_status']='completed' if diag.get('candle_ready_total',0)>0 else 'waiting_for_candle_history'
                        runtime['paper_score_refresh_message']=f"Scored {sum((diag.get('scored_pairs') or {}).values())} product/pair records; {diag.get('candle_ready_total',0)} candle-ready records across {diag.get('requested_pairs',0)} unique markets."
                        write_config(db,'runtime',runtime)
                        if diag.get('fetch_error_count',0):
                            log_event(db,'Scheduled paper opportunity scan had candle API errors.','WARNING','strategy_scan',diag)
                        db.commit()
                    if due:
                        attempted_at=datetime.now(timezone.utc).isoformat()
                        runtime['paper_cycle_attempted_at']=attempted_at
                        if queued_request:
                            runtime['paper_request_handled_at']=queued_request
                        runtime['paper_cycle_status']='running'
                        runtime['paper_cycle_message']='Paper cycle started; fetching completed hourly candles and checking live liquidity.'
                        write_config(db,'runtime',runtime); db.commit()
                        result=run_paper_cycle(db, force=False)
                        runtime=read_config(db,'runtime',{})
                        runtime['paper_cycle_status']='completed' if result.get('ok') else 'skipped'
                        runtime['paper_cycle_message']=result.get('message','Paper cycle returned no status message.')
                        runtime['paper_cycle_attempted_at']=datetime.now(timezone.utc).isoformat()
                        runtime['paper_score_refresh_at']=(runtime.get('paper_candle_diagnostics') or {}).get('as_of') or runtime['paper_cycle_attempted_at']
                        runtime['paper_score_refresh_status']='completed' if (runtime.get('paper_candle_diagnostics') or {}).get('candle_ready_total',0)>0 else 'waiting_for_candle_history'
                        if queued_request:
                            runtime['paper_request_handled_at']=queued_request
                        write_config(db,'runtime',runtime)
                        if not result.get('ok'):
                            log_event(db,'Scheduled paper cycle skipped: '+result.get('message','unknown reason'),'WARNING','worker',result.get('diagnostics',{}))
                        db.commit()
                client=CoinDCXClient()
                reconciliation={'status':'not_configured'}
                if client.credentials_present and _due(r.get('last_live_reconciliation_at'), RECONCILE_SECONDS):
                    reconciliation=reconcile_live_account(db)
                auto_result=run_auto_live_cycle(db)
                runtime=read_config(db,'runtime',{})
                runtime['worker_last_completed']=datetime.now(timezone.utc).isoformat()
                runtime['worker_last_refresh_result']={'errors':refresh_result.get('errors',[]),'updated':refresh_result.get('updated',0)} if isinstance(refresh_result,dict) else {'result':str(refresh_result)[:300]}
                runtime['worker_last_telemetry_status']=telemetry.get('as_of') if isinstance(telemetry,dict) else None
                runtime['worker_last_auto_live_status']=auto_result.get('status') if isinstance(auto_result,dict) else 'unknown'
                if client.credentials_present and reconciliation.get('status') not in ('not_configured',None):
                    runtime['worker_last_reconciliation_status']=reconciliation.get('status') or runtime.get('last_live_reconciliation_status')
                write_config(db,'runtime',runtime)
                db.commit()
        except Exception as exc:
            try:
                with SessionLocal() as db:
                    log_event(db, f'Worker iteration failed: {exc}', 'ERROR','worker', {'traceback':traceback.format_exc()[-5000:]})
                    r=read_config(db,'runtime',{}); r['market_refresh_error']=str(exc)[:500]; r['worker_last_error_at']=datetime.now(timezone.utc).isoformat(); write_config(db,'runtime',r); db.commit()
            except Exception: pass
        delay=max(1,POLL_SECONDS-(time.time()-start))
        time.sleep(delay)

if __name__=='__main__': main()
