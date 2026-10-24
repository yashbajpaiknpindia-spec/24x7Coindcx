"""Live exchange reconciliation, ledger and explicitly armed automatic strategy runner.

Live trading is disabled unless BOTH deployment gates and the database arming state
are enabled. No exchange secrets are logged or persisted. Ambiguous submissions are
marked unknown and prevent the bot from duplicating the order.
"""
from __future__ import annotations
import hashlib, json, math, os, time
from datetime import datetime, timezone, timedelta, date
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from .db import (SessionLocal, MarketSnapshot, OrderRecord, ExecutionFill, LedgerEntry,
                 AccountSnapshot, TelemetrySnapshot, StrategyPosition, Event, utcnow)
from .coindcx import CoinDCXClient, CoinDCXError
from .core import (read_config, write_config, log_event, calculate_scores, market_eligibility,
                   market_spread_bps, norm_pair, safe_json, env_float, env_int, PAIR_UNIVERSE)

ACTIVE_ORDER_STATES = {'submitting','submitted','open','partially_filled','unknown','filled_unreconciled'}

def env_bool(key: str, default=False):
    return os.getenv(key, 'true' if default else 'false').strip().lower() in ('true','1','yes','on')
TERMINAL_EXCHANGE_STATES = {'filled','cancelled','partially_cancelled','rejected'}


def _list_data(value):
    if isinstance(value, list): return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for k in ('data','orders','trades','positions','balances','wallets','transactions','results'):
            if isinstance(value.get(k), list): return [x for x in value[k] if isinstance(x,dict)]
        return [value]
    return []


def _ts(value, fallback=None):
    try:
        if isinstance(value, str) and not value.strip().replace('.', '', 1).isdigit():
            candidate = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=timezone.utc)
            return candidate.astimezone(timezone.utc)
        x=float(value)
        if x > 10_000_000_000: x /= 1000
        return datetime.fromtimestamp(x, timezone.utc)
    except Exception: return fallback or utcnow()


def _hash_key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',',':')).encode()).hexdigest()[:48]


def _insert_ledger(db: Session, key: str, *, category: str, amount: float, currency: str,
                   product='unknown', pair='', run_mode='live', cash_effect=False,
                   status='reconciled', external_ref='', occurred_at=None, details=None):
    key=str(key)[:250]
    if db.scalar(select(LedgerEntry.id).where(LedgerEntry.ledger_key==key)) is not None: return False
    db.add(LedgerEntry(ledger_key=key, occurred_at=occurred_at or utcnow(), run_mode=run_mode,
        product=product, pair=pair, category=category, amount=float(amount or 0), currency=(currency or 'UNKNOWN')[:20],
        cash_effect=bool(cash_effect), reconciliation_status=status, external_ref=str(external_ref or '')[:180],
        details_json=json.dumps(details or {}, default=str)[:12000]))
    return True


def _assets(pair, detail=None):
    detail=detail or {}
    # CoinDCX's spot market metadata calls the traded/base quantity the target currency.
    base = detail.get('target_currency_short_name') or detail.get('target_currency')
    quote = detail.get('base_currency_short_name') or detail.get('base_currency')
    if base and quote: return str(base).upper(), str(quote).upper()
    norm=str(pair or '').upper().replace('B-','')
    if '_' in norm:
        a,b=norm.split('_',1); return a,b
    return '', ''


def _market_details_map(client):
    try: details=client.spot_market_details()
    except Exception: return {}, {}
    pair_map={}; code_map={}
    for d in details if isinstance(details,list) else []:
        if not isinstance(d,dict): continue
        pair=str(d.get('pair') or d.get('symbol') or d.get('market') or '')
        code=str(d.get('market') or d.get('symbol') or '')
        if pair: pair_map[norm_pair(pair)]=d
        if code: code_map[norm_pair(code)]=pair or code
    return pair_map, code_map


def _find_order(db, product, exchange_order_id='', client_order_id=''):
    if client_order_id:
        row=db.scalar(select(OrderRecord).where(OrderRecord.client_order_id==str(client_order_id)))
        if row: return row
    if exchange_order_id:
        row=db.scalar(select(OrderRecord).where(OrderRecord.run_mode=='live',OrderRecord.product==product,OrderRecord.external_order_id==str(exchange_order_id)))
        if row: return row
    return None


def _apply_strategy_fill(db: Session, fill: ExecutionFill):
    """Update bot-owned average-price inventory and realized gross P&L from one exchange fill."""
    if not fill.strategy_owned or fill.quantity <= 0 or fill.price <= 0: return
    pos=db.scalar(select(StrategyPosition).where(StrategyPosition.product==fill.product, StrategyPosition.pair==fill.pair))
    if not pos:
        pos=StrategyPosition(product=fill.product,pair=fill.pair,signed_quantity=0,average_entry_price=0,realized_pnl_inr=0)
        db.add(pos); db.flush()
    old=float(pos.signed_quantity or 0); avg=float(pos.average_entry_price or 0)
    delta=float(fill.quantity)*(1 if fill.side=='buy' else -1)
    new=old+delta
    realized_quote=0.0
    if abs(old)<1e-12 or old*delta>0:
        total=abs(old)+abs(delta)
        avg=((abs(old)*avg)+(abs(delta)*fill.price))/total if total else fill.price
    else:
        closing=min(abs(old),abs(delta))
        realized_quote=closing*(fill.price-avg)*(1 if old>0 else -1)
        if abs(new)<1e-12: avg=0.0; new=0.0
        elif old*new<0: avg=fill.price
        # Same-side residual retains the previous average price.
    fx=env_float('INR_PER_USDT',94.75)
    realized_inr=realized_quote*fx
    pos.signed_quantity=new; pos.average_entry_price=avg; pos.realized_pnl_inr=float(pos.realized_pnl_inr or 0)+realized_inr
    pos.updated_at=utcnow()
    if abs(realized_inr)>1e-9:
        _insert_ledger(db, f'realized:{fill.external_fill_id}', category='strategy_realized_pnl', amount=realized_inr,
          currency='INR', product=fill.product, pair=fill.pair, cash_effect=False,
          external_ref=fill.external_fill_id, occurred_at=fill.occurred_at,
          details={'gross_pnl_inr':realized_inr,'quantity_closed_quote_units':closing if 'closing' in locals() else 0,
                   'fill_price':fill.price,'avg_entry_before_fill':avg,'strategy_owned':True})


def _record_fill(db: Session, *, external_fill_id: str, order: OrderRecord | None, product: str,
                 pair: str, side: str, quantity: float, price: float, occurred_at,
                 fee_amount=0.0, fee_currency='UNKNOWN', source='exchange_trade_history', raw=None,
                 base_asset='', quote_asset=''):
    if not external_fill_id or quantity <= 0 or price <= 0 or side not in ('buy','sell'):
        return False
    if db.scalar(select(ExecutionFill.id).where(ExecutionFill.external_fill_id==external_fill_id)) is not None:
        return False
    auto_owned=bool(order and order.client_order_id.startswith('cst-auto-'))
    fill=ExecutionFill(external_fill_id=external_fill_id, order_record_id=order.id if order else None,
        occurred_at=occurred_at or utcnow(), run_mode='live_auto' if auto_owned else 'live', product=product,
        pair=pair, side=side, quantity=float(quantity), price=float(price), notional=float(quantity)*float(price),
        fee_amount=float(fee_amount or 0), fee_currency=(fee_currency or 'UNKNOWN')[:20],
        strategy_owned=auto_owned, source=source, raw_json=json.dumps(raw or {},default=str)[:12000])
    db.add(fill); db.flush()
    if product=='spot':
        base_asset=(base_asset or _assets(pair)[0] or 'UNKNOWN').upper()
        quote_asset=(quote_asset or _assets(pair)[1] or 'UNKNOWN').upper()
        direction=1 if side=='buy' else -1
        _insert_ledger(db, f'fill:{external_fill_id}:base',category='spot_base_movement',amount=direction*quantity,currency=base_asset,
          product=product,pair=pair,cash_effect=True,external_ref=external_fill_id,occurred_at=occurred_at,
          details={'side':side,'quantity':quantity,'price':price,'source':source})
        _insert_ledger(db, f'fill:{external_fill_id}:quote',category='spot_quote_movement',amount=-direction*quantity*price,currency=quote_asset,
          product=product,pair=pair,cash_effect=True,external_ref=external_fill_id,occurred_at=occurred_at,
          details={'side':side,'quantity':quantity,'price':price,'source':source})
    else:
        _insert_ledger(db, f'fill:{external_fill_id}:position',category='futures_position_delta',amount=quantity*(1 if side=='buy' else -1),
          currency=_assets(pair)[0] or 'UNDERLYING',product=product,pair=pair,cash_effect=False,external_ref=external_fill_id,
          occurred_at=occurred_at,details={'price':price,'notional_usdt':quantity*price,'side':side,'source':source})
    if float(fee_amount or 0):
        # Spot account trade-history rows expose fee_amount; where the response omits a
        # fee-currency field, the market metadata's price/quote currency is used by
        # _save_spot_account_trades. Book this separately as a real spot cash movement.
        # Futures fee cashflows come from the futures transaction endpoint; a fill-side
        # fee remains memo-only there to avoid double-counting the same fee.
        fee_ccy=(fee_currency or 'UNKNOWN').upper()
        known=fee_ccy not in ('UNKNOWN','')
        if product == 'spot' and known:
            _insert_ledger(db, f'fill:{external_fill_id}:spot-fee-cash', category='spot_fee_cash_movement', amount=-abs(float(fee_amount)),
              currency=fee_ccy,product=product,pair=pair,cash_effect=True,
              status='reconciled',external_ref=external_fill_id,occurred_at=occurred_at,
              details={'fee_source':source,'currency_source':'exchange_field_or_market_quote_currency',
                       'spot_trade_fee_booked_as_cash_movement':True})
        else:
            _insert_ledger(db, f'fill:{external_fill_id}:fee-reference', category='fill_fee_reference', amount=-abs(float(fee_amount)),
              currency=fee_ccy,product=product,pair=pair,cash_effect=False,
              status='reference_only' if known else 'needs_fee_currency',external_ref=external_fill_id,occurred_at=occurred_at,
              details={'fee_source':source,'not_used_as_account_cashflow':True,
                       'reason':'Futures cash fee comes from futures transactions' if product=='futures' else 'Fee currency unknown'})
        if auto_owned and known and fee_ccy in ('USDT','INR'):
            fx=env_float('INR_PER_USDT',94.75) if fee_ccy=='USDT' else 1.0
            _insert_ledger(db, f'fill:{external_fill_id}:strategy-fee-risk', category='strategy_fee_for_risk',
              amount=-abs(float(fee_amount))*fx,currency='INR',product=product,pair=pair,cash_effect=False,
              status='reference_only',external_ref=external_fill_id,occurred_at=occurred_at,
              details={'original_fee':float(fee_amount),'original_currency':fee_ccy,'conversion_inr_per_usdt':fx,
                       'used_for_bot_daily_loss_gate':True,
                       'cashflow_source':'spot fill cash-fee row or futures account transaction'})
    _apply_strategy_fill(db,fill)
    return True


def _normalize_exchange_status(value):
    raw=str(value or '').lower()
    return {'init':'open','open':'open','partially_filled':'partially_filled','partial':'partially_filled',
            'filled':'filled','close':'filled','cancelled':'cancelled','partially_cancelled':'partially_cancelled',
            'rejected':'rejected','untriggered':'open'}.get(raw, raw or 'unknown')


def _save_spot_account_trades(db, client, detail_map, pair_code_map, now_ms):
    runtime=read_config(db,'runtime',{})
    last_ms=runtime.get('last_spot_trade_sync_ms')
    start_ms=max(0,int(last_ms)-120_000) if last_ms else int((utcnow()-timedelta(days=1)).timestamp()*1000)
    from_id=runtime.get('last_spot_trade_id')
    found=[]; pages=0; latest_ms=int(last_ms or 0); latest_id=int(runtime.get('last_spot_trade_id') or 0); sync_error=None
    for _ in range(10):
        try: raw=client.spot_trade_history(from_id=int(from_id) if from_id else None, limit=500, sort='asc')
        except Exception as exc:
            sync_error=str(exc)[:400]; break
        rows=_list_data(raw); pages+=1
        if not rows: break
        found.extend(rows)
        for row in rows:
            try:
                latest_id=max(latest_id,int(row.get('id') or 0))
                ts_raw=float(row.get('timestamp') or 0); ts_ms=int(ts_raw*1000 if ts_raw and ts_raw<10_000_000_000 else ts_raw); latest_ms=max(latest_ms,ts_ms)
            except Exception: pass
        if len(rows)<500: break
        new_id=max([int(r.get('id') or 0) for r in rows] or [0])
        if new_id <= int(from_id or 0):
            sync_error='Pagination did not advance; stopped to avoid duplicate loop.'; break
        from_id=new_id
    order_lookup={str(o.external_order_id):o for o in db.scalars(select(OrderRecord).where(OrderRecord.run_mode=='live',OrderRecord.product=='spot')).all() if o.external_order_id}
    order_lookup.update({str(o.client_order_id):o for o in db.scalars(select(OrderRecord).where(OrderRecord.run_mode=='live',OrderRecord.product=='spot')).all() if o.client_order_id})
    saved=0
    for tr in found:
        symbol=str(tr.get('symbol') or tr.get('market') or '')
        pair=pair_code_map.get(norm_pair(symbol),symbol)
        # If code is actually a pair, retain the pair-form identifier.
        detail=detail_map.get(norm_pair(pair),{})
        order_id=str(tr.get('order_id') or '')
        local_order=order_lookup.get(order_id)
        quantity=_safe_float(tr.get('quantity')); price=_safe_float(tr.get('price'))
        try: trade_id=str(tr.get('id'))
        except Exception: trade_id=''
        timestamp=tr.get('timestamp') or tr.get('created_at')
        occurred=_ts(timestamp)
        base,quote=_assets(pair,detail)
        fill_key='spot-trade:'+trade_id if trade_id else 'spot-trade:'+_hash_key(tr)
        # CoinDCX spot account-trade-history documents fee_amount as a fee in the
        # market's price/base currency. For our USDT-quoted strategy pairs this is USDT.
        fee_currency=(tr.get('fee_currency') or tr.get('fee_currency_short_name') or quote or 'UNKNOWN')
        if _record_fill(db,external_fill_id=fill_key,order=local_order,product='spot',pair=pair,side=str(tr.get('side') or '').lower(),
                        quantity=quantity,price=price,occurred_at=occurred,fee_amount=_safe_float(tr.get('fee_amount')) or 0,
                        fee_currency=fee_currency,source='spot_account_trade_history',raw=tr,base_asset=base,quote_asset=quote): saved+=1
        if local_order and local_order.status not in TERMINAL_EXCHANGE_STATES:
            # A trade-history row proves at least a partial execution, not that the
            # whole order filled. The status endpoint below determines final state.
            local_order.status='partially_filled'
            if not local_order.external_order_id: local_order.external_order_id=order_id
    if pages and found:
        runtime['last_spot_trade_sync_ms']=max(latest_ms,int(now_ms)-2_000)
        runtime['last_spot_trade_id']=latest_id
    if len(found)>=5000 and not sync_error:
        sync_error='Reached 10-page spot trade history ceiling; additional history may remain. Increase pagination before claiming full reconciliation.'
    runtime['last_spot_trade_sync_error']=sync_error
    write_config(db,'runtime',runtime)
    return {'rows_seen':len(found),'fills_inserted':saved,'pages':pages,'error':sync_error}


def _safe_float(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception: return None


def _reconcile_order_statuses(db, client):
    orders=db.scalars(select(OrderRecord).where(OrderRecord.run_mode=='live',OrderRecord.created_at>=utcnow()-timedelta(days=30)).order_by(OrderRecord.created_at)).all()
    spot_orders=[o for o in orders if o.product=='spot' and (o.status in ACTIVE_ORDER_STATES or o.created_at>=utcnow()-timedelta(hours=24))]
    futures_orders=[o for o in orders if o.product=='futures' and (o.status in ACTIVE_ORDER_STATES or o.created_at>=utcnow()-timedelta(hours=24))]
    futures_map={}
    errors=[]
    for side in ('buy','sell'):
        try:
            result=client.futures_order_list(side=side,size=1000)
            for row in _list_data(result):
                oid=str(row.get('id') or ''); cid=str(row.get('client_order_id') or '')
                if oid: futures_map['id:'+oid]=row
                if cid: futures_map['cid:'+cid]=row
        except Exception as exc: errors.append(f'futures order list {side}: {exc}')
    updated=0; futures_fill_count=0
    for order in spot_orders:
        try:
            raw=client.spot_order_status(order_id=order.external_order_id or None,client_order_id=order.client_order_id if not order.external_order_id else None)
            items=_list_data(raw); info=items[0] if items else (raw if isinstance(raw,dict) else {})
            status=_normalize_exchange_status(info.get('status'))
            if status: order.status=status
            if info.get('id'): order.external_order_id=str(info.get('id'))
            # Do not claim final fill reconciliation until real trade-history rows exist.
            if status=='filled' and not db.scalar(select(ExecutionFill.id).where(ExecutionFill.order_record_id==order.id)):
                order.status='filled_unreconciled'
            order.details_json=json.dumps({'last_exchange_status':info},default=str)[:12000]
            updated+=1
        except Exception as exc:
            errors.append(f'spot status {order.id}: {exc}')
            if order.status=='submitted' and order.created_at < utcnow()-timedelta(minutes=3): order.status='unknown'
    for order in futures_orders:
        info=futures_map.get('id:'+str(order.external_order_id)) if order.external_order_id else None
        info=info or futures_map.get('cid:'+str(order.client_order_id))
        if info:
            if info.get('id'): order.external_order_id=str(info.get('id'))
            order.status=_normalize_exchange_status(info.get('status'))
            order.details_json=json.dumps({'last_exchange_status':info},default=str)[:12000]
            updated+=1
        elif order.status in {'submitting','submitted'} and order.created_at < utcnow()-timedelta(minutes=3):
            order.status='unknown'
            errors.append(f'futures order {order.id}: not found in exchange order-list response; no retry will be attempted automatically')
        if order.external_order_id:
            # Query exact fill history for locally requested orders. Exchange trade rows are
            # the source of executed quantity/price; order acceptance alone is never a fill.
            try:
                from_d=(order.created_at.replace(tzinfo=timezone.utc) if order.created_at.tzinfo is None else order.created_at).date().isoformat()
                to_d=utcnow().date().isoformat()
                raw_tr=client.futures_trade_history(order.pair,order.external_order_id,from_d,to_d,page=1,size=1000)
                trades=_list_data(raw_tr)
                for tr in trades:
                    q=_safe_float(tr.get('quantity')); p=_safe_float(tr.get('price'))
                    if not q or not p: continue
                    ts=_ts(tr.get('timestamp') or tr.get('created_at'))
                    fill_key='futures-trade:'+_hash_key({'order_id':str(tr.get('order_id') or order.external_order_id or ''),'timestamp':tr.get('timestamp') or tr.get('created_at'),'price':p,'quantity':q,'side':str(tr.get('side') or order.side).lower(),'pair':tr.get('pair') or order.pair,'is_maker':tr.get('is_maker')})
                    saved=_record_fill(db,external_fill_id=fill_key,order=order,product='futures',pair=str(tr.get('pair') or order.pair),side=str(tr.get('side') or order.side).lower(),quantity=q,price=p,occurred_at=ts,fee_amount=_safe_float(tr.get('fee_amount')) or 0,fee_currency=tr.get('margin_currency_short_name') or 'USDT',source='futures_order_trade_history',raw=tr)
                    futures_fill_count += int(saved)
                if _normalize_exchange_status(order.status)=='filled' and not trades:
                    # Keep the event unresolved rather than fabricating a fill from avg_price.
                    order.status='filled_unreconciled'
            except Exception as exc:
                errors.append(f'futures trades {order.id}: {exc}')
                if order.status=='filled': order.status='filled_unreconciled'
    return {'orders_checked':updated,'futures_fills_inserted':futures_fill_count,'errors':errors}



def _sync_futures_account_trades(db, client):
    """Import account-wide futures fills for configured pairs, including external/manual orders.

    This rolling authenticated trade-history sync omits order_id. It is idempotent and
    reports page caps/errors so the UI cannot silently claim complete reconciliation.
    """
    runtime = read_config(db, 'runtime', {})
    last = runtime.get('last_futures_trade_sync_at')
    min_interval = max(120, env_int('LIVE_FUTURES_TRADE_SYNC_SECONDS', 300))
    if last:
        try:
            last_dt = datetime.fromisoformat(str(last).replace('Z', '+00:00'))
            if (utcnow() - last_dt).total_seconds() < min_interval:
                return {'skipped': 'interval', 'warning': runtime.get('futures_trade_sync_warning'),
                        'error': runtime.get('futures_trade_sync_error')}
        except Exception:
            pass
    days = max(1, min(14, env_int('LIVE_FUTURES_TRADE_SYNC_DAYS', 3)))
    max_pages = max(1, min(20, env_int('LIVE_FUTURES_TRADES_MAX_PAGES_PER_PAIR', 5)))
    page_size = 500
    from_date = (utcnow() - timedelta(days=days)).date().isoformat()
    to_date = utcnow().date().isoformat()
    seen = inserted = pages = 0
    errors, capped_pairs = [], []
    for pair in PAIR_UNIVERSE:
        try:
            for page in range(1, max_pages + 1):
                try:
                    raw = client.futures_trade_history(pair, None, from_date, to_date, page=page, size=page_size)
                except Exception as exc:
                    errors.append(f'{pair} page {page}: {str(exc)[:250]}')
                    break
                batch = _list_data(raw)
                pages += 1; seen += len(batch)
                for tr in batch:
                    q = _safe_float(tr.get('quantity') if tr.get('quantity') is not None else tr.get('q'))
                    px = _safe_float(tr.get('price') if tr.get('price') is not None else tr.get('p'))
                    side = str(tr.get('side') or '').lower()
                    if side not in ('buy', 'sell') or not q or not px:
                        continue
                    order_id = str(tr.get('order_id') or '')
                    local_order = _find_order(db, 'futures', exchange_order_id=order_id) if order_id else None
                    ts_raw = tr.get('timestamp') or tr.get('created_at')
                    fill_key = 'futures-trade:' + _hash_key({
                        'order_id': order_id, 'timestamp': ts_raw, 'price': px,
                        'quantity': q, 'side': side, 'pair': tr.get('pair') or pair,
                        'is_maker': tr.get('is_maker')
                    })
                    inserted += int(_record_fill(db, external_fill_id=fill_key, order=local_order,
                        product='futures', pair=str(tr.get('pair') or pair), side=side,
                        quantity=q, price=px, occurred_at=_ts(ts_raw),
                        fee_amount=_safe_float(tr.get('fee_amount')) or 0.0,
                        fee_currency=tr.get('margin_currency_short_name') or 'USDT',
                        source='futures_account_trade_history', raw=tr))
                if len(batch) < page_size:
                    break
                if page == max_pages:
                    capped_pairs.append(pair)
        except Exception as exc:
            errors.append(f'{pair}: {str(exc)[:250]}')
    runtime['last_futures_trade_sync_at'] = utcnow().isoformat()
    runtime['futures_trade_rows_seen'] = seen
    runtime['futures_trade_rows_inserted'] = inserted
    runtime['futures_trade_pages_seen'] = pages
    runtime['futures_trade_sync_error'] = '; '.join(errors[:30]) if errors else None
    runtime['futures_trade_sync_warning'] = (
        f"Reached the {max_pages}-page limit for: {', '.join(capped_pairs[:20])}; additional fills may remain."
        if capped_pairs else None)
    write_config(db, 'runtime', runtime)
    return {'rows_seen': seen, 'fills_inserted': inserted, 'pages_seen': pages,
            'capped_pairs': capped_pairs, 'error': runtime['futures_trade_sync_error'],
            'warning': runtime['futures_trade_sync_warning']}

def _sync_futures_transactions(db, client):
    """Idempotently ingest paginated futures P&L/fee/funding transactions."""
    runtime=read_config(db,'runtime',{})
    last=runtime.get('last_futures_tx_sync_at')
    if last:
        try:
            last_dt=datetime.fromisoformat(str(last).replace('Z','+00:00'))
            if (utcnow()-last_dt).total_seconds()<240:
                return {'skipped':'interval','warning':runtime.get('futures_tx_sync_warning'),'error':runtime.get('futures_tx_sync_error')}
        except Exception: pass
    max_pages=max(1,min(20,env_int('LIVE_FUTURES_TX_MAX_PAGES',10)))
    rows=[]; errors=[]; pages=0
    for page in range(1,max_pages+1):
        try:
            raw=client.futures_transactions(size=1000,page=page,stage='all')
        except Exception as exc:
            errors.append(f'page {page}: {str(exc)[:300]}'); break
        batch=_list_data(raw); pages+=1; rows.extend(batch)
        if len(batch)<1000: break
    inserted=0
    for row in rows:
        ref=_hash_key({'id':row.get('id') or row.get('transaction_id') or row.get('transactionId'),'pair':row.get('pair'),'parent_id':row.get('parent_id'),'position_id':row.get('position_id'),'created_at':row.get('created_at'),'updated_at':row.get('updated_at'),'stage':row.get('stage'),'amount':row.get('amount'),'fee_amount':row.get('fee_amount'),'source':row.get('source')})
        occurred=_ts(row.get('created_at'))
        currency=str(row.get('margin_currency_short_name') or 'USDT').upper()
        pair=str(row.get('pair') or '')
        amount=_safe_float(row.get('amount'))
        if amount not in (None,0):
            inserted+=int(_insert_ledger(db,f'futures-tx:{ref}:amount',category='futures_exchange_transaction_pnl',amount=amount,currency=currency,product='futures',pair=pair,cash_effect=True,external_ref=str(row.get('parent_id') or ref),occurred_at=occurred,details=row))
        fee=_safe_float(row.get('fee_amount')) or 0
        if fee:
            inserted+=int(_insert_ledger(db,f'futures-tx:{ref}:fee',category='futures_exchange_transaction_fee',amount=-abs(fee),currency=currency,product='futures',pair=pair,cash_effect=True,external_ref=str(row.get('parent_id') or ref),occurred_at=occurred,details=row))
    runtime['last_futures_tx_sync_at']=utcnow().isoformat()
    runtime['futures_tx_sync_error']='; '.join(errors) if errors else None
    runtime['futures_tx_rows_seen']=len(rows); runtime['futures_tx_pages_seen']=pages
    if pages>=max_pages and len(rows)>=max_pages*1000:
        runtime['futures_tx_sync_warning']=f'Reached {max_pages*1000} transaction rows in the configured pagination ceiling; more history may remain.'
    else:
        runtime['futures_tx_sync_warning']=None
    write_config(db,'runtime',runtime)
    return {'rows_seen':len(rows),'pages_seen':pages,'ledger_entries_added':inserted,'error':runtime['futures_tx_sync_error'],'warning':runtime['futures_tx_sync_warning']}


def _snapshot_account(db, client):
    runtime=read_config(db,'runtime',{})
    last=runtime.get('last_account_snapshot_at')
    if last:
        try:
            dt=datetime.fromisoformat(str(last).replace('Z','+00:00'))
            if (utcnow()-dt).total_seconds()<300: return {'skipped':'interval'}
        except Exception: pass
    values={}; errors=[]
    for name,fn in [('spot',client.spot_balances),('wallets',client.futures_wallets),('positions',client.futures_positions)]:
        try: values[name]=fn()
        except Exception as exc: values[name]=[]; errors.append(f'{name}: {exc}')
    snap=AccountSnapshot(status='partial' if errors else 'ok',spot_balances_json=json.dumps(values.get('spot',[]),default=str)[:200000],
        futures_wallets_json=json.dumps(values.get('wallets',[]),default=str)[:200000],futures_positions_json=json.dumps(values.get('positions',[]),default=str)[:200000],
        warnings_json=json.dumps(errors)[:12000])
    db.add(snap)
    runtime['last_account_snapshot_at']=utcnow().isoformat(); runtime['last_account_snapshot_status']=snap.status; runtime['last_account_snapshot_errors']=errors
    write_config(db,'runtime',runtime)
    return {'status':snap.status,'errors':errors}


def collect_market_telemetry(db: Session):
    cfg=read_config(db,'strategy_config',{})
    rows=db.scalars(select(MarketSnapshot)).all(); now=utcnow()
    data={'market_count':len(rows),'products':{},'stale_count':0,'missing_bid_ask_count':0,'unknown_turnover_count':0,
          'spread_bps':[],'liquidity_source_counts':{},'eligible_count':0,'api_error':read_config(db,'runtime',{}).get('market_refresh_error')}
    for r in rows:
        pr=data['products'].setdefault(r.product,{'count':0,'active':0,'fresh':0,'eligible':0,'book_available':0,'depth_known':0})
        pr['count']+=1; pr['active']+=int(bool(r.active))
        age=(now-(r.updated_at.replace(tzinfo=timezone.utc) if r.updated_at.tzinfo is None else r.updated_at)).total_seconds()
        if age>int(cfg.get('max_stale_seconds',120)): data['stale_count']+=1
        else: pr['fresh']+=1
        if not r.bid or not r.ask: data['missing_bid_ask_count']+=1
        spread=market_spread_bps(r.bid,r.ask)
        if spread is not None: data['spread_bps'].append(round(spread,3))
        if r.quote_turnover_usdt is None: data['unknown_turnover_count']+=1
        data['liquidity_source_counts'][r.liquidity_source]=data['liquidity_source_counts'].get(r.liquidity_source,0)+1
        raw=safe_json(r.raw_json)
        book=raw.get('spot_orderbook') if r.product=='spot' else raw.get('futures_orderbook')
        if book: pr['book_available']+=1
        bid_depth,ask_depth=book_depth(book)
        if bid_depth is not None and ask_depth is not None: pr['depth_known']+=1
        ok,_=market_eligibility(r,cfg)
        if ok: pr['eligible']+=1; data['eligible_count']+=1
    spreads=sorted(data['spread_bps'])
    data['spread_median_bps']=(spreads[len(spreads)//2] if spreads else None)
    data['spread_max_bps']=max(spreads) if spreads else None
    data['as_of']=now.isoformat()
    db.add(TelemetrySnapshot(status='warning' if data['api_error'] or data['stale_count'] or data['unknown_turnover_count'] else 'ok',details_json=json.dumps(data,default=str)[:50000]))
    runtime=read_config(db,'runtime',{}); runtime['last_market_quality']=data; write_config(db,'runtime',runtime)
    return data


def book_depth(book):
    if not isinstance(book,dict): return None,None
    def depth(levels):
        total=0.0; seen=False
        if isinstance(levels,dict):
            it=levels.items()
            for p,q in it:
                try: pp=float(p); qq=float(q)
                except Exception: continue
                if pp>0 and qq>0: total+=pp*qq; seen=True
        elif isinstance(levels,list):
            for x in levels:
                try:
                    if isinstance(x,dict): pp=float(x.get('price') or x.get('p') or x.get('rate')); qq=float(x.get('quantity') or x.get('qty') or x.get('amount') or x.get('q'))
                    else: pp=float(x[0]); qq=float(x[1])
                except Exception: continue
                if pp>0 and qq>0: total+=pp*qq; seen=True
        return total if seen else None
    return depth(book.get('bids')),depth(book.get('asks'))


def _backfill_spot_fee_cash_movements(db: Session, batch_size: int = 2000):
    """Backfill spot fee cashflows from fills saved by earlier app versions, idempotently."""
    runtime=read_config(db,'runtime',{})
    cursor=int(runtime.get('spot_fee_backfill_fill_id') or 0)
    rows=db.scalars(select(ExecutionFill).where(ExecutionFill.id>cursor,ExecutionFill.product=='spot',ExecutionFill.fee_amount>0).order_by(ExecutionFill.id).limit(max(1,min(batch_size,5000)))).all()
    inserted=0
    for fill in rows:
        fee_ccy=str(fill.fee_currency or 'UNKNOWN').upper()
        if fee_ccy not in ('UNKNOWN',''):
            inserted += int(_insert_ledger(db, f'fill:{fill.external_fill_id}:spot-fee-cash', category='spot_fee_cash_movement', amount=-abs(float(fill.fee_amount)),
                currency=fee_ccy,product='spot',pair=fill.pair,cash_effect=True,status='reconciled',
                external_ref=fill.external_fill_id,occurred_at=fill.occurred_at,
                details={'fee_source':fill.source,'backfilled':True,'currency_source':'stored_fill_fee_currency'}))
        cursor=max(cursor,fill.id)
    runtime['spot_fee_backfill_fill_id']=cursor
    runtime['spot_fee_backfill_rows_seen']=len(rows)
    runtime['spot_fee_backfill_more']=len(rows)>=max(1,min(batch_size,5000))
    write_config(db,'runtime',runtime)
    return {'rows_seen':len(rows),'cash_movements_added':inserted,'more':runtime['spot_fee_backfill_more']}


def reconcile_live_account(db: Session):
    client=CoinDCXClient()
    if not client.credentials_present: return {'status':'not_configured'}
    try:
        details,code_map=_market_details_map(client)
        now_ms=int(time.time()*1000)
        spot=_save_spot_account_trades(db,client,details,code_map,now_ms)
        fee_backfill=_backfill_spot_fee_cash_movements(db)
        orders=_reconcile_order_statuses(db,client)
        futures_trades=_sync_futures_account_trades(db,client)
        tx=_sync_futures_transactions(db,client)
        snap=_snapshot_account(db,client)
        runtime=read_config(db,'runtime',{}); runtime['last_live_reconciliation_at']=utcnow().isoformat();
        runtime['last_live_reconciliation_status']='warning' if orders.get('errors') or spot.get('error') or futures_trades.get('error') or futures_trades.get('warning') or tx.get('error') or tx.get('warning') or snap.get('errors') or fee_backfill.get('more') else 'ok'
        runtime['last_live_reconciliation']={'spot':spot,'spot_fee_backfill':fee_backfill,'orders':orders,'futures_account_trades':futures_trades,'futures_transactions':tx,'account_snapshot':snap}
        write_config(db,'runtime',runtime)
        if runtime['last_live_reconciliation_status']!='ok': log_event(db,'Live ledger reconciliation has gaps; automated rebalancing will fail closed.', 'WARNING','ledger',runtime['last_live_reconciliation'])
        db.commit()
        return runtime['last_live_reconciliation']
    except Exception as exc:
        log_event(db,f'Live account reconciliation failed: {exc}','ERROR','ledger')
        runtime=read_config(db,'runtime',{}); runtime['last_live_reconciliation_status']='error'; runtime['last_live_reconciliation_error']=str(exc)[:500]; write_config(db,'runtime',runtime)
        db.commit()
        return {'error':str(exc)[:500]}


def _metadata_quantity(price_qty: float, product: str, pair: str, detail=None, instrument=None, reference_price: float | None = None, order_type: str = 'market_order'):
    meta=(detail or {}) if product=='spot' else (instrument or {})
    if isinstance(meta,list): meta=meta[0] if meta and isinstance(meta[0],dict) else {}
    # Prefer explicit quantity increment/step; otherwise use documented asset precision.
    step=None
    for key in ('quantity_increment','quantity_step','qty_step','step_size','quantity_step_size','amount_step','step'):
        v=_safe_float(meta.get(key))
        if v and v>0: step=v; break
    precision=None
    for key in ('target_currency_precision','quantity_precision','qty_precision','base_currency_precision','amount_precision'):
        v=_safe_float(meta.get(key))
        if v is not None and 0<=v<=12 and float(v).is_integer(): precision=int(v); break
    q=float(price_qty)
    if step:
        q=math.floor((q+1e-12)/step)*step
    elif precision is not None:
        factor=10**precision; q=math.floor((q*factor)+1e-10)/factor
    else:
        return None, 'Exchange quantity precision/step could not be confirmed; refusing to guess.'
    min_q=None
    for key in ('min_quantity','min_qty','min_trade_size','min_order_quantity','minimum_quantity','min_market_orders_qty') if order_type == 'market_order' else ('min_quantity','min_qty','min_trade_size','min_order_quantity','minimum_quantity'):
        v=_safe_float(meta.get(key))
        if v and v>0: min_q=v; break
    if q<=0: return None,'Quantity rounds to zero at exchange precision.'
    if precision is not None:
        precision_min=10**(-precision)
        min_q=max(min_q or 0.0, precision_min)
    if min_q is not None and q<min_q: return None,f'Quantity {q:g} is below effective exchange minimum {min_q:g}.'
    min_notional=_safe_float(meta.get('min_notional'))
    if reference_price and min_notional and q*float(reference_price)<min_notional:
        return None,f'Notional {q*float(reference_price):.8g} is below exchange min_notional {min_notional:g}.'
    max_q=None
    for key in ('max_quantity','max_qty','max_order_quantity','max_quantity_market') if order_type == 'market_order' else ('max_quantity','max_qty','max_order_quantity'):
        v=_safe_float(meta.get(key))
        if v and v>0: max_q=v; break
    if max_q and q>max_q: return None,f'Quantity {q:g} exceeds exchange maximum {max_q:g}.'
    return q, None


def _free_balance(rows, currency):
    currency=str(currency or '').upper()
    for row in _list_data(rows):
        cur=str(row.get('currency_short_name') or row.get('currency') or row.get('currency_full_name') or '').upper()
        if cur!=currency: continue
        bal=_safe_float(row.get('balance') or row.get('available_balance') or row.get('free'))
        locked=_safe_float(row.get('locked_balance')) or 0.0
        if bal is None: return None
        return max(0.0,bal-locked)
    return 0.0


def _futures_free_wallet(rows):
    for row in _list_data(rows):
        cur=str(row.get('currency_short_name') or '').upper()
        if cur!='USDT': continue
        bal=_safe_float(row.get('balance'))
        if bal is None: return None
        locked=(_safe_float(row.get('locked_balance')) or 0)+(_safe_float(row.get('cross_order_margin')) or 0)+(_safe_float(row.get('cross_user_margin')) or 0)
        return max(0.0,bal-locked)
    return None


def _live_quality(snap, cfg, product, estimated_notional):
    ok,why=market_eligibility(snap,cfg)
    if not ok: return False,why
    raw=safe_json(snap.raw_json)
    book=raw.get('spot_orderbook') if product=='spot' else raw.get('futures_orderbook')
    bid_depth,ask_depth=book_depth(book)
    if env_bool('LIVE_REQUIRE_ORDERBOOK_DEPTH',True):
        if bid_depth is None or ask_depth is None: return False,'Order-book depth could not be parsed; failing closed.'
        required=max(env_float('LIVE_MIN_BOOK_DEPTH_USDT',50),float(estimated_notional or 0)*env_float('LIVE_BOOK_DEPTH_MULTIPLE',3))
        if min(bid_depth,ask_depth)<required: return False,f'Visible top-book depth {min(bid_depth,ask_depth):.2f} USDT below {required:.2f} USDT.'
    return True,'fresh market + spread/turnover + visible book depth pass'


def _auto_order(db, client, product, pair, side, quantity, leverage, spot_details):
    cfg=read_config(db,'strategy_config',{})
    snap=db.scalar(select(MarketSnapshot).where(MarketSnapshot.product==product,MarketSnapshot.pair==pair))
    px=float(snap.last_price) if snap and snap.last_price else 0
    notional=abs(quantity*px)
    good,reason=_live_quality(snap,cfg,product,notional) if snap else (False,'No market snapshot.')
    if not good: raise RuntimeError(f'{product} {pair} order blocked: {reason}')
    max_order=env_float('LIVE_AUTO_MAX_ORDER_NOTIONAL_USDT',10)
    if notional>max_order+1e-6: raise RuntimeError(f'{pair} order notional {notional:.4f} exceeds automated order cap {max_order:.2f} USDT.')
    client_id=f'cst-auto-{utcnow().strftime("%Y%m%d")}-{product}-{norm_pair(pair)[:10]}-{side}-{int(time.time()*1000)}'
    record=OrderRecord(run_mode='live',product=product,pair=pair,side=side,order_type='market_order',quantity=quantity,requested_price=px,
                       status='submitting',client_order_id=client_id,details_json=json.dumps({'origin':'auto_strategy','strategy':'CSM14D_VOL14D_LIQ7D_DAILY','quality_reason':reason,'estimated_notional_usdt':notional}))
    db.add(record); db.commit()  # durable idempotency marker before network submission
    submission_attempted=False
    try:
        if product=='spot':
            detail=spot_details.get(norm_pair(pair))
            if not detail: raise RuntimeError('Spot market details are missing; refusing symbol guess.')
            market=str(detail.get('market') or detail.get('symbol') or '')
            if not market: raise RuntimeError('CoinDCX spot market code missing.')
            submission_attempted=True
            resp=client.submit_spot_order(market,side,quantity,'market_order',None,detail.get('ecode'),client_id)
        else:
            instr=client.futures_instrument(pair,'USDT')
            if isinstance(instr,list): instr=instr[0] if instr else {}
            if not isinstance(instr,dict): instr={}
            if instr.get('exit_only') or instr.get('is_exit_only'): raise RuntimeError('Futures instrument is exit-only.')
            submission_attempted=True
            resp=client.submit_futures_order(pair,side,quantity,leverage,'market_order',None,'USDT',client_id)
        rows=_list_data(resp); info=rows[0] if rows else (resp if isinstance(resp,dict) else {})
        record.external_order_id=str(info.get('id') or record.external_order_id or '')
        status=_normalize_exchange_status(info.get('status'))
        if status in ('filled','open','partially_filled','rejected','cancelled','partially_cancelled'):
            record.status=status
        elif isinstance(resp,dict) and (resp.get('code') in (200,'200') or resp.get('status') in (200,'200') or str(resp.get('message','')).lower()=='success'):
            record.status='submitted' if record.external_order_id else 'unknown'
        else:
            record.status='unknown'
        record.details_json=json.dumps({'origin':'auto_strategy','response':resp,'estimated_notional_usdt':notional,'quality_reason':reason},default=str)[:12000]
        log_event(db,f'Automated live order {record.id} {product} {side} {pair}: {record.status}.', 'WARNING' if record.status in ('unknown','submitted','open','partially_filled') else 'INFO','live',{'order_id':record.id,'external_order_id':record.external_order_id,'client_order_id':client_id,'notional_usdt':notional})
        db.commit()
        return {'ok':record.status not in ('unknown','rejected'),'order_id':record.id,'status':record.status}
    except Exception as exc:
        # Pre-flight failures are rejected; only an exception after calling the exchange
        # is ambiguous and must not be blindly retried.
        record.status='unknown' if submission_attempted else 'rejected'
        record.details_json=json.dumps({'origin':'auto_strategy','submission_error':str(exc),
            'submit_outcome':'ambiguous - reconcile before retry' if submission_attempted else 'rejected before exchange submission'},default=str)[:12000]
        log_event(db,f'Automated order {"outcome uncertain" if submission_attempted else "pre-flight rejected"} for {pair}: {exc}', 'ERROR' if submission_attempted else 'WARNING','live',{'order_id':record.id,'client_order_id':client_id})
        db.commit()
        return {'ok':False,'order_id':record.id,'status':record.status,'error':str(exc)[:300]}


def run_auto_live_cycle(db: Session):
    """Once-per-UTC-day daily rebalance. Requires two deployment gates and explicit UI arm."""
    if os.getenv('LIVE_TRADING_ENABLED','false').lower()!='true' or os.getenv('AUTO_LIVE_TRADING_ENABLED','false').lower()!='true':
        return {'status':'locked','reason':'Set both LIVE_TRADING_ENABLED and AUTO_LIVE_TRADING_ENABLED in Render, then explicitly arm in the UI.'}
    state=read_config(db,'live_state',{})
    if not state.get('armed') or not state.get('auto_live_armed'):
        return {'status':'disarmed','reason':'Automatic live trading is not explicitly armed in the UI.'}
    client=CoinDCXClient()
    if not client.credentials_present: return {'status':'blocked','reason':'CoinDCX API credentials missing.'}
    runtime=read_config(db,'runtime',{})
    today=utcnow().date().isoformat()
    if runtime.get('live_auto_last_success_date')==today: return {'status':'already_ran_today','date':today}
    last_attempt=runtime.get('live_auto_last_attempt_at')
    if last_attempt:
        try:
            dt=datetime.fromisoformat(str(last_attempt).replace('Z','+00:00'))
            if (utcnow()-dt).total_seconds()<env_int('LIVE_AUTO_RETRY_SECONDS',900): return {'status':'cooldown'}
        except Exception: pass
    runtime['live_auto_last_attempt_at']=utcnow().isoformat(); write_config(db,'runtime',runtime); db.commit()
    # No trade plan may be calculated while API reconciliation has unresolved orders.
    unresolved=db.scalars(select(OrderRecord).where(OrderRecord.run_mode=='live',OrderRecord.status.in_(list(ACTIVE_ORDER_STATES)))).all()
    if unresolved:
        reason=f'{len(unresolved)} live order(s) are unresolved. Reconcile fills/status before another rebalance.'
        runtime=read_config(db,'runtime',{}); runtime['live_auto_block_reason']=reason; write_config(db,'runtime',runtime)
        log_event(db,reason,'WARNING','live_auto'); db.commit(); return {'status':'blocked','reason':reason}
    rec_status=runtime.get('last_live_reconciliation_status')
    if rec_status != 'ok':
        reason='No clean live ledger reconciliation is available; automated execution paused until account, orders, fills and fees sync successfully.'
        runtime['live_auto_block_reason']=reason; write_config(db,'runtime',runtime); db.commit(); return {'status':'blocked','reason':reason}
    # Stop after the configured bot-owned realized daily drawdown; a full account-wide
    # intraday P&L limit requires the exchange's complete position mark/PNL snapshot.
    cap=env_float('LIVE_AUTO_MAX_DAILY_LOSS_INR',500)
    midnight=datetime.combine(utcnow().date(),datetime.min.time(),tzinfo=timezone.utc)
    daily=db.scalar(select(func.sum(LedgerEntry.amount)).where(LedgerEntry.category.in_(['strategy_realized_pnl','strategy_fee_for_risk']),LedgerEntry.occurred_at>=midnight)) or 0.0
    if daily <= -abs(cap):
        reason=f'Bot-owned realized daily loss {daily:.2f} INR reached configured cap {-abs(cap):.2f}; automation remains paused.'
        state.update({'armed':False,'armed_at':None,'auto_live_armed':False}); write_config(db,'live_state',state)
        runtime['live_auto_block_reason']=reason; write_config(db,'runtime',runtime); log_event(db,reason,'ERROR','risk'); db.commit()
        return {'status':'risk_stop','reason':reason}
    cfg=read_config(db,'strategy_config',{})
    scores=calculate_scores(db,cfg)
    enabled_products=[]
    if cfg.get('product_mode') in ('spot','both'): enabled_products.append('spot')
    if cfg.get('product_mode') in ('futures','both'): enabled_products.append('futures')
    universe=cfg.get('pair_universe',PAIR_UNIVERSE)
    missing=[]
    for product in enabled_products:
        scored=scores.get(product,{}).get('all_scored',[])
        if len(scored)<len(universe): missing.append(f'{product}: {len(scored)}/{len(universe)} pairs have valid signal data')
    if missing:
        reason='Incomplete signal data; refusing partial-universe live execution. '+ '; '.join(missing)
        runtime=read_config(db,'runtime',{}); runtime['live_auto_block_reason']=reason; write_config(db,'runtime',runtime)
        log_event(db,reason,'WARNING','live_auto'); db.commit(); return {'status':'blocked','reason':reason}
    pair_details,code_map=_market_details_map(client)
    # Load account-side truth once; if it is unavailable, do not place orders.
    try:
        spot_balances=client.spot_balances(); futures_wallets=client.futures_wallets(); futures_positions=client.futures_positions(size=100)
    except Exception as exc:
        reason=f'Could not verify exchange balances/positions before live cycle: {exc}'
        runtime=read_config(db,'runtime',{}); runtime['live_auto_block_reason']=reason; write_config(db,'runtime',runtime); log_event(db,reason,'ERROR','live_auto'); db.commit()
        return {'status':'blocked','reason':reason}
    spot_rows=_list_data(spot_balances); wallet_rows=_list_data(futures_wallets); pos_rows=_list_data(futures_positions)
    fx=float(cfg.get('inr_per_usdt',env_float('INR_PER_USDT',94.75)))
    spot_usdt=_free_balance(spot_rows,'USDT')
    futures_usdt=_futures_free_wallet(wallet_rows)
    if 'spot' in enabled_products and spot_usdt is None:
        reason='Spot free USDT balance could not be verified.'; runtime['live_auto_block_reason']=reason; write_config(db,'runtime',runtime); db.commit(); return {'status':'blocked','reason':reason}
    if 'futures' in enabled_products and futures_usdt is None:
        reason='Futures available USDT margin could not be estimated from wallet fields; futures auto mode blocked.'
        runtime['live_auto_block_reason']=reason; write_config(db,'runtime',runtime); db.commit(); return {'status':'blocked','reason':reason}
    # Prevent auto mode from silently taking over positions initiated outside this bot.
    tracked={(p.product,p.pair):p for p in db.scalars(select(StrategyPosition)).all()}
    for ex in pos_rows:
        pair=str(ex.get('pair') or '')
        q=_safe_float(ex.get('active_pos')) or 0
        if abs(q)<1e-9 or pair not in universe: continue
        own=tracked.get(('futures',pair)); own_q=float(own.signed_quantity) if own else 0.0
        if abs(q-own_q)>max(1e-6,abs(q)*0.02):
            reason=f'Untracked/pre-existing futures position detected in {pair} (exchange {q:g}, bot ledger {own_q:g}); use a dedicated account or reconcile ownership first.'
            runtime=read_config(db,'runtime',{}); runtime['live_auto_block_reason']=reason; write_config(db,'runtime',runtime); log_event(db,reason,'ERROR','live_auto'); db.commit()
            return {'status':'blocked','reason':reason}
    # Build desired signed quantities. Data-quality failures preserve existing holdings;
    # they are not interpreted as signals to liquidate blindly.
    desired={}; snapshots={(m.product,m.pair):m for m in db.scalars(select(MarketSnapshot)).all()}
    budget_inr=env_float('LIVE_AUTO_CAPITAL_BUDGET_INR',3000)
    total_budget_usdt=max(0,budget_inr/fx)
    max_order=env_float('LIVE_AUTO_MAX_ORDER_NOTIONAL_USDT',10)
    max_gross=env_float('LIVE_AUTO_MAX_GROSS_EXPOSURE_USDT',50)
    lev=min(max(1,int(cfg.get('futures_leverage',1))),env_int('LIVE_MAX_LEVERAGE',2))
    targets_by_product={'spot':[],'futures':[]}
    if 'spot' in enabled_products:
        targets_by_product['spot']=[x for x in scores['spot']['longs'] if x['score']>0]
    if 'futures' in enabled_products:
        targets_by_product['futures']=[*[(x,'buy') for x in scores['futures']['longs']],*[(x,'sell') for x in scores['futures']['shorts']]]
    weight_spot=env_float('LIVE_AUTO_SPOT_WEIGHT',0.4) if 'futures' in enabled_products else 1.0
    weight_futures=1.0-weight_spot if 'spot' in enabled_products else 1.0
    for product in enabled_products:
        raw_targets=targets_by_product[product]
        viable=[]
        for target in raw_targets:
            item=target[0] if product=='futures' else target
            side=target[1] if product=='futures' else 'buy'
            snap=snapshots.get((product,item['pair']))
            estimated=max_order
            good,why=_live_quality(snap,cfg,product,estimated) if snap else (False,'no snapshot')
            if good: viable.append((item,side,snap))
            else: log_event(db,f'Auto-live omitted {product} {item["pair"]}: {why}','WARNING','live_auto')
        if product=='spot':
            product_budget=total_budget_usdt*weight_spot
        else:
            product_budget=total_budget_usdt*weight_futures*lev
        per_target=min(max_order,product_budget/max(1,len(viable)))
        for item,side,snap in viable:
            signed_side=1 if side=='buy' else -1
            desired[(product,item['pair'])]=signed_side*per_target/float(snap.last_price)
    # Preserve the bot-owned current quantity when the market is not safe enough to trade it.
    for key,pos in tracked.items():
        if key[0] not in enabled_products or abs(float(pos.signed_quantity or 0))<1e-12: continue
        snap=snapshots.get(key)
        if snap:
            good,_=_live_quality(snap,cfg,key[0],max_order)
        else: good=False
        if not good: desired[key]=float(pos.signed_quantity)
        else: desired.setdefault(key,0.0)
    # Enforce total target gross notional across both books.
    gross=0.0
    for key,q in desired.items():
        snap=snapshots.get(key)
        if snap and snap.last_price: gross+=abs(q*float(snap.last_price))
    if gross>max_gross and gross>0:
        factor=max_gross/gross
        desired={k:q*factor for k,q in desired.items()}
    # Balance-aware sizing: scale spot purchases to available USDT; futures notional is
    # limited to the estimated free wallet times leverage. No new order if fields are absent.
    spot_buy_need=0.0
    for (prod,pair),q in desired.items():
        if prod!='spot': continue
        pos=tracked.get((prod,pair)); current=float(pos.signed_quantity or 0) if pos else 0.0
        delta=q-current; snap=snapshots.get((prod,pair))
        if delta>0 and snap and snap.last_price: spot_buy_need+=delta*float(snap.last_price)
    if 'spot' in enabled_products and spot_buy_need>0 and spot_usdt is not None:
        factor=min(1.0,max(0.0,spot_usdt*0.98)/spot_buy_need)
        if factor<1:
            for key,q in list(desired.items()):
                if key[0]=='spot' and q>0: desired[key]=q*factor
    fut_target_gross=sum(abs(q*snapshots[k].last_price) for k,q in desired.items() if k[0]=='futures' and k in snapshots and snapshots[k].last_price)
    if 'futures' in enabled_products and fut_target_gross>0 and futures_usdt is not None:
        max_from_margin=max(0,futures_usdt)*lev*0.90
        factor=min(1.0,max_from_margin/fut_target_gross)
        if factor<1:
            for key,q in list(desired.items()):
                if key[0]=='futures': desired[key]=q*factor
    # Never send orders above hard limit, and don't trade if quantity precision is unknown.
    current_by_key={k:float(p.signed_quantity or 0) for k,p in tracked.items()}
    client_order_count=0; submitted=[]; failures=[]
    for key,target_q in sorted(desired.items()):
        product,pair=key; snap=snapshots.get(key)
        if not snap or not snap.last_price: continue
        current=current_by_key.get(key,0.0); delta=float(target_q)-current
        if abs(delta*float(snap.last_price))<env_float('LIVE_AUTO_MIN_ORDER_NOTIONAL_USDT',5): continue
        side='buy' if delta>0 else 'sell'; qty=abs(delta)
        detail=pair_details.get(norm_pair(pair),{}) if product=='spot' else {}
        instrument={}
        if product=='futures':
            try:
                instrument=client.futures_instrument(pair,'USDT')
                if isinstance(instrument,list): instrument=instrument[0] if instrument else {}
                if not isinstance(instrument,dict): instrument={}
            except Exception as exc:
                failures.append(f'{pair}: instrument details unavailable: {exc}'); continue
        rounded, qerr=_metadata_quantity(qty,product,pair,detail,instrument,reference_price=float(snap.last_price),order_type='market_order')
        if qerr:
            failures.append(f'{product} {pair}: {qerr}'); log_event(db,failures[-1],'WARNING','live_auto'); continue
        if product=='spot' and side=='sell':
            base,_=_assets(pair,detail); free_base=_free_balance(spot_rows,base)
            if free_base is None or rounded>free_base+1e-10:
                failures.append(f'{pair}: cannot verify enough free {base} for spot sale; skipped.'); continue
        notional=rounded*float(snap.last_price)
        if notional>max_order+1e-6:
            failures.append(f'{pair}: rounded delta {notional:.2f} USDT exceeds per-order cap; re-sizing required.'); continue
        try:
            result=_auto_order(db,client,product,pair,side,rounded,lev,pair_details)
            submitted.append(result); client_order_count+=1
            if not result.get('ok'): failures.append(f'{pair}: order is {result.get("status")}')
        except Exception as exc:
            failures.append(f'{pair}: {exc}')
    runtime=read_config(db,'runtime',{})
    runtime['live_auto_last_result']={'date':today,'at':utcnow().isoformat(),'orders_submitted':client_order_count,'failures':failures[:50],
                                      'targets':len(desired),'budget_inr':budget_inr,'budget_usdt':total_budget_usdt,'current_realized_day_pnl_inr':daily,
                                      'gross_target_before_scaling_usdt':gross,'max_gross_usdt':max_gross}
    runtime['live_auto_block_reason']='; '.join(failures[:5]) if failures else None
    # Mark today's cycle only if all orders were exchange-resolved by later reconciliation.
    # If any submit is ambiguous, the unresolved-order gate will stop the next attempt.
    if not failures and client_order_count==0:
        runtime['live_auto_last_success_date']=today
    elif not failures and all(x.get('status') in ('filled','cancelled','rejected') for x in submitted):
        runtime['live_auto_last_success_date']=today
    write_config(db,'runtime',runtime)
    log_event(db,f'Automated live rebalance planned: {client_order_count} order(s), {len(failures)} warning(s).', 'WARNING' if failures else 'INFO','live_auto',runtime['live_auto_last_result'])
    db.commit()
    return {'status':'submitted' if client_order_count else 'no_orders','result':runtime['live_auto_last_result']}


def latest_account_snapshot(db: Session):
    return db.scalar(select(AccountSnapshot).order_by(desc(AccountSnapshot.recorded_at)).limit(1))


def latest_telemetry(db: Session, limit=100):
    return db.scalars(select(TelemetrySnapshot).order_by(desc(TelemetrySnapshot.recorded_at)).limit(limit)).all()
