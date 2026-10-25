from pathlib import Path
p=Path('/app/app.py')
s=p.read_text()
if 'PORTFOLIO_LAB_FORECAST_V1' not in s:
    s += r'''

# PORTFOLIO_LAB_FORECAST_V1 -- simulated returns, not advice or a promise.
import random as pl_random
from datetime import datetime as pl_datetime, timezone as pl_timezone, timedelta as pl_timedelta

def pl_simulate_history(rows, capital, allocation_pct, extra_cost_bps):
    events=[]; skipped=0
    for p in rows:
        try:
            opened=int(p.opened_ms);closed=int(p.closed_ms);roi=float(p.roi_pct);lev=float(p.leverage or 1)
            if opened<=0 or closed<opened or not __import__('math').isfinite(roi): skipped+=1;continue
            lev=max(1.0,min(200.0,lev))
            item=(p.id,roi,lev,closed)
            events.append((opened,1,item));events.append((closed,0,item))
        except (TypeError,ValueError,OverflowError): skipped+=1
    events.sort(key=lambda e:(e[0],e[1],e[2][0]))
    equity=float(capital);reserved=0.0;margins={};daily_pnl={};peak=equity;maxdd=0.0
    for ts,kind,item in events:
        pid,roi,lev,closed=item
        if kind==1:
            margin=min(equity*allocation_pct/100.0,max(0.0,equity-reserved))
            margins[pid]=margin;reserved+=margin
        else:
            margin=margins.pop(pid,0.0)
            # Extra copier drag is bps of notional; ROI is expressed on position margin.
            net_roi=max(-100.0,min(10000.0,roi-(extra_cost_bps/100.0)*lev))
            pnl=margin*net_roi/100.0;equity+=pnl;reserved=max(0.0,reserved-margin)
            peak=max(peak,equity);maxdd=max(maxdd,peak-equity)
            day=pl_datetime.fromtimestamp(ts/1000,pl_timezone.utc).date().isoformat()
            daily_pnl[day]=daily_pnl.get(day,0.0)+pnl
    daily=[]
    if daily_pnl:
        first=pl_datetime.fromisoformat(min(daily_pnl)).date();last=pl_datetime.fromisoformat(max(daily_pnl)).date()
        day=first;eq=float(capital);prev=eq
        while day<=last:
            pnl=daily_pnl.get(day.isoformat(),0.0);eq+=pnl
            daily.append({'date':day.isoformat(),'pnl_usd':pnl,'equity_usd':eq,'daily_return_pct':(pnl/prev*100) if prev>0 else -100.0})
            prev=max(.01,eq);day+=pl_timedelta(days=1)
    return {'trades_used':len(set(x[2][0] for x in events)),'skipped':skipped,'daily':daily,
        'historical_profit_usd':equity-capital,'historical_return_pct':(equity/capital-1)*100,
        'historical_max_drawdown_usd':maxdd}

@app.get('/api/portfolio-lab/forecast')
def pl_forecast():
    try:
        market=str(pl_request.args.get('market_type','FUTURES')).upper()
        capital=max(1.0,min(float(pl_request.args.get('investment',250)),100000000))
        allocation=max(.5,min(float(pl_request.args.get('allocation_pct',10)),100))
        cost=max(0.0,min(float(pl_request.args.get('extra_cost_bps',5)),500))
        horizon=max(1,min(int(pl_request.args.get('days',7)),30))
    except (TypeError,ValueError): return pl_jsonify({'error':'invalid forecast inputs'}),400
    if market not in ('FUTURES','SPOT'): return pl_jsonify({'error':'invalid market_type'}),400
    cutoff=int((pl_datetime.now(pl_timezone.utc)-pl_timedelta(days=120)).timestamp()*1000)
    with pl_Session() as db:
        traders=list(db.scalars(pl_select(pl_Trader).where(pl_Trader.exchange=='BINANCE',pl_Trader.market_type==market).order_by(pl_Trader.roi.desc()).limit(1000)))
        ids=[t.id for t in traders]; grouped={i:[] for i in ids}
        if ids:
            positions=list(db.scalars(pl_select(pl_Position).where(pl_Position.trader_id.in_(ids),pl_Position.closed_ms.is_not(None),pl_Position.closed_ms>=cutoff).order_by(pl_Position.opened_ms.asc(),pl_Position.closed_ms.asc())))
            for p in positions: grouped.setdefault(p.trader_id,[]).append(p)
        rows=[]
        for t in traders:
            hist=[p for p in grouped.get(t.id,[]) if p.opened_ms is not None and p.closed_ms is not None and p.roi_pct is not None]
            sim=pl_simulate_history(hist,capital,allocation,cost)
            daily=sim['daily']; active=sum(1 for d in daily if abs(d['pnl_usd'])>.000001)
            ready=len(hist)>=15 and active>=10 and len(daily)>=10
            forecasts=[]
            if ready:
                returns=[max(-100,min(1000,float(d['daily_return_pct']))) for d in daily]
                rng=pl_random.Random(7429+int(t.id)*13+int(capital*100)+int(allocation*10)+int(cost*100)+horizon)
                values=[[] for _ in range(horizon)]
                for _ in range(350):
                    eq=capital
                    for day in range(horizon):
                        eq=max(0.0,eq*(1+rng.choice(returns)/100.0))
                        values[day].append(eq-capital)
                for day,nums in enumerate(values,1):
                    nums.sort();forecasts.append({'day':day,'expected_pnl_usd':sum(nums)/len(nums),'median_pnl_usd':nums[len(nums)//2],
                        'p10_pnl_usd':nums[int(.1*(len(nums)-1))],'p90_pnl_usd':nums[int(.9*(len(nums)-1))],
                        'expected_return_pct':(sum(nums)/len(nums))/capital*100})
            tail=forecasts[-1] if forecasts else {}
            rows.append({'id':t.id,'nickname':t.nickname,'portfolio_id':t.portfolio_id,'market_type':t.market_type,
                'profile_url':t.profile_url or ('https://www.binance.com/en/copy-trading/'+('spot' if market=='SPOT' else 'futures')+'/lead-details/'+str(t.portfolio_id)),
                'source_roi':t.roi,'source_pnl':t.pnl,'source_mdd':t.mdd,'source_win_rate':t.win_rate,
                'last_seen':t.last_seen.isoformat() if t.last_seen else None,'forecast_status':'READY' if ready else 'INSUFFICIENT_HISTORY',
                'forecastable_trades':len(hist),'active_close_days':active,'observed_median_leverage':__import__('statistics').median([float(p.leverage) for p in hist if p.leverage is not None]) if any(p.leverage is not None for p in hist) else None,
                'historical_modelled_profit_usd':sim['historical_profit_usd'],'historical_modelled_return_pct':sim['historical_return_pct'],
                'historical_modelled_max_drawdown_usd':sim['historical_max_drawdown_usd'],'expected_horizon_profit_usd':tail.get('expected_pnl_usd'),
                'median_horizon_profit_usd':tail.get('median_pnl_usd'),'p10_horizon_profit_usd':tail.get('p10_pnl_usd'),
                'p90_horizon_profit_usd':tail.get('p90_pnl_usd'),'forecast_days':forecasts,
                'evidence_gap':None if ready else 'Need 15 recent usable trades and at least 10 non-zero close days across at least 10 daily observations.'})
    ready=sorted((x for x in rows if x['forecast_status']=='READY'),key=lambda x:(x['expected_horizon_profit_usd'],-abs(x['p10_horizon_profit_usd'] or 0)),reverse=True)
    unready=sorted((x for x in rows if x['forecast_status']!='READY'),key=lambda x:x['forecastable_trades'],reverse=True)
    for rank,x in enumerate(ready,1): x['forecast_rank']=rank
    return pl_jsonify({'market_type':market,'investment_usd':capital,'allocation_per_position_pct':allocation,
        'extra_copy_cost_bps_of_notional':cost,'horizon_days':horizon,'forecastable_count':len(ready),
        'insufficient_history_count':len(unready),'ranked_by':'Expected modelled net hypothetical PnL over the selected horizon; the 10th–90th percentile is shown as uncertainty, not a confidence guarantee.',
        'forecast_method':'350 bootstrap paths resampling recent daily results from stored closed trades in the last 120 days.',
        'limitations':['Only stored position history is used; missing history or new/open positions are not inferred.',
        'Reported ROI is used as return on allocated margin; leverage scales the extra user-selected cost estimate.',
        'Funding, exact copy fills, actual account fee tier, slippage beyond the chosen drag, cross-margin liquidation and future regime changes are not known.',
        'This model is not actual copy-trader PnL and is not a promise of return.'],
        'ranked':ready,'insufficient_history':unready})
'''
    p.write_text(s)
