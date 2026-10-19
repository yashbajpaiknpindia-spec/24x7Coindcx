import json, os, math, time, statistics
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import select, desc, func, delete
from sqlalchemy.orm import Session
from collections import defaultdict
from .db import SessionLocal, ConfigKV, Event, MarketSnapshot, PaperPosition, PaperModePosition, MarketObservation, PaperDecisionAudit, Trade, ScalpTrade, ScalpScanSnapshot, OrderRecord, BacktestResult, utcnow
from .coindcx import CoinDCXClient, CoinDCXError

PAIR_UNIVERSE = ['B-BTC_USDT','B-ETH_USDT','B-SOL_USDT','B-ZEC_USDT','B-NEAR_USDT','B-XRP_USDT','B-DOGE_USDT','B-BNB_USDT','B-SUI_USDT','B-UNI_USDT','B-STRK_USDT','B-ENA_USDT','B-TRX_USDT','B-WLD_USDT']
STRATEGY_ID = 'CSM14D_VOL14D_LIQ7D_DAILY'
STRATEGY_NAME = '14D Cross-Sectional Momentum / Volatility Rank'
STRATEGY_VERSION = '1.0.0-research-reproduction'
PAPER_ENGINE_VERSION = '1.6.0-dual-ledger-storage-telemetry'
SCALPER_VERSION = '0.1.0-paper-fast-scalper'
SCALPER_DEFAULTS = {
    'scalper_enabled': True,
    'scalper_notional_usdt': 100.0,
    'scalper_max_open_positions': 3,
    'scalper_research_enabled': True,
    'scalper_research_notional_usdt': 100.0,
    'scalper_research_max_open_positions': 3,
    'scalper_capital_enabled': True,
    'scalper_capital_notional_usdt': 30.0,
    'scalper_capital_max_open_positions': 3,
    'scalper_min_turnover_usdt': 250000.0,
    'scalper_max_spread_bps': 8.0,
    'scalper_min_cost_multiple': 1.0,
    'scalper_min_signal_move_pct': 0.05,
    'scalper_target_net_pct': 0.15,
    'scalper_stop_net_pct': 0.40,
    'scalper_max_hold_minutes': 15,
    'scalper_pair_cooldown_minutes': 5,
    'scalper_spot_fee_pct': 0.15,
    'scalper_futures_fee_pct': 0.075,
    'scalper_fee_gst_pct': 18.0,  # GST on exchange trading fees, subject to the actual account/venue invoice.
    'scalper_normal_slippage_pct': 0.05,
    'scalper_stress_slippage_pct': 0.12,
    'scalper_spot_tax_pct': 31.2,  # 30% VDA tax plus 4% cess, before any surcharge.
    'scalper_futures_tax_pct': 31.2,  # Editable slab/cess planning estimate, not a fixed statutory rate.
    'scalper_tds_pct': 1,  # Display-only estimate for spot transfers; not deducted from P&L.

}
# Pegged stablecoins have a near-zero volatility denominator in momentum/volatility
# ranks, which can manufacture large scores from tiny price noise. Keep them visible
# in the market scanner, but don't allow them into trend strategy candidates.
STABLECOIN_BASE_ASSETS = frozenset({
    'USDC','USD1','USDE','USDD','USDS','USDP','FDUSD','TUSD','DAI','BUSD',
    'PYUSD','RLUSD','EURC','EURI','USDQ','USDX','USDK','USDT'
})

def strategy_pair_exclusion_reason(pair):
    token = str(pair or '').upper().split('_', 1)[0]
    if token.startswith('B-'):
        token = token[2:]
    if token in STABLECOIN_BASE_ASSETS:
        return 'Stablecoin base asset excluded from momentum entries; kept visible in market scan'
    return None

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
            'max_stale_seconds': 120, 'stop_loss_move_pct': 0.75, 'persistent_loss_move_pct': 0.35, 'persistent_loss_observations': 3, 'min_expected_move_pct': 0.75, 'cost_coverage_multiple': 1.5, 'auto_live_armed': False, 'paper_last_cycle': None, 'last_error': None,
        },
        'live_state': {'armed': False, 'armed_at': None, 'typed_confirmation': False, 'auto_live_armed': False},
        'runtime': {'worker_last_heartbeat': None, 'last_market_refresh': None, 'market_refresh_error': None, 'last_strategy_cycle': None, 'worker_started': None},
    }
    for key, value in defaults.items():
        if db.get(ConfigKV, key) is None: write_config(db, key, value)
    # Add new strategy settings to an existing deployment without overwriting user choices.
    strategy_cfg=read_config(db, 'strategy_config', {})
    changed=False
    for setting, default_value in SCALPER_DEFAULTS.items():
        if setting not in strategy_cfg:
            strategy_cfg[setting]=default_value
            changed=True
    # One-time migration: the first deployed default reserved 30% but omitted
    # the 4% cess. Correct only that untouched default, not a value user changed.
    if strategy_cfg.get('scalper_spot_tax_default_version') is None:
        if float(strategy_cfg.get('scalper_spot_tax_pct', 31.2) or 0) == 30.0:
            strategy_cfg['scalper_spot_tax_pct']=31.2
        strategy_cfg['scalper_spot_tax_default_version']='30pct-plus-cess-v1'
        changed=True
    # One-time upgrades migrate only untouched prior defaults, never user-customized values.
    if strategy_cfg.get('scalper_logic_version') != 'persistence-v3':
        if float(strategy_cfg.get('scalper_min_signal_move_pct', 0.25) or 0) == 0.25:
            strategy_cfg['scalper_min_signal_move_pct'] = 0.05
            changed = True
        if float(strategy_cfg.get('scalper_min_turnover_usdt', 250000) or 0) == 1_000_000.0:
            strategy_cfg['scalper_min_turnover_usdt'] = 250_000.0
            changed = True
        if float(strategy_cfg.get('scalper_max_spread_bps', 8) or 0) == 5.0:
            strategy_cfg['scalper_max_spread_bps'] = 8.0
            changed = True
        if strategy_cfg.get('scalper_spot_tax_default_version') != 'custom' and float(strategy_cfg.get('scalper_futures_tax_pct', 30) or 0) == 30.0:
            strategy_cfg['scalper_futures_tax_pct'] = 31.2
            changed = True
        strategy_cfg['scalper_logic_version'] = 'persistence-v3'
        changed = True
    if changed:
        write_config(db, 'strategy_config', strategy_cfg)
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
    # Public CoinDCX spot tickers use concatenated symbols (BTCUSDT), while app
    # pairs use B-BTC_USDT. Map via market details before ranking; otherwise the
    # scanner silently falls back to the legacy 14-pair watchlist.
    details_by_ticker = {}
    for detail in spot_details if isinstance(spot_details, list) else []:
        if not isinstance(detail, dict): continue
        ticker_name = detail.get('coindcx_name') or detail.get('market') or detail.get('symbol') or detail.get('pair')
        target = str(detail.get('target_currency_short_name') or '').upper().strip()
        quote = str(detail.get('base_currency_short_name') or '').upper().strip()
        if ticker_name:
            details_by_ticker[norm_pair(ticker_name)] = detail
        if ticker_name and target and quote:
            details_by_ticker[norm_pair(ticker_name)]['_canonical_pair'] = f'B-{target}_{quote}'

    ranked = []
    for t in spot_tickers if isinstance(spot_tickers, list) else []:
        if not isinstance(t, dict): continue
        raw_name = str(t.get('market') or t.get('pair') or t.get('symbol') or '').upper().strip()
        if not raw_name: continue
        detail = details_by_ticker.get(norm_pair(raw_name), {})
        canonical = str(detail.get('_canonical_pair') or '').upper()
        if raw_name.startswith('B-') and raw_name.endswith('_USDT'):
            pair = raw_name
        elif canonical.startswith('B-') and canonical.endswith('_USDT'):
            pair = canonical
        elif raw_name.endswith('USDT') and len(raw_name) > 4:
            pair = f'B-{raw_name[:-4]}_USDT'
        else:
            continue
        if not pair.startswith('B-') or not pair.endswith('_USDT'): continue
        price = num(t.get('last_price') or t.get('lastPrice') or t.get('close') or t.get('last'))
        volume = num(t.get('volume') or t.get('base_volume') or t.get('vol'))
        if price is not None and price > 0 and volume is not None and volume >= 0:
            # On the USDT-quoted ticker this field is already the exchange-reported
            # 24h volume/turnover proxy. Multiplying by price would square the
            # scale (e.g. BTC's ~$721m reported volume became ~$58t).
            ranked.append((volume, pair))
    ranked.sort(reverse=True)
    discovered = list(dict.fromkeys(pair for _, pair in ranked))
    # The configured limit is the total unique universe, not 60 + the seed watchlist.
    scan_universe = discovered[:broad_limit]
    for seed_pair in PAIR_UNIVERSE:
        if len(scan_universe) >= broad_limit: break
        if seed_pair not in scan_universe: scan_universe.append(seed_pair)
    if not scan_universe: scan_universe = PAIR_UNIVERSE[:broad_limit]

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
    details_map = {norm_pair(x.get('coindcx_name') or x.get('pair') or x.get('market') or x.get('symbol')): x for x in spot_details if isinstance(x, dict)}
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
        quote = vol if vol is not None and vol >= 0 else None
        raw = {'spot_ticker':st, 'spot_detail':detail, 'spot_orderbook':sbook}
        row = db.scalar(select(MarketSnapshot).where(MarketSnapshot.product=='spot', MarketSnapshot.pair==pair))
        spot_status=str(detail.get('status') or 'active' if st else 'inactive').lower()
        values = dict(last_price=last, bid=bid, ask=ask, quote_turnover_usdt=quote, liquidity_source='reported_24h_ticker_volume_usdt_pair' if quote is not None else 'unknown', active=bool(st) and spot_status=='active', exit_only=False, updated_at=now, raw_json=json.dumps(raw, default=str))
        if row:
            for k,v in values.items(): setattr(row,k,v)
        else: db.add(MarketSnapshot(product='spot', pair=pair, **values))
        updated += 1
        ft = future_map.get(norm, {})
        f_last = num(ft.get('ls') or ft.get('last_price') or ft.get('lastPrice') or ft.get('p') or ft.get('last') or ft.get('mark_price'))
        f_vol = num(ft.get('v') or ft.get('volume'))
        f_quote = f_vol if f_vol is not None and f_vol >= 0 else None
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
        values = dict(last_price=f_last, bid=f_bid, ask=f_ask, quote_turnover_usdt=f_quote, liquidity_source='reported_24h_futures_volume_usdt_pair' if f_quote is not None else 'unknown', active=active_ok, exit_only=exit_only, updated_at=now, raw_json=json.dumps(rawf, default=str))
        if row:
            for k,v in values.items(): setattr(row,k,v)
        else: db.add(MarketSnapshot(product='futures', pair=pair, **values))
        updated += 1
    # Sample each pair at most once every 5 minutes. A per-minute row for every
    # scanned pair would crowd out 24h counterfactuals on a small Postgres disk.
    last_obs_rows=db.execute(select(MarketObservation.product,MarketObservation.pair,func.max(MarketObservation.observed_at)).group_by(MarketObservation.product,MarketObservation.pair)).all()
    last_obs={(product,pair):(ts.replace(tzinfo=timezone.utc) if ts and ts.tzinfo is None else ts) for product,pair,ts in last_obs_rows}
    for snap in db.scalars(select(MarketSnapshot)).all():
        previous=last_obs.get((snap.product,snap.pair))
        if previous and (now-previous).total_seconds()<300:
            continue
        db.add(MarketObservation(observed_at=now, product=snap.product, pair=snap.pair,
            last_price=snap.last_price, bid=snap.bid, ask=snap.ask,
            turnover_usdt=snap.quote_turnover_usdt, active=snap.active,
            source_updated_at=snap.updated_at))
    db.flush()
    # Retain up to 30 days, with a 500k-row hard cap (roughly ten days at the current 176-pair universe).
    db.execute(delete(MarketObservation).where(MarketObservation.observed_at < now - timedelta(days=30)))
    observation_count = db.scalar(select(func.count(MarketObservation.id))) or 0
    if observation_count > 500000:
        excess = observation_count - 500000
        oldest_ids = select(MarketObservation.id).order_by(MarketObservation.observed_at.asc(), MarketObservation.id.asc()).limit(excess)
        db.execute(delete(MarketObservation).where(MarketObservation.id.in_(oldest_ids)))
    # Evaluate pending counterfactuals on every market refresh, not just strategy rebalance.
    evaluate_paper_decision_audits(db, read_config(db,'strategy_config',{}))
    runtime = read_config(db, 'runtime', {})
    runtime.update({'last_market_refresh': now.isoformat(), 'market_refresh_error': '; '.join(errors)[:1000] if errors else None, 'scan_universe_count': len(scan_universe), 'scan_universe_limit': broad_limit, 'scan_universe_pairs': scan_universe, 'scan_universe_source': 'live CoinDCX USDT tickers ranked by reported 24h volume (no price multiplier)'})
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

def _scalp_fee_pct(product: str, config: dict):
    key = 'scalper_spot_fee_pct' if product == 'spot' else 'scalper_futures_fee_pct'
    fallback = 'spot_fee_pct' if product == 'spot' else 'futures_fee_pct'
    return max(0.0, float(config.get(key, config.get(fallback, 0.15 if product == 'spot' else 0.075))))


def _scalp_fee_cost_pct(product: str, config: dict):
    """Trading fee plus 18% GST on the fee; not GST on trade notional."""
    fee = _scalp_fee_pct(product, config)
    gst_pct = max(0.0, float(config.get('scalper_fee_gst_pct', 18.0)))
    return fee * (1.0 + gst_pct / 100.0)


def _scalp_slippage_pct(config: dict):
    normal = config.get('scalper_cost_case', config.get('paper_cost_case', 'NORMAL')) != 'STRESS'
    key = 'scalper_normal_slippage_pct' if normal else 'scalper_stress_slippage_pct'
    fallback = 'normal_slippage_pct' if normal else 'stress_slippage_pct'
    return max(0.0, float(config.get(key, config.get(fallback, 0.05 if normal else 0.12))))


def _scalp_orderbook_depth(snap, side, levels=10):
    """Return USDT value in the best N displayed levels on each side; None if unknown."""
    try:
        raw = json.loads(snap.raw_json or '{}') if isinstance(snap.raw_json, str) else (snap.raw_json or {})
        book = raw.get('spot_orderbook' if snap.product == 'spot' else 'futures_orderbook') or {}
        rows = book.get('bids' if side == 'buy' else 'asks')
        values = []
        if isinstance(rows, dict):
            for price, qty in rows.items():
                p, q = float(price), float(qty)
                if p > 0 and q > 0 and math.isfinite(p) and math.isfinite(q):
                    values.append((p, q))
        elif isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    p = float(row.get('price') or row.get('p') or row.get('rate') or 0)
                    q = float(row.get('quantity') or row.get('qty') or row.get('amount') or row.get('q') or 0)
                else:
                    p, q = float(row[0]), float(row[1])
                if p > 0 and q > 0 and math.isfinite(p) and math.isfinite(q):
                    values.append((p, q))
        if not values:
            return None
        values.sort(key=lambda x: x[0], reverse=(side == 'buy'))
        return sum(p*q for p, q in values[:max(1, int(levels))])
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def _scalp_required_move_pct(product: str, config: dict, snap: MarketSnapshot):
    """Move required to cover spread/fees/slippage/tax reserve and target; not a forecast."""
    spread_bps = market_spread_bps(snap.bid, snap.ask)
    if spread_bps is None:
        return None
    spread_pct = spread_bps / 100.0
    fees = 2.0 * _scalp_fee_cost_pct(product, config)
    slips = 2.0 * _scalp_slippage_pct(config)
    target = max(0.0, float(config.get('scalper_target_net_pct', 0.15)))
    tax_key = 'scalper_spot_tax_pct' if product == 'spot' else 'scalper_futures_tax_pct'
    tax = min(0.95, max(0.0, float(config.get(tax_key, 31.2))/100.0))
    if product == 'spot':
        return spread_pct + (fees + slips + target) / max(0.05, 1.0-tax)
    return spread_pct + fees + slips + target / max(0.05, 1.0-tax)


def _scalp_estimated_net_pct(product: str, config: dict, snap: MarketSnapshot, directional_move_pct: float):
    spread = (market_spread_bps(snap.bid, snap.ask) or 0.0) / 100.0
    move = max(0.0, float(directional_move_pct))
    fees = 2.0 * _scalp_fee_cost_pct(product, config)
    slippage = 2.0 * _scalp_slippage_pct(config)
    tax_key = 'scalper_spot_tax_pct' if product == 'spot' else 'scalper_futures_tax_pct'
    tax = min(0.95, max(0.0, float(config.get(tax_key, 31.2))/100.0))
    gross_after_spread = move - spread
    if product == 'spot':
        return gross_after_spread - fees - slippage - max(0.0, gross_after_spread)*tax
    pre_tax_net = gross_after_spread - fees - slippage
    return pre_tax_net - max(0.0, pre_tax_net)*tax


def _entry_cost_hurdle_pct(product: str, config: dict, snap: MarketSnapshot):
    # Shared paper-strategy cost hurdle remains tied to its own paper settings.
    fee = float(config.get('spot_fee_pct' if product == 'spot' else 'futures_fee_pct', 0.15 if product == 'spot' else 0.075))
    slip = float(config.get('normal_slippage_pct', 0.05)) if config.get('paper_cost_case', 'NORMAL') == 'NORMAL' else float(config.get('stress_slippage_pct', 0.12))
    spread_bps = market_spread_bps(snap.bid, snap.ask)
    if spread_bps is None:
        return None
    return 2.0 * (fee + slip) + spread_bps / 100.0


def _scalp_cost_hurdle_pct(product: str, config: dict, snap: MarketSnapshot):
    spread_bps = market_spread_bps(snap.bid, snap.ask)
    if spread_bps is None:
        return None
    return 2.0 * (_scalp_fee_cost_pct(product, config) + _scalp_slippage_pct(config)) + spread_bps / 100.0

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
    # Score the same unique market universe shown by the scanner. The live
    # discovery list is already ranked and capped; seeds are only a fallback
    # when discovery has not run yet, otherwise prepending them can silently
    # inflate 60 markets to 74 and change the ranked opportunities.
    discovered = runtime.get('scan_universe_pairs') or []
    if discovered:
        universe = list(dict.fromkeys(discovered))
    else:
        universe = list(dict.fromkeys(config.get('pair_universe') or PAIR_UNIVERSE))
    universe_limit = max(20, min(150, int(runtime.get('scan_universe_limit') or env_int('SCAN_UNIVERSE_LIMIT', 60))))
    universe = universe[:universe_limit]
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
        momentum_24h = closes[-1] / closes[-25] - 1.0
        momentum_72h = closes[-1] / closes[-73] - 1.0
        returns=[]
        for i in range(max(1,len(closes)-14*24),len(closes)):
            if closes[i-1] > 0: returns.append(closes[i]/closes[i-1]-1)
        vol = statistics.pstdev(returns) if len(returns)>2 else 0
        score = momentum / max(vol, 0.0001)
        turnover = statistics.mean([closes[i]*vols[i] for i in range(max(0,len(closes)-7*24),len(closes))])
        exclusion_reason = strategy_pair_exclusion_reason(pair)
        score_results.setdefault(product,[]).append({
            'pair':pair,'score':score,'momentum_pct':momentum*100,
            'momentum_24h_pct':momentum_24h*100,'momentum_72h_pct':momentum_72h*100,
            'expected_move_pct':max(abs(momentum_24h)*0.75, vol*math.sqrt(24)*0.75)*100,
            'hourly_volatility_pct':vol*100,'turnover_proxy':turnover,
            'last_price':closes[-1], 'strategy_eligible':not bool(exclusion_reason),
            'exclusion_reason':exclusion_reason
        })
    # Rank by each market's candle-derived turnover proxy, but report actual coverage.
    for product, items in list(score_results.items()):
        items.sort(key=lambda x:x['turnover_proxy'], reverse=True)
        strategy_items=[x for x in items if x.get('strategy_eligible',True)]
        top_n=int(config.get('liquid_universe_size',8))
        liquid=strategy_items[:top_n]
        liquid.sort(key=lambda x:x['score'])
        score_results[product]={'liquid_universe':liquid,'all_scored':items,'longs':sorted(liquid,key=lambda x:x['score'],reverse=True)[:int(config.get('long_count',3))],
                               'shorts':liquid[:int(config.get('short_count',3))]}
    # Persist the scored rows for a live UI table, independently of the paper rebalance.
    strategy_scan = {}
    for product in ('spot', 'futures'):
        result = score_results.get(product)
        if not isinstance(result, dict):
            strategy_scan[product] = []
            continue
        items = result.get('all_scored', [])
        liquid_pairs = {x['pair'] for x in result.get('liquid_universe', [])}
        long_pairs = {x['pair'] for x in result.get('longs', [])}
        short_pairs = {x['pair'] for x in result.get('shorts', [])}
        ranked_score = sorted(items, key=lambda x: x.get('score', 0), reverse=True)
        score_rank = {x['pair']: i + 1 for i, x in enumerate(ranked_score)}
        rows = []
        for item in items:
            pair = item['pair']
            if not item.get('strategy_eligible', True):
                side, reason = 'EXCLUDED', item.get('exclusion_reason') or 'Excluded from strategy entries'
            else:
                side, reason = 'NONE', 'Outside the strategy shortlist'
            if item.get('strategy_eligible', True) and product == 'spot' and pair in long_pairs:
                if item.get('score', 0) > 0:
                    side, reason = 'LONG', 'Positive-score leader in the liquidity shortlist'
                else:
                    side, reason = 'WATCH', 'Shortlist leader but score is not positive; spot is long-only'
            elif item.get('strategy_eligible', True) and product == 'futures' and pair in long_pairs and item.get('score', 0) > 0 and item.get('momentum_72h_pct', 0) > 0 and item.get('momentum_24h_pct', 0) > 0:
                side, reason = 'LONG', 'Positive 14D score with 72H and 24H trend confirmation'
            elif item.get('strategy_eligible', True) and product == 'futures' and pair in short_pairs and item.get('score', 0) < 0 and item.get('momentum_72h_pct', 0) < 0 and item.get('momentum_24h_pct', 0) < 0:
                side, reason = 'SHORT', 'Negative 14D score with 72H and 24H trend confirmation'
            elif item.get('strategy_eligible', True) and product == 'futures' and (pair in long_pairs or pair in short_pairs):
                side, reason = 'WATCH', 'Ranked candidate rejected: trend windows do not agree'
            elif item.get('strategy_eligible', True) and pair in liquid_pairs:
                side, reason = 'WATCH', 'In the liquidity shortlist but not selected by signal rank'
            rows.append({**item, 'signal': side, 'signal_reason': reason,
                         'liquid_shortlist': pair in liquid_pairs, 'strategy_rank': score_rank.get(pair)})
        strategy_scan[product] = rows

    score_results['_diagnostics']={'requested_pairs':len(universe),'products_requested':enabled_products,'candle_responses':candle_counts,
        'candle_ready_pairs':usable_pairs,'candle_ready_total':candle_ready,'fetch_error_count':len(fetch_errors),
        'fetch_errors':fetch_errors[:10],'scored_pairs':{k:len(v.get('all_scored',[])) for k,v in score_results.items() if k in ('spot','futures')},
        'as_of':utcnow().isoformat()}
    runtime=read_config(db,'runtime',{})
    runtime['paper_candle_diagnostics']=score_results['_diagnostics']
    runtime['paper_strategy_scan']={'as_of':score_results['_diagnostics']['as_of'],'strategy_id':STRATEGY_ID,'products':strategy_scan}
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
    """Mark paper positions and enforce protective exits on every fresh market poll."""
    cfg = read_config(db, 'strategy_config', {})
    fx = float(cfg.get('inr_per_usdt', 94.75))
    now = utcnow()
    snapshots = {(s.product, s.pair): s for s in db.scalars(select(MarketSnapshot)).all()}
    positions = db.scalars(select(PaperPosition).where(PaperPosition.is_open == True)).all()
    constrained_positions = db.scalars(select(PaperModePosition).where(PaperModePosition.is_open == True)).all()
    all_positions = positions + constrained_positions
    closed = 0
    for pos in all_positions:
        snap = snapshots.get((pos.product, pos.pair))
        if not snap or not snap.last_price or not pos.entry_price:
            continue
        updated = snap.updated_at.replace(tzinfo=timezone.utc) if snap.updated_at.tzinfo is None else snap.updated_at
        if (now - updated).total_seconds() > int(cfg.get('max_stale_seconds', 120)):
            continue
        last = float(snap.last_price)
        # Use the executable side of the book for stop decisions, not a mid/last-price fantasy fill.
        exit_price = float(snap.bid if pos.side == 'buy' else snap.ask) if (snap.bid if pos.side == 'buy' else snap.ask) else last
        direction = 1 if pos.side == 'buy' else -1
        pos.last_mark_price = last
        pos.last_unrealized_pnl_inr = (last - pos.entry_price) * pos.quantity * direction * fx
        adverse_move_pct = ((exit_price / pos.entry_price) - 1.0) * direction * 100.0
        trade = db.get(Trade, pos.trade_id) if pos.trade_id else None
        metadata = safe_json(trade.metadata_json if trade else '{}')
        persistent_threshold = float(cfg.get('persistent_loss_move_pct', 0.35))
        adverse_count = int(metadata.get('consecutive_adverse_observations', 0) or 0)
        if adverse_move_pct <= -persistent_threshold:
            adverse_count += 1
        else:
            adverse_count = 0
        # Persist sampled trade path so closed trades can explain entry quality and giveback.
        if metadata.get('first_observed_move_pct') is None:
            metadata['first_observed_move_pct'] = round(adverse_move_pct, 5)
            metadata['first_observed_at'] = now.isoformat()
        metadata['best_favorable_move_pct'] = round(max(float(metadata.get('best_favorable_move_pct', 0.0) or 0.0), adverse_move_pct), 5)
        metadata['worst_adverse_move_pct'] = round(min(float(metadata.get('worst_adverse_move_pct', 0.0) or 0.0), adverse_move_pct), 5)
        metadata['max_giveback_from_peak_pct'] = round(max(0.0, float(metadata.get('best_favorable_move_pct', 0.0) or 0.0) - adverse_move_pct), 5)
        metadata['consecutive_adverse_observations'] = adverse_count
        metadata['last_adverse_move_pct'] = round(adverse_move_pct, 5)
        metadata['last_risk_check_at'] = now.isoformat()
        if trade:
            trade.metadata_json = json.dumps(metadata, separators=(',', ':'), default=str)
        stop_pct = float(cfg.get('stop_loss_move_pct', 0.75))
        required_count = max(1, int(cfg.get('persistent_loss_observations', 3)))
        reason = None
        if adverse_move_pct <= -stop_pct:
            reason = f'hard stop: adverse price move {adverse_move_pct:.2f}% reached -{stop_pct:.2f}% limit'
        elif adverse_count >= required_count:
            reason = f'persistent loss: {adverse_count} consecutive checks at or beyond -{persistent_threshold:.2f}%'
        if reason:
            _close_paper_position(db, pos, exit_price, cfg, reason=reason)
            log_event(db, f'Protective paper exit {pos.product} {pos.pair} {pos.side}: {reason}', 'WARNING', 'paper_risk',
                      {'trade_id': pos.trade_id, 'entry_price': pos.entry_price, 'exit_price': exit_price,
                       'adverse_move_pct': adverse_move_pct, 'stop_loss_move_pct': stop_pct})
            closed += 1
    db.commit()
    return {'marked': len(all_positions), 'protective_exits': closed}


def _close_paper_position(db: Session, pos: PaperPosition, price: float, cfg: dict, reason='signal rebalance exit'):
    fx=float(cfg.get('inr_per_usdt',94.75))
    direction=1 if pos.side=='buy' else -1
    gross=(price-pos.entry_price)*pos.quantity*direction*fx
    fee_pct=float(cfg.get('spot_fee_pct' if pos.product=='spot' else 'futures_fee_pct',0.15 if pos.product=='spot' else 0.075))/100
    slip_pct=float(cfg.get('normal_slippage_pct',0.05))/100 if cfg.get('paper_cost_case','NORMAL')=='NORMAL' else float(cfg.get('stress_slippage_pct',0.12))/100
    entry_notional=float(pos.notional_usdt or abs(pos.quantity*pos.entry_price))
    exit_notional=abs(pos.quantity*price)
    entry_fee=entry_notional*fee_pct*fx; exit_fee=exit_notional*fee_pct*fx
    entry_slip=entry_notional*slip_pct*fx; exit_slip=exit_notional*slip_pct*fx
    opened = pos.opened_at.replace(tzinfo=timezone.utc) if pos.opened_at.tzinfo is None else pos.opened_at
    held_hours=max(0,(utcnow()-opened).total_seconds()/3600)
    funding=0.0
    if pos.product=='futures' and cfg.get('paper_cost_case')=='STRESS':
        funding=entry_notional*(float(cfg.get('funding_stress_pct_per_8h',0.01))/100)*(held_hours/8)*fx
    trade=db.get(Trade,pos.trade_id) if pos.trade_id else None
    if trade:
        trade.closed_at=utcnow(); trade.exit_price=price; trade.gross_pnl_inr=gross
        trade.fees_inr=entry_fee+exit_fee; trade.slippage_inr=entry_slip+exit_slip; trade.funding_inr=funding
        trade.net_pnl_inr=gross-trade.fees_inr-trade.slippage_inr-funding; trade.status='closed'; trade.reason=reason
        metadata=safe_json(trade.metadata_json)
        metadata['held_seconds']=int((trade.closed_at-opened).total_seconds())
        metadata['held_minutes']=round(metadata['held_seconds']/60.0,2)
        metadata['exit_reason']=reason
        best_fav=float(metadata.get('best_favorable_move_pct', 0.0) or 0.0)
        first_move=metadata.get('first_observed_move_pct')
        cost_total=float(trade.fees_inr or 0)+float(trade.slippage_inr or 0)+float(trade.funding_inr or 0)
        if gross > 0 and trade.net_pnl_inr <= 0:
            diagnosis='Price moved in the trade direction before costs, but modeled fees/slippage/funding erased the gross gain.'
        elif best_fav >= 0.40 and trade.net_pnl_inr <= 0:
            diagnosis=f'Trade showed a sampled favorable excursion of +{best_fav:.2f}% but closed net negative; no profit-lock exit captured that move before the reversal.'
        elif first_move is not None and float(first_move) <= -0.35 and best_fav < 0.20:
            diagnosis=f'Entry was adverse from the first sampled check ({float(first_move):.2f}%) and no meaningful favorable move was later observed.'
        elif 'hard stop' in reason.lower() or 'persistent loss' in reason.lower():
            diagnosis=f'Protective exit after adverse movement; sampled worst move was {float(metadata.get("worst_adverse_move_pct", 0.0) or 0.0):.2f}%. Stops are evaluated only on fresh worker observations, so gaps can exceed the threshold.'
        elif ('rebalance' in reason.lower() or 'signal no longer' in reason.lower() or 'direction changed' in reason.lower()) and best_fav >= 0.20:
            diagnosis=f'Exit followed a rebalance/signal change after a sampled +{best_fav:.2f}% favorable move; review profit giveback (not an intrabar-complete record).'
        elif trade.net_pnl_inr < 0:
            diagnosis='Net loss at exit. Older trade path may be incomplete; compare entry signal, exit reason and modeled costs before assigning an entry-versus-exit cause.'
        else:
            diagnosis='Closed without a detected cost-erased gain or large sampled giveback.'
        metadata['cost_total_inr']=round(cost_total, 4)
        metadata['diagnosis']=diagnosis
        trade.metadata_json=json.dumps(metadata,separators=(',',':'),default=str)
    pos.is_open=False; pos.last_mark_price=price; pos.last_unrealized_pnl_inr=0




def evaluate_paper_decision_audits(db: Session, cfg: dict):
    """Compare rejected and accepted signals with observed future executable quotes."""
    now=utcnow()
    horizons=[('1h',1,30),('4h',4,45),('24h',24,120)]
    pending=db.scalars(select(PaperDecisionAudit).where(
        (PaperDecisionAudit.evaluated_1h==False) | (PaperDecisionAudit.evaluated_4h==False) | (PaperDecisionAudit.evaluated_24h==False)
    ).order_by(PaperDecisionAudit.decision_at.asc()).limit(1200)).all()
    updated=0
    for audit in pending:
        decision_at=audit.decision_at.replace(tzinfo=timezone.utc) if audit.decision_at.tzinfo is None else audit.decision_at
        if not audit.reference_price or audit.reference_price<=0 or audit.proposed_side not in ('buy','sell'):
            continue
        direction=1 if audit.proposed_side=='buy' else -1
        for label,hours,tolerance_min in horizons:
            flag='evaluated_'+label
            if getattr(audit,flag):
                continue
            target=decision_at+timedelta(hours=hours)
            if now < target:
                continue
            # A future quote is valid only close to the intended horizon; don't treat a
            # stale next-day quote as a 1-hour result.
            obs=db.scalar(select(MarketObservation).where(
                MarketObservation.product==audit.product,
                MarketObservation.pair==audit.pair,
                MarketObservation.observed_at>=target,
                MarketObservation.observed_at<=target+timedelta(minutes=tolerance_min),
                MarketObservation.last_price.is_not(None)
            ).order_by(MarketObservation.observed_at.asc()).limit(1))
            if not obs:
                continue
            exit_price=(obs.bid if audit.proposed_side=='buy' else obs.ask) or obs.last_price
            if not exit_price or exit_price<=0:
                continue
            gross=((float(exit_price)/float(audit.reference_price))-1)*direction*100
            cost=float(audit.estimated_cost_pct) if audit.estimated_cost_pct is not None else None
            setattr(audit,'outcome_'+label+'_pct',round(gross,5))
            setattr(audit,'net_outcome_'+label+'_pct',round(gross-cost,5) if cost is not None else None)
            setattr(audit,flag,True)
            updated+=1
    # Keep audit/history bounded; retain recent evidence, never trim actual trade ledgers.
    db.execute(delete(PaperDecisionAudit).where(PaperDecisionAudit.decision_at < now-timedelta(days=90)))
    count=db.scalar(select(func.count(PaperDecisionAudit.id))) or 0
    if count>100000:
        excess=count-100000
        old_ids=select(PaperDecisionAudit.id).order_by(PaperDecisionAudit.decision_at.asc(),PaperDecisionAudit.id.asc()).limit(excess)
        db.execute(delete(PaperDecisionAudit).where(PaperDecisionAudit.id.in_(old_ids)))
    return updated


def record_paper_decision_audits(db: Session, products: dict, viable: list, cfg: dict, snap_map: dict):
    """Store each candidate gate decision so we can test whether rejections were justified."""
    now=utcnow()
    accepted={(p,i['pair'],s) for p,i,s,lev,snap,hurdle,expected in viable}
    candidates=[]
    for product in ('spot','futures'):
        result=products.get(product,{})
        if not isinstance(result,dict):
            continue
        if product=='spot':
            candidates.extend((product,item,'buy') for item in result.get('longs',[]))
        else:
            candidates.extend((product,item,'buy') for item in result.get('longs',[]))
            candidates.extend((product,item,'sell') for item in result.get('shorts',[]))
    seen=set()
    for product,item,side in candidates:
        key=(product,item['pair'],side)
        if key in seen:
            continue
        seen.add(key)
        reason=''
        decision='accepted' if key in accepted else 'rejected'
        snap=snap_map.get((product,item['pair']))
        expected=float(item.get('expected_move_pct') or 0)
        hurdle=_entry_cost_hurdle_pct(product,cfg,snap) if snap else None
        ref_price=None
        if snap:
            ref_price=(snap.ask if side=='buy' else snap.bid) or snap.last_price
        if not item.get('strategy_eligible',True):
            reason=item.get('exclusion_reason') or 'pair excluded from strategy'
        elif not trend_confirmed_audit(item,side):
            reason='trend confirmation failed: 14D score, 24H and 72H direction must agree'
        else:
            ok,why=market_eligibility(snap,cfg) if snap else (False,'no market snapshot')
            if not ok:
                reason='market/liquidity gate: '+why
            else:
                minimum=max(float(cfg.get('min_expected_move_pct',0.75)),
                    (hurdle or 999.0)*float(cfg.get('cost_coverage_multiple',1.5)))
                if hurdle is None or expected < minimum:
                    reason=f'cost gate: expected move {expected:.3f}% below required {minimum:.3f}% (estimated round-trip cost {hurdle if hurdle is not None else "unknown"}%)'
                elif key not in accepted:
                    reason='not opened by current entry selection'
        db.add(PaperDecisionAudit(decision_at=now,product=product,pair=item['pair'],proposed_side=side,
            mode='unrestricted',decision=decision,rejection_reason=reason,reference_price=ref_price,
            entry_bid=snap.bid if snap else None,entry_ask=snap.ask if snap else None,
            expected_move_pct=expected,estimated_cost_pct=hurdle,score=float(item.get('score') or 0),
            momentum_24h_pct=float(item.get('momentum_24h_pct') or 0),
            momentum_72h_pct=float(item.get('momentum_72h_pct') or 0)))
    evaluate_paper_decision_audits(db,cfg)


def trend_confirmed_audit(item,side):
    score=float(item.get('score') or 0)
    m24=float(item.get('momentum_24h_pct') or 0)
    m72=float(item.get('momentum_72h_pct') or 0)
    return score>0 and m24>0 and m72>0 if side=='buy' else score<0 and m24<0 and m72<0

def run_paper_cycle(db: Session, force: bool = False):
    cfg=read_config(db,'strategy_config',{})
    cfg.setdefault('capital_allocation_pct_per_position',10.0)
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
        runtime=read_config(db,'runtime',{}); runtime['last_strategy_cycle']={'at':utcnow().isoformat(),'status':'skipped','message':msg,'diagnostics':diagnostics,'paper_engine_version':PAPER_ENGINE_VERSION}
        runtime['paper_cycle_status']='skipped'; runtime['paper_cycle_message']=msg; runtime['paper_cycle_attempted_at']=utcnow().isoformat(); write_config(db,'runtime',runtime)
        log_event(db,msg,'WARNING','strategy',diagnostics); db.commit()
        return {'ok':False,'message':msg,'diagnostics':diagnostics}

    fx=float(cfg.get('inr_per_usdt',94.75))
    selected=[]
    def trend_confirmed(item, side):
        score=float(item.get('score') or 0)
        m24=float(item.get('momentum_24h_pct') or 0)
        m72=float(item.get('momentum_72h_pct') or 0)
        if side=='buy':
            return score > 0 and m24 > 0 and m72 > 0
        return score < 0 and m24 < 0 and m72 < 0

    if cfg.get('product_mode') in ('spot','both') and 'spot' in products:
        for item in products['spot']['longs']:
            if trend_confirmed(item,'buy'):
                selected.append(('spot',item,'buy',1))
            else:
                log_event(db,f"Skipped spot entry {item['pair']}: 14D/72H/24H direction not aligned.",'INFO','strategy_gate')
    if cfg.get('product_mode') in ('futures','both') and 'futures' in products:
        lev=float(cfg.get('futures_leverage',1))
        for item in products['futures']['longs']:
            if trend_confirmed(item,'buy'):
                selected.append(('futures',item,'buy',lev))
            else:
                log_event(db,f"Skipped futures long {item['pair']}: 14D/72H/24H direction not aligned.",'INFO','strategy_gate')
        for item in products['futures']['shorts']:
            if trend_confirmed(item,'sell'):
                selected.append(('futures',item,'sell',lev))
            else:
                log_event(db,f"Skipped futures short {item['pair']}: 14D/72H/24H direction not aligned.",'INFO','strategy_gate')

    # Apply current liquidity, spread and expected-move-vs-cost gates before any entry or rebalance decision.
    snap_map={(x.product,x.pair):x for x in db.scalars(select(MarketSnapshot)).all()}
    viable=[]
    for product,item,side,lev in selected:
        snap=snap_map.get((product,item['pair']))
        ok,why=market_eligibility(snap,cfg) if snap else (False,'no market snapshot')
        if not ok:
            log_event(db,f"Skipped paper entry {product} {item['pair']}: {why}",'WARNING','strategy_gate')
            continue
        spread=market_spread_bps(snap.bid,snap.ask)
        hurdle=_entry_cost_hurdle_pct(product,cfg,snap)
        expected=float(item.get('expected_move_pct') or 0)
        minimum=max(float(cfg.get('min_expected_move_pct',0.75)),
                    (hurdle or 999.0)*float(cfg.get('cost_coverage_multiple',1.5)))
        if hurdle is None or expected < minimum:
            log_event(db,f"Skipped paper entry {product} {item['pair']}: estimated move {expected:.3f}% does not clear cost hurdle {minimum:.3f}% (round-trip costs {hurdle if hurdle is not None else 'unknown'}%).",
                      'INFO','strategy_gate',{'expected_move_pct':expected,'round_trip_cost_pct':hurdle,'required_move_pct':minimum,'spread_bps':spread})
            continue
        viable.append((product,item,side,lev,snap,hurdle,expected))

    record_paper_decision_audits(db, products, viable, cfg, snap_map)

    # Reconcile only positions that no longer qualify or whose target side changed.
    # Never liquidate a still-valid position simply because a scheduled scan ran.
    desired={(product,item['pair']):(side,product,item,lev,snap,hurdle,expected)
             for product,item,side,lev,snap,hurdle,expected in viable}
    open_positions=db.scalars(select(PaperPosition).where(PaperPosition.is_open==True)).all()
    for pos in open_positions:
        key=(pos.product,pos.pair)
        target=desired.get(key)
        if target and target[0]==pos.side:
            continue
        snap=snap_map.get(key)
        if snap and snap.last_price:
            age=(utcnow()-(snap.updated_at.replace(tzinfo=timezone.utc) if snap.updated_at.tzinfo is None else snap.updated_at)).total_seconds()
            if age < int(cfg.get('max_stale_seconds',120)):
                px=(snap.bid if pos.side=='buy' else snap.ask) or snap.last_price
                reason='signal no longer qualifies after costs/trend checks' if not target else 'signal direction changed'
                _close_paper_position(db,pos,float(px),cfg,reason=reason)
            else:
                log_event(db,f"Preserving {pos.product} {pos.pair}: cannot safely rebalance without fresh mark.",'WARNING','paper_risk')
        else:
            log_event(db,f"Preserving {pos.product} {pos.pair}: cannot safely rebalance without fresh mark.",'WARNING','paper_risk')
    db.flush()
    still_open={(p.product,p.pair):p for p in db.scalars(select(PaperPosition).where(PaperPosition.is_open==True)).all()}
    opened=0
    for product,item,side,lev,snap,hurdle,expected in viable:
        key=(product,item['pair'])
        if key in still_open:
            # Same market and same direction is retained; never duplicate an open position.
            continue
        price=float(snap.ask if side=='buy' else snap.bid)
        if price <= 0 or not math.isfinite(price):
            log_event(db,f"Skipped paper entry {product} {item['pair']}: invalid executable entry quote.",'WARNING','strategy_gate')
            continue
        each_notional=float(cfg.get('research_notional_usdt',1000.0))
        qty=each_notional/price
        fee_pct=float(cfg.get('spot_fee_pct' if product=='spot' else 'futures_fee_pct',0.15 if product=='spot' else 0.075))/100
        slip_pct=float(cfg.get('normal_slippage_pct',0.05))/100 if cfg.get('paper_cost_case','NORMAL')=='NORMAL' else float(cfg.get('stress_slippage_pct',0.12))/100
        fees=each_notional*fee_pct*fx; slips=each_notional*slip_pct*fx
        trade=Trade(run_mode='paper',product=product,pair=item['pair'],side=side,quantity=qty,entry_price=price,leverage=lev,
                    fees_inr=fees,slippage_inr=slips,net_pnl_inr=-(fees+slips),gross_pnl_inr=0,status='open',strategy=STRATEGY_ID,
                    reason='entry: trend-confirmed signal clears estimated round-trip cost hurdle',
                    metadata_json=json.dumps({'entry_reason':'trend-confirmed signal clears estimated round-trip cost hurdle','best_favorable_move_pct':0.0,'worst_adverse_move_pct':0.0,'score':item['score'],'momentum_pct':item['momentum_pct'],
                        'momentum_24h_pct':item.get('momentum_24h_pct'),'momentum_72h_pct':item.get('momentum_72h_pct'),
                        'expected_move_pct':expected,'estimated_round_trip_cost_pct':hurdle,
                        'required_move_pct':max(float(cfg.get('min_expected_move_pct',0.75)),hurdle*float(cfg.get('cost_coverage_multiple',1.5))),
                        'liquidity_turnover_proxy':item['turnover_proxy'],'entry_bid':snap.bid,'entry_ask':snap.ask}))
        db.add(trade); db.flush()
        db.add(PaperPosition(product=product,pair=item['pair'],side=side,quantity=qty,entry_price=price,notional_usdt=each_notional,leverage=lev,
                             opened_at=utcnow(),strategy=STRATEGY_ID,trade_id=trade.id,last_mark_price=price,last_unrealized_pnl_inr=0,is_open=True))
        opened+=1
    # Independent capital-constrained track. It consumes only its own positions/trades;
    # unrestricted research above remains fixed-notional and is not affected by capital.
    capital_inr=max(0.0,float(cfg.get('starting_capital_inr',30000)))
    allocation_pct=max(1.0,min(50.0,float(cfg.get('capital_allocation_pct_per_position',10.0))))
    constrained_open=db.scalars(select(PaperModePosition).where(PaperModePosition.is_open==True)).all()
    constrained_desired={(p,i['pair']):(side,p,i,lev,snap,hurdle,expected)
        for p,i,side,lev,snap,hurdle,expected in viable}
    for pos in constrained_open:
        target=constrained_desired.get((pos.product,pos.pair))
        if target and target[0]==pos.side:
            continue
        snap=snap_map.get((pos.product,pos.pair))
        if snap and snap.last_price:
            age=(utcnow()-(snap.updated_at.replace(tzinfo=timezone.utc) if snap.updated_at.tzinfo is None else snap.updated_at)).total_seconds()
            if age < int(cfg.get('max_stale_seconds',120)):
                px=(snap.bid if pos.side=='buy' else snap.ask) or snap.last_price
                _close_paper_position(db,pos,float(px),cfg,reason='capital track: signal no longer qualifies or direction changed')
    db.flush()
    constrained_open=db.scalars(select(PaperModePosition).where(PaperModePosition.is_open==True)).all()
    constrained_map={(p.product,p.pair):p for p in constrained_open}
    reserved_margin_inr=sum(float(p.notional_usdt or 0)*fx/max(float(p.leverage or 1),1.0) for p in constrained_open)
    capital_opened=0
    for product,item,side,lev,snap,hurdle,expected in viable:
        key=(product,item['pair'])
        if key in constrained_map:
            continue
        available=max(0.0,capital_inr-reserved_margin_inr)
        allocation=min(available,capital_inr*allocation_pct/100.0)
        if allocation <= 1.0:
            reason=f'insufficient available capital/margin: ₹{available:.2f} available; required allocation is above ₹1.00'
            db.add(PaperDecisionAudit(decision_at=utcnow(),product=product,pair=item['pair'],proposed_side=side,
                mode='capital_constrained',decision='rejected',rejection_reason=reason,
                reference_price=float(snap.ask if side=='buy' else snap.bid) if (snap.ask if side=='buy' else snap.bid) else snap.last_price,
                entry_bid=snap.bid,entry_ask=snap.ask,expected_move_pct=expected,estimated_cost_pct=hurdle,
                score=float(item.get('score') or 0),momentum_24h_pct=float(item.get('momentum_24h_pct') or 0),
                momentum_72h_pct=float(item.get('momentum_72h_pct') or 0)))
            log_event(db,f'Skipped capital-constrained entry {product} {item["pair"]}: insufficient unreserved paper capital.', 'INFO','capital_gate',{'available_margin_inr':available})
            continue
        effective_lev=max(1.0,float(lev if product=='futures' else 1.0))
        notional=min(float(cfg.get('research_notional_usdt',1000.0)), allocation*effective_lev/max(fx,1.0))
        required_margin=notional*fx/effective_lev
        if notional <= 0 or required_margin > available+0.01:
            continue
        price=float(snap.ask if side=='buy' else snap.bid)
        if price <= 0 or not math.isfinite(price):
            continue
        qty=notional/price
        fee_pct=float(cfg.get('spot_fee_pct' if product=='spot' else 'futures_fee_pct',0.15 if product=='spot' else 0.075))/100
        slip_pct=float(cfg.get('normal_slippage_pct',0.05))/100 if cfg.get('paper_cost_case','NORMAL')=='NORMAL' else float(cfg.get('stress_slippage_pct',0.12))/100
        fees=notional*fee_pct*fx; slips=notional*slip_pct*fx
        trade=Trade(run_mode='paper_capital',product=product,pair=item['pair'],side=side,quantity=qty,entry_price=price,leverage=effective_lev,
            fees_inr=fees,slippage_inr=slips,net_pnl_inr=-(fees+slips),gross_pnl_inr=0,status='open',strategy=STRATEGY_ID,
            reason='capital-constrained entry; margin reserved against configured starting capital',
            metadata_json=json.dumps({'entry_reason':'capital-constrained entry; margin reserved against configured starting capital','best_favorable_move_pct':0.0,'worst_adverse_move_pct':0.0,'capital_inr':capital_inr,'reserved_margin_inr':required_margin,
                'allocation_pct':allocation_pct,'score':item.get('score'),'momentum_24h_pct':item.get('momentum_24h_pct'),
                'momentum_72h_pct':item.get('momentum_72h_pct'),'expected_move_pct':expected,
                'estimated_round_trip_cost_pct':hurdle,'entry_bid':snap.bid,'entry_ask':snap.ask}))
        db.add(PaperDecisionAudit(decision_at=utcnow(),product=product,pair=item['pair'],proposed_side=side,
            mode='capital_constrained',decision='accepted',rejection_reason='',reference_price=price,
            entry_bid=snap.bid,entry_ask=snap.ask,expected_move_pct=expected,estimated_cost_pct=hurdle,
            score=float(item.get('score') or 0),momentum_24h_pct=float(item.get('momentum_24h_pct') or 0),
            momentum_72h_pct=float(item.get('momentum_72h_pct') or 0)))
        db.add(trade); db.flush()
        db.add(PaperModePosition(mode='capital_constrained',product=product,pair=item['pair'],side=side,quantity=qty,
            entry_price=price,notional_usdt=notional,leverage=effective_lev,opened_at=utcnow(),strategy=STRATEGY_ID,
            trade_id=trade.id,last_mark_price=price,last_unrealized_pnl_inr=0,is_open=True))
        reserved_margin_inr += required_margin
        capital_opened += 1
    cfg['paper_last_cycle']=utcnow().isoformat(); cfg['last_error']=None; write_config(db,'strategy_config',cfg)
    runtime=read_config(db,'runtime',{})
    runtime['last_strategy_cycle']={'at':utcnow().isoformat(),'status':'ok','scan_universe_count':runtime.get('scan_universe_count',0),
        'signals':{k:len(v.get('all_scored',[])) for k,v in products.items()},
        'opened_positions':opened,'capital_track_opened_positions':capital_opened,'capital_track_open_positions':len(constrained_open)+capital_opened,'selected_signals':len(selected),'eligible_signals':len(viable),
        'candle_diagnostics':diagnostics,'paper_engine_version':PAPER_ENGINE_VERSION}
    runtime['paper_cycle_status']='completed'
    runtime['paper_cycle_message']=f"Dual-mode cycle completed; scored {sum(len(v.get('all_scored',[])) for v in products.values())} product/pair records; unrestricted research opened {opened}, capital-constrained track opened {capital_opened}, and {len(selected)-len(viable)} candidates failed market/cost gates."
    runtime['paper_cycle_attempted_at']=utcnow().isoformat(); write_config(db,'runtime',runtime)
    log_event(db,f"Paper strategy cycle completed: {opened} new positions opened; {len(still_open)} retained.",'INFO','paper',
              {'strategy':STRATEGY_ID,'selected':[{'product':p,'pair':i['pair'],'side':side,'score':i['score']} for p,i,side,lev,snap,hurdle,expected in viable],
               'diagnostics':diagnostics})
    db.commit()
    return {'ok':True,'message':runtime['paper_cycle_message'],'signals':products,'opened_positions':opened,'capital_track_opened_positions':capital_opened,'diagnostics':diagnostics}

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



def _scalp_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _scalp_spread_bps(snap):
    return market_spread_bps(snap.bid, snap.ask) if snap and snap.bid and snap.ask else None


def build_scalper_scan(db: Session, cfg: dict | None = None, now=None):
    """Rank explainable scalper candidates using cost-aware gates and displayed-book depth."""
    cfg = cfg or read_config(db, 'strategy_config', {})
    now = now or utcnow()
    min_turnover = float(cfg.get('scalper_min_turnover_usdt', 250_000))
    max_spread = float(cfg.get('scalper_max_spread_bps', 8))
    min_move = max(0.0, float(cfg.get('scalper_min_signal_move_pct', 0.05)))
    snapshots = db.scalars(select(MarketSnapshot)).all()
    obs_rows = db.scalars(select(MarketObservation)
        .where(MarketObservation.observed_at >= now - timedelta(minutes=25))
        .order_by(MarketObservation.observed_at.desc())).all()
    history = defaultdict(list)
    for obs in obs_rows:
        key = (obs.product, obs.pair)
        if len(history[key]) < 3 and obs.last_price and obs.last_price > 0:
            history[key].append(obs)
    rows = []
    target_net = float(cfg.get('scalper_target_net_pct', 0.15))
    notional = max(10.0, min(500.0, float(cfg.get('scalper_notional_usdt', 100))))
    for snap in snapshots:
        spread_bps = _scalp_spread_bps(snap)
        row = {'product':snap.product,'pair':snap.pair,'price':snap.last_price,
            'turnover_usdt':snap.quote_turnover_usdt,'spread_bps':spread_bps,'bid':snap.bid,'ask':snap.ask,'entry_price_estimate':None,
            'side':'—','return_5m_pct':None,'return_previous_5m_pct':None,'return_10m_pct':None,'cost_hurdle_pct':None,
            'required_move_pct':None,'expected_continuation_pct':None,'estimated_net_pct':None,'edge_multiple':None,
            'bid_depth_10_usdt':_scalp_orderbook_depth(snap,'buy',10),
            'ask_depth_10_usdt':_scalp_orderbook_depth(snap,'sell',10),'entry_depth_10_usdt':None,
            'eligible':False,'reason':'No valid setup yet','move_is_observed_not_forecast':True}
        updated = _scalp_utc(snap.updated_at)
        age = (now-updated).total_seconds() if updated else 1e9
        sample = history.get((snap.product,snap.pair),[])
        if not snap.active: row['reason']='Market inactive'
        elif snap.exit_only: row['reason']='Futures instrument is exit-only'
        elif strategy_pair_exclusion_reason(snap.pair): row['reason']='Stablecoin base asset excluded'
        elif age>90: row['reason']=f'Snapshot stale ({age:.0f}s); cannot enter'
        elif not snap.bid or not snap.ask or snap.bid<=0 or snap.ask<snap.bid: row['reason']='Executable bid/ask unavailable'
        elif spread_bps is None: row['reason']='Spread unknown'
        elif spread_bps>max_spread: row['reason']=f'Spread {spread_bps:.2f} bps exceeds {max_spread:.1f} bps'
        elif snap.quote_turnover_usdt is None or snap.quote_turnover_usdt<min_turnover:
            row['reason']=f'24h turnover below {min_turnover:,.0f} USDT'
        elif len(sample)<3: row['reason']='Collecting at least 3 recent 5-minute observations'
        else:
            newest,prior,older=sample[0],sample[1],sample[2]
            gaps=[(_scalp_utc(newest.observed_at)-_scalp_utc(prior.observed_at)).total_seconds(),
                  (_scalp_utc(prior.observed_at)-_scalp_utc(older.observed_at)).total_seconds()]
            if any(g<90 or g>720 for g in gaps) or (now-_scalp_utc(newest.observed_at)).total_seconds()>720:
                row['reason']='Recent price history has a gap; wait for fresh samples'
            else:
                r5=(float(newest.last_price)/float(prior.last_price)-1)*100
                # "previous 5m" is the interval prior to the newest sample. The
                # 10m return is cumulative and must not masquerade as independent confirmation.
                previous5=(float(prior.last_price)/float(older.last_price)-1)*100
                r10=(float(newest.last_price)/float(older.last_price)-1)*100
                side='buy' if r5>0 else 'sell'
                direction=1 if side=='buy' else -1
                aligned_previous=direction*previous5
                # Conservative shrinkage proxy for the *next* interval, not an ML
                # forecast: discount current momentum and only credit prior momentum
                # when it pointed in the same direction. Outcome review will validate it.
                continuation=max(0.0,0.65*abs(r5)+0.35*max(0.0,aligned_previous))
                hurdle=_scalp_cost_hurdle_pct(snap.product,cfg,snap)
                required=_scalp_required_move_pct(snap.product,cfg,snap)
                edge=continuation/hurdle if hurdle and hurdle>0 else None
                entry_depth=row['bid_depth_10_usdt'] if side=='sell' else row['ask_depth_10_usdt']
                estimate=_scalp_estimated_net_pct(snap.product,cfg,snap,continuation)
                row.update({'side':side,'entry_price_estimate':snap.ask if side=='buy' else snap.bid,
                    'return_5m_pct':r5,'return_previous_5m_pct':previous5,'return_10m_pct':r10,
                    'cost_hurdle_pct':hurdle,'required_move_pct':required,
                    'expected_continuation_pct':continuation,'edge_multiple':edge,
                    'estimated_net_pct':estimate,'entry_depth_10_usdt':entry_depth})
                if snap.product=='spot' and side=='sell':
                    row['reason']='Spot is long-only; bearish setup not shortable'
                elif r5==0:
                    row['reason']='No directional 5m impulse'
                elif abs(r5)<min_move:
                    row['reason']=f'5m move {abs(r5):.3f}% below soft noise floor {min_move:.3f}%'
                elif aligned_previous < -min_move:
                    row['reason']=f'Reversal: previous 5m interval moved {previous5:+.3f}% against the latest {r5:+.3f}% impulse'
                elif entry_depth is not None and entry_depth<notional:
                    row['reason']=f'Top-10 entry-side depth {entry_depth:,.0f} USDT is below {notional:,.0f} USDT order size'
                elif required is None or estimate<target_net:
                    row['reason']=f'Continuation proxy implies {estimate:+.3f}% net after modeled costs/reserve; target is +{target_net:.3f}%'
                elif abs(r5)>=0.75 and abs(r5)>max(abs(previous5)*1.8,0.25):
                    row['reason']='Late impulse: latest 5m burst is much larger than the preceding 5m interval'
                else:
                    row['eligible']=True
                    row['reason']='Liquidity/depth pass; recent and preceding 5m momentum align and continuation proxy clears the net target (proxy not yet validated)'
        rows.append(row)
    rows.sort(key=lambda x:(not x['eligible'],-(x['estimated_net_pct'] if x['estimated_net_pct'] is not None else -999),-(x['turnover_usdt'] or 0)))
    return rows


def _scalp_calculate(trade, exit_price, cfg, fx):
    direction=1 if trade.side=='buy' else -1
    entry_notional=abs(float(trade.quantity or 0)*float(trade.entry_price or 0))
    exit_notional=abs(float(trade.quantity or 0)*float(exit_price or 0))
    gross=(float(exit_price)-float(trade.entry_price))*float(trade.quantity)*direction*fx
    fee_pct=_scalp_fee_cost_pct(trade.product,cfg)/100.0
    slip_pct=_scalp_slippage_pct(cfg)/100.0
    fees=(entry_notional+exit_notional)*fee_pct*fx
    slippage=(entry_notional+exit_notional)*slip_pct*fx
    if trade.product=='spot':
        tax_rate=max(0.0,float(cfg.get('scalper_spot_tax_pct',31.2)))
        taxable_basis=max(0.0,gross)
    else:
        tax_rate=max(0.0,float(cfg.get('scalper_futures_tax_pct',31.2)))
        taxable_basis=max(0.0,gross-fees-slippage)
    tax=taxable_basis*tax_rate/100.0
    net=gross-fees-slippage-tax
    tds=exit_notional*fx*max(0.0,float(cfg.get('scalper_tds_pct',1)))/100.0 if trade.product=='spot' else 0.0
    return {'gross':gross,'fees':fees,'slippage':slippage,'tax':tax,'net_after_tax':net,'tds':tds,'exit_notional':exit_notional}


def _scalp_mode(trade):
    return safe_json(trade.metadata_json or '{}').get('mode') or 'research'


def _record_scalper_scan(db: Session, now, mode, candidates):
    runtime=read_config(db,'runtime',{})
    key=f'scalper_scan_snapshot_at_{mode}'
    previous=runtime.get(key)
    if previous:
        try:
            dt=datetime.fromisoformat(previous.replace('Z','+00:00'))
            dt=dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            if (now-dt).total_seconds()<240: return
        except Exception: pass
    eligible=[x for x in candidates if x.get('eligible')][:15]
    rejected=[x for x in candidates if not x.get('eligible') and x.get('return_5m_pct') is not None]
    rejected.sort(key=lambda x:-(abs(float(x.get('return_5m_pct') or 0))/max(float(x.get('required_move_pct') or 0.01),0.01)))
    keys=('product','pair','price','bid','ask','entry_price_estimate','side','return_5m_pct','return_previous_5m_pct','return_10m_pct','expected_continuation_pct','turnover_usdt','spread_bps',
          'bid_depth_10_usdt','ask_depth_10_usdt','entry_depth_10_usdt','cost_hurdle_pct','required_move_pct',
          'estimated_net_pct','edge_multiple','eligible','reason')
    payload=[{k:x.get(k) for k in keys} for x in eligible+rejected[:25]]
    db.add(ScalpScanSnapshot(scanned_at=now,mode=mode,candidates_json=json.dumps(payload,separators=(',',':'),default=str)))
    db.flush()
    old_ids=db.scalars(select(ScalpScanSnapshot.id).where(ScalpScanSnapshot.mode==mode)
        .order_by(desc(ScalpScanSnapshot.scanned_at)).offset(400)).all()
    if old_ids: db.execute(delete(ScalpScanSnapshot).where(ScalpScanSnapshot.id.in_(old_ids)))
    runtime=read_config(db,'runtime',{}); runtime[key]=now.isoformat(); write_config(db,'runtime',runtime)


def _run_scalper_lane(db: Session, now=None, mode='research', cfg_override=None):
    """Run one isolated paper-only track (research or capital-constrained)."""
    now=now or utcnow()
    cfg=dict(cfg_override or read_config(db,'strategy_config',{}))
    cfg['scalper_notional_usdt']=float(cfg.get(f'scalper_{mode}_notional_usdt',cfg.get('scalper_notional_usdt',100)))
    cfg['scalper_max_open_positions']=int(cfg.get(f'scalper_{mode}_max_open_positions',cfg.get('scalper_max_open_positions',3)))
    lane_enabled=bool(cfg.get('scalper_enabled',True) and cfg.get(f'scalper_{mode}_enabled',mode=='research'))
    fx=float(cfg.get('inr_per_usdt',94.75))
    snapshots={(s.product,s.pair):s for s in db.scalars(select(MarketSnapshot)).all()}
    opened_count=closed_count=0
    open_trades=db.scalars(select(ScalpTrade).where(ScalpTrade.status=='open').order_by(ScalpTrade.opened_at.asc())).all()
    for trade in [t for t in open_trades if _scalp_mode(t)==mode]:
        snap=snapshots.get((trade.product,trade.pair))
        updated=_scalp_utc(snap.updated_at) if snap else None
        if not snap or not snap.last_price or updated is None or (now-updated).total_seconds()>90: continue
        meta=safe_json(trade.metadata_json or '{}')
        trade_cfg=dict(cfg); trade_cfg.update(meta.get('cost_settings') or {})
        trade_fx=float(meta.get('inr_per_usdt') or fx)
        exit_price=float((snap.bid if trade.side=='buy' else snap.ask) or snap.last_price)
        mark=_scalp_calculate(trade,exit_price,trade_cfg,trade_fx)
        denom=max(abs(float(trade.quantity or 0)*float(trade.entry_price or 0))*trade_fx,1.0)
        move_pct=((exit_price/float(trade.entry_price))-1)*(1 if trade.side=='buy' else -1)*100
        trade.best_favorable_pct=max(float(trade.best_favorable_pct or 0),move_pct)
        trade.worst_adverse_pct=min(float(trade.worst_adverse_pct or 0),move_pct)
        trade.gross_pnl_inr=mark['gross']; trade.fees_inr=mark['fees']; trade.slippage_inr=mark['slippage']
        trade.tax_reserve_inr=mark['tax']; trade.tds_estimate_inr=mark['tds']
        trade.unrealized_net_after_tax_inr=mark['net_after_tax']
        elapsed=max(0.0,(now-_scalp_utc(trade.opened_at)).total_seconds()/60)
        net_pct=mark['net_after_tax']/denom*100; reason=None
        if net_pct>=float(meta.get('target_net_pct',cfg.get('scalper_target_net_pct',0.15))):
            reason=f'take profit: estimated net-after-tax return +{net_pct:.3f}% reached target'
        elif net_pct<=-abs(float(meta.get('stop_net_pct',cfg.get('scalper_stop_net_pct',0.40)))):
            reason=f'loss stop: modeled net return {net_pct:.3f}% reached loss limit'
        elif elapsed>=float(meta.get('max_hold_minutes',cfg.get('scalper_max_hold_minutes',15))):
            reason=f'time exit after {elapsed:.1f} minutes; fast setup did not finish in time'
        if reason:
            trade.closed_at=now; trade.exit_price=exit_price; trade.status='closed'; trade.exit_reason=reason
            trade.unrealized_net_after_tax_inr=0; trade.net_after_tax_inr=mark['net_after_tax']
            trade.metadata_json=json.dumps({**meta,'held_minutes':round(elapsed,2),'best_favorable_pct':trade.best_favorable_pct,
                'worst_adverse_pct':trade.worst_adverse_pct,'exit_reason':reason,'closed_at':now.isoformat()},separators=(',',':'),default=str)
            closed_count+=1
    db.flush()
    candidates=build_scalper_scan(db,cfg,now)
    _record_scalper_scan(db,now,mode,candidates)
    if lane_enabled:
        all_open=db.scalars(select(ScalpTrade).where(ScalpTrade.status=='open')).all()
        current_open=[t for t in all_open if _scalp_mode(t)==mode]
        live_keys={(t.product,t.pair) for t in current_open}
        cooldown=max(0,min(120,int(cfg.get('scalper_pair_cooldown_minutes',5))))
        recent_closed=[]
        if cooldown>0:
            all_recent=db.scalars(select(ScalpTrade).where(ScalpTrade.status=='closed',
                ScalpTrade.closed_at>=now-timedelta(minutes=cooldown))).all()
            recent_closed=[t for t in all_recent if _scalp_mode(t)==mode]
        cooled_keys={(t.product,t.pair) for t in recent_closed}
        max_open=max(1,min(10,int(cfg.get(f'scalper_{mode}_max_open_positions',cfg.get('scalper_max_open_positions',3)))))
        slots=max(0,max_open-len(current_open))
        if mode=='capital':
            capital_limit=(float(cfg.get('starting_capital_inr',30000))/max(fx,1e-9))*(float(cfg.get('capital_allocation_pct_per_position',10.0))/100.0)
            notional=max(10.0,min(500.0,float(cfg.get('scalper_capital_notional_usdt',30)),capital_limit))
        else:
            notional=max(10.0,min(500.0,float(cfg.get('scalper_research_notional_usdt',cfg.get('scalper_notional_usdt',100)))))
        cfg['scalper_notional_usdt']=notional
        for item in candidates:
            if slots<=0: break
            if not item['eligible']: continue
            key=(item['product'],item['pair'])
            if key in live_keys or key in cooled_keys: continue
            snap=snapshots.get(key)
            if not snap: continue
            side=item['side']; entry_price=float((snap.ask if side=='buy' else snap.bid) or 0)
            if entry_price<=0 or not math.isfinite(entry_price): continue
            quantity=notional/entry_price
            fee_pct=_scalp_fee_cost_pct(item['product'],cfg)/100.0
            slip_pct=_scalp_slippage_pct(cfg)/100.0
            cost_settings={k:cfg.get(k) for k in ('scalper_spot_fee_pct','scalper_futures_fee_pct',
                'scalper_normal_slippage_pct','scalper_stress_slippage_pct','scalper_fee_gst_pct','spot_fee_pct','futures_fee_pct',
                'normal_slippage_pct','stress_slippage_pct','paper_cost_case','scalper_cost_case','scalper_spot_tax_pct',
                'scalper_futures_tax_pct','scalper_tds_pct')}
            meta={'scalper_version':'0.2.0-dual-paper-tracks-cost-aware','mode':mode,'entry_reason':item['reason'],
                'return_5m_pct':item.get('return_5m_pct'),'return_previous_5m_pct':item.get('return_previous_5m_pct'),'return_10m_pct':item.get('return_10m_pct'),
                'expected_continuation_pct':item.get('expected_continuation_pct'),'required_move_pct':item.get('required_move_pct'),'estimated_net_pct':item.get('estimated_net_pct'),
                'entry_bid':snap.bid,'entry_ask':snap.ask,'expected_move_not_forecast':abs(float(item.get('return_5m_pct') or 0)),
                'turnover_usdt':item.get('turnover_usdt'),'spread_bps':item.get('spread_bps'),
                'bid_depth_10_usdt':item.get('bid_depth_10_usdt'),'ask_depth_10_usdt':item.get('ask_depth_10_usdt'),
                'entry_depth_10_usdt':item.get('entry_depth_10_usdt'),'cost_settings':cost_settings,'inr_per_usdt':fx,
                'target_net_pct':cfg.get('scalper_target_net_pct',0.15),'stop_net_pct':cfg.get('scalper_stop_net_pct',0.40),
                'max_hold_minutes':cfg.get('scalper_max_hold_minutes',15)}
            db.add(ScalpTrade(opened_at=now,product=item['product'],pair=item['pair'],side=side,
                quantity=quantity,entry_price=entry_price,notional_usdt=notional,status='open',
                entry_score=float(item.get('edge_multiple') or 0),cost_hurdle_pct=float(item.get('cost_hurdle_pct') or 0),
                spread_bps=float(item.get('spread_bps') or 0),fees_inr=notional*fee_pct*fx*2,
                slippage_inr=notional*slip_pct*fx*2,
                metadata_json=json.dumps(meta,separators=(',',':'),default=str)))
            live_keys.add(key); cooled_keys.add(key); slots-=1; opened_count+=1
    db.flush()
    closed_all=db.scalars(select(ScalpTrade).where(ScalpTrade.status=='closed')).all()
    closed=[t for t in closed_all if _scalp_mode(t)==mode]
    wins=[float(t.net_after_tax_inr or 0) for t in closed if float(t.net_after_tax_inr or 0)>0]
    losses=[float(t.net_after_tax_inr or 0) for t in closed if float(t.net_after_tax_inr or 0)<0]
    lane_open=[t for t in db.scalars(select(ScalpTrade).where(ScalpTrade.status=='open')).all() if _scalp_mode(t)==mode]
    return {'ok':True,'mode':mode,'opened':opened_count,'closed':closed_count,'open':len(lane_open),
        'closed_count':len(closed),'profit_factor_after_tax':(sum(wins)/abs(sum(losses)) if losses else None),
        'net_after_tax_inr':sum(float(t.net_after_tax_inr or 0) for t in closed),
        'open_net_inr':sum(float(t.unrealized_net_after_tax_inr or 0) for t in lane_open),'candidates':candidates}


def run_scalper_cycle(db: Session, now=None):
    """Update both isolated paper tracks. Exchange-order API is never called."""
    now=now or utcnow()
    base_cfg=read_config(db,'strategy_config',{})
    lanes={}
    for mode in ('research','capital'):
        lanes[mode]=_run_scalper_lane(db,now,mode,base_cfg)
    runtime=read_config(db,'runtime',{})
    runtime['scalper_lane_cycles']={mode:{k:v for k,v in res.items() if k!='candidates'} for mode,res in lanes.items()}
    closed=db.scalars(select(ScalpTrade).where(ScalpTrade.status=='closed')).all()
    wins=[float(t.net_after_tax_inr or 0) for t in closed if float(t.net_after_tax_inr or 0)>0]
    losses=[float(t.net_after_tax_inr or 0) for t in closed if float(t.net_after_tax_inr or 0)<0]
    opened=db.scalars(select(ScalpTrade).where(ScalpTrade.status=='open')).all()
    runtime['scalper_last_cycle']={'at':now.isoformat(),'status':'ok','enabled':bool(base_cfg.get('scalper_enabled',True)),
        'opened':sum(x['opened'] for x in lanes.values()),'closed':sum(x['closed'] for x in lanes.values()),
        'open':len(opened),'closed_count':len(closed),'rolling_profit_factor_after_tax':sum(wins)/abs(sum(losses)) if losses else None,
        'target_profit_factor':1.25,'version':'0.2.0-dual-paper-tracks-cost-aware'}
    write_config(db,'runtime',runtime); db.flush()
    return {'ok':True,'opened':runtime['scalper_last_cycle']['opened'],'closed':runtime['scalper_last_cycle']['closed'],
        'open':len(opened),'closed_count':len(closed),'profit_factor_after_tax':runtime['scalper_last_cycle']['rolling_profit_factor_after_tax'],
        'lanes':{mode:{k:v for k,v in result.items() if k!='candidates'} for mode,result in lanes.items()}}
