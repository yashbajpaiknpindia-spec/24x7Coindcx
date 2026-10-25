from pathlib import Path
p=Path('/app/app.py')
s=p.read_text()
if 'PORTFOLIO_LAB_API_V1' not in s:
    s += '''\n\n# PORTFOLIO_LAB_API_V1\nfrom flask import jsonify as pl_jsonify, request as pl_request\nfrom sqlalchemy import select as pl_select\nfrom models import SessionLocal as pl_Session, Trader as pl_Trader, Position as pl_Position\n\n@app.get('/api/portfolio-lab/portfolios')\ndef pl_portfolios():\n    market=str(pl_request.args.get('market_type','FUTURES')).upper()\n    if market not in ('FUTURES','SPOT'): return pl_jsonify({'error':'invalid market_type'}),400\n    with pl_Session() as db:\n        ts=list(db.scalars(pl_select(pl_Trader).where(pl_Trader.exchange=='BINANCE',pl_Trader.market_type==market).order_by(pl_Trader.roi.desc()).limit(1000)))\n        out=[]\n        for t in ts:\n            count=db.query(pl_Position).filter(pl_Position.trader_id==t.id).count()\n            url=t.profile_url or ('https://www.binance.com/en/copy-trading/'+('spot' if market=='SPOT' else 'futures')+'/lead-details/'+str(t.portfolio_id))\n            out.append({'id':t.id,'nickname':t.nickname,'portfolio_id':t.portfolio_id,'market_type':t.market_type,'profile_url':url,'roi':t.roi,'pnl':t.pnl,'mdd':t.mdd,'win_rate':t.win_rate,'stored_positions':count,'history_status':t.history_status})\n    return pl_jsonify({'market_type':market,'count':len(out),'items':out})\n'''
    p.write_text(s)


s=p.read_text()
if "PORTFOLIO_LAB_DETAIL_V1" not in s:
    s += r'''

# PORTFOLIO_LAB_DETAIL_V1
from models import TraderSnapshot as pl_Snapshot

@app.get('/api/portfolio-lab/portfolio/<int:trader_id>')
def pl_portfolio_detail(trader_id):
    try:
        offset=max(0,int(pl_request.args.get('offset',0)))
        limit=max(10,min(200,int(pl_request.args.get('limit',100))))
    except ValueError:
        return pl_jsonify({'error':'invalid pagination'}),400
    with pl_Session() as db:
        t=db.get(pl_Trader,trader_id)
        if t is None or t.exchange!='BINANCE': return pl_jsonify({'error':'portfolio not found'}),404
        all_rows=list(db.scalars(pl_select(pl_Position).where(pl_Position.trader_id==trader_id).order_by(pl_Position.closed_ms.asc(),pl_Position.id.asc())))
        closed=[p for p in all_rows if p.closed_ms is not None and p.close_pnl is not None]
        curve=[];cum=0.0;peak=0.0;maxdd=0.0
        for p in closed:
            cum+=float(p.close_pnl or 0.0);peak=max(peak,cum);dd=max(0.0,peak-cum);maxdd=max(maxdd,dd)
            curve.append({'closed_ms':p.closed_ms,'position_id':p.id,'symbol':p.symbol,'cumulative_realized_pnl':cum,'drawdown_from_cumulative_peak':dd})
        snaps=list(db.scalars(pl_select(pl_Snapshot).where(pl_Snapshot.trader_id==trader_id).order_by(pl_Snapshot.captured_at.desc()).limit(200)));snaps.reverse()
        mae=sum(1 for p in all_rows if p.mae_pct is not None and p.mfe_pct is not None)
        pnls=[float(p.close_pnl) for p in closed];wins=[x for x in pnls if x>0];losses=[x for x in pnls if x<0]
        lev=[float(p.leverage) for p in all_rows if p.leverage is not None and float(p.leverage)>0]
        profile={'id':t.id,'nickname':t.nickname,'portfolio_id':t.portfolio_id,'market_type':t.market_type,
            'profile_url':t.profile_url or ('https://www.binance.com/en/copy-trading/'+('spot' if t.market_type=='SPOT' else 'futures')+'/lead-details/'+str(t.portfolio_id)),
            'roi':t.roi,'pnl':t.pnl,'mdd':t.mdd,'win_rate':t.win_rate,'last_seen':t.last_seen.isoformat() if t.last_seen else None,
            'last_trade_ms':t.last_trade_ms,'history_status':t.history_status,'history_synced_at':t.history_synced_at.isoformat() if t.history_synced_at else None}
        coverage={'stored_positions':len(all_rows),'closed_pnl_records':len(closed),'with_mae_mfe':mae,
            'with_open_and_close_timestamps':sum(1 for p in all_rows if p.opened_ms is not None and p.closed_ms is not None),
            'missing_open_timestamp':sum(1 for p in all_rows if p.opened_ms is None),
            'missing_close_timestamp':sum(1 for p in all_rows if p.closed_ms is None),
            'path_analyzed':sum(1 for p in all_rows if p.path_status=='ANALYZED')}
        behavior={'closed_trade_win_rate_pct':100*len(wins)/len(pnls) if pnls else None,'net_recorded_closed_pnl':sum(pnls),
            'average_win':sum(wins)/len(wins) if wins else None,'average_loss':sum(losses)/len(losses) if losses else None,
            'profit_factor':sum(wins)/abs(sum(losses)) if losses else ('INF' if wins else None),
            'largest_win':max(wins) if wins else None,'largest_loss':min(losses) if losses else None,
            'median_observed_leverage':__import__('statistics').median(lev) if lev else None,
            'max_observed_leverage':max(lev) if lev else None,
            'average_mae_pct':sum(p.mae_pct for p in all_rows if p.mae_pct is not None)/sum(1 for p in all_rows if p.mae_pct is not None) if any(p.mae_pct is not None for p in all_rows) else None,
            'average_mfe_pct':sum(p.mfe_pct for p in all_rows if p.mfe_pct is not None)/sum(1 for p in all_rows if p.mfe_pct is not None) if any(p.mfe_pct is not None for p in all_rows) else None}
        snapshot_out=[{'captured_at':x.captured_at.isoformat() if x.captured_at else None,'time_range':x.time_range,'roi':x.roi,'pnl':x.pnl,'mdd':x.mdd,'win_rate':x.win_rate,'copier_pnl':x.copier_pnl} for x in snaps]
        page=all_rows[offset:offset+limit]
        trades=[{'id':p.id,'symbol':p.symbol,'side':p.side,'leverage':p.leverage,'margin_mode':p.margin_mode,
            'entry_price':p.entry_price,'exit_price':p.exit_price,'close_pnl':p.close_pnl,'roi_pct':p.roi_pct,
            'opened_ms':p.opened_ms,'closed_ms':p.closed_ms,'mae_pct':p.mae_pct,'mfe_pct':p.mfe_pct,
            'time_to_mae_min':p.time_to_mae_min,'time_to_mfe_min':p.time_to_mfe_min,'coverage_pct':p.coverage_pct,
            'path_status':p.path_status,'close_status':'CLOSED' if p.closed_ms is not None else 'CLOSE_TIME_NOT_REPORTED'} for p in sorted(page,key=lambda x:(x.closed_ms or x.opened_ms or 0,x.id),reverse=True)]
    return pl_jsonify({'profile':profile,'coverage':coverage,'behavior':behavior,
        'curve':{'points':curve,'net_recorded_closed_pnl':cum,'max_drawdown_from_cumulative_realized_peak_usd':maxdd,
            'basis':'Cumulative recorded close_pnl sorted by close time; not account equity or true concurrent-position drawdown.',
            'first_close_ms':curve[0]['closed_ms'] if curve else None,'last_close_ms':curve[-1]['closed_ms'] if curve else None},
        'snapshots':snapshot_out,'trade_offset':offset,'trade_limit':limit,'trade_total':len(all_rows),'trades':trades,
        'open_position_note':'A missing close timestamp does not prove a position is currently open. Public live leader positions are unverified.'})
'''
    p.write_text(s)
