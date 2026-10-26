from pathlib import Path
import hashlib
import json
import re

root = Path("/app")
app_path = root / "app.py"
html_path = root / "templates" / "index.html"
js_path = root / "static" / "app.js"

def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"Cannot patch {label}: expected one anchor, found {n}")
    return text.replace(old, new, 1)

# ---------------------------------------------------------------------------
# A. Make the model import unconditional. Previously this alias was installed
# only by an optional detail-API patch; the profile-list API still referenced it.
# ---------------------------------------------------------------------------
app = app_path.read_text()
import_line = "from models import TraderSnapshot as pl_Snapshot"
if not re.search(r"(?m)^from models import TraderSnapshot as pl_Snapshot\s*$", app):
    app += "\n" + import_line + "\n"
    app_path.write_text(app)

# ---------------------------------------------------------------------------
# B. Multi-Trader: evaluate on a selectable time period, apply a real minimum
# win-rate filter, and permit different ranking priorities without relaxing
# the underlying eligibility / missing-evidence guardrails.
# ---------------------------------------------------------------------------
app = app_path.read_text()
app = replace_once(
    app,
    'def _mt_report(market_type="FUTURES", min_closed_trades=10, min_profit_factor=1.2, max_mdd_pct=20, min_roi_7d=-5, max_selected=5):',
    'def _mt_report(market_type="FUTURES", min_closed_trades=10, min_profit_factor=1.2, max_mdd_pct=20, min_roi_7d=-5, evaluation_period="30D", min_win_rate_pct=50, ranking_priority="STABILITY", max_selected=5):',
    "Multi-Trader report arguments"
)
old_limits = '''    min_closed_trades=max(1,min(int(min_closed_trades),500)); min_profit_factor=max(.5,min(float(min_profit_factor),10))
    max_mdd_pct=max(1,min(float(max_mdd_pct),100)); min_roi_7d=max(-100,min(float(min_roi_7d),100)); max_selected=max(1,min(int(max_selected),10))
'''
new_limits = '''    min_closed_trades=max(1,min(int(min_closed_trades),500)); min_profit_factor=max(.5,min(float(min_profit_factor),10))
    max_mdd_pct=max(1,min(float(max_mdd_pct),100)); min_roi_7d=max(-100,min(float(min_roi_7d),100)); max_selected=max(1,min(int(max_selected),10))
    try: min_win_rate_pct=max(0.0,min(float(min_win_rate_pct),100.0))
    except (TypeError,ValueError,OverflowError): min_win_rate_pct=50.0
    evaluation_period=str(evaluation_period or "30D").upper()
    if evaluation_period not in ("7D","30D","90D","365D"): evaluation_period="30D"
    # The current collector has no verified 7D Spot metrics. Use its supported 30D source window.
    if market_type=="SPOT" and evaluation_period=="7D": evaluation_period="30D"
    ranking_priority=str(ranking_priority or "STABILITY").upper()
    if ranking_priority not in ("STABILITY","WIN_RATE","PROFIT_FACTOR","PERIOD_ROI","LOW_DRAWDOWN"): ranking_priority="STABILITY"
'''
app = replace_once(app, old_limits, new_limits, "Multi-Trader filter normalization")

period_anchor = '''            roi7,roi30,roi90,roi365=[pm(k,"roi") for k in ("7D","30D","90D","365D")]
            mdd7,mdd30,mdd365=[pm(k,"mdd") for k in ("7D","30D","365D")]
'''
period_new = '''            roi7,roi30,roi90,roi365=[pm(k,"roi") for k in ("7D","30D","90D","365D")]
            mdd7,mdd30,mdd365=[pm(k,"mdd") for k in ("7D","30D","365D")]
            period_values={"7D":(roi7,mdd7),"30D":(roi30,mdd30),"90D":(roi90,pm("90D","mdd")),"365D":(roi365,mdd365)}
            selected_roi,selected_mdd=period_values[evaluation_period]
'''
app = replace_once(app, period_anchor, period_new, "selected-period metrics")

old_period_gates = '''            if roi7 is None: reasons.append("MISSING_SOURCE_7D_ROI")
            if mdd7 is None: reasons.append("MISSING_SOURCE_7D_MDD")
            if mdd30 is None: reasons.append("MISSING_SOURCE_30D_MDD")
            if roi7 is not None and roi7<min_roi_7d: reasons.append("RECENT_ROI_BELOW_FLOOR")
            if mdd7 is not None and abs(mdd7)>max_mdd_pct: reasons.append("7D_MDD_LIMIT_EXCEEDED")
            if mdd30 is not None and abs(mdd30)>max_mdd_pct: reasons.append("30D_MDD_LIMIT_EXCEEDED")
'''
new_period_gates = '''            if selected_roi is None: reasons.append(f"MISSING_SOURCE_{evaluation_period}_ROI")
            elif selected_roi<min_roi_7d: reasons.append(f"{evaluation_period}_ROI_BELOW_FLOOR")
            if selected_mdd is None: reasons.append(f"MISSING_SOURCE_{evaluation_period}_MDD")
            elif abs(selected_mdd)>max_mdd_pct: reasons.append(f"{evaluation_period}_MDD_LIMIT_EXCEEDED")
            # Keep the recent 30D drawdown guard in force even when ranking a longer period.
            if evaluation_period!="30D" and mdd30 is None: reasons.append("MISSING_SOURCE_30D_MDD")
            if mdd30 is not None and abs(mdd30)>max_mdd_pct: reasons.append("30D_MDD_LIMIT_EXCEEDED")
'''
app = replace_once(app, old_period_gates, new_period_gates, "period-specific ROI/MDD gates")

old_spot_block = '''            # Apply Spot's supported 30-day evidence after reasons has been initialized.
            if market_type=="SPOT":
                reasons=[r for r in reasons if r not in ("MISSING_SOURCE_7D_ROI","MISSING_SOURCE_7D_MDD","RECENT_ROI_BELOW_FLOOR","7D_MDD_LIMIT_EXCEEDED")]
                if roi30 is None:
                    reasons.append("MISSING_SOURCE_30D_ROI")
                elif roi30 < min_roi_7d:
                    reasons.append("RECENT_30D_ROI_BELOW_FLOOR")
'''
new_spot_block = '''            # All period gates above use evaluation_period; Spot 7D has already been
            # normalized to 30D. Do not apply a second hard-coded 30D ROI rule here.
'''
app = replace_once(app, old_spot_block, new_spot_block, "remove duplicate hard-coded Spot filter")

score_anchor = '''            score=50+max(-20,min(20,roi7 or 0))*.7+max(-30,min(30,roi30 or 0))*.35+max(-50,min(50,roi90 or 0))*.1
'''
score_new = '''            # Return score uses the selected period; the primary default rank remains
            # confidence-adjusted stability (drawdown + adverse movement + outcomes).
            score=50+max(-20,min(20,selected_roi or 0))*.7+max(-30,min(30,roi30 or 0))*.25+max(-50,min(50,roi365 or 0))*.05
'''
app = replace_once(app, score_anchor, score_new, "selected-period return score")

# Apply the win-rate filter only after source and verified closed-trade win-rate
# fields have been populated by the stability evidence patch.
filter_anchor = '''            score+=(min(pf,3)-1)*10 if pf is not None else -12
'''
filter_new = '''            score+=(min(pf,3)-1)*10 if pf is not None else -12
            _rank_win_rate = closed_wr if len(closed)>=min_closed_trades and closed_wr is not None else source_wr
            if min_win_rate_pct>0:
                if _rank_win_rate is None:
                    reasons.append("WIN_RATE_NOT_AVAILABLE")
                elif _rank_win_rate<min_win_rate_pct:
                    reasons.append("WIN_RATE_BELOW_FLOOR")
'''
app = replace_once(app, filter_anchor, filter_new, "minimum win-rate gate")

# Calculate an explicit priority score for the requested ranking mode, without
# using win rate alone to determine paper allocation weights.
append_anchor = '            rows.append({"id":t.id,"nickname":t.nickname,"portfolio_id":t.portfolio_id,"profile_url":t.profile_url,"market_type":t.market_type,'
priority_block = '''            _adjusted_stability=(max(0,min(100,stability_score*(0.5+0.5*stability_confidence/100.0))) if stability_score is not None else None)
            if ranking_priority=="WIN_RATE":
                _priority_score=max(0,min(100,float(_rank_win_rate))) if _rank_win_rate is not None else None
            elif ranking_priority=="PROFIT_FACTOR":
                _priority_score=max(0,min(100,float(pf)*50.0)) if pf is not None else None
            elif ranking_priority=="PERIOD_ROI":
                _priority_score=max(0,min(100,50.0+float(selected_roi)*1.5)) if selected_roi is not None else None
            elif ranking_priority=="LOW_DRAWDOWN":
                _priority_score=max(0,min(100,100.0-2.0*abs(float(selected_mdd)))) if selected_mdd is not None else None
            else:
                _priority_score=_adjusted_stability if _adjusted_stability is not None else score
'''
app = replace_once(app, append_anchor, priority_block + append_anchor, "calculate ranking-priority score")

row_metrics_old = '"last_seen":_iso(t.last_seen),"age_days":round(age,2) if age is not None else None,"roi_7d":roi7,"roi_30d":roi30,"roi_90d":roi90,"roi_365d":roi365,'
row_metrics_new = '"last_seen":_iso(t.last_seen),"age_days":round(age,2) if age is not None else None,"evaluation_period":evaluation_period,"effective_period_roi":selected_roi,"effective_period_mdd":selected_mdd,"ranking_priority":ranking_priority,"priority_score":round(_priority_score,2) if _priority_score is not None else None,"rank_win_rate_pct":_rank_win_rate,"roi_7d":roi7,"roi_30d":roi30,"roi_90d":roi90,"roi_365d":roi365,'
app = replace_once(app, row_metrics_old, row_metrics_new, "store selected-period and priority fields")

# Sort candidates and choose the shortlist by the requested priority, then account
# for historical symbol overlap. Missing scores sort behind populated evidence.
sort_pattern = re.compile(r'(?m)^    rows\.sort\(key=lambda x:.*?reverse=True\)$')
sort_matches = list(sort_pattern.finditer(app))
if len(sort_matches) != 1:
    raise RuntimeError(f"Cannot replace Multi-Trader candidate sort: found {len(sort_matches)}")
app = app[:sort_matches[0].start()] + '    rows.sort(key=lambda x:(x["eligible"],x["priority_score"] is not None,x["priority_score"] if x["priority_score"] is not None else -1,x["confidence_adjusted_stability_score"] if x["confidence_adjusted_stability_score"] is not None else -1,x["score"],x["stored_closed_trades"]),reverse=True)' + app[sort_matches[0].end():]

old_overlap = 'adjusted=(x.get("confidence_adjusted_stability_score") if x.get("confidence_adjusted_stability_score") is not None else x["score"])-overlap*18'
if old_overlap in app:
    app = replace_once(app, old_overlap, 'adjusted=(x.get("priority_score") if x.get("priority_score") is not None else x["score"])-overlap*18', "use selected ranking priority in shortlist")
elif 'adjusted=(x.get("priority_score") if x.get("priority_score") is not None else x["score"])-overlap*18' not in app:
    raise RuntimeError("Cannot locate Multi-Trader overlap-aware selection score")

# Return the selected score and active filter settings to the UI and persisted snapshot.
key_anchor = '"id","nickname","portfolio_id","profile_url","score","stability_score"'
key_new = '"id","nickname","portfolio_id","profile_url","ranking_priority","priority_score","rank_win_rate_pct","effective_period","effective_period_roi","effective_period_mdd","score","stability_score"'
app = replace_once(app, key_anchor, key_new, "selected portfolio summary fields")

settings_old = '"settings":{"min_closed_trades":min_closed_trades,"min_profit_factor":min_profit_factor,"max_mdd_pct":max_mdd_pct,"min_roi_7d":min_roi_7d,"max_selected":max_selected},'
settings_new = '"settings":{"min_closed_trades":min_closed_trades,"min_profit_factor":min_profit_factor,"max_mdd_pct":max_mdd_pct,"min_roi_7d":min_roi_7d,"evaluation_period":evaluation_period,"min_win_rate_pct":min_win_rate_pct,"ranking_priority":ranking_priority,"max_selected":max_selected},'
app = replace_once(app, settings_old, settings_new, "persist active rank filters")

get_old = 'request.args.get("min_roi_7d",-5),request.args.get("max_selected",5)'
get_new = 'request.args.get("min_roi_7d",-5),request.args.get("evaluation_period","30D"),request.args.get("min_win_rate_pct",50),request.args.get("ranking_priority","STABILITY"),request.args.get("max_selected",5)'
app = replace_once(app, get_old, get_new, "candidate API filter arguments")
post_old = 'data.get("min_roi_7d",-5),data.get("max_selected",5)'
post_new = 'data.get("min_roi_7d",-5),data.get("evaluation_period","30D"),data.get("min_win_rate_pct",50),data.get("ranking_priority","STABILITY"),data.get("max_selected",5)'
app = replace_once(app, post_old, post_new, "saved-evaluation API filter arguments")
app_path.write_text(app)

# ---------------------------------------------------------------------------
# C. Trade behaviour board: a real database-backed per-portfolio view. All
# rates/PF use verified closes only. Raw Spot activity is counted, not mislabelled
# as closed trades. The API uses grouped SQL and a bounded path sample per profile.
# ---------------------------------------------------------------------------
app = app_path.read_text()
if 'TRADE_BEHAVIOUR_PORTFOLIO_BOARD_V1' not in app:
    app += r'''

# TRADE_BEHAVIOUR_PORTFOLIO_BOARD_V1
from flask import jsonify as tb_jsonify, request as tb_request
from sqlalchemy import select as tb_select, func as tb_func, case as tb_case
from models import SessionLocal as tb_Session, Trader as tb_Trader, Position as tb_Position, TraderSnapshot as tb_Snapshot
import json as tb_json
import time as tb_time

def _tb_num(v):
    try:
        if v in (None, ""): return None
        x=float(v)
        return x if __import__("math").isfinite(x) else None
    except (TypeError,ValueError,OverflowError): return None

@app.get("/api/trade-behaviour")
def api_trade_behaviour():
    market=str(tb_request.args.get("market_type","FUTURES")).upper()
    if market not in ("FUTURES","SPOT"):
        return tb_jsonify({"error":"market_type must be FUTURES or SPOT"}),400
    try:
        period_days=int(tb_request.args.get("period_days",30))
        if period_days not in (7,30,90,365): period_days=30
        min_wr=max(0.0,min(100.0,float(tb_request.args.get("min_win_rate_pct",0))))
        limit=max(25,min(500,int(tb_request.args.get("limit",250))))
    except (TypeError,ValueError,OverflowError):
        return tb_jsonify({"error":"invalid trade behaviour filters"}),400
    sort_by=str(tb_request.args.get("sort_by","STABILITY")).upper()
    if sort_by not in ("STABILITY","WIN_RATE","PROFIT_FACTOR","NET_PNL","LOWER_ADVERSE","ROI"):
        sort_by="STABILITY"
    effective_period="30D" if market=="SPOT" and period_days==7 else str(period_days)+"D"
    cutoff=int(tb_time.time()*1000)-period_days*86400000
    verified_spot=("PAIRED_SPOT_TRADE","CLOSED_SPOT_TRADE","VERIFIED_SPOT_CLOSED_TRADE")
    with tb_Session() as db:
        traders=list(db.scalars(tb_select(tb_Trader).where(
            tb_Trader.exchange=="BINANCE",tb_Trader.market_type==market
        ).order_by(tb_Trader.last_seen.desc().nullslast(),tb_Trader.id.asc()).limit(1000)))
        ids=[t.id for t in traders]
        if not ids:
            return tb_jsonify({"market_type":market,"period_days":period_days,"effective_period":effective_period,
                "profile_count":0,"profiles_displayed":0,"activity_records":0,"verified_closed_trades":0,
                "analysed_paths":0,"items":[],"note":"No profiles have been collected for this market yet."})
        event_ts=tb_func.coalesce(tb_Position.closed_ms,tb_Position.opened_ms)
        valid_closed=tb_Position.close_pnl.is_not(None) & tb_Position.closed_ms.is_not(None)
        valid_path=tb_Position.mae_pct.is_not(None) & tb_Position.mfe_pct.is_not(None) & tb_Position.closed_ms.is_not(None)
        if market=="SPOT":
            valid_closed=valid_closed & tb_Position.source_kind.in_(verified_spot)
            valid_path=valid_path & tb_Position.source_kind.in_(verified_spot)
        # One grouped query for activity, verified closes, realized outcomes and path counts.
        stmt=tb_select(
            tb_Position.trader_id,
            tb_func.count(tb_Position.id).label("activity_count"),
            tb_func.count(tb_Position.id).filter(valid_closed).label("closed_count"),
            tb_func.count(tb_Position.id).filter(valid_closed & (tb_Position.close_pnl>0)).label("wins"),
            tb_func.count(tb_Position.id).filter(valid_closed & (tb_Position.close_pnl<0)).label("losses"),
            tb_func.sum(tb_Position.close_pnl).filter(valid_closed).label("net_pnl"),
            tb_func.sum(tb_case((valid_closed & (tb_Position.close_pnl>0),tb_Position.close_pnl),else_=0.0)).label("gross_profit"),
            tb_func.sum(tb_case((valid_closed & (tb_Position.close_pnl<0),-tb_Position.close_pnl),else_=0.0)).label("gross_loss_abs"),
            tb_func.count(tb_Position.id).filter(valid_path).label("path_count"),
            tb_func.avg(tb_func.abs(tb_Position.mae_pct)).filter(valid_path).label("avg_mae"),
            tb_func.avg(tb_func.abs(tb_Position.mfe_pct)).filter(valid_path).label("avg_mfe"),
            tb_func.min(event_ts).label("first_ms"),
            tb_func.max(event_ts).label("last_ms")
        ).where(tb_Position.trader_id.in_(ids),event_ts>=cutoff).group_by(tb_Position.trader_id)
        aggregates={}
        for r in db.execute(stmt):
            aggregates[r[0]]={"activity_count":int(r[1] or 0),"closed_count":int(r[2] or 0),
                "wins":int(r[3] or 0),"losses":int(r[4] or 0),"net_pnl":float(r[5]) if r[5] is not None else None,
                "gross_profit":float(r[6] or 0),"gross_loss_abs":float(r[7] or 0),"path_count":int(r[8] or 0),
                "avg_mae":float(r[9]) if r[9] is not None else None,"avg_mfe":float(r[10]) if r[10] is not None else None,
                "first_ms":int(r[11]) if r[11] is not None else None,"last_ms":int(r[12]) if r[12] is not None else None}
        # Keep only the newest 50 analysed paths per profile for the distribution statistics.
        ranked_paths=tb_select(
            tb_Position.trader_id.label("trader_id"),
            tb_Position.mae_pct.label("mae_pct"),
            tb_Position.mfe_pct.label("mfe_pct"),
            tb_func.row_number().over(partition_by=tb_Position.trader_id,
                order_by=[tb_Position.closed_ms.desc().nullslast(),tb_Position.id.desc()]).label("path_rank")
        ).where(tb_Position.trader_id.in_(ids),event_ts>=cutoff,valid_path).subquery()
        path_values={i:{"mae":[],"mfe":[]} for i in ids}
        for tid,mae,mfe in db.execute(tb_select(
            ranked_paths.c.trader_id,ranked_paths.c.mae_pct,ranked_paths.c.mfe_pct
        ).where(ranked_paths.c.path_rank<=50)):
            path_values.setdefault(tid,{"mae":[],"mfe":[]})["mae"].append(abs(float(mae)))
            path_values.setdefault(tid,{"mae":[],"mfe":[]})["mfe"].append(abs(float(mfe)))
        # Latest non-null source win rate per profile, via a windowed SQL query (no N+1 selects).
        snapshot_wr={}
        ranked_wr=tb_select(
            tb_Snapshot.trader_id.label("trader_id"),tb_Snapshot.win_rate.label("win_rate"),
            tb_func.row_number().over(partition_by=tb_Snapshot.trader_id,
                order_by=[tb_Snapshot.captured_at.desc().nullslast(),tb_Snapshot.id.desc()]).label("wr_rank")
        ).where(tb_Snapshot.trader_id.in_(ids),tb_Snapshot.win_rate.is_not(None)).subquery()
        for tid,wr in db.execute(tb_select(ranked_wr.c.trader_id,ranked_wr.c.win_rate).where(ranked_wr.c.wr_rank==1)):
            snapshot_wr[tid]=_tb_num(wr)
        out=[]
        for t in traders:
            a=aggregates.get(t.id,{"activity_count":0,"closed_count":0,"wins":0,"losses":0,
                "net_pnl":None,"gross_profit":0.0,"gross_loss_abs":0.0,"path_count":0,
                "avg_mae":None,"avg_mfe":None,"first_ms":None,"last_ms":None})
            paths=path_values.get(t.id,{"mae":[],"mfe":[]})
            maes=sorted(paths["mae"]); mfes=sorted(paths["mfe"])
            p90=maes[int(round((len(maes)-1)*.90))] if maes else None
            median_mae=__import__("statistics").median(maes) if maes else None
            median_mfe=__import__("statistics").median(mfes) if mfes else None
            closed_wr=100.0*a["wins"]/a["closed_count"] if a["closed_count"] else None
            source_wr=_tb_num(t.win_rate)
            if source_wr is None: source_wr=snapshot_wr.get(t.id)
            rank_wr=closed_wr if a["closed_count"]>=10 and closed_wr is not None else source_wr
            if min_wr>0 and (rank_wr is None or rank_wr<min_wr):
                continue
            pf=(a["gross_profit"]/a["gross_loss_abs"]) if a["gross_loss_abs"]>0 else ("INF" if a["gross_profit"]>0 else None)
            try: periods=tb_json.loads(t.period_metrics or "{}")
            except Exception: periods={}
            period_obj=periods.get(effective_period,{}) if isinstance(periods,dict) else {}
            period_roi=_tb_num(period_obj.get("roi")) if isinstance(period_obj,dict) else None
            period_mdd=_tb_num(period_obj.get("mdd")) if isinstance(period_obj,dict) else None
            if period_mdd is None: period_mdd=_tb_num(t.mdd)
            mdd_score=max(0.0,100.0-2.0*abs(period_mdd)) if period_mdd is not None else None
            adverse_score=max(0.0,100.0-5.0*min(float(p90),20.0)) if p90 is not None else None
            outcome_parts=[]
            if closed_wr is not None: outcome_parts.append(closed_wr)
            elif source_wr is not None: outcome_parts.append(max(0.0,min(100.0,source_wr)))
            if isinstance(pf,(float,int)): outcome_parts.append(max(0.0,min(100.0,float(pf)*50.0)))
            outcome=sum(outcome_parts)/len(outcome_parts) if outcome_parts else None
            components=[]
            if mdd_score is not None: components.append((mdd_score,.45))
            if adverse_score is not None: components.append((adverse_score,.35))
            if outcome is not None: components.append((outcome,.20))
            stability=sum(v*w for v,w in components)/sum(w for v,w in components) if components else None
            confidence=40.0 if period_mdd is not None else 0.0
            confidence+=min(40.0,4.0*a["path_count"])+min(15.0,.75*a["closed_count"])+(5.0 if source_wr is not None else 0.0)
            out.append({
                "id":t.id,"nickname":t.nickname,"portfolio_id":t.portfolio_id,
                "profile_url":t.profile_url or ("https://www.binance.com/en/copy-trading/"+("spot" if market=="SPOT" else "futures")+"/lead-details/"+str(t.portfolio_id)),
                "market_type":market,"period_days":period_days,"effective_period":effective_period,
                "activity_records":a["activity_count"],"stored_total_positions":t.history_count,
                "verified_closed_trades":a["closed_count"],"wins":a["wins"],"losses":a["losses"],
                "source_win_rate_pct":source_wr,"closed_win_rate_pct":closed_wr,"rank_win_rate_pct":rank_wr,
                "profit_factor":pf,"net_realized_pnl_usd":a["net_pnl"],
                "average_win_usd":(a["gross_profit"]/a["wins"]) if a["wins"] else None,
                "average_loss_usd":(-a["gross_loss_abs"]/a["losses"]) if a["losses"] else None,
                "median_mae_pct":median_mae,"p90_mae_pct":p90,"max_mae_pct":max(maes) if maes else None,
                "average_mae_pct":a["avg_mae"],"median_mfe_pct":median_mfe,"average_mfe_pct":a["avg_mfe"],
                "analysed_paths":a["path_count"],"path_sample_size":len(maes),
                "period_roi_pct":period_roi,"period_mdd_pct":period_mdd,
                "first_trade_ms":a["first_ms"],"last_trade_ms":a["last_ms"],
                "stability_score":round(stability,2) if stability is not None else None,
                "stability_confidence_pct":round(min(100.0,confidence),1),
                "win_rate_basis":"VERIFIED_CLOSED_TRADES" if a["closed_count"]>=10 and closed_wr is not None else ("SOURCE_PROFILE_OR_SNAPSHOT" if source_wr is not None else "NOT_CAPTURED"),
                "history_coverage_pct":(min(100.0,100.0*a["activity_count"]/float(t.total_positions)) if t.total_positions and float(t.total_positions)>0 else None)
            })
    def metric(item):
        if sort_by=="WIN_RATE": return item.get("rank_win_rate_pct") if item.get("rank_win_rate_pct") is not None else -1.0
        if sort_by=="PROFIT_FACTOR":
            pf=item.get("profit_factor")
            return 1e6 if pf=="INF" else (pf if pf is not None else -1.0)
        if sort_by=="NET_PNL": return item.get("net_realized_pnl_usd") if item.get("net_realized_pnl_usd") is not None else -1e30
        if sort_by=="LOWER_ADVERSE": return -item["p90_mae_pct"] if item.get("p90_mae_pct") is not None else -1e6
        if sort_by=="ROI": return item.get("period_roi_pct") if item.get("period_roi_pct") is not None else -1e30
        return item.get("stability_score") if item.get("stability_score") is not None else -1.0
    out.sort(key=lambda x:(metric(x),x.get("stability_confidence_pct",0),x.get("verified_closed_trades",0)),reverse=True)
    return tb_jsonify({
        "market_type":market,"period_days":period_days,"effective_period":effective_period,
        "minimum_win_rate_pct":min_wr,"sort_by":sort_by,"profile_count":len(traders),"profiles_displayed":len(out),
        "activity_records":sum(x["activity_records"] for x in out),
        "verified_closed_trades":sum(x["verified_closed_trades"] for x in out),
        "analysed_paths":sum(x["analysed_paths"] for x in out),
        "items":out[:limit],
        "note":"PF, closed win rate and realized PnL use verified closed records only. Spot raw activity is counted separately and is not treated as a completed trade."
    })
'''
    app_path.write_text(app)

# ---------------------------------------------------------------------------
# D. Add a first-class Trade behaviour board to the existing history page.
# ---------------------------------------------------------------------------
html=html_path.read_text()
if 'id="tb-rows"' not in html:
    opening=re.search(r'<section class="view" id="view-history"[^>]*>',html)
    if not opening:
        raise RuntimeError("Cannot locate Trade behaviour view")
    panel = r'''
      <article class="panel" id="tb-portfolio-behaviour">
        <div class="panel-header"><div><div class="eyebrow">PORTFOLIO BEHAVIOUR · VERIFIED TRADE EVIDENCE</div><h3>Portfolio trade-behaviour ranking</h3><p>Win/loss statistics use verified closes; MAE/MFE uses the bounded analysed-path sample.</p></div><span class="tag blue">READ-ONLY</span></div>
        <div class="field-row">
          <label>Market<select id="tb-market"><option value="FUTURES">Futures</option><option value="SPOT">Spot</option></select></label>
          <label>History window<select id="tb-period"><option value="7">7 days</option><option value="30" selected>30 days</option><option value="90">90 days</option><option value="365">365 days</option></select></label>
          <label>Minimum win rate (%)<input id="tb-min-win-rate" type="number" min="0" max="100" step="1" value="0"></label>
          <label>Rank portfolios by<select id="tb-sort"><option value="STABILITY">Balanced stability</option><option value="WIN_RATE">Highest win rate</option><option value="LOWER_ADVERSE">Lowest P90 adverse move</option><option value="PROFIT_FACTOR">Best profit factor</option><option value="ROI">Selected-period ROI</option><option value="NET_PNL">Net realized PnL</option></select></label>
        </div>
        <div class="button-row"><button id="tb-refresh" class="btn primary">↻ Refresh behaviour analysis</button><span class="tag gray" id="tb-meta">Waiting for data</span></div>
        <div class="kpi-grid">
          <article class="kpi-card"><div class="kpi-head"><span>Profiles evaluated</span></div><div class="kpi-value" id="tb-profiles">—</div><div class="kpi-foot">Stored Binance profiles</div></article>
          <article class="kpi-card"><div class="kpi-head"><span>Activity records</span></div><div class="kpi-value" id="tb-activities">—</div><div class="kpi-foot">Selected time window</div></article>
          <article class="kpi-card"><div class="kpi-head"><span>Verified closed trades</span></div><div class="kpi-value" id="tb-closed">—</div><div class="kpi-foot">Realized PnL available</div></article>
          <article class="kpi-card"><div class="kpi-head"><span>Analysed paths</span></div><div class="kpi-value" id="tb-paths">—</div><div class="kpi-foot">MAE / MFE available</div></article>
        </div>
        <div class="notice-box" id="tb-note">Loading portfolio behaviour from stored records. Spot activity without verified entry/close pairing will not be treated as a win or a loss.</div>
        <div class="table-scroll"><table class="compact-table"><thead><tr><th>Portfolio / official profile</th><th>Activity / closed / paths</th><th>Source WR / closed WR</th><th>Profit factor / net PnL</th><th>Median / P90 MAE · median MFE</th><th>Period ROI / MDD · history range</th><th>Stability / confidence</th></tr></thead><tbody id="tb-rows"><tr><td colspan="7" class="empty-state">Loading portfolio behaviour…</td></tr></tbody></table></div>
      </article>
'''
    html=html[:opening.end()]+panel+html[opening.end():]
html_path.write_text(html)

# ---------------------------------------------------------------------------
# E. Make Portfolio Lab load forecasts automatically, not only after a click.
# Profiles refresh on the existing page timer; the forecast re-runs on entry,
# manual refresh, market change and a three-minute foreground refresh.
# ---------------------------------------------------------------------------
js=js_path.read_text()
pl_start=js.find("async function loadPortfolioLab(){")
pl_end=js.find("\n$('#pl-run-forecast')",pl_start)
if pl_start<0 or pl_end<0:
    raise RuntimeError("Cannot locate Portfolio Lab loader for auto-forecast patch")
new_loader = r'''async function loadPortfolioLab(autoForecast=true){pl.market=$('#pl-market').value;$('#pl-profile-rows').innerHTML='<tr><td colspan="6" class="empty-state">Refreshing stored portfolios…</td></tr>';try{const d=await api('/api/portfolio-lab/portfolios?market_type='+pl.market);pl.portfolios=d.items||[];plRenderPortfolios();if(!pl.portfolios.length&&pl.market==='SPOT')$('#pl-rank-note').textContent='Spot profiles are stored, but no verified Spot closed-trade history is available for a reliable win-rate/PnL forecast. Unpaired activity remains visible without invented results.';if(pl.selected&&pl.portfolios.some(t=>Number(t.id)===Number(pl.selected)))await plLoadPortfolio(pl.selected,pl.offset);else pl.selected=null;if(autoForecast)await plRunForecast();}catch(e){$('#pl-profile-rows').innerHTML='<tr><td colspan="6" class="empty-state">'+esc(e.message)+'</td></tr>';$('#pl-rank-note').textContent='Portfolio list failed: '+e.message;$('#pl-rank-rows').innerHTML='<tr><td colspan="7" class="empty-state">'+esc(e.message)+'</td></tr>'}}'''
js=js[:pl_start]+new_loader+js[pl_end:]
js=js.replace("$('#pl-refresh').addEventListener('click',async()=>{await loadPortfolioLab();await plRunForecast()});","$('#pl-refresh').addEventListener('click',()=>loadPortfolioLab(true));")
js=js.replace("$('#pl-market').addEventListener('change',async()=>{pl.selected=null;await loadPortfolioLab();await plRunForecast()});","$('#pl-market').addEventListener('change',()=>{pl.selected=null;loadPortfolioLab(true)});")

# Wire UI controls and apply ranking filters immediately when changed.
mt_filters_old = 'function mtFilters(){const v=(id,def)=>{const raw=$(id).value;const x=Number(raw);return raw!==""&&Number.isFinite(x)?x:def};return {market_type:$("#mt-market").value,max_selected:v("#mt-max-selected",5),min_closed_trades:v("#mt-min-trades",10),min_profit_factor:v("#mt-min-pf",1.2),max_mdd_pct:v("#mt-max-mdd",20),min_roi_7d:v("#mt-min-roi7",-5)}}'
mt_filters_new = 'function mtFilters(){const v=(id,def)=>{const raw=$(id).value;const x=Number(raw);return raw!==""&&Number.isFinite(x)?x:def};return {market_type:$("#mt-market").value,max_selected:v("#mt-max-selected",5),min_closed_trades:v("#mt-min-trades",10),min_profit_factor:v("#mt-min-pf",1.2),max_mdd_pct:v("#mt-max-mdd",20),min_roi_7d:v("#mt-min-roi7",-5),evaluation_period:$("#mt-period").value,min_win_rate_pct:v("#mt-min-win-rate",50),ranking_priority:$("#mt-ranking-priority").value}}'
js=replace_once(js,mt_filters_old,mt_filters_new,"Multi-Trader UI filter payload")
js=js.replace('$("#mt-market").addEventListener("change",()=>loadMultiTrader(false));','''function mtSyncPeriodOptions(){const market=$("#mt-market").value;const opt=$("#mt-period").querySelector('option[value="7D"]');if(opt)opt.disabled=market==="SPOT";if(market==="SPOT"&&$("#mt-period").value==="7D")$("#mt-period").value="30D"}mtSyncPeriodOptions();$("#mt-market").addEventListener("change",()=>{mtSyncPeriodOptions();loadMultiTrader(false)});$("#mt-period").addEventListener("change",()=>loadMultiTrader(false));$("#mt-min-win-rate").addEventListener("change",()=>loadMultiTrader(false));$("#mt-ranking-priority").addEventListener("change",()=>loadMultiTrader(false));''')

# Load the new behaviour board via the same authenticated API helper used elsewhere.
behaviour_js = r'''
function tbMoney(v){return v===null||v===undefined||!Number.isFinite(Number(v))?'—':'$'+Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function tbPct(v){return v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toFixed(2)+'%'}
function tbStamp(v){if(v===null||v===undefined||v==='')return '—';const d=new Date(Number(v));return Number.isNaN(d.getTime())?'—':d.toLocaleDateString('en-GB',{timeZone:'UTC'})}
async function loadTradeBehaviour(){const q=new URLSearchParams({market_type:$('#tb-market').value,period_days:$('#tb-period').value,min_win_rate_pct:$('#tb-min-win-rate').value||0,sort_by:$('#tb-sort').value,limit:250});$('#tb-note').textContent='Calculating portfolio behaviour from stored trades…';$('#tb-rows').innerHTML='<tr><td colspan="7" class="empty-state">Loading verified trade statistics…</td></tr>';try{const d=await api('/api/trade-behaviour?'+q.toString());$('#tb-profiles').textContent=Number(d.profile_count||0).toLocaleString();$('#tb-activities').textContent=Number(d.activity_records||0).toLocaleString();$('#tb-closed').textContent=Number(d.verified_closed_trades||0).toLocaleString();$('#tb-paths').textContent=Number(d.analysed_paths||0).toLocaleString();$('#tb-meta').textContent=d.profiles_displayed+' shown · '+d.effective_period+' · '+d.sort_by;$('#tb-note').textContent=d.note+(Number(d.minimum_win_rate_pct||0)>0?' Minimum effective win rate '+d.minimum_win_rate_pct+'% applied.':' No minimum win-rate filter applied.');const rows=d.items||[];$('#tb-rows').innerHTML=rows.length?rows.map(t=>'<tr><td><b>'+esc(t.nickname||'Unknown')+'</b><small style="display:block">'+esc(t.portfolio_id||'')+' · '+esc(t.market_type)+'</small><a target="_blank" rel="noopener noreferrer" href="'+esc(t.profile_url)+'">Open Binance ↗</a></td><td>'+Number(t.activity_records||0)+' / '+Number(t.verified_closed_trades||0)+' / '+Number(t.analysed_paths||0)+'</td><td>Source '+tbPct(t.source_win_rate_pct)+'<small style="display:block">Closed '+tbPct(t.closed_win_rate_pct)+'</small><small>'+esc(t.win_rate_basis||'NOT_CAPTURED')+'</small></td><td>'+(t.profit_factor==='INF'?'∞':(t.profit_factor===null?'—':Number(t.profit_factor).toFixed(2)))+'<small style="display:block">'+tbMoney(t.net_realized_pnl_usd)+'</small><small>'+Number(t.wins||0)+' W / '+Number(t.losses||0)+' L</small></td><td>Median '+tbPct(t.median_mae_pct)+'<small style="display:block">P90 '+tbPct(t.p90_mae_pct)+' · MFE '+tbPct(t.median_mfe_pct)+'</small><small>Paths '+Number(t.path_sample_size||0)+'</small></td><td>ROI '+tbPct(t.period_roi_pct)+'<small style="display:block">MDD '+tbPct(t.period_mdd_pct)+'</small><small>'+tbStamp(t.first_trade_ms)+' → '+tbStamp(t.last_trade_ms)+'</small></td><td><b>'+(t.stability_score===null?'—':Number(t.stability_score).toFixed(1)+'/100')+'</b><small style="display:block">'+Number(t.stability_confidence_pct||0).toFixed(0)+'% evidence confidence</small></td></tr>').join(''):'<tr><td colspan="7" class="empty-state">No portfolios match this time window/filter. Try a longer period or lower minimum win rate. Spot raw activity does not count as a verified closed trade.</td></tr>'}catch(e){$('#tb-meta').textContent='Load failed';$('#tb-note').textContent='Trade behaviour failed: '+e.message;$('#tb-rows').innerHTML='<tr><td colspan="7" class="empty-state">'+esc(e.message)+'</td></tr>'}}
if(!window.__biTradeBehaviourControlsWired){window.__biTradeBehaviourControlsWired=true;['#tb-market','#tb-period','#tb-min-win-rate','#tb-sort'].forEach(sel=>{const el=$(sel);if(el)el.addEventListener('change',loadTradeBehaviour)});const refresh=$('#tb-refresh');if(refresh)refresh.addEventListener('click',loadTradeBehaviour)}
'''
if 'async function loadTradeBehaviour()' not in js:
    js += "\n" + behaviour_js + "\n"

# Display the active priority score while keeping stability and confidence visible.
score_cell_old = "n(t.stability_score,1)+'/100</b><small>'+esc(confidence)"
score_cell_new = "n(t.priority_score!==undefined&&t.priority_score!==null?t.priority_score:t.stability_score,1)+'/100</b><small>'+esc(t.ranking_priority||'STABILITY')+' priority · stability '+n(t.stability_score,1)+'/100 · '+esc(confidence)"
if score_cell_old in js:
    js=replace_once(js,score_cell_old,score_cell_new,"Multi-Trader priority score display")

# Ensure foreground data refreshes while a relevant page is open.
js=js.replace("if(state.view==='history')loadPaths();","if(state.view==='history'){loadTradeBehaviour();loadPaths();}")
js=js.replace("if(state.view==='traders')loadTraders();","if(state.view==='traders')loadTraders();if(state.view==='portfolio-lab')loadPortfolioLab(false);")

auto_timers = r'''
if(!window.__biPortfolioForecastTimer){window.__biPortfolioForecastTimer=window.setInterval(function(){const v=document.getElementById('view-portfolio-lab');if(v&&v.classList.contains('active')&&typeof loadPortfolioLab==='function'){loadPortfolioLab(true).catch(function(e){console.error('Portfolio Lab auto-refresh failed',e)})}},180000)}
if(!window.__biTradeBehaviourTimer){window.__biTradeBehaviourTimer=window.setInterval(function(){const v=document.getElementById('view-history');if(v&&v.classList.contains('active')&&typeof loadTradeBehaviour==='function')loadTradeBehaviour().catch(function(e){console.error('Trade behaviour auto-refresh failed',e)})},60000)}
if(!window.__biMultiTraderTimer){window.__biMultiTraderTimer=window.setInterval(function(){const v=document.getElementById('view-multi-trader');if(v&&v.classList.contains('active')&&typeof loadMultiTrader==='function')loadMultiTrader(false).catch(function(e){console.error('Multi-Trader auto-refresh failed',e)})},60000)}
'''
js += "\n// BI_RESEARCH_PAGE_AUTO_REFRESH_V1\n" + auto_timers + "\n"
js_path.write_text(js)

# ---------------------------------------------------------------------------
# F. Add visible filter controls for Multi-Trader and the behaviour page.
# ---------------------------------------------------------------------------
html=html_path.read_text()
if 'id="mt-min-win-rate"' not in html:
    old_roi = '<label>Minimum recent ROI (%) (30D Spot; 7D Futures)<input id="mt-min-roi7" type="number" min="-100" max="100" value="-5"></label></div>'
    if html.count(old_roi)!=1:
        raise RuntimeError(f"Cannot add rank filters: ROI control anchor count={html.count(old_roi)}")
    new_roi = old_roi + '''
          <div class="field-row"><label>Minimum win rate (%)<input id="mt-min-win-rate" type="number" min="0" max="100" step="1" value="50"></label><label>Evaluation period<select id="mt-period"><option value="7D">7 days</option><option value="30D" selected>30 days</option><option value="90D">90 days</option><option value="365D">365 days</option></select></label></div>
          <div class="field-row"><label>Ranking priority<select id="mt-ranking-priority"><option value="STABILITY" selected>Balanced stability</option><option value="WIN_RATE">Highest win rate</option><option value="LOW_DRAWDOWN">Lowest drawdown</option><option value="PROFIT_FACTOR">Best profit factor</option><option value="PERIOD_ROI">Selected-period ROI</option></select></label></div>'''
    html=html.replace(old_roi,new_roi,1)
html=html.replace('<th>Stability / confidence</th>','<th>Priority score / stability</th>',1)
html=html.replace('Requires fresh source data, enough stored closed trades, and a computable historical profit factor. Futures uses 7D ROI/MDD plus 30D MDD; Spot uses verified 30D ROI/MDD because a 7D Spot period is not verified in this collector. Missing periods are never inferred.',
    'Requires fresh source data, verified win-rate evidence when the win-rate filter is enabled, enough stored closed trades and an estimable profit factor. The selected period drives ROI/MDD screening; the 30D drawdown guard remains active. Spot uses 30D if 7D is requested. Ranking priority changes sorting, never the evidence guardrails.')

js_path.write_text(js)

# Re-cache-bust after ALL JS additions from this patch; the prior cache step runs earlier.
html = html_path.read_text()
version = "bi-" + hashlib.sha256(js.encode("utf-8")).hexdigest()[:12]
cache_pattern = re.compile(
    r'(?P<prefix><script\\b[^>]*\\bsrc\\s*=\\s*)(?P<q>["\\\'])(?P<src>.*?app\\.js.*?)(?:\\?v=[^"\\\']*)?(?P=q)(?P<suffix>[^>]*>)',
    re.IGNORECASE | re.DOTALL
)
cache_matches = list(cache_pattern.finditer(html))
if len(cache_matches) != 1:
    raise RuntimeError(f"Expected exactly one app.js script include for final research-page cache bust; found {len(cache_matches)}")
match = cache_matches[0]
html = html[:match.start()] + match.group("prefix") + match.group("q") + match.group("src") + "?v=" + version + match.group("q") + match.group("suffix") + html[match.end():]
html_path.write_text(html)
print(f"Research ranking/behaviour pages installed. Final JS cache key: {version}")
"""
