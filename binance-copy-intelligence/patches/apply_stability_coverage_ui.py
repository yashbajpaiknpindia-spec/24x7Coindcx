from pathlib import Path
import re

root = Path("/app")
app_path = root / "app.py"
js_path = root / "static" / "app.js"
html_path = root / "templates" / "index.html"

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Cannot patch {label}: anchor count={count}")
    return text.replace(old, new, 1)

def replace_section(text, start_marker, end_marker, replacement, label):
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"Cannot locate {label} start")
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        raise RuntimeError(f"Cannot locate {label} end")
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]

# ---------------------------------------------------------------------------
# 1) Extend the Multi-Trader evidence set, then rank primarily on stability.
# ---------------------------------------------------------------------------
app = app_path.read_text()
if "STABILITY_COVERAGE_METRICS_V1" not in app:
    app = replace_once(
        app,
        '        tids=[t.id for t in traders]; grouped={i:[] for i in tids}\n        if tids:\n            for p in db.scalars(select(Position).where(Position.trader_id.in_(tids),Position.close_pnl.is_not(None)).order_by(Position.closed_ms.desc().nullslast(),Position.id.desc())):\n                grouped.setdefault(p.trader_id,[]).append(p)\n',
        '''        tids=[t.id for t in traders]; grouped={i:[] for i in tids}; path_grouped={i:[] for i in tids}
        if tids:
            closed_query=select(Position).where(Position.trader_id.in_(tids),Position.close_pnl.is_not(None),Position.closed_ms.is_not(None))
            if market_type=="SPOT":
                closed_query=closed_query.where(Position.source_kind.in_(("PAIRED_SPOT_TRADE","CLOSED_SPOT_TRADE","VERIFIED_SPOT_CLOSED_TRADE")))
            for p in db.scalars(closed_query.order_by(Position.closed_ms.desc().nullslast(),Position.id.desc())):
                grouped.setdefault(p.trader_id,[]).append(p)
            for p in db.scalars(select(Position).where(Position.trader_id.in_(tids)).order_by(Position.closed_ms.desc().nullslast(),Position.id.desc())):
                path_grouped.setdefault(p.trader_id,[]).append(p)
        source_snapshot_wr={}
        if tids:
            try:
                for sid, sw in db.execute(select(pl_Snapshot.trader_id, pl_Snapshot.win_rate).where(pl_Snapshot.trader_id.in_(tids)).order_by(pl_Snapshot.captured_at.desc())):
                    if sid not in source_snapshot_wr and sw is not None:
                        source_snapshot_wr[sid]=sw
            except Exception:
                source_snapshot_wr={}
''',
        "Multi-Trader all-position/source-snapshot collection")
    app = replace_once(
        app,
        '            closed=grouped.get(t.id,[]); stats=trade_statistics(closed); pf=_mt_num(stats.get("profit_factor"))\n',
        '''            closed=grouped.get(t.id,[]); all_positions=path_grouped.get(t.id,[]); stats=trade_statistics(closed); pf=_mt_num(stats.get("profit_factor"))
            source_wr=_mt_num(t.win_rate)
            source_wr_source="PROFILE_FIELD" if source_wr is not None else None
            if source_wr is None:
                source_wr=_mt_num(source_snapshot_wr.get(t.id))
                if source_wr is not None: source_wr_source="LATEST_SAVED_SNAPSHOT"
            path_rows=[p for p in all_positions if p.closed_ms is not None and p.mae_pct is not None and p.mfe_pct is not None and (market_type!="SPOT" or str(p.source_kind or "").upper() in ("PAIRED_SPOT_TRADE","CLOSED_SPOT_TRADE","VERIFIED_SPOT_CLOSED_TRADE"))]
            maes=[abs(float(p.mae_pct)) for p in path_rows if p.mae_pct is not None]
            mfes=[abs(float(p.mfe_pct)) for p in path_rows if p.mfe_pct is not None]
            sorted_mae=sorted(maes)
            median_mae=__import__("statistics").median(sorted_mae) if sorted_mae else None
            p90_mae=sorted_mae[int(round((len(sorted_mae)-1)*0.90))] if sorted_mae else None
            max_mae=max(sorted_mae) if sorted_mae else None
            median_mfe=__import__("statistics").median(mfes) if mfes else None
            mae_before_mfe=[p for p in path_rows if p.time_to_mae_min is not None and p.time_to_mfe_min is not None]
            mae_before_mfe_pct=(100.0*sum(1 for p in mae_before_mfe if float(p.time_to_mae_min)<float(p.time_to_mfe_min))/len(mae_before_mfe)) if mae_before_mfe else None
            path_coverage_pct=(100.0*len(path_rows)/len(all_positions)) if all_positions else None
            source_total=_mt_num(t.total_positions)
            history_coverage_pct=(min(100.0,100.0*len(all_positions)/source_total) if source_total and source_total>0 else None)
            now_ms=int(__import__("time").time()*1000)
            events=[int(p.closed_ms or p.opened_ms) for p in all_positions if p.closed_ms is not None or p.opened_ms is not None]
            trade_count_7d=sum(1 for ts in events if ts>=now_ms-7*86400000)
            trade_count_30d=sum(1 for ts in events if ts>=now_ms-30*86400000)
            trade_count_90d=sum(1 for ts in events if ts>=now_ms-90*86400000)
            trade_count_365d=sum(1 for ts in events if ts>=now_ms-365*86400000)
            mdd_values=[abs(float(v)) for v in (mdd7,mdd30,mdd365) if v is not None]
            mdd_stability=(max(0.0,100.0-2.0*sum(mdd_values)/len(mdd_values)) if mdd_values else None)
            adverse_stability=(max(0.0,100.0-5.0*min(float(p90_mae),20.0)) if p90_mae is not None else None)
            outcome_values=[]
            closed_wr=_mt_num(stats.get("win_rate_pct"))
            outcome_wr=closed_wr if closed_wr is not None else source_wr
            if outcome_wr is not None: outcome_values.append(max(0.0,min(100.0,float(outcome_wr))))
            if pf is not None: outcome_values.append(max(0.0,min(100.0,float(pf)/2.0*100.0)))
            outcome_stability=(sum(outcome_values)/len(outcome_values)) if outcome_values else None
            stability_parts=[]
            if mdd_stability is not None: stability_parts.append((mdd_stability,0.45))
            if adverse_stability is not None: stability_parts.append((adverse_stability,0.35))
            if outcome_stability is not None: stability_parts.append((outcome_stability,0.20))
            stability_score=(sum(v*w for v,w in stability_parts)/sum(w for v,w in stability_parts)) if stability_parts else None
            stability_confidence=40.0*(len(mdd_values)/3.0)+40.0*min(1.0,len(path_rows)/10.0)+15.0*min(1.0,len(closed)/20.0)+(5.0 if source_wr is not None else 0.0)
            if market_type=="SPOT":
                # Verified Spot source supports 30D/90D/180D/365D, not a verified 7D metric.
                # Evaluate Spot on 30D fields rather than excluding every Spot profile.
                reasons=[r for r in reasons if r not in ("MISSING_SOURCE_7D_ROI","MISSING_SOURCE_7D_MDD","RECENT_ROI_BELOW_FLOOR","7D_MDD_LIMIT_EXCEEDED")]
                if roi30 is None:
                    reasons.append("MISSING_SOURCE_30D_ROI")
                elif roi30 < min_roi_7d:
                    reasons.append("RECENT_30D_ROI_BELOW_FLOOR")
            evidence_gaps=[]
            if source_wr is None: evidence_gaps.append("NO_SOURCE_WIN_RATE_CAPTURED")
            if not closed: evidence_gaps.append("NO_CLOSED_PNL_SAMPLE")
            if not path_rows: evidence_gaps.append("NO_ANALYZED_MAE_MFE_PATHS")
            if history_coverage_pct is None: evidence_gaps.append("SOURCE_TOTAL_HISTORY_COUNT_UNKNOWN")
            all_events=[v for p in all_positions for v in (p.opened_ms,p.closed_ms) if v is not None]
            first_trade_ms=min(all_events) if all_events else None
            last_trade_ms=max(all_events) if all_events else None
            audit_fields=(
                sum(1 for p in all_positions if p.opened_ms is not None)
                +sum(1 for p in all_positions if p.closed_ms is not None)
                +sum(1 for p in all_positions if p.entry_price is not None)
                +sum(1 for p in all_positions if p.exit_price is not None)
                +sum(1 for p in all_positions if p.close_pnl is not None)
                +sum(1 for p in all_positions if p.mae_pct is not None and p.mfe_pct is not None)
            )
            audit_coverage_pct=(100.0*audit_fields/(6.0*len(all_positions))) if all_positions else None
''',
        "Multi-Trader behavioural metrics")
    app = replace_once(
        app,
        '            score=50+max(-20,min(20,roi7 or 0))*.7+max(-30,min(30,roi30 or 0))*.35+max(-50,min(50,roi90 or 0))*.1\n',
        '''            score=50+max(-20,min(20,roi7 or 0))*.7+max(-30,min(30,roi30 or 0))*.35+max(-50,min(50,roi90 or 0))*.1
''',
        "preserve return score")
    app = replace_once(
        app,
        '                "profit_factor":pf,"win_rate_pct":stats.get("win_rate_pct"),"net_realized_pnl":stats.get("net_realized_pnl"),\n                "average_win":stats.get("average_win"),"average_loss":stats.get("average_loss"),"stored_path_coverage_pct":stats.get("path_coverage_pct"),\n                "symbols":symbols,"score":round(max(0,min(100,score)),2),"eligible":not reasons,"reasons":reasons,"selected":False,"allocation_pct":0})\n',
        '''                "profit_factor":pf,"win_rate_pct":closed_wr,"source_win_rate_pct":source_wr,"source_win_rate_source":source_wr_source,"net_realized_pnl":stats.get("net_realized_pnl"),
                "average_win":stats.get("average_win"),"average_loss":stats.get("average_loss"),"stored_path_coverage_pct":path_coverage_pct,
                "stored_positions":len(all_positions),"source_total_positions":t.total_positions,"history_coverage_pct":history_coverage_pct,"audit_field_coverage_pct":audit_coverage_pct,
                "path_trades_analyzed":len(path_rows),"path_coverage_pct":path_coverage_pct,"median_mae_pct":median_mae,"p90_mae_pct":p90_mae,"max_mae_pct":max_mae,"median_mfe_pct":median_mfe,
                "trades_mae_gte_2pct_pct":(100.0*sum(1 for v in maes if v>=2.0)/len(maes)) if maes else None,
                "trades_mae_gte_3pct_pct":(100.0*sum(1 for v in maes if v>=3.0)/len(maes)) if maes else None,"mae_before_mfe_pct":mae_before_mfe_pct,"mae_sample_count":len(maes),
                "trade_count_7d":trade_count_7d,"trade_count_30d":trade_count_30d,"trade_count_90d":trade_count_90d,"trade_count_365d":trade_count_365d,
                "first_trade_ms":first_trade_ms,"last_trade_ms":last_trade_ms,"evidence_gaps":evidence_gaps,
                "stability_score":round(max(0,min(100,stability_score)),2) if stability_score is not None else None,
                "confidence_adjusted_stability_score":round(max(0,min(100,stability_score*(0.5+0.5*stability_confidence/100.0))),2) if stability_score is not None else None,
                "stability_confidence_pct":round(max(0,min(100,stability_confidence)),1),
                "stability_confidence_label":"HIGH" if stability_confidence>=75 else ("MEDIUM" if stability_confidence>=50 else "LOW"),
                "stability_components":{"profile_mdd_score":round(mdd_stability,2) if mdd_stability is not None else None,"trade_adverse_score":round(adverse_stability,2) if adverse_stability is not None else None,"outcome_score":round(outcome_stability,2) if outcome_stability is not None else None},
                "symbols":symbols,"score":round(max(0,min(100,score)),2),"eligible":not reasons,"reasons":reasons,"selected":False,"allocation_pct":0})
''',
        "Multi-Trader row evidence")
    app = app.replace(
        '    rows.sort(key=lambda x:(x["eligible"],x["score"],x["stored_closed_trades"]),reverse=True)',
        '    rows.sort(key=lambda x:(x["eligible"],x["confidence_adjusted_stability_score"] is not None,x["confidence_adjusted_stability_score"] if x["confidence_adjusted_stability_score"] is not None else -1,x["stability_score"] if x["stability_score"] is not None else -1,x["score"],x["stored_closed_trades"]),reverse=True)',
        1)
    app = app.replace(
        '            adjusted=x["score"]-overlap*18',
        '            adjusted=(x.get("confidence_adjusted_stability_score") if x.get("confidence_adjusted_stability_score") is not None else x["score"])-overlap*18',
        1)
    app = app.replace(
        '        weights={x["id"]:max(1,x["score"])/max(5,abs(x["mdd_30d"] or max_mdd_pct)) for x in chosen}',
        '        weights={x["id"]:max(1,x.get("confidence_adjusted_stability_score") if x.get("confidence_adjusted_stability_score") is not None else x["score"])/max(5,abs(x["mdd_30d"] if x["mdd_30d"] is not None else max_mdd_pct)) for x in chosen}',
        1)
    app = app.replace(
        'for k in ("id","nickname","portfolio_id","profile_url","score","allocation_pct","mdd_30d","profit_factor","stored_closed_trades","symbols","selection_reason")',
        'for k in ("id","nickname","portfolio_id","profile_url","score","stability_score","confidence_adjusted_stability_score","stability_confidence_pct","stability_confidence_label","allocation_pct","mdd_30d","p90_mae_pct","median_mae_pct","path_coverage_pct","profit_factor","stored_closed_trades","source_win_rate_pct","symbols","selection_reason")',
        1)
    app += "\n# STABILITY_COVERAGE_METRICS_V1\n"
    app_path.write_text(app)

# ---------------------------------------------------------------------------
# 2) Enrich Portfolio Lab APIs with explicit history, audit and path coverage.
# ---------------------------------------------------------------------------
app = app_path.read_text()
if "PORTFOLIO_HISTORY_COVERAGE_V1" not in app:
    start_marker = "@app.get('/api/portfolio-lab/portfolios')"
    end_marker = "@app.get('/api/portfolio-lab/portfolio/<int:trader_id>')"
    start = app.find(start_marker)
    end = app.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise RuntimeError("Cannot locate Portfolio Lab profile-list endpoint")
    new_profiles = '''@app.get('/api/portfolio-lab/portfolios')
def pl_portfolios():
    market=str(pl_request.args.get('market_type','FUTURES')).upper()
    if market not in ('FUTURES','SPOT'): return pl_jsonify({'error':'invalid market_type'}),400
    with pl_Session() as db:
        ts=list(db.scalars(pl_select(pl_Trader).where(pl_Trader.exchange=='BINANCE',pl_Trader.market_type==market).order_by(pl_Trader.roi.desc()).limit(1000)))
        ids=[t.id for t in ts]
        grouped={i:[] for i in ids}
        if ids:
            for p in db.scalars(pl_select(pl_Position).where(pl_Position.trader_id.in_(ids)).order_by(pl_Position.closed_ms.desc().nullslast(),pl_Position.id.desc())):
                grouped.setdefault(p.trader_id,[]).append(p)
        latest_source_wr={}
        if ids:
            for tid, wr, captured in db.execute(pl_select(pl_Snapshot.trader_id,pl_Snapshot.win_rate,pl_Snapshot.captured_at).where(pl_Snapshot.trader_id.in_(ids)).order_by(pl_Snapshot.captured_at.desc())):
                if tid not in latest_source_wr and wr is not None:
                    latest_source_wr[tid]=(wr,captured)
        now_ms=int(__import__('time').time()*1000)
        out=[]
        for t in ts:
            rows=grouped.get(t.id,[])
            pnl_rows=[p for p in rows if p.close_pnl is not None and p.closed_ms is not None and p.path_status!='UNPAIRED_SPOT_ACTIVITY' and (t.market_type!='SPOT' or str(p.source_kind or '').upper() in ('PAIRED_SPOT_TRADE','CLOSED_SPOT_TRADE','VERIFIED_SPOT_CLOSED_TRADE'))]
            path_rows=[p for p in rows if p.mae_pct is not None and p.mfe_pct is not None]
            maes=[abs(float(p.mae_pct)) for p in path_rows]
            sorted_mae=sorted(maes)
            median_mae=__import__('statistics').median(sorted_mae) if sorted_mae else None
            p90_mae=sorted_mae[int(round((len(sorted_mae)-1)*0.90))] if sorted_mae else None
            source_total=float(t.total_positions or 0)
            history_coverage=min(100.0,100.0*len(rows)/source_total) if source_total>0 else None
            fields=(sum(1 for p in rows if p.opened_ms is not None)+sum(1 for p in rows if p.closed_ms is not None)+sum(1 for p in rows if p.entry_price is not None)+sum(1 for p in rows if p.exit_price is not None)+sum(1 for p in rows if p.close_pnl is not None)+sum(1 for p in rows if p.mae_pct is not None and p.mfe_pct is not None))
            audit_coverage=100.0*fields/(6.0*len(rows)) if rows else None
            events=[int(p.closed_ms or p.opened_ms) for p in rows if p.closed_ms is not None or p.opened_ms is not None]
            all_events=[v for p in rows for v in (p.opened_ms,p.closed_ms) if v is not None]
            source_wr=t.win_rate
            source_wr_source='PROFILE_FIELD' if source_wr is not None else None
            if source_wr is None and t.id in latest_source_wr:
                source_wr=latest_source_wr[t.id][0]
                source_wr_source='LATEST_SAVED_SNAPSHOT'
            profile_metric_values=[t.roi,t.pnl,t.mdd,t.sharpe,source_wr,t.aum,t.copier_pnl,t.win_positions,t.total_positions,t.last_trade_ms]
            profile_metrics_present=sum(1 for value in profile_metric_values if value is not None)
            profile_metric_coverage_pct=100.0*profile_metrics_present/len(profile_metric_values)
            recent=lambda days:sum(1 for x in events if x>=now_ms-days*86400000)
            url=t.profile_url or ('https://www.binance.com/en-IN/copy-trading/lead-details/'+str(t.portfolio_id)+'?timeRange=90D' if t.portfolio_id else None)
            out.append({'id':t.id,'nickname':t.nickname,'portfolio_id':t.portfolio_id,'market_type':t.market_type,'profile_url':url,
                'roi':t.roi,'pnl':t.pnl,'mdd':t.mdd,'win_rate':source_wr,'source_win_rate_pct':source_wr,'source_win_rate_source':source_wr_source,
                'profile_metric_coverage_pct':profile_metric_coverage_pct,'profile_metrics_present':profile_metrics_present,'profile_metrics_expected':len(profile_metric_values),
                'closed_trade_win_rate_pct':100.0*sum(1 for p in pnl_rows if float(p.close_pnl)>0)/len(pnl_rows) if pnl_rows else None,
                'stored_positions':len(rows),'source_total_positions':t.total_positions,'closed_pnl_records':len(pnl_rows),
                'with_mae_mfe':len(path_rows),'path_coverage_pct':100.0*len(path_rows)/len(rows) if rows else None,
                'history_coverage_pct':history_coverage,'audit_field_coverage_pct':audit_coverage,
                'median_mae_pct':median_mae,'p90_mae_pct':p90_mae,
                'trades_mae_gte_2pct_pct':100.0*sum(1 for v in maes if v>=2.0)/len(maes) if maes else None,
                'trades_mae_gte_3pct_pct':100.0*sum(1 for v in maes if v>=3.0)/len(maes) if maes else None,
                'trade_count_7d':recent(7),'trade_count_30d':recent(30),'trade_count_90d':recent(90),'trade_count_365d':recent(365),
                'first_trade_ms':min(all_events) if all_events else None,'last_trade_ms':max(all_events) if all_events else None,
                'history_status':t.history_status,'source_win_rate_status':('AVAILABLE_FROM_'+source_wr_source if source_wr_source else 'NO_SOURCE_WIN_RATE_CAPTURED'),
                'closed_win_rate_status':('NO_VERIFIED_SPOT_TRADE_PAIRING' if t.market_type=='SPOT' and not pnl_rows else ('COMPUTED_FROM_VERIFIED_CLOSED_TRADES' if pnl_rows else 'NO_CLOSED_PNL_RECORDS'))})
    return pl_jsonify({'market_type':market,'count':len(out),'items':out})

'''
    app = app[:start] + new_profiles + app[end:]
    app = replace_once(
        app,
        '        all_rows=list(db.scalars(pl_select(pl_Position).where(pl_Position.trader_id==trader_id).order_by(pl_Position.closed_ms.asc(),pl_Position.id.asc())))\n',
        '''        source_win_rate=t.win_rate
        source_win_rate_source='PROFILE_FIELD' if source_win_rate is not None else None
        if source_win_rate is None:
            for _snap in db.scalars(pl_select(pl_Snapshot).where(pl_Snapshot.trader_id==trader_id).order_by(pl_Snapshot.captured_at.desc()).limit(100)):
                if _snap.win_rate is not None:
                    source_win_rate=_snap.win_rate
                    source_win_rate_source='LATEST_SAVED_SNAPSHOT'
                    break
        if source_win_rate is None:
            source_win_rate_source='NO_SOURCE_WIN_RATE_CAPTURED'
        profile_metric_values=[t.roi,t.pnl,t.mdd,t.sharpe,source_win_rate,t.aum,t.copier_pnl,t.win_positions,t.total_positions,t.last_trade_ms]
        profile_metrics_present=sum(1 for value in profile_metric_values if value is not None)
        profile_metric_coverage_pct=100.0*profile_metrics_present/len(profile_metric_values)
        all_rows=list(db.scalars(pl_select(pl_Position).where(pl_Position.trader_id==trader_id).order_by(pl_Position.closed_ms.asc().nullsfirst(),pl_Position.id.asc())))
''',
        "selected portfolio source win rate fallback")
    app = replace_once(
        app,
        "        closed=[p for p in all_rows if p.closed_ms is not None and p.close_pnl is not None]\n",
        "        closed=[p for p in all_rows if p.closed_ms is not None and p.close_pnl is not None and p.path_status!='UNPAIRED_SPOT_ACTIVITY' and (t.market_type!='SPOT' or str(p.source_kind or '').upper() in ('PAIRED_SPOT_TRADE','CLOSED_SPOT_TRADE','VERIFIED_SPOT_CLOSED_TRADE'))]\n        pnl_rows=closed\n",
        "selected portfolio closed-PnL set")
    app = replace_once(
        app,
        "'roi':t.roi,'pnl':t.pnl,'mdd':t.mdd,'win_rate':t.win_rate,'last_seen':t.last_seen.isoformat() if t.last_seen else None,",
        "'roi':t.roi,'pnl':t.pnl,'mdd':t.mdd,'win_rate':source_win_rate,'source_win_rate_pct':source_win_rate,'source_win_rate_source':source_win_rate_source,'source_total_positions':t.total_positions,'last_seen':t.last_seen.isoformat() if t.last_seen else None,",
        "profile detail win rate/source count")
    cov_start = app.find("        coverage={'stored_positions':len(all_rows),'closed_pnl_records':len(closed),'with_mae_mfe':mae,")
    cov_end = app.find("        snapshot_out=[", cov_start)
    if cov_start < 0 or cov_end < 0:
        raise RuntimeError("Cannot locate Portfolio Lab coverage/behaviour block")
    metrics_block = '''        event_ms=[int(p.closed_ms or p.opened_ms) for p in all_rows if p.closed_ms is not None or p.opened_ms is not None]
        all_event_ms=[v for p in all_rows for v in (p.opened_ms,p.closed_ms) if v is not None]
        now_ms=int(__import__('time').time()*1000)
        trade_counts={days:sum(1 for ts in event_ms if ts>=now_ms-days*86400000) for days in (7,30,90,365)}
        source_total=float(t.total_positions or 0)
        trade_history_coverage_pct=min(100.0,100.0*len(all_rows)/source_total) if source_total>0 else None
        audit_fields=(sum(1 for p in all_rows if p.opened_ms is not None)+sum(1 for p in all_rows if p.closed_ms is not None)+sum(1 for p in all_rows if p.entry_price is not None)+sum(1 for p in all_rows if p.exit_price is not None)+sum(1 for p in all_rows if p.close_pnl is not None)+sum(1 for p in all_rows if p.mae_pct is not None and p.mfe_pct is not None))
        audit_field_coverage_pct=100.0*audit_fields/(6.0*len(all_rows)) if all_rows else None
        path_coverage_pct=100.0*mae/len(all_rows) if all_rows else None
        mae_values=[abs(float(p.mae_pct)) for p in all_rows if p.mae_pct is not None]
        mfe_values=[abs(float(p.mfe_pct)) for p in all_rows if p.mfe_pct is not None]
        mae_sorted=sorted(mae_values)
        mfe_sorted=sorted(mfe_values)
        median_mae=__import__('statistics').median(mae_sorted) if mae_sorted else None
        p90_mae=mae_sorted[int(round((len(mae_sorted)-1)*0.90))] if mae_sorted else None
        max_mae=max(mae_sorted) if mae_sorted else None
        median_mfe=__import__('statistics').median(mfe_sorted) if mfe_sorted else None
        timed_paths=[p for p in all_rows if p.mae_pct is not None and p.mfe_pct is not None and p.time_to_mae_min is not None and p.time_to_mfe_min is not None]
        mae_before_mfe_pct=100.0*sum(1 for p in timed_paths if float(p.time_to_mae_min)<float(p.time_to_mfe_min))/len(timed_paths) if timed_paths else None
        coverage={'stored_positions':len(all_rows),'source_total_positions':t.total_positions,'profile_metric_coverage_pct':profile_metric_coverage_pct,'profile_metrics_present':profile_metrics_present,'profile_metrics_expected':len(profile_metric_values),'closed_pnl_records':len(pnl_rows),'with_mae_mfe':mae,
            'path_coverage_pct':path_coverage_pct,'trade_history_coverage_pct':trade_history_coverage_pct,'audit_field_coverage_pct':audit_field_coverage_pct,
            'with_open_and_close_timestamps':sum(1 for p in all_rows if p.opened_ms is not None and p.closed_ms is not None),
            'with_entry_price':sum(1 for p in all_rows if p.entry_price is not None),'with_exit_price':sum(1 for p in all_rows if p.exit_price is not None),
            'with_closed_pnl':len(pnl_rows),'missing_open_timestamp':sum(1 for p in all_rows if p.opened_ms is None),
            'missing_close_timestamp':sum(1 for p in all_rows if p.closed_ms is None),
            'path_analyzed':sum(1 for p in all_rows if p.path_status=='ANALYZED'),
            'trade_count_7d':trade_counts[7],'trade_count_30d':trade_counts[30],'trade_count_90d':trade_counts[90],'trade_count_365d':trade_counts[365],
            'first_trade_ms':min(all_event_ms) if all_event_ms else None,'last_trade_ms':max(all_event_ms) if all_event_ms else None}
        pnls=[float(p.close_pnl) for p in pnl_rows];wins=[x for x in pnls if x>0];losses=[x for x in pnls if x<0]
        lev=[float(p.leverage) for p in all_rows if p.leverage is not None and float(p.leverage)>0]
        behavior={'market_type':t.market_type,'source_platform_win_rate_pct':source_win_rate,'source_win_rate_source':source_win_rate_source,'profile_metric_coverage_pct':profile_metric_coverage_pct,
            'source_roi':t.roi,'source_mdd':t.mdd,'closed_pnl_records':len(pnl_rows),
            'closed_trade_win_rate_pct':100.0*len(wins)/len(pnls) if pnls else None,'closed_win_rate_status':('NO_VERIFIED_SPOT_TRADE_PAIRING' if t.market_type=='SPOT' and not pnl_rows else ('COMPUTED_FROM_VERIFIED_CLOSED_TRADES' if pnl_rows else 'NO_CLOSED_PNL_RECORDS')),'net_recorded_closed_pnl':sum(pnls),
            'average_win':sum(wins)/len(wins) if wins else None,'average_loss':sum(losses)/len(losses) if losses else None,
            'profit_factor':sum(wins)/abs(sum(losses)) if losses else ('INF' if wins else None),
            'largest_win':max(wins) if wins else None,'largest_loss':min(losses) if losses else None,
            'median_observed_leverage':__import__('statistics').median(lev) if lev else None,'max_observed_leverage':max(lev) if lev else None,
            'leverage_coverage_pct':100.0 if t.market_type=='SPOT' else (100.0*sum(1 for p in all_rows if p.leverage is not None and float(p.leverage)>0)/len(all_rows) if all_rows else 0.0),
            'average_mae_pct':sum(mae_values)/len(mae_values) if mae_values else None,'median_mae_pct':median_mae,'p90_mae_pct':p90_mae,'max_mae_pct':max_mae,
            'mae_sample_count':len(mae_values),'median_mfe_pct':median_mfe,'average_mfe_pct':sum(mfe_values)/len(mfe_values) if mfe_values else None,
            'trades_mae_gte_2pct_pct':100.0*sum(1 for v in mae_values if v>=2.0)/len(mae_values) if mae_values else None,
            'trades_mae_gte_3pct_pct':100.0*sum(1 for v in mae_values if v>=3.0)/len(mae_values) if mae_values else None,
            'mae_before_mfe_pct':mae_before_mfe_pct,'trade_count_7d':trade_counts[7],'trade_count_30d':trade_counts[30],
            'trade_count_90d':trade_counts[90],'trade_count_365d':trade_counts[365],
            'first_trade_ms':min(all_event_ms) if all_event_ms else None,'last_trade_ms':max(all_event_ms) if all_event_ms else None}
'''
    app = app[:cov_start] + metrics_block + app[cov_end:]
    app += "\n# PORTFOLIO_HISTORY_COVERAGE_V1\n"
    app_path.write_text(app)

# ---------------------------------------------------------------------------
# 3) Compact, paginated UI; separate source win rate from calculated win rate.
# ---------------------------------------------------------------------------
html = html_path.read_text()

# Replace the oversized readability override with compact laptop-friendly defaults.
css = '''<style id="BINANCE_INTEL_DESKTOP_READABILITY_V1">
html{font-size:14px!important}
body{font-size:14px!important;line-height:1.35}
p,.help-text,.run-sub,.notice-box,.metric-explain,label{font-size:13px!important;line-height:1.4}
h1{font-size:28px!important;line-height:1.2}h2{font-size:24px!important;line-height:1.2}
h3{font-size:18px!important;line-height:1.25}
button,.btn,input,select,textarea{font-size:13px!important;min-height:34px}
table{width:100%;max-width:100%;min-width:0!important;table-layout:fixed;border-collapse:collapse}
table th,table td{font-size:12px!important;padding:7px 8px!important;line-height:1.3;white-space:normal!important;overflow-wrap:anywhere;word-break:normal;vertical-align:top}
small,.eyebrow,.tag,.kpi-foot{font-size:11px!important}
.kpi-value{font-size:26px!important;line-height:1.1}
.nav-link{font-size:14px!important;min-height:36px}
.panel{padding:16px}
.table-scroll{width:100%;max-width:100%;overflow-x:hidden!important}
.table-scroll table{width:100%;max-width:100%;min-width:0!important;table-layout:fixed}
.table-scroll th,.table-scroll td{white-space:normal!important;overflow-wrap:anywhere;word-break:normal}
#pl-profile-rows td,#mt-rows td,#pl-rank-rows td,#pl-trade-rows td{font-size:11.5px!important;padding:7px 6px!important}
#pl-profile-rows small,#mt-rows small,#pl-rank-rows small,#pl-trade-rows small{display:block;color:#8c98a8;font-size:10.5px!important;line-height:1.25;margin-top:3px}
.table-pager{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:10px;flex-wrap:wrap}
.table-pager span{font-size:12px;color:#9fb0c2}
.table-pager button{padding:5px 10px;min-height:30px}
.coverage-summary{margin:10px 0 14px;padding:12px 14px;border:1px solid #314655;border-radius:10px;background:#0b1420;color:#d8e5f2;font-size:12px;line-height:1.45}
.coverage-track{height:6px;max-width:420px;margin-top:7px;background:#233242;border-radius:99px;overflow:hidden}
.coverage-fill{height:100%;background:#62e4b3;border-radius:99px}
.profile-coverage{display:block;white-space:normal;margin-top:5px;font-size:10.5px;color:#9fb0c2}
.status-chip{white-space:normal}
@media(min-width:1100px){body{font-size:14px!important}.help-text,p,.run-sub,.notice-box{font-size:13px!important}table th,table td{font-size:12px!important}.kpi-value{font-size:27px!important}}
@media(max-width:900px){.panel{padding:12px}.table-scroll table th,.table-scroll table td{font-size:11px!important;padding:6px 5px!important}.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.section-heading{gap:10px;align-items:flex-start}.section-heading h2{font-size:22px!important}.panel-header{gap:8px;flex-wrap:wrap}.field-row{grid-template-columns:1fr;gap:8px}.table-scroll table th,.table-scroll table td{font-size:10.5px!important;padding:5px 4px!important}.table-pager{justify-content:space-between}}
</style>'''
style_pattern = re.compile(r'<style id="BINANCE_INTEL_DESKTOP_READABILITY_V1">.*?</style>', re.S)
if style_pattern.search(html):
    html = style_pattern.sub(css, html, count=1)
else:
    if "</head>" not in html:
        raise RuntimeError("Cannot install compact layout: missing head close tag")
    html = html.replace("</head>", css + "\n</head>", 1)

# Compact Multi-Trader ranking table: risk/behaviour first, detail available by Inspect.
mt_match = re.search(r'<div class="table-scroll"><table><thead><tr>.*?</tr></thead><tbody id="mt-rows"', html, re.S)
if not mt_match:
    raise RuntimeError("Cannot locate Multi-Trader ranking table markup")
mt_table = '<div class="table-scroll mt-ranking-scroll"><table class="compact-table"><thead><tr><th>Portfolio / recent ROI</th><th>Stability / confidence</th><th>MDD 7D / 30D / 365D</th><th>Typical / P90 adverse move</th><th>Source WR / closed WR</th><th>Records 7D / 30D / 90D</th><th>Path coverage</th><th>Decision / evidence gaps</th><th>Inspect</th></tr></thead><tbody id="mt-rows"'
html = html[:mt_match.start()] + mt_table + html[mt_match.end():]
html = html.replace('id="mt-rows"><tr><td colspan="14" class="empty-state">No evaluation yet.</td></tr></tbody></table></div></article>',
                    'id="mt-rows"><tr><td colspan="9" class="empty-state">No evaluation yet.</td></tr></tbody></table></div><div class="table-pager"><button id="mt-prev-page" class="btn secondary" disabled>← Previous</button><span id="mt-page-meta">No rows</span><button id="mt-next-page" class="btn secondary" disabled>Next →</button></div></article>',1)

# Forecast ranking is now seven compact columns; source and observed closed win-rates remain distinct.
pl_rank_match = re.search(r'<table><thead><tr>.*?</tr></thead><tbody id="pl-rank-rows"', html, re.S)
if not pl_rank_match:
    raise RuntimeError("Cannot locate Portfolio Lab forecast table")
rank_table = '<table class="compact-table"><thead><tr><th>Portfolio / rank / win rates</th><th>Expected / median PnL</th><th>10th–90th percentile</th><th>Observed leverage / coverage</th><th>Historical modelled PnL</th><th>Historical max drawdown</th><th>Trades / inspect</th></tr></thead><tbody id="pl-rank-rows"'
html = html[:pl_rank_match.start()] + rank_table + html[pl_rank_match.end():]
html = html.replace('<td colspan="10" class="empty-state">Run a forecast', '<td colspan="7" class="empty-state">Run a forecast', 1)

# Replace the nine-column saved-profile index with a compact coverage-first view.
profile_match = re.search(r'<table><thead><tr><th>Portfolio</th>.*?</tr></thead><tbody id="pl-profile-rows"', html, re.S)
if not profile_match:
    raise RuntimeError("Cannot locate saved portfolio table")
profile_table = '<table class="compact-table"><thead><tr><th>Portfolio / source</th><th>Source WR / closed WR</th><th>Stored / reported total · records by period</th><th>Trade-path coverage / typical adverse move</th><th>History period / status</th><th>Inspect</th></tr></thead><tbody id="pl-profile-rows"'
html = html[:profile_match.start()] + profile_table + html[profile_match.end():]
html = html.replace('id="pl-profile-rows"><tr><td colspan="9" class="empty-state">Loading profiles…</td></tr></tbody></table></div></article>',
                    'id="pl-profile-rows"><tr><td colspan="6" class="empty-state">Loading profiles…</td></tr></tbody></table></div><div class="table-pager"><button id="pl-profile-prev" class="btn secondary" disabled>← Previous</button><span id="pl-profile-page-meta">No rows</span><button id="pl-profile-next" class="btn secondary" disabled>Next →</button></div></article>', 1)
html = html.replace('id="pl-coverage-summary"', 'id="pl-coverage-summary"', 1)
old_detail = '<div id="pl-official-link" class="run-sub">Official portfolio link will appear here.</div>\n        <div class="kpi-grid">'
new_detail = '<div id="pl-official-link" class="run-sub">Official portfolio link will appear here.</div>\n        <div id="pl-coverage-summary" class="coverage-summary">Portfolio coverage will be calculated from source-reported totals, stored records, audit fields and analysed trade paths.</div>\n        <div class="kpi-grid">'
if 'id="pl-coverage-summary"' not in html:
    html = replace_once(html, old_detail, new_detail, "selected profile coverage banner")

# The full trade table has nine columns, combining time/price/status facts to avoid horizontal scrolling.
trade_match = re.search(r'<table><thead><tr>.*?</tr></thead><tbody id="pl-trade-rows"', html, re.S)
if not trade_match:
    raise RuntimeError("Cannot locate Portfolio Lab trade-history table")
trade_table = '<table class="compact-table"><thead><tr><th>Entry → close time / status</th><th>Symbol / side</th><th>Entry → exit price</th><th>Leverage / margin</th><th>Closed PnL / ROI</th><th>Adverse / favourable move</th><th>Time to MAE / MFE</th><th>Path coverage / status</th><th>Scenario PnL</th></tr></thead><tbody id="pl-trade-rows"'
html = html[:trade_match.start()] + trade_table + html[trade_match.end():]
html = html.replace('id="pl-trade-rows"><tr><td colspan="14" class="empty-state">Select a portfolio to load trades.</td></tr></tbody>',
                    'id="pl-trade-rows"><tr><td colspan="9" class="empty-state">Select a portfolio to load trades.</td></tr></tbody>',1)
html_path.write_text(html)

js = js_path.read_text()

# Portfolio list: show coverage and counts without forcing a wide grid.
js = replace_section(
    js,
    "function plRenderPortfolios(){",
    "\nfunction plRankRow",
    '''function plRenderPortfolios(){const allRows=pl.portfolios;const pages=Math.max(1,Math.ceil(allRows.length/plProfilePageSize));plProfilePage=Math.min(plProfilePage,pages-1);const rows=allRows.slice(plProfilePage*plProfilePageSize,(plProfilePage+1)*plProfilePageSize);$('#pl-profile-meta').textContent=allRows.length+' stored · '+pl.market;$('#pl-profile-rows').innerHTML=allRows.length?rows.map(t=>{const hc=t.history_coverage_pct===null||t.history_coverage_pct===undefined?'Unknown':plPct(t.history_coverage_pct);const pc=t.path_coverage_pct===null||t.path_coverage_pct===undefined?'Unknown':plPct(t.path_coverage_pct);const dates=(t.first_trade_ms?plTime(t.first_trade_ms):'—')+' → '+(t.last_trade_ms?plTime(t.last_trade_ms):'—');const wr=(t.source_win_rate_pct===null||t.source_win_rate_pct===undefined?'Source WR not captured':('Source WR '+plPct(t.source_win_rate_pct)))+' · '+(t.closed_trade_win_rate_pct===null||t.closed_trade_win_rate_pct===undefined?'Closed WR unavailable':('Closed WR '+plPct(t.closed_trade_win_rate_pct)));const total=t.source_total_positions===null||t.source_total_positions===undefined||Number(t.source_total_positions)<=0?'source total unknown':('reported total '+Number(t.source_total_positions));return '<tr><td><b>'+esc(t.nickname||'Unknown')+'</b><small>'+esc(t.market_type)+' · '+esc(t.portfolio_id||'')+'</small>'+plLink(t.profile_url)+'<span class="profile-coverage">Profile metrics: '+plPct(t.profile_metric_coverage_pct)+'<br>Source-total history coverage: '+hc+'<br>Audit-field coverage: '+(t.audit_field_coverage_pct===null||t.audit_field_coverage_pct===undefined?'Unknown':plPct(t.audit_field_coverage_pct))+'</span></td><td>'+esc(wr)+'<small>Source value: '+esc(t.source_win_rate_source||'Not captured')+'</small><small>Closed-PnL sample: '+Number(t.closed_pnl_records||0)+'</small><small>Closed-WR status: '+esc(t.closed_win_rate_status||'NO_CLOSED_PNL_RECORDS')+'</small></td><td>'+Number(t.stored_positions||0)+' stored · '+esc(total)+'<small>Records in 7D / 30D / 90D: '+Number(t.trade_count_7d||0)+' / '+Number(t.trade_count_30d||0)+' / '+Number(t.trade_count_90d||0)+'</small></td><td>'+Number(t.with_mae_mfe||0)+' / '+Number(t.stored_positions||0)+' paths<small>Path coverage: '+pc+' · median adverse: '+plPct(t.median_mae_pct)+' · P90: '+plPct(t.p90_mae_pct)+'</small></td><td>'+esc(dates)+'<small>'+esc(t.history_status||'unknown')+'</small></td><td><button class="icon-button" data-pl-id="'+Number(t.id)+'">Inspect</button></td></tr>'}).join(''):'<tr><td colspan="6" class="empty-state">'+(pl.market==='SPOT'?'No Spot profiles are stored. Source discovery must succeed before a portfolio can be shown.':'No stored portfolios found.')+'</td></tr>';$('#pl-profile-prev').disabled=plProfilePage<=0;$('#pl-profile-next').disabled=plProfilePage>=pages-1;$('#pl-profile-page-meta').textContent=allRows.length?((plProfilePage*plProfilePageSize+1)+'–'+Math.min((plProfilePage+1)*plProfilePageSize,allRows.length)+' of '+allRows.length):'No rows';$$('[data-pl-id]').forEach(b=>b.addEventListener('click',()=>plLoadPortfolio(Number(b.dataset.plId),0)))}''',
    "compact Portfolio Lab profile renderer")
js = js.replace("let pl={market:'FUTURES',portfolios:[],ranked:[],unready:[],selected:null,offset:0,limit:100,forecast:[]};",
                "let pl={market:'FUTURES',portfolios:[],ranked:[],unready:[],selected:null,offset:0,limit:25,forecast:[]};let plProfilePage=0;const plProfilePageSize=25;",1)

# Forecast rank renderer: seven columns including both win-rate sources and the observed leverage coverage.
js = replace_section(
    js,
    "function plRankRow(t,ranked){",
    "\nasync function plRunForecast",
    '''function plRankRow(t,ranked){return '<tr><td><b>'+(ranked?'#'+esc(t.forecast_rank||'—')+' ':'')+esc(t.nickname||'Unknown')+'</b><small>'+esc((t.market_type||pl.market).toUpperCase())+' · '+esc(t.portfolio_id||'')+'</small>'+plLink(t.profile_url)+'<small>Source WR: '+plPct(t.source_win_rate)+' · closed WR: '+plPct(t.closed_trade_win_rate_pct)+'</small></td><td><b>'+plUsd(t.expected_horizon_profit_usd)+'</b><small>Median: '+plUsd(t.median_horizon_profit_usd)+'</small></td><td>'+plUsd(t.p10_horizon_profit_usd)+'<small>to '+plUsd(t.p90_horizon_profit_usd)+'</small></td><td>'+(t.observed_median_leverage===null||t.observed_median_leverage===undefined?'Not reported':Number(t.observed_median_leverage).toFixed(2)+'×')+'<small>Max: '+(t.observed_max_leverage===null||t.observed_max_leverage===undefined?'—':Number(t.observed_max_leverage).toFixed(2)+'×')+' · coverage '+plPct(t.leverage_coverage_pct)+'</small></td><td>'+plUsd(t.historical_modelled_profit_usd)+'</td><td>'+plUsd(t.historical_modelled_max_drawdown_usd)+'</td><td>'+Number(t.forecastable_trades||0)+' records <small><button class="icon-button" data-pl-id="'+Number(t.id)+'">Inspect</button></small></td></tr>'}''',
    "compact Portfolio Lab forecast row")
js = replace_section(
    js,
    "function plRenderBehavior(b){",
    "\nasync function plLoadPortfolio",
    """function plRenderBehavior(b){const rows=[['Market',b.market_type||pl.market],['Source-reported win rate',plPct(b.source_platform_win_rate_pct)],['Source-rate origin',b.source_win_rate_source||'Not captured'],['Closed-PnL win rate',plPct(b.closed_trade_win_rate_pct)],['Closed-WR status',b.closed_win_rate_status||'NO_CLOSED_PNL_RECORDS'],['Closed-PnL sample',b.closed_pnl_records],['Profit factor',b.profit_factor==='INF'?'∞':(b.profit_factor===null?'—':Number(b.profit_factor).toFixed(2))],['Average win',plUsd(b.average_win)],['Average loss',plUsd(b.average_loss)],['Largest loss',plUsd(b.largest_loss)],['Median leverage',b.median_observed_leverage===null?'—':Number(b.median_observed_leverage).toFixed(2)+'×'],['Maximum leverage',b.max_observed_leverage===null?'—':Number(b.max_observed_leverage).toFixed(2)+'×'],['Leverage data coverage',plPct(b.leverage_coverage_pct)],['Median adverse move (MAE)',plPct(b.median_mae_pct)],['90th-percentile adverse move',plPct(b.p90_mae_pct)],['Worst observed adverse move',plPct(b.max_mae_pct)],['Median favourable move (MFE)',plPct(b.median_mfe_pct)],['Trades with ≥2% adverse move',plPct(b.trades_mae_gte_2pct_pct)],['Trades with ≥3% adverse move',plPct(b.trades_mae_gte_3pct_pct)],['MAE occurred before MFE',plPct(b.mae_before_mfe_pct)],['MAE/MFE sample count',b.mae_sample_count],['Records in 7D / 30D / 90D',Number(b.trade_count_7d||0)+' / '+Number(b.trade_count_30d||0)+' / '+Number(b.trade_count_90d||0)],['History period',plTime(b.first_trade_ms)+' → '+plTime(b.last_trade_ms)]];$('#pl-behaviour').innerHTML=rows.map(p=>'<div><b>'+esc(p[0])+'</b><p>'+esc(String(p[1]===null||p[1]===undefined?'—':p[1]))+'</p></div>').join('')}""",
    "expanded Portfolio Lab behaviour statistics")
js = replace_once(
    js,
    "$('#pl-official-link').innerHTML=plLink(t.profile_url)+' · last stored refresh '+esc(t.last_seen||'unknown');$('#pl-kpi-trades').textContent=c.stored_positions;$('#pl-kpi-paths').textContent=c.with_mae_mfe+' / '+c.stored_positions;",
    "$('#pl-official-link').innerHTML=plLink(t.profile_url)+' · last stored refresh '+esc(t.last_seen||'unknown');const mc=c.profile_metric_coverage_pct===null||c.profile_metric_coverage_pct===undefined?'Unknown':plPct(c.profile_metric_coverage_pct);const hc=c.trade_history_coverage_pct===null||c.trade_history_coverage_pct===undefined?'Unknown (source total not reported)':plPct(c.trade_history_coverage_pct);const ac=c.audit_field_coverage_pct===null||c.audit_field_coverage_pct===undefined?'Unknown':plPct(c.audit_field_coverage_pct);const pc=c.path_coverage_pct===null||c.path_coverage_pct===undefined?'Unknown':plPct(c.path_coverage_pct);$('#pl-coverage-summary').textContent='Evidence coverage — portfolio metrics: '+mc+' ('+Number(c.profile_metrics_present||0)+' of '+Number(c.profile_metrics_expected||10)+' fields present); source-total history coverage: '+hc+'; trade-field completeness: '+ac+'; analysed MAE/MFE paths: '+pc+' ('+Number(c.with_mae_mfe||0)+' of '+Number(c.stored_positions||0)+'); closed-PnL samples: '+Number(c.closed_pnl_records||0)+'; source-reported total: '+(c.source_total_positions===null||c.source_total_positions===undefined?'unknown':Number(c.source_total_positions))+'. Coverage measures evidence completeness, not profitability.';$('#pl-kpi-trades').textContent=c.stored_positions;$('#pl-kpi-paths').textContent=c.with_mae_mfe+' / '+c.stored_positions;",
    "selected profile coverage summary")
# Replace only the wide 14-cell trade-row renderer with nine compact combined cells.
trade_start = js.find("$('#pl-trade-rows').innerHTML=d.trades.length?")
trade_end = js.find(";const end=Math.min", trade_start)
if trade_start < 0 or trade_end < 0:
    raise RuntimeError("Cannot locate Portfolio Lab trade-row renderer")
trade_render = """$('#pl-trade-rows').innerHTML=d.trades.length?d.trades.map(v=>{const z=sc[v.id]||{};return '<tr><td>'+plTime(v.opened_ms)+'<small>to '+plTime(v.closed_ms)+'</small><small>'+esc(v.close_status)+'</small></td><td>'+esc(v.symbol||'—')+'<small>'+esc(v.side||'—')+'</small></td><td>'+(v.entry_price===null?'—':Number(v.entry_price).toPrecision(7))+'<small>to '+(v.exit_price===null?'—':Number(v.exit_price).toPrecision(7))+'</small></td><td>'+(v.leverage===null?'—':Number(v.leverage).toFixed(2)+'×')+'<small>'+esc(v.margin_mode||'—')+'</small></td><td>'+plUsd(v.close_pnl)+'<small>'+plPct(v.roi_pct)+'</small></td><td>'+plPct(v.mae_pct)+'<small>to MFE '+plPct(v.mfe_pct)+'</small></td><td>'+(v.time_to_mae_min===null?'—':Number(v.time_to_mae_min).toFixed(0)+'m')+'<small>to MFE '+(v.time_to_mfe_min===null?'—':Number(v.time_to_mfe_min).toFixed(0)+'m')+'</small></td><td>'+plPct(v.coverage_pct)+'<small>'+esc(v.path_status||'NOT_ANALYZED')+'</small></td><td>'+plUsd(z.hypothetical_pnl_usd)+'</td></tr>'}).join(''):'<tr><td colspan="9" class="empty-state">No position rows stored for this portfolio.</td></tr>'"""
js = js[:trade_start] + trade_render + js[trade_end:]
js = js.replace('colspan="12" class="empty-state">No portfolio meets the evidence threshold', 'colspan="7" class="empty-state">No portfolio meets the evidence threshold',1)

# Stability-first Multi-Trader table with 25-row pages and clear source-vs-derived WR.
if "MT_STABILITY_PAGER_V1" not in js:
    js = replace_once(js, "function renderMT(d){", "let mtTableRows=[];let mtPage=0;const mtPageSize=25;\nfunction renderMT(d){", "Multi-Trader pagination state")
    js = replace_section(
        js,
        "function renderMT(d){",
        "\nasync function loadMTHistory",
        '''function renderMT(d){
 $("#mt-total").textContent=n(d.monitored_count,0);$("#mt-eligible").textContent=n(d.eligible_count,0);$("#mt-blocked").textContent=n(d.blocked_count,0);$("#mt-selected-count").textContent=n(d.selected_count,0);
 $("#mt-asof").textContent="As of "+(d.evaluated_at_utc||"unknown")+(d.evaluation_id?" · saved #"+d.evaluation_id:"");
 $("#mt-table-meta").textContent=n(d.candidate_rows_returned,0)+" profiles evaluated · stability-first ranking";
 $("#mt-note").textContent=(d.monitored_count===0?"No profiles found for this market. Run discovery first. ":d.selected_count+" selected for PAPER MODE; "+d.blocked_count+" blocked/incomplete. ")+"Rows with weak path coverage show that limitation rather than receiving invented MAE/MFE. Stability is evidence-weighted, not a guaranteed future result.";
 const picked=d.selected_portfolios||[];$("#mt-picked").innerHTML=picked.length?picked.map(t=>'<div class="run-item"><div><div class="run-title">'+esc(t.nickname||t.portfolio_id)+' · stability '+n(t.stability_score,1)+'/100 · '+esc(t.stability_confidence_label||'LOW')+' evidence</div><div class="run-sub">'+esc(t.portfolio_id)+' · paper weight '+n(t.allocation_pct,1,'%')+' · PF '+n(t.profit_factor,2)+' · 30D MDD '+n(t.mdd_30d,2,'%')+' · P90 adverse '+n(t.p90_mae_pct,2,'%')+' · path coverage '+n(t.path_coverage_pct,1,'%')+'</div><div class="run-sub">'+esc(t.selection_reason||"Selected by stability-first risk screen")+'</div></div><span class="run-badge completed">PAPER ONLY</span></div>').join(""):'<div class="empty-state">No portfolio passed every risk filter. Missing history is not treated as a pass.</div>';
 mtTableRows=d.candidates||[];mtPage=0;renderMTPage();
}
function renderMTPage(){
 const rows=mtTableRows.slice(mtPage*mtPageSize,(mtPage+1)*mtPageSize);
 $("#mt-rows").innerHTML=rows.length?rows.map(t=>{const gaps=(t.evidence_gaps||[]).join('; ')||'No listed data gaps';const blocked=(t.reasons||[]).join('; ');const decision=(t.decision||'—')+(t.selected?' · paper '+n(t.allocation_pct,1,'%'):'');const historyCov=t.history_coverage_pct===null||t.history_coverage_pct===undefined?'unknown source total':n(t.history_coverage_pct,1,'%')+' of source total';const sourceWR=t.source_win_rate_pct===null||t.source_win_rate_pct===undefined?'Not captured':n(t.source_win_rate_pct,2,'%');const closedWR=t.win_rate_pct===null||t.win_rate_pct===undefined?'Not calculable':n(t.win_rate_pct,2,'%');const confidence=t.stability_confidence_label||'LOW';const official=t.profile_url||('https://www.binance.com/en-IN/copy-trading/lead-details/'+t.portfolio_id+'?timeRange=90D');return '<tr><td><strong>'+esc(t.nickname||"Unknown")+'</strong><small>'+esc(t.market_type)+' · '+esc(t.portfolio_id)+'</small><a target="_blank" rel="noopener noreferrer" href="'+esc(official)+'">Open Binance ↗</a><small>ROI 7D / 30D: '+n(t.roi_7d,2,'%')+' / '+n(t.roi_30d,2,'%')+'</small></td><td><b>'+n(t.stability_score,1)+'/100</b><small>'+esc(confidence)+' · '+n(t.stability_confidence_pct,0,'%')+' confidence</small><small>confidence-adjusted stability '+n(t.confidence_adjusted_stability_score,1)+'/100 · return score '+n(t.score,1)+'</small></td><td>'+n(t.mdd_7d,2,'%')+' / '+n(t.mdd_30d,2,'%')+' / '+n(t.mdd_365d,2,'%')+'</td><td>Median '+n(t.median_mae_pct,2,'%')+'<small>P90 '+n(t.p90_mae_pct,2,'%')+' · max '+n(t.max_mae_pct,2,'%')+'</small><small>≥2% adverse: '+n(t.trades_mae_gte_2pct_pct,1,'%')+' · ≥3%: '+n(t.trades_mae_gte_3pct_pct,1,'%')+'</small></td><td>Source '+sourceWR+'<small>Closed PnL '+closedWR+' ('+n(t.stored_closed_trades,0)+' records)</small></td><td>'+n(t.trade_count_7d,0)+' / '+n(t.trade_count_30d,0)+' / '+n(t.trade_count_90d,0)+'<small>Total stored '+n(t.stored_positions,0)+' · '+esc(historyCov)+'</small></td><td>'+n(t.path_trades_analyzed,0)+' / '+n(t.stored_positions,0)+' analyzed<small>'+n(t.path_coverage_pct,1,'%')+' path coverage</small><small>First / last: '+(t.first_trade_ms?new Date(Number(t.first_trade_ms)).toISOString().slice(0,10):'—')+' / '+(t.last_trade_ms?new Date(Number(t.last_trade_ms)).toISOString().slice(0,10):'—')+'</small></td><td><span class="status-chip">'+esc(decision)+'</span><small>'+esc(blocked||gaps)+'</small><small>Evidence gaps: '+esc(gaps)+'</small></td><td><button class="icon-button" data-mt-inspect="'+Number(t.id)+'">Inspect</button></td></tr>'}).join(""):'<tr><td colspan="9" class="empty-state">No candidates. Run discovery first or check source health.</td></tr>';
 const pages=Math.max(1,Math.ceil(mtTableRows.length/mtPageSize));$("#mt-page-meta").textContent=mtTableRows.length?((mtPage*mtPageSize+1)+'–'+Math.min((mtPage+1)*mtPageSize,mtTableRows.length)+' of '+mtTableRows.length):'No rows';$("#mt-prev-page").disabled=mtPage<=0;$("#mt-next-page").disabled=mtPage>=pages-1;
 $$("[data-mt-inspect]").forEach(b=>b.addEventListener("click",()=>{view("traders");openTrader(Number(b.dataset.mtInspect))}));
}
$("#mt-prev-page").addEventListener("click",()=>{if(mtPage>0){mtPage--;renderMTPage()}});
$("#mt-next-page").addEventListener("click",()=>{if((mtPage+1)*mtPageSize<mtTableRows.length){mtPage++;renderMTPage()}});
// MT_STABILITY_PAGER_V1''',
        "stability-first Multi-Trader renderer")
js += "\n// STABILITY_COVERAGE_METRICS_V1\n"
js += "\n$('#pl-profile-prev').addEventListener('click',()=>{if(plProfilePage>0){plProfilePage--;plRenderPortfolios()}});$('#pl-profile-next').addEventListener('click',()=>{if((plProfilePage+1)*plProfilePageSize<pl.portfolios.length){plProfilePage++;plRenderPortfolios()}});$('#pl-market').addEventListener('change',()=>{plProfilePage=0});\n"
js_path.write_text(js)
print("Installed stability-first ranking, history/path coverage, source-win-rate fallback and compact paginated tables.")
