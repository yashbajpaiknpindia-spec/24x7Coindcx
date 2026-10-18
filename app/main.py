import os, json, secrets, hmac, csv, io, re, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from .db import Base, engine, SessionLocal, ConfigKV, Event, MarketSnapshot, PaperPosition, Trade, OrderRecord, BacktestResult, ExecutionFill, LedgerEntry, AccountSnapshot, TelemetrySnapshot, StrategyPosition, utcnow
from .coindcx import CoinDCXClient, CoinDCXError
from .core import (initialize_defaults, read_config, write_config, log_event, refresh_markets, market_eligibility,
                   market_spread_bps, dashboard_summary, paper_equity, mark_paper_positions, run_paper_cycle,
                   PAIR_UNIVERSE, STRATEGY_ID, STRATEGY_NAME, STRATEGY_VERSION, norm_pair, safe_json, env_float, env_int)
from .live_engine import (reconcile_live_account, collect_market_telemetry, run_auto_live_cycle, latest_account_snapshot, latest_telemetry, _live_quality, _list_data, _assets, _free_balance, _futures_free_wallet, _metadata_quantity, _normalize_exchange_status)

APP_NAME = 'CoinDCX Strategy Terminal'
ROOT = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv('SECRET_KEY', 'local-dev-secret-change-this-before-deploying-32chars')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')
ADMIN_PASSWORD_CONFIGURED = len(ADMIN_PASSWORD) >= 14 and ADMIN_PASSWORD.lower() not in {'password12345678','changemechangeme','local-dev-change-me'}
LIVE_TRADING_ENABLED = os.getenv('LIVE_TRADING_ENABLED', 'false').lower() == 'true'
AUTO_LIVE_TRADING_ENABLED = os.getenv('AUTO_LIVE_TRADING_ENABLED', 'false').lower() == 'true'

app = FastAPI(title=APP_NAME, version='1.4.5', docs_url='/api/docs')
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site='lax', https_only=os.getenv('COOKIE_SECURE','false').lower() == 'true', session_cookie='cdx_terminal_session', max_age=60*60*12)
app.mount('/static', StaticFiles(directory=str(ROOT/'app'/'static')), name='static')
templates = Jinja2Templates(directory=str(ROOT/'app'/'templates'))

@app.on_event('startup')
def on_startup():
    # Do not crash-loop on a missing dashboard password. Health remains available so
    # Render can finish deployment; interactive login stays locked until configured.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        initialize_defaults(db)
        cfg=read_config(db,'strategy_config',{})
        if os.getenv('AUTO_START_PAPER','true').lower() == 'true':
            cfg['paper_enabled']=True; write_config(db,'strategy_config',cfg)
        if not ADMIN_PASSWORD_CONFIGURED:
            log_event(db, 'Admin login is locked because ADMIN_PASSWORD is missing or weak. Configure a 14+ character secret in Render.', 'ERROR', 'security')
        # Never restore an armed real-trading session after a web-service restart.
        live_state = read_config(db, 'live_state', {})
        if live_state.get('armed'):
            live_state.update({'armed': False, 'armed_at': None, 'auto_live_armed': False})
            write_config(db, 'live_state', live_state)
            log_event(db, 'Live mode automatically disarmed on web-service startup.', 'WARNING', 'live')
        db.commit()

@app.get('/health')
def health():
    try:
        with SessionLocal() as db:
            db.execute(select(ConfigKV.key).limit(1)).all()
        return {'ok': True, 'service': APP_NAME, 'version': '1.4.5', 'database': 'reachable', 'admin_auth_configured': ADMIN_PASSWORD_CONFIGURED, 'live_trading_enabled': LIVE_TRADING_ENABLED, 'auto_live_env_enabled': AUTO_LIVE_TRADING_ENABLED}
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)[:200]}, status_code=503)

def authed(request: Request): return bool(request.session.get('authenticated'))

def must_auth(request: Request):
    if not authed(request): raise HTTPException(status_code=401, detail='Login required')

def verify_csrf(request: Request, token: str):
    expected = request.session.get('csrf', '')
    if not expected or not token or not hmac.compare_digest(str(expected), str(token)):
        raise HTTPException(status_code=403, detail='Invalid or missing CSRF token. Reload the page and try again.')

def context(request: Request, page: str, title: str, **extra):
    with SessionLocal() as db:
        summary = dashboard_summary(db)
        events = db.scalars(select(Event).order_by(desc(Event.created_at)).limit(6)).all()
    ctx = {'request':request,'page':page,'title':title,'app_name':APP_NAME,'summary':summary,'events':events,
           'live_trading_enabled':LIVE_TRADING_ENABLED,'auto_live_trading_enabled':AUTO_LIVE_TRADING_ENABLED,
           'api_key_configured':bool(os.getenv('COINDCX_API_KEY')),'api_secret_configured':bool(os.getenv('COINDCX_API_SECRET')),
           'admin_password_configured':ADMIN_PASSWORD_CONFIGURED,
           'csrf_token':request.session.get('csrf',''),
           'now_utc':datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
    ctx.update(extra)
    return ctx

@app.get('/', response_class=HTMLResponse)
def root(request: Request): return RedirectResponse('/dashboard' if authed(request) else '/login', status_code=303)

@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    if authed(request): return RedirectResponse('/dashboard', status_code=303)
    return templates.TemplateResponse('login.html', {'request':request,'app_name':APP_NAME,'error':None if ADMIN_PASSWORD_CONFIGURED else 'Login is locked: configure a strong ADMIN_PASSWORD (14+ characters) in Render Environment. The service is running, but this account is not configured yet.'})

@app.post('/login')
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not ADMIN_PASSWORD_CONFIGURED:
        return templates.TemplateResponse('login.html', {'request':request,'app_name':APP_NAME,'error':'Login is locked because ADMIN_PASSWORD is not configured as a strong 14+ character secret in Render Environment.'}, status_code=503)
    if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD):
        request.session.clear(); request.session['authenticated']=True; request.session['csrf']=secrets.token_urlsafe(24)
        with SessionLocal() as db: log_event(db,'Admin session started.','INFO','security'); db.commit()
        return RedirectResponse('/dashboard', status_code=303)
    with SessionLocal() as db: log_event(db,'Rejected login attempt.','WARNING','security'); db.commit()
    return templates.TemplateResponse('login.html', {'request':request,'app_name':APP_NAME,'error':'Invalid username or password.'}, status_code=401)

@app.post('/logout')
def logout(request: Request):
    request.session.clear(); return RedirectResponse('/login', status_code=303)

@app.get('/dashboard', response_class=HTMLResponse)
def dashboard(request: Request):
    if not authed(request): return RedirectResponse('/login', status_code=303)
    with SessionLocal() as db:
        positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True).order_by(desc(PaperPosition.opened_at)).limit(12)).all()
        markets=db.scalars(select(MarketSnapshot).order_by(MarketSnapshot.product, MarketSnapshot.pair)).all()
        recent=db.scalars(select(Trade).order_by(desc(Trade.created_at)).limit(10)).all()
        cfg=read_config(db,'strategy_config',{})
        eq=paper_equity(db)
    return templates.TemplateResponse('dashboard.html', context(request,'dashboard','Overview',positions=positions,markets=markets,recent=recent,cfg=cfg,equity=eq))

@app.get('/markets', response_class=HTMLResponse)
def markets_page(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{})
        rows=db.scalars(select(MarketSnapshot).order_by(MarketSnapshot.product,MarketSnapshot.pair)).all()
        markets=[]
        for r in rows:
            ok,why=market_eligibility(r,cfg)
            markets.append({'row':r,'eligible':ok,'reason':why,'spread':market_spread_bps(r.bid,r.ask)})
    return templates.TemplateResponse('markets.html',context(request,'markets','Markets & Liquidity',markets=markets,pairs=PAIR_UNIVERSE))

@app.get('/strategy', response_class=HTMLResponse)
def strategy_page(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db: cfg=read_config(db,'strategy_config',{}); runtime=read_config(db,'runtime',{})
    return templates.TemplateResponse('strategy.html',context(request,'strategy','Strategy Lab',cfg=cfg,runtime=runtime,pairs=PAIR_UNIVERSE,discovered_pairs=runtime.get('scan_universe_pairs',[]),scan_limit=runtime.get('scan_universe_limit',env_int('SCAN_UNIVERSE_LIMIT',60)),strategy_id=STRATEGY_ID,strategy_name=STRATEGY_NAME,strategy_version=STRATEGY_VERSION))

@app.post('/strategy/save')
def strategy_save(request: Request, product_mode: str=Form('both'), leverage: float=Form(1), cost_case: str=Form('NORMAL'), min_turnover: float=Form(250000), max_spread_bps: float=Form(50), capital: float=Form(30000)):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    if product_mode not in ('spot','futures','both') or cost_case not in ('NORMAL','STRESS'): raise HTTPException(400,'Invalid setting.')
    if leverage not in (1,2,3,5): raise HTTPException(400,'Leverage must be one of the research cases: 1x, 2x, 3x or 5x.')
    if not 1000 <= capital <= 10000000: raise HTTPException(400,'Capital outside allowed configuration range.')
    if min_turnover < 0 or max_spread_bps <= 0 or max_spread_bps > 500: raise HTTPException(400,'Invalid market liquidity thresholds.')
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{}); cfg.update({'product_mode':product_mode,'futures_leverage':leverage,'paper_cost_case':cost_case,'min_quote_turnover_usdt':min_turnover,'max_spread_bps':max_spread_bps,'starting_capital_inr':capital})
        write_config(db,'strategy_config',cfg); log_event(db,'Strategy settings updated.','INFO','settings',{'product_mode':product_mode,'leverage':leverage,'cost_case':cost_case}); db.commit()
    return RedirectResponse('/strategy?saved=1',status_code=303)

@app.post('/markets/refresh')
def markets_refresh(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db: result=refresh_markets(db)
    return RedirectResponse('/markets?refreshed=1' if not result['errors'] else '/markets?partial=1',status_code=303)

@app.get('/api/market-data/detail')
def market_detail(request: Request, product: str, pair: str):
    must_auth(request)
    client=CoinDCXClient()
    try:
        if product=='spot':
            book=client.spot_orderbook(pair,20); trades=client.spot_trades(pair,30)
        elif product=='futures':
            book=client.futures_orderbook(pair,20); trades=client.futures_trades(pair)
        else: raise HTTPException(400,'Invalid product.')
        # Return small bounded responses only; never show private account fields.
        return {'product':product,'pair':pair,'orderbook':book,'trades':trades[:30] if isinstance(trades,list) else trades}
    except CoinDCXError as exc: raise HTTPException(502,str(exc))

@app.get('/api/dashboard')
def api_dashboard(request: Request):
    must_auth(request)
    with SessionLocal() as db:
        summary=dashboard_summary(db); eq=summary['paper_equity']
        markets=db.scalars(select(MarketSnapshot).order_by(desc(MarketSnapshot.quote_turnover_usdt)).limit(20)).all()
        return {'summary':summary,'markets':[{'product':m.product,'pair':m.pair,'last_price':m.last_price,'bid':m.bid,'ask':m.ask,'turnover':m.quote_turnover_usdt,'updated_at':m.updated_at.isoformat()} for m in markets]}

@app.get('/paper', response_class=HTMLResponse)
def paper_page(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{}); runtime=read_config(db,'runtime',{}); eq=paper_equity(db)
        positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True).order_by(desc(PaperPosition.opened_at))).all()
        trades=db.scalars(select(Trade).where(Trade.run_mode=='paper').order_by(desc(Trade.created_at)).limit(100)).all()
        closed=db.scalars(select(Trade).where(Trade.run_mode=='paper',Trade.status=='closed')).all()
    now_utc=datetime.now(timezone.utc)
    fx=float(cfg.get('inr_per_usdt',94.75))
    for p in positions:
        opened=p.opened_at.replace(tzinfo=timezone.utc) if p.opened_at.tzinfo is None else p.opened_at.astimezone(timezone.utc)
        p.held_minutes=max(0,(now_utc-opened).total_seconds()/60)
        p.invested_usdt=float(p.notional_usdt or abs(p.quantity*p.entry_price))
        p.invested_inr=p.invested_usdt*fx
        p.estimated_margin_inr=p.invested_inr/max(float(p.leverage or 1),1.0) if p.product=='futures' else p.invested_inr
        stop=float(cfg.get('stop_loss_move_pct',0.75))/100
        p.stop_price=p.entry_price*(1-stop if p.side=='buy' else 1+stop)
    for t in trades:
        opened=t.created_at.replace(tzinfo=timezone.utc) if t.created_at.tzinfo is None else t.created_at.astimezone(timezone.utc)
        ended=t.closed_at.replace(tzinfo=timezone.utc) if t.closed_at and t.closed_at.tzinfo is None else (t.closed_at.astimezone(timezone.utc) if t.closed_at else now_utc)
        t.held_minutes=max(0,(ended-opened).total_seconds()/60)
        t.invested_usdt=abs(float(t.quantity or 0)*float(t.entry_price or 0))
        t.invested_inr=t.invested_usdt*fx
    wins=sum(1 for t in closed if (t.net_pnl_inr or 0)>0)
    losses=sum(1 for t in closed if (t.net_pnl_inr or 0)<0)
    stats={'closed':len(closed),'wins':wins,'losses':losses,'win_rate':(100*wins/len(closed) if closed else None),
           'profit_factor':(sum(t.net_pnl_inr for t in closed if (t.net_pnl_inr or 0)>0)/abs(sum(t.net_pnl_inr for t in closed if (t.net_pnl_inr or 0)<0)) if any((t.net_pnl_inr or 0)<0 for t in closed) else None),
           'net_pnl_inr':sum(t.net_pnl_inr or 0 for t in closed)}
    return templates.TemplateResponse('paper.html',context(request,'paper','Paper Trading',cfg=cfg,runtime=runtime,equity=eq,positions=positions,trades=trades,paper_stats=stats))

@app.post('/paper/start')
def paper_start(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{})
        cfg['paper_enabled']=True
        # Queue a fresh run even when a daily rebalance already occurred today.
        request_at=datetime.now(timezone.utc).isoformat()
        cfg['paper_cycle_requested_at']=request_at
        write_config(db,'strategy_config',cfg)
        runtime=read_config(db,'runtime',{})
        runtime['paper_cycle_status']='queued'
        runtime['paper_cycle_message']='Paper cycle queued by Start; waiting for the background worker.'
        runtime['paper_cycle_requested_at']=request_at
        write_config(db,'runtime',runtime)
        log_event(db,'Paper engine enabled; immediate paper cycle queued.','INFO','paper',{'requested_at':request_at})
        db.commit()
    return RedirectResponse('/paper?started=1',status_code=303)

@app.get('/api/paper-status')
def api_paper_status(request: Request):
    if not authed(request): return JSONResponse({'error':'login_required'}, status_code=401)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{}); runtime=read_config(db,'runtime',{})
        markets=db.scalars(select(MarketSnapshot)).all()
        now=datetime.now(timezone.utc)
        fresh=0
        for m in markets:
            updated=m.updated_at
            if updated is not None:
                updated=updated.replace(tzinfo=timezone.utc) if updated.tzinfo is None else updated.astimezone(timezone.utc)
                if (now-updated).total_seconds() <= int(cfg.get('max_stale_seconds',120)): fresh+=1
        heartbeat=runtime.get('worker_last_heartbeat')
        try:
            hb=datetime.fromisoformat(str(heartbeat).replace('Z','+00:00')) if heartbeat else None
            if hb and hb.tzinfo is None: hb=hb.replace(tzinfo=timezone.utc)
            heartbeat_age=int(max(0,(now-hb).total_seconds())) if hb else None
        except Exception: heartbeat_age=None
        diag=runtime.get('paper_candle_diagnostics',{}) or {}
        cycle=runtime.get('last_strategy_cycle',{}) or {}
        return {'paper_enabled':bool(cfg.get('paper_enabled')),'scan_universe_count':runtime.get('scan_universe_count',0),
            'scan_universe_limit':runtime.get('scan_universe_limit',0),'scan_universe_source':runtime.get('scan_universe_source','Not scanned yet'),
            'market_snapshot_count':len(markets),'fresh_snapshot_count':fresh,'last_market_refresh':runtime.get('last_market_refresh'),
            'market_refresh_error':runtime.get('market_refresh_error'),'worker_last_heartbeat':heartbeat,'worker_heartbeat_age_seconds':heartbeat_age,
            'paper_cycle_status':runtime.get('paper_cycle_status','waiting'),'paper_cycle_message':runtime.get('paper_cycle_message','No paper cycle has been recorded yet.'),
            'paper_cycle_attempted_at':runtime.get('paper_cycle_attempted_at'),'paper_last_cycle':cfg.get('paper_last_cycle'),
            'last_strategy_cycle':cycle,'candle_diagnostics':diag,'open_positions':db.scalar(select(func.count(PaperPosition.id)).where(PaperPosition.is_open==True)) or 0,
            'closed_trades':db.scalar(select(func.count(Trade.id)).where(Trade.run_mode=='paper',Trade.status=='closed')) or 0}



@app.get('/api/paper-scan-results')
def api_paper_scan_results(request: Request):
    """Authenticated, read-only view of live market scans and the last real strategy score run."""
    if not authed(request):
        return JSONResponse({'error':'login_required','message':'Your session expired. Sign in again to view live scan results.'}, status_code=401)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{})
        runtime=read_config(db,'runtime',{})
        discovered=runtime.get('scan_universe_pairs') or cfg.get('pair_universe') or PAIR_UNIVERSE
        pairs=list(dict.fromkeys(str(p) for p in discovered if p))
        requested_limit=max(20,min(150,env_int('SCAN_UNIVERSE_LIMIT',60)))
        pairs=pairs[:requested_limit]
        if not pairs: pairs=PAIR_UNIVERSE[:requested_limit]
        product_mode=cfg.get('product_mode','both')
        products=['spot','futures'] if product_mode=='both' else ([product_mode] if product_mode in ('spot','futures') else ['spot','futures'])
        snapshots=db.scalars(select(MarketSnapshot).where(MarketSnapshot.pair.in_(pairs))).all() if pairs else []
        by_market={(m.product,m.pair):m for m in snapshots}
        spot_turnover={m.pair:float(m.quote_turnover_usdt or 0) for m in snapshots if m.product=='spot'}
        pair_order=sorted(pairs,key=lambda pair:spot_turnover.get(pair,0),reverse=True)
        market_rank={pair:i+1 for i,pair in enumerate(pair_order)}
        strategy_scan=runtime.get('paper_strategy_scan') or {}
        products_scan=strategy_scan.get('products') or {}
        score_by_market={}
        for product, values in products_scan.items():
            for item in values or []:
                if isinstance(item,dict) and item.get('pair'):
                    score_by_market[(product,item['pair'])]=item
        open_positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True)).all()
        open_map={(p.product,p.pair):p for p in open_positions}
        recent_trades=db.scalars(select(Trade).where(Trade.run_mode=='paper').order_by(desc(Trade.created_at)).limit(400)).all()
        trade_map={}
        for trade in recent_trades:
            trade_map.setdefault((trade.product,trade.pair),trade)
        now=datetime.now(timezone.utc)
        rows=[]
        for pair in pair_order:
            for product in products:
                snap=by_market.get((product,pair))
                scored=score_by_market.get((product,pair),{})
                spread=market_spread_bps(snap.bid,snap.ask) if snap else None
                updated=snap.updated_at if snap else None
                if updated is not None:
                    updated=updated.replace(tzinfo=timezone.utc) if updated.tzinfo is None else updated.astimezone(timezone.utc)
                    age=max(0,int((now-updated).total_seconds()))
                else: age=None
                if snap:
                    eligible, eligibility_reason=market_eligibility(snap,cfg)
                else:
                    eligible, eligibility_reason=False,'No market snapshot yet; waiting for a live scanner refresh'
                position=open_map.get((product,pair))
                trade=trade_map.get((product,pair))
                if position:
                    paper_state='OPEN PAPER POSITION'
                elif trade and trade.status=='closed':
                    paper_state='LAST TRADE CLOSED'
                elif scored.get('signal') in ('LONG','SHORT'):
                    paper_state='ELIGIBLE CANDIDATE' if eligible else 'BLOCKED BY LIQUIDITY GATE'
                elif scored:
                    paper_state='WATCH / NO ENTRY'
                else:
                    paper_state='WAITING FOR CANDLES'
                rows.append({
                    'rank':market_rank[pair], 'pair':pair, 'product':product,
                    'last_price':snap.last_price if snap else None,
                    'turnover_usdt_proxy':snap.quote_turnover_usdt if snap else None,
                    'liquidity_source':snap.liquidity_source if snap else 'not available',
                    'bid':snap.bid if snap else None, 'ask':snap.ask if snap else None,
                    'spread_bps':spread, 'active':bool(snap.active) if snap else False,
                    'exit_only':bool(snap.exit_only) if snap else False,
                    'snapshot_age_seconds':age, 'updated_at':updated.isoformat() if updated else None,
                    'eligible':bool(eligible), 'eligibility_reason':eligibility_reason,
                    'candle_ready':bool(scored), 'strategy_score':scored.get('score'),
                    'momentum_pct':scored.get('momentum_pct'),
                    'hourly_volatility_pct':scored.get('hourly_volatility_pct'),
                    'strategy_turnover_proxy':scored.get('turnover_proxy'),
                    'strategy_rank':scored.get('strategy_rank'),
                    'liquid_shortlist':bool(scored.get('liquid_shortlist',False)),
                    'signal':scored.get('signal','NO SCORE'),
                    'signal_reason':scored.get('signal_reason','Strategy has not produced a score for this market yet'),
                    'paper_state':paper_state,
                    'paper_unrealized_pnl_inr':float(position.last_unrealized_pnl_inr or 0) if position else None,
                    'last_trade_status':trade.status if trade else None,
                    'last_trade_net_pnl_inr':float(trade.net_pnl_inr or 0) if trade else None,
                    'leverage':float(position.leverage or 1) if position else float(cfg.get('futures_leverage',1) or 1),
                })
        unique_eligible=sum(1 for pair in pairs if any(r['pair']==pair and r['eligible'] for r in rows))
        opportunity_rows=[r for r in rows if r['signal'] in ('LONG','SHORT')]
        eligible_opportunities=[r for r in opportunity_rows if r['eligible']]
        diag=runtime.get('paper_candle_diagnostics') or {}
        heartbeat=runtime.get('worker_last_heartbeat')
        try:
            hb=datetime.fromisoformat(str(heartbeat).replace('Z','+00:00')) if heartbeat else None
            if hb and hb.tzinfo is None: hb=hb.replace(tzinfo=timezone.utc)
            heartbeat_age=int(max(0,(now-hb).total_seconds())) if hb else None
        except Exception: heartbeat_age=None
        return {
            'ok':True,'as_of':now.isoformat(),'universe_count':len(pairs),
            'scan_universe_limit':runtime.get('scan_universe_limit',requested_limit),
            'scan_universe_source':runtime.get('scan_universe_source','Waiting for first successful CoinDCX scan'),
            'last_market_refresh':runtime.get('last_market_refresh'),
            'market_refresh_error':runtime.get('market_refresh_error'),
            'worker_last_heartbeat':heartbeat,'worker_heartbeat_age_seconds':heartbeat_age,
            'paper_cycle_status':runtime.get('paper_cycle_status','waiting'),
            'paper_cycle_message':runtime.get('paper_cycle_message','Paper cycle has not reported a result yet'),
            'paper_cycle_attempted_at':runtime.get('paper_cycle_attempted_at'),
            'strategy_as_of':strategy_scan.get('as_of'),
            'strategy_id':strategy_scan.get('strategy_id'),
            'candle_diagnostics':diag,
            'summary':{'unique_markets':len(pairs),'product_checks':len(rows),
                       'snapshots_present':sum(1 for r in rows if r['last_price'] is not None and r['last_price']>0),
                       'snapshot_records_updated':sum(1 for r in rows if r['updated_at']),
                       'liquidity_gate_passes':sum(1 for r in rows if r['eligible']),
                       'unique_markets_with_any_pass':unique_eligible,
                       'candle_ready_records':sum(1 for r in rows if r['candle_ready']),
                       'strategy_opportunities':len(opportunity_rows),
                       'eligible_opportunities':len(eligible_opportunities),
                       'open_paper_positions':len(open_positions),
                       'closed_paper_trades':db.scalar(select(func.count(Trade.id)).where(Trade.run_mode=='paper',Trade.status=='closed')) or 0},
            'rows':rows,
        }


@app.post('/paper/pause')
def paper_pause(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{}); cfg['paper_enabled']=False; write_config(db,'strategy_config',cfg); log_event(db,'Paper strategy engine paused. Existing paper positions remain open and marked.','WARNING','paper'); db.commit()
    return RedirectResponse('/paper?paused=1',status_code=303)

@app.post('/paper/cycle')
def paper_cycle(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        refresh_markets(db)
        result=run_paper_cycle(db,force=True)
    return RedirectResponse('/paper?cycle=1' if result.get('ok') else '/paper?cycle_error=1',status_code=303)

@app.get('/live', response_class=HTMLResponse)
def live_page(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        live=read_config(db,'live_state',{}); cfg=read_config(db,'strategy_config',{}); runtime=read_config(db,'runtime',{})
        orders=db.scalars(select(OrderRecord).where(OrderRecord.run_mode=='live').order_by(desc(OrderRecord.created_at)).limit(25)).all()
        fills=db.scalars(select(ExecutionFill).order_by(desc(ExecutionFill.occurred_at)).limit(10)).all()
        latest_rec=runtime.get('last_live_reconciliation',{})
        latest_acct=latest_account_snapshot(db)
        unresolved_count=db.scalar(select(func.count(OrderRecord.id)).where(OrderRecord.run_mode=='live',OrderRecord.status.in_(['submitting','submitted','open','partially_filled','unknown','filled_unreconciled']))) or 0
        market_rows=db.scalars(select(MarketSnapshot).order_by(MarketSnapshot.product,MarketSnapshot.pair)).all()
    choices=[]
    for m in market_rows:
        ok,why=market_eligibility(m,cfg)
        if ok: choices.append({'product':m.product,'pair':m.pair,'price':m.last_price,'spread':market_spread_bps(m.bid,m.ask),'turnover':m.quote_turnover_usdt})
    return templates.TemplateResponse('live.html',context(request,'live','Live Execution',live=live,cfg=cfg,runtime=runtime,orders=orders,choices=choices,fills=fills,latest_rec=latest_rec,latest_acct=latest_acct,unresolved_count=unresolved_count,live_trading_enabled=LIVE_TRADING_ENABLED,auto_live_trading_enabled=AUTO_LIVE_TRADING_ENABLED,api_key_configured=bool(os.getenv('COINDCX_API_KEY')),api_secret_configured=bool(os.getenv('COINDCX_API_SECRET')),max_leverage=env_int('LIVE_MAX_LEVERAGE',2),max_order=env_float('LIVE_MAX_ORDER_NOTIONAL_USDT',25),max_gross=env_float('LIVE_MAX_GROSS_EXPOSURE_USDT',100),auto_max_order=env_float('LIVE_AUTO_MAX_ORDER_NOTIONAL_USDT',10),auto_max_gross=env_float('LIVE_AUTO_MAX_GROSS_EXPOSURE_USDT',50),auto_budget=env_float('LIVE_AUTO_CAPITAL_BUDGET_INR',3000),env_auto_loss=env_float('LIVE_AUTO_MAX_DAILY_LOSS_INR',500),admin_password_configured=ADMIN_PASSWORD_CONFIGURED))

@app.post('/live/arm')
def live_arm(request: Request, confirmation: str=Form(''), csrf_token: str=Form('')):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    verify_csrf(request, csrf_token)
    if not LIVE_TRADING_ENABLED: return RedirectResponse('/live?blocked=env',status_code=303)
    if confirmation.strip() != 'ARM LIVE TRADING': return RedirectResponse('/live?blocked=phrase',status_code=303)
    client=CoinDCXClient()
    try: client.user_info()
    except Exception as exc:
        with SessionLocal() as db: log_event(db,f'Live arming failed: {exc}','ERROR','live'); db.commit()
        return RedirectResponse('/live?blocked=api',status_code=303)
    with SessionLocal() as db:
        live=read_config(db,'live_state',{}); live.update({'armed':True,'armed_at':utcnow().isoformat(),'typed_confirmation':True,'auto_live_armed':False,'auto_live_armed_at':None}); write_config(db,'live_state',live)
        log_event(db,'Live mode armed after explicit phrase and API connectivity check.','WARNING','live'); db.commit()
    return RedirectResponse('/live?armed=1',status_code=303)

@app.post('/live/auto-arm')
def live_auto_arm(request: Request, confirmation: str=Form(''), csrf_token: str=Form('')):
    if not authed(request): return RedirectResponse('/login', status_code=303)
    verify_csrf(request, csrf_token)
    if not LIVE_TRADING_ENABLED or not AUTO_LIVE_TRADING_ENABLED:
        return RedirectResponse('/live?blocked=auto_env', status_code=303)
    if confirmation.strip() != 'ARM AUTOMATED LIVE TRADING':
        return RedirectResponse('/live?blocked=auto_phrase', status_code=303)
    client=CoinDCXClient()
    if not client.credentials_present:
        return RedirectResponse('/live?blocked=api_credentials', status_code=303)
    try:
        client.user_info()
        # Validate required read-only account endpoints before allowing the worker to
        # consider orders. This does not submit an order.
        client.spot_balances(); client.futures_positions(size=10)
    except Exception as exc:
        with SessionLocal() as db:
            log_event(db, f'Auto-live arming check failed: {exc}', 'ERROR', 'live_auto'); db.commit()
        return RedirectResponse('/live?blocked=api', status_code=303)
    with SessionLocal() as db:
        live=read_config(db,'live_state',{})
        live.update({'armed':True,'armed_at':utcnow().isoformat(),'auto_live_armed':True,
                     'auto_live_armed_at':utcnow().isoformat(),'typed_confirmation':True})
        write_config(db,'live_state',live)
        log_event(db,'Automated live strategy explicitly armed after typed confirmation and account endpoint checks. Worker remains subject to market-quality, balance, reconciliation and notional checks.','WARNING','live_auto')
        db.commit()
    return RedirectResponse('/live?auto_armed=1', status_code=303)

@app.post('/live/auto-cycle')
def live_auto_cycle_now(request: Request, confirmation: str=Form(''), csrf_token: str=Form('')):
    if not authed(request): return RedirectResponse('/login', status_code=303)
    verify_csrf(request, csrf_token)
    if confirmation.strip() != 'RUN AUTOMATED REBALANCE NOW':
        return RedirectResponse('/live?blocked=cycle_phrase', status_code=303)
    with SessionLocal() as db:
        result=run_auto_live_cycle(db)
        log_event(db, 'Manual immediate auto-cycle request: '+str(result.get('status')), 'WARNING' if result.get('status') in ('blocked','risk_stop','locked','disarmed') else 'INFO', 'live_auto', result)
        db.commit()
    return RedirectResponse('/live?cycle_status='+str(result.get('status','unknown')), status_code=303)

@app.post('/live/disarm')
def live_disarm(request: Request, csrf_token: str=Form('')):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    verify_csrf(request, csrf_token)
    with SessionLocal() as db:
        live=read_config(db,'live_state',{}); live.update({'armed':False,'armed_at':None,'auto_live_armed':False,'auto_live_armed_at':None}); write_config(db,'live_state',live)
        log_event(db,'Live mode disarmed.','WARNING','live'); db.commit()
    return RedirectResponse('/live?disarmed=1',status_code=303)

@app.post('/live/order')
def live_order(request: Request, product: str=Form(...), pair: str=Form(...), side: str=Form(...), quantity: float=Form(...), leverage: int=Form(1), order_type: str=Form('market_order'), limit_price: float=Form(0), confirmation: str=Form(''), csrf_token: str=Form('')):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    verify_csrf(request, csrf_token)
    if not LIVE_TRADING_ENABLED: return RedirectResponse('/live?blocked=env',status_code=303)
    if confirmation.strip() != 'SUBMIT LIVE ORDER': return RedirectResponse('/live?blocked=phrase',status_code=303)
    with SessionLocal() as db:
        live=read_config(db,'live_state',{}); cfg=read_config(db,'strategy_config',{})
        if not live.get('armed'): return RedirectResponse('/live?blocked=disarmed',status_code=303)
        if product not in ('spot','futures') or side not in ('buy','sell') or order_type not in ('market_order','limit_order') or not math.isfinite(quantity) or quantity <= 0 or not math.isfinite(limit_price):
            return RedirectResponse('/live?blocked=invalid',status_code=303)
        snap=db.scalar(select(MarketSnapshot).where(MarketSnapshot.product==product,MarketSnapshot.pair==pair))
        px=float(limit_price) if order_type=='limit_order' and limit_price>0 else (float(snap.last_price) if snap and snap.last_price else 0.0)
        ok, reason=_live_quality(snap,cfg,product,quantity*px) if snap else (False,'market snapshot missing')
        if not ok: log_event(db,f'Live order blocked for {pair}: {reason}','WARNING','live'); db.commit(); return RedirectResponse('/live?blocked=liquidity',status_code=303)
        notional=quantity*px
        fx=float(cfg.get('inr_per_usdt',94.75))
        if notional > env_float('LIVE_MAX_ORDER_NOTIONAL_USDT',25):
            log_event(db,f'Live order blocked for {pair}: notional {notional:.4f} USDT above per-order cap.','WARNING','live'); db.commit(); return RedirectResponse('/live?blocked=notional',status_code=303)
        if product=='futures' and (leverage < 1 or leverage > env_int('LIVE_MAX_LEVERAGE',2)):
            return RedirectResponse('/live?blocked=leverage',status_code=303)
        if order_type=='limit_order' and limit_price<=0: return RedirectResponse('/live?blocked=price',status_code=303)
        # Conservative app-level 24h notional cap. The exchange's own account/margin rules still apply.
        cutoff=utcnow()-timedelta(hours=24)
        prev=db.scalars(select(OrderRecord).where(OrderRecord.run_mode=='live',OrderRecord.created_at>=cutoff,OrderRecord.status.notin_(['rejected','cancelled']))).all()
        previous=sum(abs(o.quantity*(o.requested_price or 0)) for o in prev)
        gross_cap=env_float('LIVE_MAX_GROSS_EXPOSURE_USDT',100)
        if previous + notional > gross_cap:
            log_event(db,'Live order blocked by rolling 24-hour order-notional cap.','WARNING','live',{'prior_notional':previous,'new_notional':notional,'cap':gross_cap}); db.commit(); return RedirectResponse('/live?blocked=gross',status_code=303)
        order=OrderRecord(run_mode='live',product=product,pair=pair,side=side,order_type=order_type,quantity=quantity,requested_price=px,status='submitting',client_order_id=f'cdxt-{int(time.time()*1000)}')
        db.add(order); db.flush()
        client=CoinDCXClient(); submission_attempted=False
        try:
            if product=='spot':
                details=client.spot_market_details()
                matched=next((d for d in details if isinstance(d,dict) and norm_pair(d.get('pair') or d.get('market') or d.get('symbol'))==norm_pair(pair)),None)
                if not matched: raise CoinDCXError(f"Could not map {pair} to CoinDCX spot order market. Refusing to guess the order symbol.")
                market_code=matched.get('market') or matched.get('symbol')
                if not market_code: raise CoinDCXError('Spot market-code missing from CoinDCX market details; refusing to guess.')
                rounded, qerr = _metadata_quantity(quantity, 'spot', pair, matched, {}, reference_price=px, order_type=order_type)
                if qerr: raise CoinDCXError(qerr)
                if abs(rounded-quantity) > max(1e-12, abs(quantity)*1e-9):
                    raise CoinDCXError(f'Quantity {quantity:g} violates exchange precision/step; nearest valid quantity is {rounded:g}.')
                balances=_list_data(client.spot_balances())
                base_asset,quote_asset=_assets(pair,matched)
                spend_asset=quote_asset if side=='buy' else base_asset
                required=notional if side=='buy' else quantity
                available=_free_balance(balances,spend_asset)
                if available is None or available+1e-10<required:
                    raise CoinDCXError(f'Insufficient or unverifiable free spot {spend_asset} balance; required {required:g}, reported free {available}.')
                submission_attempted=True
                resp=client.submit_spot_order(str(market_code),side,quantity,order_type,px if order_type=='limit_order' else None,matched.get('ecode'),order.client_order_id)
            else:
                instrument=client.futures_instrument(pair,'USDT')
                if isinstance(instrument,list) and instrument: instrument=instrument[0]
                if not isinstance(instrument,dict): instrument={}
                if instrument.get('exit_only') or instrument.get('is_exit_only') or str(instrument.get('status') or '').lower() in ('exit_only','inactive'):
                    raise CoinDCXError('This futures instrument is currently exit-only or inactive.')
                rounded, qerr = _metadata_quantity(quantity, 'futures', pair, {}, instrument, reference_price=px, order_type=order_type)
                if qerr: raise CoinDCXError(qerr)
                if abs(rounded-quantity) > max(1e-12, abs(quantity)*1e-9):
                    raise CoinDCXError(f'Quantity {quantity:g} violates exchange precision/step; nearest valid quantity is {rounded:g}.')
                wallets=client.futures_wallets(); free_margin=_futures_free_wallet(wallets)
                estimated_margin=notional/max(1,leverage)*1.05
                if free_margin is None or free_margin+1e-10<estimated_margin:
                    raise CoinDCXError(f'Insufficient or unverifiable free USDT futures margin; estimated initial-margin need {estimated_margin:.4f}, reported free {free_margin}.')
                submission_attempted=True
                resp=client.submit_futures_order(pair,side,quantity,leverage,order_type,px if order_type=='limit_order' else None,'USDT',order.client_order_id)
            data=resp.get('orders',[resp]) if isinstance(resp,dict) else resp
            info=data[0] if isinstance(data,list) and data and isinstance(data[0],dict) else (data if isinstance(data,dict) else {})
            ext_id=str(info.get('id') or info.get('order_id') or '')
            ex_status=_normalize_exchange_status(info.get('status'))
            # Do not present acceptance as a fill: exchange trade-history rows must reconcile it.
            order.external_order_id=ext_id
            if ex_status in ('rejected','cancelled','partially_cancelled'):
                order.status=ex_status
            elif ex_status=='filled':
                order.status='filled_unreconciled'
            elif ext_id and ex_status in ('open','partially_filled'):
                order.status=ex_status
            elif ext_id:
                order.status='submitted'
            else:
                order.status='unknown'
            order.details_json=json.dumps({'response':resp,'normalized_exchange_status':ex_status,
                'reconciliation_note':'order acceptance is not a fill; matched account trade-history rows are required'},default=str)[:12000]
            log_event(db,f'Live {product} {side} order response for {pair}: {order.status}. Exchange acceptance is not a fill.','WARNING' if order.status in ('unknown','filled_unreconciled','submitted','open','partially_filled') else 'INFO','live',{'order_record_id':order.id,'external_order_id':ext_id,'notional_usdt':notional})
            db.commit()
            return RedirectResponse('/live?submitted=1' if order.status not in ('unknown','rejected') else '/live?blocked=api',status_code=303)
        except Exception as exc:
            order.status='unknown' if submission_attempted else 'rejected'; order.details_json=json.dumps({'error':str(exc),'submit_outcome':'ambiguous; reconcile exchange status before any retry' if submission_attempted else 'preflight rejected before exchange submission'},default=str)
            log_event(db,f'Live order {"submission outcome uncertain" if submission_attempted else "preflight rejected"} for {pair}: {exc}','ERROR' if submission_attempted else 'WARNING','live'); db.commit()
            return RedirectResponse('/live?blocked=api',status_code=303)

@app.get('/orders',response_class=HTMLResponse)
def orders_page(request:Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        orders=db.scalars(select(OrderRecord).order_by(desc(OrderRecord.created_at)).limit(200)).all()
        trades=db.scalars(select(Trade).order_by(desc(Trade.created_at)).limit(200)).all()
    return templates.TemplateResponse('orders.html',context(request,'orders','Orders & Fills',orders=orders,trades=trades))

@app.get('/positions',response_class=HTMLResponse)
def positions_page(request:Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True).order_by(desc(PaperPosition.opened_at))).all()
        eq=paper_equity(db); live=read_config(db,'live_state',{})
    live_account={'configured':CoinDCXClient().credentials_present,'futures_positions':[],'spot_balances':[],'error':None,'as_of':None}
    if live_account['configured']:
        try:
            client=CoinDCXClient()
            fps=client.futures_positions(size=100)
            sbs=client.spot_balances()
            if isinstance(fps,dict): fps=fps.get('data',fps.get('positions',[]))
            if isinstance(sbs,dict): sbs=sbs.get('data',sbs.get('balances',[]))
            live_account['futures_positions']=[x for x in (fps or []) if isinstance(x,dict) and abs(float(x.get('active_pos') or 0))>0]
            live_account['spot_balances']=[x for x in (sbs or []) if isinstance(x,dict) and (float(x.get('balance') or 0)+float(x.get('locked_balance') or 0))>0]
            live_account['as_of']=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        except Exception as exc:
            live_account['error']=str(exc)[:300]
    return templates.TemplateResponse('positions.html',context(request,'positions','Positions',positions=positions,equity=eq,live=live,live_account=live_account))

def _json_container(raw, default):
    try:
        value=json.loads(raw or '')
        if isinstance(value,dict):
            for key in ('data','balances','wallets','positions','transactions','results'):
                if isinstance(value.get(key),list): return value[key]
        return value
    except Exception: return default

@app.get('/capital', response_class=HTMLResponse)
def capital_page(request: Request):
    if not authed(request): return RedirectResponse('/login', status_code=303)
    with SessionLocal() as db:
        snap=latest_account_snapshot(db)
        strategy_positions=db.scalars(select(StrategyPosition).order_by(StrategyPosition.product,StrategyPosition.pair)).all()
        markets=db.scalars(select(MarketSnapshot)).all()
        eq=paper_equity(db); runtime=read_config(db,'runtime',{})
    prices={(m.product,m.pair):m.last_price for m in markets}
    deployed={'spot':0.0,'futures':0.0}
    pos_rows=[]
    for pos in strategy_positions:
        mark=prices.get((pos.product,pos.pair)) or pos.last_mark_price or pos.average_entry_price
        notional=abs(float(pos.signed_quantity or 0)*float(mark or 0))
        deployed[pos.product]=deployed.get(pos.product,0.0)+notional
        pos_rows.append({'position':pos,'mark':mark,'notional':notional,'unrealized_quote':(float(mark or 0)-float(pos.average_entry_price or 0))*float(pos.signed_quantity or 0)})
    spot=_json_container(snap.spot_balances_json,[]) if snap else []
    wallets=_json_container(snap.futures_wallets_json,[]) if snap else []
    futures=_json_container(snap.futures_positions_json,[]) if snap else []
    warnings=_json_container(snap.warnings_json,[]) if snap else []
    return templates.TemplateResponse('capital.html',context(request,'capital','Capital Deployment',snapshot=snap,spot_balances=spot if isinstance(spot,list) else [],futures_wallets=wallets if isinstance(wallets,list) else [],futures_positions=futures if isinstance(futures,list) else [],snapshot_warnings=warnings if isinstance(warnings,list) else [],strategy_positions=pos_rows,deployed=deployed,paper_equity=eq,runtime=runtime,fx=env_float('INR_PER_USDT',94.75)))

@app.get('/ledger', response_class=HTMLResponse)
def ledger_page(request: Request):
    if not authed(request): return RedirectResponse('/login', status_code=303)
    with SessionLocal() as db:
        entries=db.scalars(select(LedgerEntry).order_by(desc(LedgerEntry.occurred_at)).limit(400)).all()
        fills=db.scalars(select(ExecutionFill).order_by(desc(ExecutionFill.occurred_at)).limit(250)).all()
        counts={}
        for status,count in db.execute(select(LedgerEntry.reconciliation_status,func.count(LedgerEntry.id)).group_by(LedgerEntry.reconciliation_status)).all(): counts[status]=count
        runtime=read_config(db,'runtime',{})
    needs_review=sum(v for k,v in counts.items() if k not in ('reconciled',))
    return templates.TemplateResponse('ledger.html',context(request,'ledger','Execution Ledger',entries=entries,fills=fills,status_counts=counts,needs_review=needs_review,runtime=runtime))

@app.get('/api/ledger.csv')
def ledger_csv(request: Request):
    must_auth(request)
    with SessionLocal() as db:
        entries=db.scalars(select(LedgerEntry).order_by(LedgerEntry.occurred_at)).all()
    out=io.StringIO(); writer=csv.writer(out)
    writer.writerow(['ledger_key','occurred_at','run_mode','product','pair','category','amount','currency','cash_effect','reconciliation_status','external_ref','details_json'])
    for x in entries: writer.writerow([x.ledger_key,x.occurred_at,x.run_mode,x.product,x.pair,x.category,x.amount,x.currency,x.cash_effect,x.reconciliation_status,x.external_ref,x.details_json])
    return HTMLResponse(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=coindcx_execution_ledger.csv'})

@app.get('/telemetry', response_class=HTMLResponse)
def telemetry_page(request: Request):
    if not authed(request): return RedirectResponse('/login', status_code=303)
    with SessionLocal() as db:
        rows=latest_telemetry(db,limit=100); latest=rows[0] if rows else None
        runtime=read_config(db,'runtime',{}); account=latest_account_snapshot(db)
        details=safe_json(latest.details_json) if latest else runtime.get('last_market_quality',{})
        history=[]
        for row in rows:
            d=safe_json(row.details_json)
            history.append({'row':row,'details':d})
    return templates.TemplateResponse('telemetry.html',context(request,'telemetry','Data Quality & Telemetry',rows=rows,history=history,latest=latest,details=details,runtime=runtime,account=account))

@app.get('/analytics',response_class=HTMLResponse)
def analytics_page(request:Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        trades=db.scalars(select(Trade).where(Trade.run_mode=='paper',Trade.status=='closed').order_by(Trade.closed_at)).all()
        eq=paper_equity(db)
        labels=[]; daily={}
        for t in trades:
            if t.closed_at: daily[str(t.closed_at.date())]=daily.get(str(t.closed_at.date()),0)+(t.net_pnl_inr or 0)
        labels=sorted(daily); vals=[round(daily[x],2) for x in labels]
        cumulative=[]; s=float(read_config(db,'strategy_config',{}).get('starting_capital_inr',30000))
        for v in vals: s+=v; cumulative.append(round(s,2))
        closed=[t for t in trades]
        wins=sum(t.net_pnl_inr for t in closed if (t.net_pnl_inr or 0)>0); losses=abs(sum(t.net_pnl_inr for t in closed if (t.net_pnl_inr or 0)<0))
        stats={'count':len(closed),'wins':sum(1 for t in closed if (t.net_pnl_inr or 0)>0),'win_rate':sum(1 for t in closed if (t.net_pnl_inr or 0)>0)/len(closed)*100 if closed else None,'profit_factor':wins/losses if losses else None,'net':sum(t.net_pnl_inr for t in closed)}
    return templates.TemplateResponse('analytics.html',context(request,'analytics','Performance Analytics',labels=labels,values=vals,cumulative=cumulative,stats=stats,equity=eq))

@app.get('/backtests',response_class=HTMLResponse)
def backtests_page(request:Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        rows=db.scalars(select(BacktestResult).order_by(desc(BacktestResult.imported_at),BacktestResult.experiment).limit(250)).all()
    return templates.TemplateResponse('backtests.html',context(request,'backtests','Backtest Archive',results=rows))

@app.post('/backtests/import')
async def backtests_import(request:Request, file:UploadFile=File(...)):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    name=file.filename or ''
    if not (name.lower().endswith('.csv') or name.lower().endswith('.json')): raise HTTPException(400,'Upload a CSV or JSON results file.')
    content=await file.read()
    if len(content)>10_000_000: raise HTTPException(413,'File too large; limit is 10 MB.')
    try:
        if name.lower().endswith('.json'): rows=json.loads(content.decode('utf-8'))
        else: rows=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
        if isinstance(rows,dict): rows=rows.get('results',rows.get('data',[]))
        if not isinstance(rows,list): raise ValueError('Expected an array/list of rows.')
    except Exception as exc: raise HTTPException(400,f'Cannot parse results file: {exc}')
    mapping={'experiment':['experiment','run','run_id','experiment_id'],'strategy':['strategy','strategy_name','strategy_id'],'period':['period','sample','period_name','segment'],'product':['product','market','market_type'],'exposure_x':['exposure_x','leverage','leverage_x'],'cost_case':['cost_case','cost','scenario'],'return_pct':['return_pct','return_percent','return'],'net_pnl_inr':['net_pnl_inr','pnl_inr','net_pnl'],'max_drawdown_pct':['max_drawdown_pct','max_close_drawdown_pct','max_drawdown'],'adverse_drawdown_pct':['max_adverse_intrabar_drawdown_proxy_pct','adverse_drawdown_pct'],'profit_factor':['daily_profit_factor','profit_factor'],'avg_daily_pnl_inr':['average_daily_pnl_inr','avg_daily_pnl_inr'],'profitable_days_pct':['profitable_days_pct']}
    def pick(row, keys, default=None):
        for k in keys:
            if k in row and row[k] not in ('',None): return row[k]
        return default
    def fval(v):
        if v is None: return None
        try: return float(str(v).replace(',',''))
        except Exception: return None
    count=0
    with SessionLocal() as db:
        for r in rows[:5000]:
            if not isinstance(r,dict): continue
            prod=str(pick(r,mapping['product'],'unknown')).lower()
            if prod not in ('spot','futures'): prod='unknown'
            db.add(BacktestResult(experiment=str(pick(r,mapping['experiment'],'Imported CSV'))[:100],strategy=str(pick(r,mapping['strategy'],'Imported strategy'))[:150],period=str(pick(r,mapping['period'],'Unspecified period'))[:100],product=prod,
                exposure_x=fval(pick(r,mapping['exposure_x'],1)) or 1,cost_case=str(pick(r,mapping['cost_case'],'UNKNOWN'))[:20],return_pct=fval(pick(r,mapping['return_pct'])),net_pnl_inr=fval(pick(r,mapping['net_pnl_inr'])),
                max_drawdown_pct=fval(pick(r,mapping['max_drawdown_pct'])),adverse_drawdown_pct=fval(pick(r,mapping['adverse_drawdown_pct'])),profit_factor=fval(pick(r,mapping['profit_factor'])),avg_daily_pnl_inr=fval(pick(r,mapping['avg_daily_pnl_inr'])),profitable_days_pct=fval(pick(r,mapping['profitable_days_pct'])),notes='Imported by user; source file and assumptions should be checked.',metrics_json=json.dumps(r,default=str)[:10000]))
            count+=1
        log_event(db,f'Imported {count} historical backtest result rows from {name}.','INFO','backtest'); db.commit()
    return RedirectResponse(f'/backtests?imported={count}',status_code=303)

@app.get('/journal',response_class=HTMLResponse)
def journal_page(request:Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db: rows=db.scalars(select(Event).order_by(desc(Event.created_at)).limit(500)).all()
    return templates.TemplateResponse('journal.html',context(request,'journal','Audit Journal',rows=rows))

@app.get('/settings',response_class=HTMLResponse)
def settings_page(request:Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{}); runtime=read_config(db,'runtime',{}); live=read_config(db,'live_state',{})
    return templates.TemplateResponse('settings.html',context(request,'settings','Connections & Settings',cfg=cfg,runtime=runtime,live=live,api_key_configured=bool(os.getenv('COINDCX_API_KEY')),api_secret_configured=bool(os.getenv('COINDCX_API_SECRET')),database_url_present=bool(os.getenv('DATABASE_URL')),live_trading_enabled=LIVE_TRADING_ENABLED,auto_live_trading_enabled=AUTO_LIVE_TRADING_ENABLED,admin_password_configured=ADMIN_PASSWORD_CONFIGURED))

@app.post('/settings/test-coindcx')
def test_coindcx(request:Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    client=CoinDCXClient()
    result=''
    try:
        info=client.user_info()
        if isinstance(info,dict): result='Authenticated. User info API returned a response; private fields are not stored.'
        else: result='Authenticated endpoint responded.'
        status='ok'
    except Exception as exc: result=str(exc); status='error'
    with SessionLocal() as db: log_event(db,f'CoinDCX connectivity test: {status}.','INFO' if status=='ok' else 'ERROR','integration',{'message':result}); db.commit()
    return RedirectResponse('/settings?test='+status,status_code=303)

@app.get('/api/external-account')
def external_account(request:Request):
    must_auth(request)
    if not CoinDCXClient().credentials_present: raise HTTPException(400,'Server API credentials are not configured.')
    c=CoinDCXClient(); payload={}
    errors=[]
    for key,fn in [('user_info',c.user_info),('spot_balances',c.spot_balances),('futures_positions',c.futures_positions)]:
        try: payload[key]=fn()
        except Exception as exc: errors.append(f'{key}: {exc}')
    return {'data':payload,'errors':errors,'as_of':datetime.now(timezone.utc).isoformat()}

@app.get('/api/summary.csv')
def summary_csv(request:Request):
    must_auth(request)
    with SessionLocal() as db: rows=db.scalars(select(Trade).order_by(Trade.created_at)).all()
    out=io.StringIO(); writer=csv.writer(out)
    writer.writerow(['id','created_at','closed_at','run_mode','product','pair','side','quantity','entry_price','exit_price','leverage','gross_pnl_inr','fees_inr','slippage_inr','funding_inr','net_pnl_inr','status','strategy','reason','external_order_id'])
    for t in rows: writer.writerow([t.id,t.created_at,t.closed_at,t.run_mode,t.product,t.pair,t.side,t.quantity,t.entry_price,t.exit_price,t.leverage,t.gross_pnl_inr,t.fees_inr,t.slippage_inr,t.funding_inr,t.net_pnl_inr,t.status,t.strategy,t.reason,t.external_order_id])
    return HTMLResponse(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=coindcx_trade_ledger.csv'})
