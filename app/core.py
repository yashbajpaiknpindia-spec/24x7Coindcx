import json, os, math, time, statistics
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from .db import SessionLocal, ConfigKV, Event, MarketSnapshot, PaperPosition, Trade, OrderRecord, BacktestResult, utcnow
from .coindcx import CoinDCXClient, CoinDCXError

PAIR_UNIVERSE = ['B-BTC_USDT','B-ETH_USDT','B-SOL_USDT','B-ZEC_USDT','B-NEAR_USDT','B-XRP_USDT','B-DOGE_USDT','B-BNB_USDT','B-SUI_USDT','B-UNI_USDT','B-STRK_USDT','B-ENA_USDT','B-TRX_USDT','B-WLD_USDT']
STRATEGY_ID = 'CSM14D_VOL14D_LIQ7D_DAILY'
STRATEGY_NAME = '14D Cross-Sectional Momentum / Volatility Rank'
STRATEGY_VERSION = '1.0.0-research-reproduction'

def env_float(k, d):
    try: return float(os.getenv(k, d))
    except Exception: return float(d)

def env_int(k, d):
    try: return int(os.getenv(k, d))
    except Exception: return int(d)

def read_config(db: Session, key: str, default=None):
    row = db.get(ConfigKV, key)
    if not row: return default
    try: return json.loads(row.value)
    except Exception: return default

def write_config(db: Session, key: str, value):
    row = db.get(ConfigKV, key)
    encoded = json.dumps(value, separators=(',', ':'), default=str)
    if row:
        row.value = encoded; row.updated_at = utcnow()
    else: db.add(ConfigKV(key=key, value=encoded))
    db.flush()

def log_event(db: Session, message: str, level='INFO', category='system', details=None):
    db.add(Event(level=level, category=category, message=message[:500], details_json=json.dumps(details or {}, default=str)[:12000]))

def initialize_defaults(db: Session):
    defaults = {
        'strategy_config': {
            'strategy_id': STRATEGY_ID, 'name': STRATEGY_NAME,
            'pair_universe': PAIR_UNIVERSE, 'liquid_universe_size': 8, 'long_count': 3, 'short_count': 3,
            'momentum_days': 14, 'volatility_days': 14, 'turnover_days': 7, 'rebalance_hours': 24,
            'starting_capital_inr': env_float('STARTING_CAPITAL_INR', 30000), 'inr_per_usdt': env_float('INR_PER_USDT', 94.75),
            'futures_leverage': env_float('DEFAULT_FUTURES_LEVERAGE', 1), 'product_mode': 'both',
            'paper_enabled': False, 'research_notional_usdt': env_float('PAPER_RESEARCH_NOTIONAL_USDT', 1000), 'paper_cost_case': 'NORMAL', 'spot_fee_pct': env_float('SPOT_TAKER_FEE_PCT', 0.15),
            'futures_fee_pct': env_float('FUTURES_TAKER_FEE_PCT', 0.075), 'normal_slippage_pct': env_float('NORMAL_SLIPPAGE_PCT', 0.05),
            'stress_slippage_pct': env_float('STRESS_SLIPPAGE_PCT', 0.12), 'funding_stress_pct_per_8h': 0.01,
            'min_quote_turnover_usdt': env_float('MIN_QUOTE_TURNOVER_USDT', 250000), 'max_spread_bps': env_float('MAX_SPREAD_BPS', 50),
            'max_stale_seconds': 120, 'auto_live_armed': False, 'paper_last_cycle': None, 'last_error': None,
        },
        'live_state': {'armed': False, 'armed_at': None, 'typed_confirmation': False, 'auto_live_armed': False},
        'runtime': {'worker_last_heartbeat': None, 'last_market_refresh': None, 'market_refresh_error': None, 'last_strategy_cycle': None, 'worker_started': None},
    }
    for key, value in defaults.items():
        if db.get(ConfigKV, key) is None: write_config(db, key, value)
    seed_backtests(db)
    db.commit()

def seed_backtests(db: Session):
    if os.getenv('SEED_HISTORICAL_RESULTS','true').lower() != 'true': return
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'seed_data', 'backtests.json')
    try:
        rows = json.load(open(path, encoding='utf-8'))
    except Exception: rows = []
    existing={(x.experiment,x.strategy,x.period) for x in db.scalars(select(BacktestResult)).all()}
    added=0
    for r in rows:
        if (r['experiment'],r['strategy'],r['period']) in existing: continue
        db.add(BacktestResult(experiment=r['experiment'], strategy=r['strategy'], period=r['period'], product=r['product'],
          exposure_x=r.get('exposure_x',1), cost_case=r.get('cost_case','NORMAL'), return_pct=r.get('return_pct'), net_pnl_inr=r.get('net_pnl_inr'),
          max_drawdown_pct=r.get('max_drawdown_pct'), adverse_drawdown_pct=r.get('adverse_drawdown_pct'), profit_factor=r.get('profit_factor'),
          avg_daily_pnl_inr=r.get('avg_daily_pnl_inr'), profitable_days_pct=r.get('profitable_days_pct'), notes=r.get('notes',''), metrics_json=json.dumps(r.get('metrics',{}))))
        added+=1
    if added: log_event(db, f'Added {added} historical result snapshots from prior research outputs; snapshots are not reruns.', 'INFO', 'backtest')

def norm_pair(s):
    return ''.join(ch for ch in str(s or '').upper().replace('B-', '') if ch.isalnum())

def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception: return None

def safe_json(s):
    try: return json.loads(s or '{}')
    except Exception: return {}

def market_spread_bps(bid, ask):
    if not bid or not ask or bid <= 0 or ask <= 0 or ask < bid: return None
    return ((ask - bid) / ((ask + bid) / 2.0)) * 10000

def refresh_markets(db: Session):
    client = CoinDCXClient()
    errors = []
    spot_tickers, spot_details, futures_prices, futures_active = [], [], [], []
    spot_books = {}
    def get_spot_tickers(): return client.spot_tickers()
    def get_spot_details(): return client.spot_market_details()
    def get_futures_prices(): return client.futures_prices()
    def get_futures_active(): return client.futures_active_instruments('USDT')
    calls = {'spot_tickers': get_spot_tickers, 'spot_details':get_spot_details, 'futures_prices':get_futures_prices, 'futures_active':get_futures_active}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fn): name for name, fn in calls.items()}
        for f in as_completed(futs):
            name = futs[f]
            try:
                v = f.result()
                if name == 'spot_tickers': spot_tickers = v
                elif name == 'spot_details': spot_details = v
                elif name == 'futures_prices': futures_prices = v
                else: futures_active = v
            except Exception as exc: errors.append(f'{name}: {exc}')

    # Expand beyond the old hard-coded 14-pair list: rank current USDT spot markets
    # by observed quote turnover proxy and scan a configurable broad candidate set.
    # This is a discovery universe, not a claim that every market is tradeable.
    broad_limit = max(20, min(150, env_int('SCAN_UNIVERSE_LIMIT', 60)))
    ranked = []
    for t in spot_tickers if isinstance(spot_tickers, list) else []:
        if not isinstance(t, dict): continue
        name = str(t.get('market') or t.get('pair') or t.get('symbol') or '').upper()
        if not name.endswith('USDT') or not name.startswith('B-'): continue
        price = num(t.get('last_price') or t.get('lastPrice') or t.get('close') or t.get('last'))
        volume = num(t.get('volume') or t.get('base_volume') or t.get('vol'))
        if price and volume is not None and volume >= 0: ranked.append((price*volume, name))
    ranked.sort(reverse=True)
    discovered = [pair for _, pair in ranked[:broad_limit]]
    scan_universe = list(dict.fromkeys(PAIR_UNIVERSE + discovered))

    # Futures price events often omit the top bid/ask. Pull live top-of-book
    # snapshots, otherwise the liquidity filter must reject the market.
    futures_books = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(client.futures_orderbook, pair, 20): pair for pair in scan_universe}
        for f in as_completed(futs):
            pair = futs[f]
            try: futures_books[pair] = f.result()
            except Exception as exc: errors.append(f'futures_book {pair}: {exc}')

    # Capture spot order books as well as futures books so live eligibility can
    # require actual top-of-book/depth information rather than a turnover proxy alone.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(client.spot_orderbook, pair, 20): pair for pair in scan_universe}
        for f in as_completed(futs):
            pair = futs[f]
            try: spot_books[pair] = f.result()
            except Exception as exc: errors.append(f'spot_book {pair}: {exc}')

    def top_of_book(book):
        if not isinstance(book, dict): return (None, None)
        def best(levels, side):
            if isinstance(levels, dict):
                values=[]
                for price, qty in levels.items():
                    try:
                        pp, qq = float(price), float(qty)
                        if pp > 0 and qq >= 0: values.append(pp)
                    except Exception: pass
                return (max(values) if side == 'bid' else min(values)) if values else None
            if isinstance(levels, list):
                values=[]
                for row in levels:
                    try:
                        if isinstance(row, dict): pp=float(row.get('price') or row.get('p') or row.get('rate'))
                        else: pp=float(row[0])
                        if pp > 0: values.append(pp)
                    except Exception: pass
                return (max(values) if side == 'bid' else min(values)) if values else None
            return None
        return best(book.get('bids'), 'bid'), best(book.get('asks'), 'ask')
    ticker_map = {norm_pair(x.get('market') or x.get('pair') or x.get('symbol')): x for x in spot_tickers if isinstance(x, dict)}
    details_map = {norm_pair(x.get('pair') or x.get('market')): x for x in spot_details if isinstance(x, dict)}
    future_map = {norm_pair(x.get('mkt') or x.get('pair') or x.get('market') or x.get('s') or x.get('symbol')): x for x in futures_prices if isinstance(x, dict)}
    if isinstance(futures_active, dict):
        futures_active = futures_active.get('data', futures_active.get('instruments', []))
    # CoinDCX's documented active_instruments response is usually a list of pair
    # strings (e.g. B-BTC_USDT), not a list of metadata dictionaries. Support both
    # response shapes, otherwise the whole futures universe would be falsely marked
    # inactive whenever the endpoint returns its documented string form.
    active_map = {}
    active_set = set()
    if isinstance(futures_active, list):
        for item in futures_active:
            if isinstance(item, dict):
                name = item.get('pair') or item.get('instrument_name') or item.get('symbol') or item.get('market')
                if name:
                    active_map[norm_pair(name)] = item
                    active_set.add(norm_pair(name))
            elif isinstance(item, str) and item.strip():
                active_set.add(norm_pair(item))
    now = utcnow()
    updated = 0
    for pair in scan_universe:
        norm = norm_pair(pair)
        st = ticker_map.get(norm, {})
        detail = details_map.get(norm, {})
        last = num(st.get('last_price') or st.get('lastPrice') or st.get('close') or st.get('last') or st.get('bid'))
        bid = num(st.get('bid')); ask = num(st.get('ask'))
        sbook = spot_books.get(pair, {})
        book_bid, book_ask = top_of_book(sbook)
        bid = bid or book_bid; ask = ask or book_ask
        vol = num(st.get('volume'))
        quote = (vol * last) if vol is not None and last is not None and vol >= 0 else None
        raw = {'spot_ticker':st, 'spot_detail':detail, 'spot_orderbook':sbook}
        row = db.scalar(select(MarketSnapshot).where(MarketSnapshot.product=='spot', MarketSnapshot.pair==pair))
        spot_status=str(detail.get('status') or 'active' if st else 'inactive').lower()
        values = dict(last_price=last, bid=bid, ask=ask, quote_turnover_usdt=quote, liquidity_source='estimated_24h_base_volume_x_last' if quote is not None else 'unknown', active=bool(st) and spot_status=='active', exit_only=False, updated_at=now, raw_json=json.dumps(raw, default=str))
        if row:
            for k,v in values.items(): setattr(row,k,v)
        else: db.add(MarketSnapshot(product='spot', pair=pair, **values))
        updated += 1
        ft = future_map.get(norm, {})
        f_last = num(ft.get('ls') or ft.get('last_price') or ft.get('lastPrice') or ft.get('p') or ft.get('last') or ft.get('mark_price'))
        f_vol = num(ft.get('v') or ft.get('volume'))
        f_quote = (f_vol * f_last) if f_vol is not None and f_last is not None and f_vol >= 0 else None
        book = futures_books.get(pair, {})
        book_bid, book_ask = top_of_book(book)
        f_bid = num(ft.get('bid') or ft.get('best_bid')) or book_bid
        f_ask = num(ft.get('ask') or ft.get('best_ask')) or book_ask
        instr = active_map.get(norm, {})
        instr_status=str(instr.get('status') or '').lower() if isinstance(instr,dict) else ''
        exit_only = bool(ft.get('exit_only') or ft.get('is_exit_only') or (instr.get('exit_only') if isinstance(instr,dict) else False) or (instr.get('is_exit_only') if isinstance(instr,dict) else False) or instr_status=='exit_only')
        active_ok=(norm in active_set) and not exit_only and instr_status not in ('inactive','expired','delisted')
        rawf = {'future_ticker': ft, 'futures_orderbook': book, 'instrument': instr}
        row = db.scalar(select(MarketSnapshot).where(MarketSnapshot.product=='futures', MarketSnapshot.pair==pair))
        values = dict(last_price=f_last, bid=f_bid, ask=f_ask, quote_turnover_usdt=f_quote, liquidity_source='estimated_24h_base_volume_x_last' if f_quote is not None else 'unknown', active=active_ok, exit_only=exit_only, updated_at=now, raw_json=json.dumps(rawf, default=str))
        if row:
            for k,v in values.items(): setattr(row,k,v)
        else: db.add(MarketSnapshot(product='futures', pair=pair, **values))
        updated += 1
    runtime = read_config(db, 'runtime', {})
    runtime.update({'last_market_refresh': now.isoformat(), 'market_refresh_error': '; '.join(errors)[:1000] if errors else None, 'scan_universe_count': len(scan_universe), 'scan_universe_limit': broad_limit, 'scan_universe_pairs': scan_universe, 'scan_universe_source': 'live CoinDCX USDT tickers ranked by volume × last price plus legacy watchlist'})
    write_config(db, 'runtime', runtime)
    if errors: log_event(db, 'Market refresh completed with partial failures.', 'WARNING', 'market_data', {'errors':errors,'snapshots_updated':updated})
    else: log_event(db, f'Market refresh completed ({updated} spot/futures snapshots updated).', 'INFO', 'market_data')
    db.commit()
    return {'updated':updated,'errors':errors}

def market_eligibility(snap: MarketSnapshot, config: dict):
    spread = market_spread_bps(snap.bid, snap.ask)
    if not snap.active: return False, 'not active / not matched by live ticker'
    if snap.exit_only: return False, 'futures instrument is exit-only'
    if snap.last_price is None or snap.last_price <= 0: return False, 'no live price'
    if (utcnow() - (snap.updated_at.replace(tzinfo=timezone.utc) if snap.updated_at.tzinfo is None else snap.updated_at)).total_seconds() > int(config.get('max_stale_seconds',120)):
        return False, 'market snapshot stale'
    min_turn = float(config.get('min_quote_turnover_usdt',250000))
    if snap.quote_turnover_usdt is None: return False, '24h turnover unknown; cannot confirm liquidity'
    if snap.quote_turnover_usdt < min_turn: return False, f'24h turnover below {min_turn:,.0f} USDT proxy threshold'
    max_spread = float(config.get('max_spread_bps',50))
    if spread is not None and spread > max_spread: return False, f'spread {spread:.1f} bps exceeds {max_spread:.1f} bps'
    if spread is None: return False, 'best bid/ask unavailable; spread cannot be verified'
    return True, 'passes configured liquidity/spread checks'

def normalize_candles(rows):
    out=[]
    for row in rows or []:
        try:
            t = float(row.get('time') or row.get('t') or row.get('timestamp') or 0)
            if t < 10_000_000_000: t *= 1000
            c = float(row.get('close') or row.get('c'))
            v = float(row.get('volume') or row.get('v') or row.get('q') or 0)
            if t > 0 and c > 0 and math.isfinite(c) and math.isfinite(v): out.append((int(t),c,v))
        except Exception: continue
    uniq={t:(c,v) for t,c,v in out}
    return sorted([(t,*cv) for t,cv in uniq.items()], key=lambda x:x[0])

def calculate_scores(db: Session, config: dict):
    client = CoinDCXClient()
    runtime = read_config(db, 'runtime', {})
    # Score the exchange-discovered universe as well as the legacy seed list.
    # Previously refresh_markets discovered dozens of pairs but this function
    # continued fetching candles for only the original 14.
    universe = list(dict.fromkeys((config.get('pair_universe') or PAIR_UNIVERSE) + (runtime.get('scan_universe_pairs') or [])))
    frames=[]; fetch_errors=[]
    def load(pair, product):
        rows = client.spot_candles(pair,'1h',500) if product=='spot' else client.futures_candles(pair,60,500)
        return pair, product, normalize_candles(rows)
    jobs=[]
    enabled_products=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for product in ['spot','futures']:
            if product == 'spot' and config.get('product_mode') not in ('spot','both'): continue
            if product == 'futures' and config.get('product_mode') not in ('futures','both'): continue
            enabled_products.append(product)
            for pair in universe: jobs.append(pool.submit(load,pair,product))
        for f in as_completed(jobs):
            try: frames.append(f.result())
            except Exception as exc:
                fetch_errors.append(str(exc)[:240])
                log_event(db, f'Candlestick fetch failed: {exc}', 'WARNING','market_data')
    score_results={}; candle_ready=0; usable_pairs={p:0 for p in enabled_products}; candle_counts={p:0 for p in enabled_products}
    for pair, product, data in frames:
        candle_counts[product] += 1
        if len(data) < (14*24 + 10): continue
        closes=[x[1] for x in data]
        vols=[x[2] for x in data]
        # Exclude the latest possibly-open bar.
        closes=closes[:-1]; vols=vols[:-1]
        if len(closes) < 14*24+2: continue
        candle_ready += 1; usable_pairs[product] += 1
        momentum = closes[-1] / closes[-(14*24+1)] - 1.0
        returns=[]
        for i in range(max(1,len(closes)-14*24),len(closes)):
            if closes[i-1] > 0: returns.append(closes[i]/closes[i-1]-1)
        vol = statistics.pstdev(returns) if len(returns)>2 else 0
        score = momentum / max(vol, 0.0001)
        turnover = statistics.mean([closes[i]*vols[i] for i in range(max(0,len(closes)-7*24),len(closes))])
        score_results.setdefault(product,[]).append({'pair':pair,'score':score,'momentum_pct':momentum*100,'hourly_volatility_pct':vol*100,'turnover_proxy':turnover,'last_price':closes[-1]})
    # Rank by each market's candle-derived turnover proxy, but report actual coverage.
    for product, items in list(score_results.items()):
        items.sort(key=lambda x:x['turnover_proxy'], reverse=True)
        top_n=int(config.get('liquid_universe_size',8))
        liquid=items[:top_n]
        liquid.sort(key=lambda x:x['score'])
        score_results[product]={'liquid_universe':liquid,'all_scored':items,'longs':sorted(liquid,key=lambda x:x['score'],reverse=True)[:int(config.get('long_count',3))],
                               'shorts':liquid[:int(config.get('short_count',3))]}
    score_results['_diagnostics']={'requested_pairs':len(universe),'products_requested':enabled_products,'candle_responses':candle_counts,
        'candle_ready_pairs':usable_pairs,'candle_ready_total':candle_ready,'fetch_error_count':len(fetch_errors),
        'fetch_errors':fetch_errors[:10],'scored_pairs':{k:len(v.get('all_scored',[])) for k,v in score_results.items() if k in ('spot','futures')},
        'as_of':utcnow().isoformat()}
    runtime=read_config(db,'runtime',{})
    runtime['paper_candle_diagnostics']=score_results['_diagnostics']
    write_config(db,'runtime',runtime)
    return score_results

def paper_equity(db: Session, product: str | None = None):
    cfg = read_config(db,'strategy_config',{})
    start=float(cfg.get('starting_capital_inr',30000))
    q=select(Trade).where(Trade.run_mode=='paper')
    if product: q=q.where(Trade.product==product)
    trades=db.scalars(q).all()
    closed=sum(t.net_pnl_inr for t in trades if t.status=='closed')
    open_ids={t.id:t for t in trades if t.status=='open'}
    unrl=0.0
    positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True, *([PaperPosition.product==product] if product else []))).all()
    for p in positions:
        unrl += float(p.last_unrealized_pnl_inr or 0)
        t=open_ids.get(p.trade_id)
        if t:
            unrl -= float(t.fees_inr or 0) + float(t.slippage_inr or 0)
    return {'starting_capital_inr':start,'realized_pnl_inr':closed,'unrealized_pnl_inr':unrl,'equity_inr':start+closed+unrl}

def mark_paper_positions(db: Session):
    cfg=read_config(db,'strategy_config',{})
    fx=float(cfg.get('inr_per_usdt',94.75))
    prices={(s.product,s.pair):s.last_price for s in db.scalars(select(MarketSnapshot)).all()}
    positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True)).all()
    for p in positions:
        price=prices.get((p.product,p.pair))
        if price and p.entry_price:
            direction=1 if p.side=='buy' else -1
            p.last_mark_price=price
            p.last_unrealized_pnl_inr=(price-p.entry_price)*p.quantity*direction*fx
    db.commit()

def _close_paper_position(db: Session, pos: PaperPosition, price: float, cfg: dict, reason='daily rebalance'):
    fx=float(cfg.get('inr_per_usdt',94.75)); lev=float(pos.leverage or 1)
    direction=1 if pos.side=='buy' else -1
    gross=(price-pos.entry_price)*pos.quantity*direction*fx
    fee_pct=float(cfg.get('spot_fee_pct' if pos.product=='spot' else 'futures_fee_pct',0.15 if pos.product=='spot' else 0.075))/100
    slip_pct=float(cfg.get('normal_slippage_pct',0.05))/100 if cfg.get('paper_cost_case','NORMAL')=='NORMAL' else float(cfg.get('stress_slippage_pct',0.12))/100
    entry_notional=float(pos.notional_usdt or abs(pos.quantity*pos.entry_price))
    exit_notional=abs(pos.quantity*price)
    entry_fee=entry_notional*fee_pct*fx; exit_fee=exit_notional*fee_pct*fx
    entry_slip=entry_notional*slip_pct*fx; exit_slip=exit_notional*slip_pct*fx
    held_hours=max(0,(utcnow()-(pos.opened_at.replace(tzinfo=timezone.utc) if pos.opened_at.tzinfo is None else pos.opened_at)).total_seconds()/3600)
    funding=0.0
    if pos.product=='futures' and cfg.get('paper_cost_case')=='STRESS':
        funding=entry_notional*(float(cfg.get('funding_stress_pct_per_8h',0.01))/100)*(held_hours/8)*fx
    trade=db.get(Trade,pos.trade_id) if pos.trade_id else None
    if trade:
        trade.closed_at=utcnow(); trade.exit_price=price; trade.gross_pnl_inr=gross
        trade.fees_inr=entry_fee+exit_fee; trade.slippage_inr=entry_slip+exit_slip; trade.funding_inr=funding
        trade.net_pnl_inr=gross-trade.fees_inr-trade.slippage_inr-funding; trade.status='closed'; trade.reason=reason
    pos.is_open=False; pos.last_mark_price=price; pos.last_unrealized_pnl_inr=0

def run_paper_cycle(db: Session, force: bool = False):
    cfg=read_config(db,'strategy_config',{})
    if not cfg.get('paper_enabled') and not force:
        return {'ok':False,'message':'Paper engine is paused. Enable paper trading first.'}
    scores=calculate_scores(db,cfg)
    diagnostics=scores.get('_diagnostics',{}) if isinstance(scores,dict) else {}
    products={k:v for k,v in scores.items() if k in ('spot','futures') and isinstance(v,dict)}
    if not products:
        ready=diagnostics.get('candle_ready_total',0)
        requested=diagnostics.get('requested_pairs',len(cfg.get('pair_universe',PAIR_UNIVERSE)))
        msg=(f'Strategy cycle skipped: no market produced enough completed 1-hour candles for 14-day scoring '
             f'({ready} pairs candle-ready across {requested} discovered pairs). Check candle readiness and API errors below.')
        runtime=read_config(db,'runtime',{}); runtime['last_strategy_cycle']={'at':utcnow().isoformat(),'status':'skipped','message':msg,'diagnostics':diagnostics}
        runtime['paper_cycle_status']='skipped'; runtime['paper_cycle_message']=msg; runtime['paper_cycle_attempted_at']=utcnow().isoformat(); write_config(db,'runtime',runtime)
        log_event(db,msg,'WARNING','strategy',diagnostics); db.commit()
        return {'ok':False,'message':msg,'diagnostics':diagnostics}
    fx=float(cfg.get('inr_per_usdt',94.75)); starting_eq=paper_equity(db)['equity_inr']
    selected=[]
    if cfg.get('product_mode') in ('spot','both') and 'spot' in products:
        pos=[x for x in products['spot']['longs'] if x['score']>0]
        selected += [('spot',x,'buy',1) for x in pos]
    if cfg.get('product_mode') in ('futures','both') and 'futures' in products:
        lev=float(cfg.get('futures_leverage',1))
        selected += [('futures',x,'buy',lev) for x in products['futures']['longs']]
        selected += [('futures',x,'sell',lev) for x in products['futures']['shorts']]
    # Close/reconcile current paper positions at current fresh, verified market marks.
    positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True)).all()
    snap_map={(x.product,x.pair):x for x in db.scalars(select(MarketSnapshot)).all()}
    for p in positions:
        snap=snap_map.get((p.product,p.pair))
        if snap and snap.last_price and (utcnow()-(snap.updated_at.replace(tzinfo=timezone.utc) if snap.updated_at.tzinfo is None else snap.updated_at)).total_seconds()<int(cfg.get('max_stale_seconds',120)):
            _close_paper_position(db,p,float(snap.last_price),cfg)
        else:
            log_event(db,f'Cannot close paper position {p.product} {p.pair}: no fresh mark; preserving it.', 'WARNING','paper')
    db.flush()
    eq=paper_equity(db)['equity_inr']
    # Only select candidates with current snapshot and active, liquid market checks.
    viable=[]
    for product, item, side, lev in selected:
        snap=snap_map.get((product,item['pair']))
        ok,why=market_eligibility(snap,cfg) if snap else (False,'no market snapshot')
        if ok: viable.append((product,item,side,lev,snap))
        else: log_event(db,f'Skipped paper entry {product} {item["pair"]}: {why}', 'WARNING','strategy')
    futures= [x for x in viable if x[0]=='futures']; spots=[x for x in viable if x[0]=='spot']
    for product, items in [('futures',futures),('spot',spots)]:
        if not items: continue
        # Research paper book is intentionally not constrained by configured capital.
        # Each signal gets a fixed notional so aggregate strategy capacity can be measured;
        # the separate Capital page continues to show account-sized exposure/equity.
        # This is simulation only and does not imply real margin availability.
        each_notional=float(cfg.get('research_notional_usdt', 1000.0))
        for product,item,side,lev,snap in items:
            price=float(snap.last_price); qty=each_notional/price
            fee_pct=float(cfg.get('spot_fee_pct' if product=='spot' else 'futures_fee_pct',0.15 if product=='spot' else 0.075))/100
            slip_pct=float(cfg.get('normal_slippage_pct',0.05))/100 if cfg.get('paper_cost_case','NORMAL')=='NORMAL' else float(cfg.get('stress_slippage_pct',0.12))/100
            fees=each_notional*fee_pct*fx; slips=each_notional*slip_pct*fx
            trade=Trade(run_mode='paper',product=product,pair=item['pair'],side=side,quantity=qty,entry_price=price,leverage=lev,
                        fees_inr=fees,slippage_inr=slips,net_pnl_inr=-(fees+slips),gross_pnl_inr=0,status='open',strategy=STRATEGY_ID,
                        reason='entry: daily UTC cross-sectional rebalance',metadata_json=json.dumps({'score':item['score'],'momentum_pct':item['momentum_pct'],'liquidity_turnover_proxy':item['turnover_proxy']}))
            db.add(trade); db.flush()
            db.add(PaperPosition(product=product,pair=item['pair'],side=side,quantity=qty,entry_price=price,notional_usdt=each_notional,leverage=lev,
                                 opened_at=utcnow(),strategy=STRATEGY_ID,trade_id=trade.id,last_mark_price=price,last_unrealized_pnl_inr=0,is_open=True))
    cfg['paper_last_cycle']=utcnow().isoformat(); cfg['last_error']=None; write_config(db,'strategy_config',cfg)
    runtime=read_config(db,'runtime',{})
    runtime['last_strategy_cycle']={'at':utcnow().isoformat(),'status':'ok','scan_universe_count':runtime.get('scan_universe_count',0),'signals':{k:len(v.get('all_scored',[])) for k,v in products.items()},'opened_positions':len(viable),'selected_signals':len(selected),'eligible_signals':len(viable),'candle_diagnostics':diagnostics}
    runtime['paper_cycle_status']='completed'
    runtime['paper_cycle_message']=f'Cycle completed; scored {sum(len(v.get("all_scored",[])) for v in products.values())} pairs and opened {len(viable)} positions.'
    runtime['paper_cycle_attempted_at']=utcnow().isoformat(); write_config(db,'runtime',runtime)
    log_event(db,f'Paper strategy cycle completed: {len(viable)} candidate positions opened across enabled products.', 'INFO','paper', {'strategy':STRATEGY_ID,'selected':[{ 'product':p,'pair':i['pair'],'side':s,'score':i['score']} for p,i,s,l,ss in viable], 'diagnostics':diagnostics})
    db.commit()
    return {'ok':True,'message':f'Paper strategy cycle complete; opened {len(viable)} positions.','signals':products,'opened_positions':len(viable),'diagnostics':diagnostics}

def dashboard_summary(db: Session):
    cfg=read_config(db,'strategy_config',{}); live=read_config(db,'live_state',{}); runtime=read_config(db,'runtime',{})
    markets=db.scalars(select(MarketSnapshot)).all()
    fresh=0; eligible=0
    for s in markets:
        age=(utcnow()-(s.updated_at.replace(tzinfo=timezone.utc) if s.updated_at.tzinfo is None else s.updated_at)).total_seconds()
        if age<120: fresh+=1
        ok,_=market_eligibility(s,cfg)
        eligible+=int(ok)
    eq=paper_equity(db)
    open_trades=db.scalar(select(func.count(Trade.id)).where(Trade.status=='open',Trade.run_mode=='paper')) or 0
    closed=db.scalars(select(Trade).where(Trade.status=='closed',Trade.run_mode=='paper')).all()
    wins=sum(1 for t in closed if (t.net_pnl_inr or 0)>0)
    losses=sum(1 for t in closed if (t.net_pnl_inr or 0)<0)
    gross_wins=sum(t.net_pnl_inr for t in closed if (t.net_pnl_inr or 0)>0)
    gross_losses=abs(sum(t.net_pnl_inr for t in closed if (t.net_pnl_inr or 0)<0))
    pf=(gross_wins/gross_losses) if gross_losses>0 else None
    return {'config':cfg,'live':live,'runtime':runtime,'market_count':len(markets),'fresh_markets':fresh,'eligible_markets':eligible,'paper_equity':eq,'open_paper_trades':open_trades,'closed_paper_trades':len(closed),'win_rate':(wins/len(closed)*100 if closed else None),'profit_factor':pf}
