import os, json, secrets, hmac, csv, io, re, math
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from sqlalchemy import select, desc, func, text
from sqlalchemy.orm import Session
from .db import Base, engine, SessionLocal, ConfigKV, Event, MarketSnapshot, PaperPosition, PaperModePosition, MarketObservation, PaperDecisionAudit, Trade, ScalpTrade, OrderRecord, BacktestResult, ExecutionFill, LedgerEntry, AccountSnapshot, TelemetrySnapshot, StrategyPosition, utcnow
from .coindcx import CoinDCXClient, CoinDCXError
from .core import (initialize_defaults, read_config, write_config, log_event, refresh_markets, market_eligibility,
                   market_spread_bps, _entry_cost_hurdle_pct, dashboard_summary, paper_equity, mark_paper_positions, run_paper_cycle, build_scalper_scan, run_scalper_cycle, _scalp_calculate,
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

app = FastAPI(title=APP_NAME, version='1.7.0', docs_url='/api/docs')
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site='lax', https_only=os.getenv('COOKIE_SECURE','false').lower() == 'true', session_cookie='cdx_terminal_session', max_age=60*60*12)
app.mount('/static', StaticFiles(directory=str(ROOT/'app'/'static')), name='static')
templates = Jinja2Templates(directory=str(ROOT/'app'/'templates'))
IST = ZoneInfo('Asia/Kolkata')

def _format_ist(value, fmt='%d %b %Y %H:%M IST'):
    if value is None:
        return '—'
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(IST).strftime(fmt)
    except Exception:
        return str(value)

templates.env.filters['ist'] = _format_ist

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
        return {'ok': True, 'service': APP_NAME, 'version': '1.7.0', 'database': 'reachable', 'admin_auth_configured': ADMIN_PASSWORD_CONFIGURED, 'live_trading_enabled': LIVE_TRADING_ENABLED, 'auto_live_env_enabled': AUTO_LIVE_TRADING_ENABLED}
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
           'now_utc':datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'now_ist':datetime.now(timezone.utc).astimezone(IST).strftime('%d %b %Y %I:%M:%S %p IST')}
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

def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@app.get('/loss-review', response_class=HTMLResponse)
def loss_review_page(request: Request):
    if not authed(request):
        return RedirectResponse('/login', status_code=303)
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{})
        runtime=read_config(db,'runtime',{})
        tax_pct=float(cfg.get('scalper_tax_pct',30))
        fx=float(cfg.get('inr_per_usdt',94.75))
        trades=db.scalars(select(Trade).where(Trade.run_mode.in_(['paper','paper_capital']),Trade.status=='closed').order_by(desc(Trade.closed_at)).limit(200)).all()
        coverage=db.execute(select(func.min(MarketObservation.observed_at),func.max(MarketObservation.observed_at),func.count(MarketObservation.id))).one()
        first_obs,last_obs,obs_count=coverage
        summaries={h:{'evaluated':0,'held_better':0,'exit_better':0,'avg_delta':None,'_deltas':[]} for h in ('1h','4h','24h')}
        rows=[]
        for t in trades:
            opened=_as_utc(t.created_at); closed=_as_utc(t.closed_at)
            metadata=safe_json(t.metadata_json or '{}')
            actual_tax=max(0.0,float(t.gross_pnl_inr or 0))*tax_pct/100
            actual_after_tax=float(t.net_pnl_inr or 0)-actual_tax
            t.actual_after_tax=actual_after_tax
            t.diagnosis=_paper_trade_diagnosis(t)
            horizon_rows=[]
            entry_notional=abs(float(t.quantity or 0)*float(t.entry_price or 0))
            fee_pct=float(cfg.get('spot_fee_pct' if t.product=='spot' else 'futures_fee_pct',0.15 if t.product=='spot' else 0.075))/100
            slip_pct=float(cfg.get('normal_slippage_pct',0.05))/100 if cfg.get('paper_cost_case','NORMAL')=='NORMAL' else float(cfg.get('stress_slippage_pct',0.12))/100
            for key,delta in (('1h',timedelta(hours=1)),('4h',timedelta(hours=4)),('24h',timedelta(hours=24))):
                if not closed:
                    horizon_rows.append({'name':key,'status':'Unavailable','label':'No close timestamp','note':'No closed timestamp to anchor this comparison.'})
                    continue
                target=closed+delta
                if target>now:
                    horizon_rows.append({'name':key,'status':'Pending','label':'Horizon not reached','note':'Wait until the full horizon has elapsed.'})
                    continue
                tolerance=timedelta(minutes=15)
                obs=db.scalars(select(MarketObservation).where(
                    MarketObservation.product==t.product,MarketObservation.pair==t.pair,
                    MarketObservation.observed_at>=target,
                    MarketObservation.observed_at<=target+tolerance
                ).order_by(MarketObservation.observed_at.asc()).limit(1)).first()
                if not obs or not obs.last_price or not t.entry_price or not t.quantity:
                    horizon_rows.append({'name':key,'status':'Insufficient data','label':'Cannot judge',
                        'note':'No stored 5-minute market observation close enough to the target time. This is not evidence that the exit was right or wrong.'})
                    continue
                # Hypothetical hold: same original entry and quantity, marked at the closest
                # recorded executable exit quote at the horizon. This cannot recover hidden intrabar highs/lows.
                fallback=not bool(obs.bid and obs.ask)
                future_exit=float((obs.bid if t.side=='buy' else obs.ask) if (obs.bid if t.side=='buy' else obs.ask) else obs.last_price)
                direction=1 if t.side=='buy' else -1
                gross=(future_exit-float(t.entry_price))*float(t.quantity)*direction*fx
                exit_notional=abs(float(t.quantity)*future_exit)
                fees=(entry_notional+exit_notional)*fee_pct*fx
                slips=(entry_notional+exit_notional)*slip_pct*fx
                elapsed_hours=max(0,(target-opened).total_seconds()/3600) if opened else delta.total_seconds()/3600
                funding=0.0
                if t.product=='futures' and cfg.get('paper_cost_case')=='STRESS':
                    funding=entry_notional*(float(cfg.get('funding_stress_pct_per_8h',0.01))/100)*(elapsed_hours/8)*fx
                tax=max(0.0,gross)*tax_pct/100
                after_tax=gross-fees-slips-funding-tax
                delta_net=after_tax-actual_after_tax
                tolerance_inr=max(5.0,entry_notional*fx*0.001)
                if delta_net>tolerance_inr:
                    label='Potentially exited too early'
                elif delta_net < -tolerance_inr:
                    label='Exit better than holding to this point'
                else:
                    label='Similar result at this point'
                row={'name':key,'status':'Evaluated','label':label,'gross_inr':gross,'fees_inr':fees,
                    'slippage_inr':slips,'funding_inr':funding,'tax_inr':tax,'net_after_tax_inr':after_tax,
                    'delta_inr':delta_net,'at':obs.observed_at,'price':future_exit,
                    'note':('Used last-price fallback because executable bid/ask was missing. ' if fallback else '')+
                           'Endpoint comparison only; it does not show the path between checks or prove a position would have survived.'}
                horizon_rows.append(row)
                summ=summaries[key]; summ['evaluated']+=1; summ['_deltas'].append(delta_net)
                if delta_net>tolerance_inr: summ['held_better']+=1
                elif delta_net < -tolerance_inr: summ['exit_better']+=1
            t.review_rows=horizon_rows
            rows.append(t)
        for summ in summaries.values():
            summ['avg_delta']=sum(summ['_deltas'])/len(summ['_deltas']) if summ['_deltas'] else None
            summ.pop('_deltas',None)
    return templates.TemplateResponse('loss_review.html',context(request,'loss_review','Loss re-evaluation',trades=rows,review_stats=summaries,
        observation_start=first_obs,observation_end=last_obs,observation_count=obs_count,tax_pct=tax_pct,runtime=runtime))


@app.get('/scalper', response_class=HTMLResponse)
def scalper_page(request: Request):
    if not authed(request):
        return RedirectResponse('/login', status_code=303)
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{})
        runtime=read_config(db,'runtime',{})
        candidates=build_scalper_scan(db,cfg,now)
        trades=db.scalars(select(ScalpTrade).order_by(desc(ScalpTrade.opened_at)).limit(100)).all()
        closed=db.scalars(select(ScalpTrade).where(ScalpTrade.status=='closed').order_by(desc(ScalpTrade.closed_at)).limit(500)).all()
        open_trades=[t for t in trades if t.status=='open']
        winners=[float(t.net_after_tax_inr or 0) for t in closed if (t.net_after_tax_inr or 0)>0]
        losers=[float(t.net_after_tax_inr or 0) for t in closed if (t.net_after_tax_inr or 0)<0]
        pf=sum(winners)/abs(sum(losers)) if losers else None
        open_marked=sum(float(t.unrealized_net_after_tax_inr or 0) for t in open_trades)
        net=sum(float(t.net_after_tax_inr or 0) for t in closed)
        stats={'open':len(open_trades),'closed':len(closed),'wins':len(winners),'losses':len(losers),
               'profit_factor':pf,'net_after_tax':net,'open_net':open_marked,
               'eligible':sum(1 for x in candidates if x['eligible']),
               'scanned':len(candidates),'sample_target':50,
               'pf_validated':len(closed)>=50 and pf is not None and pf>=1.25}
        for t in trades:
            opened=_as_utc(t.opened_at)
            ended=_as_utc(t.closed_at) if t.closed_at else now
            t.held_minutes=max(0,(ended-opened).total_seconds()/60) if opened else 0
            t.entry_reason=safe_json(t.metadata_json or '{}').get('entry_reason','—')
    return templates.TemplateResponse('scalper.html',context(request,'scalper','Fast scalping lab',cfg=cfg,runtime=runtime,
        candidates=candidates[:100],trades=trades,scalper_stats=stats))


@app.post('/scalper/start')
def scalper_start(request: Request):
    if not authed(request):
        return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{})
        cfg['scalper_enabled']=True
        write_config(db,'strategy_config',cfg)
        log_event(db,'Fast scalping paper simulation enabled. No exchange orders were sent.','INFO','scalper')
        db.commit()
    return RedirectResponse('/scalper?started=1',status_code=303)


@app.post('/scalper/pause')
def scalper_pause(request: Request):
    if not authed(request):
        return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{})
        cfg['scalper_enabled']=False
        write_config(db,'strategy_config',cfg)
        log_event(db,'Fast scalping paper simulation paused. Existing positions remain monitored and can exit under their risk rules.','WARNING','scalper')
        db.commit()
    return RedirectResponse('/scalper?paused=1',status_code=303)


@app.get('/paper', response_class=HTMLResponse)
def paper_page(request: Request):
    if not authed(request): return RedirectResponse('/login',status_code=303)
    with SessionLocal() as db:
        cfg=read_config(db,'strategy_config',{}); runtime=read_config(db,'runtime',{}); eq=paper_equity(db)
        positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True).order_by(desc(PaperPosition.opened_at))).all()
        trades=db.scalars(select(Trade).where(Trade.run_mode=='paper').order_by(desc(Trade.created_at)).limit(100)).all()
        closed=db.scalars(select(Trade).where(Trade.run_mode=='paper',Trade.status=='closed')).all()
        capital_positions=db.scalars(select(PaperModePosition).where(PaperModePosition.is_open==True).order_by(desc(PaperModePosition.opened_at))).all()
        capital_trades=db.scalars(select(Trade).where(Trade.run_mode=='paper_capital').order_by(desc(Trade.created_at)).limit(100)).all()
        capital_closed=db.scalars(select(Trade).where(Trade.run_mode=='paper_capital',Trade.status=='closed')).all()
        observation_count=db.scalar(select(func.count(MarketObservation.id))) or 0
        audits=db.scalars(select(PaperDecisionAudit).order_by(desc(PaperDecisionAudit.decision_at)).limit(10000)).all()
        recent_audits=audits[:100]
        audit_stats={}
        for mode in ('unrestricted','capital_constrained'):
            group=[a for a in audits if a.mode==mode]
            rejected=[a for a in group if a.decision=='rejected']
            accepted=[a for a in group if a.decision=='accepted']
            data={'decisions':len(group),'rejected':len(rejected),'accepted':len(accepted),'reasons':{}}
            def reason_key(a):
                return (a.rejection_reason or 'unspecified').split(':',1)[0][:100]
            for a in rejected:
                reason=reason_key(a)
                data['reasons'].setdefault(reason,{'count':0,'1h':{},'4h':{},'24h':{}})
                data['reasons'][reason]['count']+=1
            for horizon in ('1h','4h','24h'):
                flag='evaluated_'+horizon; net='net_outcome_'+horizon+'_pct'
                evaluated=[a for a in rejected if getattr(a,flag)]
                false_rejections=[a for a in evaluated if getattr(a,net) is not None and getattr(a,net)>0]
                right_rejections=[a for a in evaluated if getattr(a,net) is not None and getattr(a,net)<=0]
                accepted_eval=[a for a in accepted if getattr(a,flag) and getattr(a,net) is not None]
                data[horizon]={'evaluated_rejections':len(evaluated),'would_win':len(false_rejections),
                    'likely_correct':len(right_rejections),'false_rejection_rate_pct':100*len(false_rejections)/len(evaluated) if evaluated else None,
                    'accepted_evaluated':len(accepted_eval),'accepted_wins':sum(1 for a in accepted_eval if getattr(a,net)>0),
                    'accepted_net_avg_pct':sum(getattr(a,net) for a in accepted_eval)/len(accepted_eval) if accepted_eval else None}
                for reason,reason_data in data['reasons'].items():
                    reason_rows=[a for a in rejected if reason_key(a)==reason and getattr(a,flag) and getattr(a,net) is not None]
                    reason_wins=[a for a in reason_rows if getattr(a,net)>0]
                    reason_losses=[a for a in reason_rows if getattr(a,net)<=0]
                    reason_data[horizon]={'evaluated':len(reason_rows),'would_win':len(reason_wins),'likely_correct':len(reason_losses),
                        'false_rejection_rate_pct':100*len(reason_wins)/len(reason_rows) if reason_rows else None,
                        'average_net_pct':sum(getattr(a,net) for a in reason_rows)/len(reason_rows) if reason_rows else None}
            audit_stats[mode]=data
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
    for p in capital_positions:
        opened=p.opened_at.replace(tzinfo=timezone.utc) if p.opened_at.tzinfo is None else p.opened_at.astimezone(timezone.utc)
        p.held_minutes=max(0,(now_utc-opened).total_seconds()/60)
        p.invested_usdt=float(p.notional_usdt or abs(p.quantity*p.entry_price))
        p.invested_inr=p.invested_usdt*fx
        p.estimated_margin_inr=p.invested_inr/max(float(p.leverage or 1),1.0) if p.product=='futures' else p.invested_inr
        stop=float(cfg.get('stop_loss_move_pct',0.75))/100
        p.stop_price=p.entry_price*(1-stop if p.side=='buy' else 1+stop)
    for t in capital_trades:
        opened=t.created_at.replace(tzinfo=timezone.utc) if t.created_at.tzinfo is None else t.created_at.astimezone(timezone.utc)
        ended=t.closed_at.replace(tzinfo=timezone.utc) if t.closed_at and t.closed_at.tzinfo is None else (t.closed_at.astimezone(timezone.utc) if t.closed_at else now_utc)
        t.held_minutes=max(0,(ended-opened).total_seconds()/60)
        t.diagnosis=_paper_trade_diagnosis(t)
    for t in trades:
        opened=t.created_at.replace(tzinfo=timezone.utc) if t.created_at.tzinfo is None else t.created_at.astimezone(timezone.utc)
        ended=t.closed_at.replace(tzinfo=timezone.utc) if t.closed_at and t.closed_at.tzinfo is None else (t.closed_at.astimezone(timezone.utc) if t.closed_at else now_utc)
        t.held_minutes=max(0,(ended-opened).total_seconds()/60)
        t.invested_usdt=abs(float(t.quantity or 0)*float(t.entry_price or 0))
        t.invested_inr=t.invested_usdt*fx
        t.diagnosis=_paper_trade_diagnosis(t)
    wins=sum(1 for t in closed if (t.net_pnl_inr or 0)>0)
    losses=sum(1 for t in closed if (t.net_pnl_inr or 0)<0)
    stats={'closed':len(closed),'wins':wins,'losses':losses,'win_rate':(100*wins/len(closed) if closed else None),
           'profit_factor':(sum(t.net_pnl_inr for t in closed if (t.net_pnl_inr or 0)>0)/abs(sum(t.net_pnl_inr for t in closed if (t.net_pnl_inr or 0)<0)) if any((t.net_pnl_inr or 0)<0 for t in closed) else None),
           'net_pnl_inr':sum(t.net_pnl_inr or 0 for t in closed)}
    capital_wins=sum(1 for t in capital_closed if (t.net_pnl_inr or 0)>0)
    capital_losses=abs(sum(t.net_pnl_inr or 0 for t in capital_closed if (t.net_pnl_inr or 0)<0))
    capital_gain=sum(t.net_pnl_inr or 0 for t in capital_closed if (t.net_pnl_inr or 0)>0)
    capital_net=sum(t.net_pnl_inr or 0 for t in capital_closed)
    capital_reserved=sum(float(p.notional_usdt or 0)*fx/max(float(p.leverage or 1),1.0) for p in capital_positions)
    capital_stats={'closed':len(capital_closed),'wins':capital_wins,'losses':sum(1 for t in capital_closed if (t.net_pnl_inr or 0)<0),
        'win_rate':(100*capital_wins/len(capital_closed) if capital_closed else None),
        'profit_factor':(capital_gain/capital_losses if capital_losses>0 else None),'net_pnl_inr':capital_net,
        'open':len(capital_positions),'reserved_margin_inr':capital_reserved,'capital_inr':float(cfg.get('starting_capital_inr',30000)),
        'available_margin_inr':max(0.0,float(cfg.get('starting_capital_inr',30000))-capital_reserved)}
    return templates.TemplateResponse('paper.html',context(request,'paper','Paper Trading',cfg=cfg,runtime=runtime,equity=eq,positions=positions,trades=trades,paper_stats=stats,capital_positions=capital_positions,capital_trades=capital_trades,capital_stats=capital_stats,observation_count=observation_count,audit_stats=audit_stats,recent_audits=recent_audits))

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
            'capital_constrained_open_positions':db.scalar(select(func.count(PaperModePosition.id)).where(PaperModePosition.is_open==True)) or 0,
            'closed_trades':db.scalar(select(func.count(Trade.id)).where(Trade.run_mode=='paper',Trade.status=='closed')) or 0,
            'capital_constrained_closed_trades':db.scalar(select(func.count(Trade.id)).where(Trade.run_mode=='paper_capital',Trade.status=='closed')) or 0}





@app.get('/api/paper-rejection-audit')
def api_paper_rejection_audit(request: Request):
    if not authed(request): return JSONResponse({'error':'login_required'}, status_code=401)
    with SessionLocal() as db:
        audits=db.scalars(select(PaperDecisionAudit).order_by(desc(PaperDecisionAudit.decision_at)).limit(100)).all()
        payload=[]
        for a in audits:
            payload.append({'id':a.id,'at':a.decision_at.isoformat() if a.decision_at else None,'mode':a.mode,
                'product':a.product,'pair':a.pair,'side':a.proposed_side,'decision':a.decision,'reason':a.rejection_reason,
                'expected_move_pct':a.expected_move_pct,'estimated_cost_pct':a.estimated_cost_pct,
                'outcome_1h_pct':a.outcome_1h_pct,'net_outcome_1h_pct':a.net_outcome_1h_pct,'evaluated_1h':a.evaluated_1h,
                'outcome_4h_pct':a.outcome_4h_pct,'net_outcome_4h_pct':a.net_outcome_4h_pct,'evaluated_4h':a.evaluated_4h,
                'outcome_24h_pct':a.outcome_24h_pct,'net_outcome_24h_pct':a.net_outcome_24h_pct,'evaluated_24h':a.evaluated_24h})
        summary={}
        recent_ids=select(PaperDecisionAudit.id).order_by(desc(PaperDecisionAudit.decision_at)).limit(10000).subquery()
        for mode in ('unrestricted','capital_constrained'):
            base=select(func.count(PaperDecisionAudit.id)).where(PaperDecisionAudit.id.in_(select(recent_ids.c.id)),PaperDecisionAudit.mode==mode,PaperDecisionAudit.decision=='rejected')
            summary[mode+'_rejected']=db.scalar(base) or 0
        summary['rejected_would_win_1h']=db.scalar(select(func.count(PaperDecisionAudit.id)).where(
            PaperDecisionAudit.id.in_(select(recent_ids.c.id)),PaperDecisionAudit.decision=='rejected',PaperDecisionAudit.evaluated_1h==True,PaperDecisionAudit.net_outcome_1h_pct>0)) or 0
        summary['rejected_correct_1h']=db.scalar(select(func.count(PaperDecisionAudit.id)).where(
            PaperDecisionAudit.id.in_(select(recent_ids.c.id)),PaperDecisionAudit.decision=='rejected',PaperDecisionAudit.evaluated_1h==True,PaperDecisionAudit.net_outcome_1h_pct<=0)) or 0
        summary['total_decisions']=db.scalar(select(func.count(PaperDecisionAudit.id)).where(PaperDecisionAudit.id.in_(select(recent_ids.c.id)))) or 0
        return {'count':len(payload),'total_decisions':summary['total_decisions'],'summary':summary,'retention_days':90,'decisions':payload}

@app.get('/api/system-health')
def api_system_health(request: Request):
    """Bounded operational telemetry: process RSS, configured memory ceiling, and DB footprint."""
    if not authed(request):
        return JSONResponse({'error':'login_required'}, status_code=401)
    memory_bytes=None
    try:
        with open('/proc/self/status','r',encoding='utf-8') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    memory_bytes=int(line.split()[1])*1024
                    break
    except Exception:
        pass
    memory_limit=int(float(os.getenv('RENDER_MEMORY_LIMIT_MB','512'))*1024*1024)
    db_info={'engine':engine.dialect.name,'database_bytes':None,'table_bytes':None,'allocated_disk_bytes':int(float(os.getenv('DB_DISK_GB','15'))*1024**3),'observation_rows':0,'market_snapshot_rows':0,'trade_rows':0,'event_rows':0,'history_window_days':30,'history_hard_row_cap':100000}
    try:
        with SessionLocal() as db:
            db_info['observation_rows']=db.scalar(select(func.count(MarketObservation.id))) or 0
            db_info['market_snapshot_rows']=db.scalar(select(func.count(MarketSnapshot.id))) or 0
            db_info['trade_rows']=db.scalar(select(func.count(Trade.id))) or 0
            db_info['event_rows']=db.scalar(select(func.count(Event.id))) or 0
            if engine.dialect.name=='postgresql':
                row=db.execute(text("SELECT pg_database_size(current_database()) AS db_bytes")).mappings().first()
                if row: db_info['database_bytes']=int(row['db_bytes'])
                row=db.execute(text("SELECT COALESCE(SUM(pg_total_relation_size((quote_ident(schemaname)||'.'||quote_ident(tablename))::regclass)),0) AS table_bytes FROM pg_tables WHERE schemaname='public'")).mappings().first()
                if row: db_info['table_bytes']=int(row['table_bytes'])
            elif engine.dialect.name=='sqlite':
                row=db.execute(text('PRAGMA page_count')).scalar() or 0
                pagesize=db.execute(text('PRAGMA page_size')).scalar() or 0
                db_info['database_bytes']=int(row*pagesize)
                db_info['table_bytes']=db_info['database_bytes']
    except Exception as exc:
        db_info['error']=str(exc)[:180]
    used=db_info.get('database_bytes')
    db_info['estimated_disk_remaining_bytes']=max(0,db_info['allocated_disk_bytes']-used) if used is not None else None
    return {'as_of':datetime.now(timezone.utc).isoformat(),'process_memory_rss_bytes':memory_bytes,
        'memory_limit_bytes':memory_limit,'memory_used_pct':round(memory_bytes/memory_limit*100,2) if memory_bytes is not None and memory_limit else None,
        'memory_remaining_bytes':max(0,memory_limit-memory_bytes) if memory_bytes is not None else None,'database':db_info,
        'note':'RSS is this web process, not a replacement for Render service-level peak metrics. Database remaining space is an estimate from configured disk size minus database size.'}

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
                candidate_signal=scored.get('signal','NO SCORE')
                signal=candidate_signal
                signal_reason=scored.get('signal_reason','Strategy has not produced a score for this market yet')
                hurdle=_entry_cost_hurdle_pct(product,cfg,snap) if snap and signal in ('LONG','SHORT') and eligible else None
                expected_move=float(scored.get('expected_move_pct') or 0)
                required_move=max(float(cfg.get('min_expected_move_pct',0.75)),
                                  (hurdle if hurdle is not None else 999.0)*float(cfg.get('cost_coverage_multiple',1.5)))
                cost_eligible=bool(signal in ('LONG','SHORT') and hurdle is not None and expected_move >= required_move)
                if signal in ('LONG','SHORT') and eligible and not cost_eligible:
                    signal='WATCH'
                    signal_reason=f'Blocked by cost gate: expected move {expected_move:.2f}% vs required {required_move:.2f}%; round-trip cost estimate {hurdle if hurdle is not None else "unknown"}%.'
                if position:
                    paper_state='OPEN PAPER POSITION'
                elif trade and trade.status=='closed':
                    paper_state='LAST TRADE CLOSED'
                elif candidate_signal in ('LONG','SHORT') and eligible and not cost_eligible:
                    paper_state='BLOCKED BY COST GATE'
                elif signal in ('LONG','SHORT'):
                    paper_state='ELIGIBLE CANDIDATE' if eligible and cost_eligible else 'BLOCKED BY LIQUIDITY / COST GATE'
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
                    'signal':signal,
                    'signal_reason':signal_reason,
                    'expected_move_pct':expected_move if scored else None,
                    'estimated_round_trip_cost_pct':hurdle,
                    'required_move_pct':required_move if candidate_signal in ('LONG','SHORT') and hurdle is not None else None,
                    'cost_eligible':cost_eligible,
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

def _paper_trade_diagnosis(trade):
    metadata=safe_json(trade.metadata_json or '{}')
    if trade.status != 'closed':
        return 'Open paper position; outcome is not known yet.'
    gross=float(trade.gross_pnl_inr or 0)
    net=float(trade.net_pnl_inr or 0)
    costs=float(trade.fees_inr or 0)+float(trade.slippage_inr or 0)+float(trade.funding_inr or 0)
    reason=str(trade.reason or metadata.get('exit_reason') or 'exit reason not recorded')
    entry_score=metadata.get('score')
    momentum=metadata.get('momentum_pct')
    if entry_score is not None and ((trade.side == 'buy' and float(entry_score) < 0) or (trade.side == 'sell' and float(entry_score) > 0)):
        return f'ENTRY-SIGNAL MISMATCH: stored 14D score {float(entry_score):.2f} did not agree with the {trade.side.upper()} direction. This is evidence of a weak/inconsistent entry, not proof of the full intratrade path.'
    if momentum is not None and abs(float(momentum)) >= 100:
        return f'POSSIBLE LATE ENTRY: stored 14D momentum was extreme ({float(momentum):+.1f}%). It may be a spike-chase; candles immediately before entry are unavailable to prove entry timing.'
    if metadata.get('diagnosis'):
        return str(metadata['diagnosis'])
    if gross > 0 and net <= 0:
        return 'Gross trade gain was erased by modeled fees/slippage/funding.'
    if 'hard stop' in reason.lower() or 'persistent loss' in reason.lower():
        return 'Protective stop exit. Older trade has no full sampled path, so the exact first-adverse time is unknown.'
    if 'daily rebalance' in reason.lower():
        return 'Closed by daily rebalance, not a price-triggered profit target; older trade has no full intratrade path to prove whether profit was given back.'
    if 'signal no longer' in reason.lower() or 'direction changed' in reason.lower():
        return 'Closed after signal/cost/trend eligibility changed; older trade has no full intratrade path to prove whether profit was given back.'
    if net < 0:
        return 'Net loss at exit; older trade path is incomplete, so entry quality versus late exit cannot be determined reliably.'
    return 'Net-positive closed trade. Intratrade excursion tracking was not available for this older record.'


@app.get('/ledger', response_class=HTMLResponse)
def ledger_page(request: Request):
    if not authed(request): return RedirectResponse('/login', status_code=303)
    with SessionLocal() as db:
        entries=db.scalars(select(LedgerEntry).order_by(desc(LedgerEntry.occurred_at)).limit(400)).all()
        fills=db.scalars(select(ExecutionFill).order_by(desc(ExecutionFill.occurred_at)).limit(250)).all()
        counts={}
        for status,count in db.execute(select(LedgerEntry.reconciliation_status,func.count(LedgerEntry.id)).group_by(LedgerEntry.reconciliation_status)).all(): counts[status]=count
        runtime=read_config(db,'runtime',{})
        paper_trades=db.scalars(select(Trade).where(Trade.run_mode.in_(['paper','paper_capital'])).order_by(desc(Trade.created_at)).limit(250)).all()
        paper_positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True).order_by(desc(PaperPosition.opened_at))).all()
        capital_positions=db.scalars(select(PaperModePosition).where(PaperModePosition.is_open==True).order_by(desc(PaperModePosition.opened_at))).all()
        cfg=read_config(db,'strategy_config',{})
    now_utc=datetime.now(timezone.utc)
    fx=float(cfg.get('inr_per_usdt',94.75))
    for t in paper_trades:
        opened=t.created_at.replace(tzinfo=timezone.utc) if t.created_at and t.created_at.tzinfo is None else t.created_at
        ended=t.closed_at.replace(tzinfo=timezone.utc) if t.closed_at and t.closed_at.tzinfo is None else (t.closed_at or now_utc)
        t.held_minutes=max(0,(ended-opened).total_seconds()/60) if opened else 0
        t.invested_usdt=abs(float(t.quantity or 0)*float(t.entry_price or 0))
        t.diagnosis=_paper_trade_diagnosis(t)
    needs_review=sum(v for k,v in counts.items() if k not in ('reconciled',))
    return templates.TemplateResponse('ledger.html',context(request,'ledger','Execution Ledger',entries=entries,fills=fills,status_counts=counts,needs_review=needs_review,runtime=runtime,paper_trades=paper_trades,paper_positions=paper_positions,capital_positions=capital_positions))

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
