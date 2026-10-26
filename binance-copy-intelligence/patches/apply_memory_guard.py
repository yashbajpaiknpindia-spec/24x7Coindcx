from pathlib import Path
import hashlib
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

# The service runs on Render Free (512 MiB). The former Multi-Trader scan loaded
# every Position ORM object twice and scanned all snapshot win-rates into Python
# on each scheduled cycle. That caused repeat OOM restarts and blank/intermittent UI.
app = app_path.read_text()
if "RESOURCE_GUARD_V1" not in app:
    old_collect = '''        tids=[t.id for t in traders]; grouped={i:[] for i in tids}; path_grouped={i:[] for i in tids}
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
'''
    new_collect = '''        tids=[t.id for t in traders]; grouped={i:[] for i in tids}; path_grouped={i:[] for i in tids}
        position_counts={i:0 for i in tids}; closed_counts={i:0 for i in tids}; audit_field_counts={i:0 for i in tids}
        period_counts={7:{},30:{},90:{},365:{}}; event_ranges={}
        if tids:
            # Count full stored history with SQL aggregates; don't load all rows into web-worker memory.
            for _tid,_count in db.execute(select(Position.trader_id,func.count(Position.id)).where(Position.trader_id.in_(tids)).group_by(Position.trader_id)):
                position_counts[_tid]=int(_count or 0)
            _audit_stmt=select(
                Position.trader_id,
                func.count(Position.opened_ms),func.count(Position.closed_ms),
                func.count(Position.entry_price),func.count(Position.exit_price),func.count(Position.close_pnl),
                func.count(Position.id).filter(Position.mae_pct.is_not(None),Position.mfe_pct.is_not(None))
            ).where(Position.trader_id.in_(tids)).group_by(Position.trader_id)
            for _row in db.execute(_audit_stmt):
                audit_field_counts[_row[0]]=sum(int(_n or 0) for _n in _row[1:])
            closed_count_stmt=select(Position.trader_id,func.count(Position.id)).where(
                Position.trader_id.in_(tids),Position.close_pnl.is_not(None),Position.closed_ms.is_not(None))
            if market_type=="SPOT":
                closed_count_stmt=closed_count_stmt.where(Position.source_kind.in_(("PAIRED_SPOT_TRADE","CLOSED_SPOT_TRADE","VERIFIED_SPOT_CLOSED_TRADE")))
            for _tid,_count in db.execute(closed_count_stmt.group_by(Position.trader_id)):
                closed_counts[_tid]=int(_count or 0)
            # Ranking metrics use at most the latest 50 verified closed trades per profile.
            closed_rank_query=select(
                Position.id.label("position_id"),
                func.row_number().over(partition_by=Position.trader_id,order_by=[Position.closed_ms.desc().nullslast(),Position.id.desc()]).label("sample_rank")
            ).where(Position.trader_id.in_(tids),Position.close_pnl.is_not(None),Position.closed_ms.is_not(None))
            if market_type=="SPOT":
                closed_rank_query=closed_rank_query.where(Position.source_kind.in_(("PAIRED_SPOT_TRADE","CLOSED_SPOT_TRADE","VERIFIED_SPOT_CLOSED_TRADE")))
            closed_ranked=closed_rank_query.subquery()
            closed_query=select(Position).join(closed_ranked,Position.id==closed_ranked.c.position_id).where(closed_ranked.c.sample_rank<=50)
            for p in db.scalars(closed_query.order_by(Position.closed_ms.desc().nullslast(),Position.id.desc())):
                grouped.setdefault(p.trader_id,[]).append(p)
            # Only read positions that already have analyzed MAE/MFE. Raw/unpaired activity
            # cannot count as a verified trade path and does not need an ORM object here.
            path_query=select(Position).where(
                Position.trader_id.in_(tids),Position.closed_ms.is_not(None),
                Position.mae_pct.is_not(None),Position.mfe_pct.is_not(None),
                Position.path_status=="ANALYZED"
            )
            if market_type=="SPOT":
                path_query=path_query.where(Position.source_kind.in_(("PAIRED_SPOT_TRADE","CLOSED_SPOT_TRADE","VERIFIED_SPOT_CLOSED_TRADE")))
            for p in db.scalars(path_query.order_by(Position.closed_ms.desc().nullslast(),Position.id.desc())):
                path_grouped.setdefault(p.trader_id,[]).append(p)
            _event_expr=func.coalesce(Position.closed_ms,Position.opened_ms)
            _now_ms=int(__import__("time").time()*1000)
            for _days in (7,30,90,365):
                _cutoff=_now_ms-_days*86400000
                for _tid,_count in db.execute(select(Position.trader_id,func.count(Position.id)).where(
                    Position.trader_id.in_(tids),_event_expr>=_cutoff).group_by(Position.trader_id)):
                    period_counts[_days][_tid]=int(_count or 0)
            for _tid,_omin,_omax,_cmin,_cmax in db.execute(select(
                Position.trader_id,func.min(Position.opened_ms),func.max(Position.opened_ms),
                func.min(Position.closed_ms),func.max(Position.closed_ms)
            ).where(Position.trader_id.in_(tids)).group_by(Position.trader_id)):
                _mins=[v for v in (_omin,_cmin) if v is not None]
                _maxs=[v for v in (_omax,_cmax) if v is not None]
                event_ranges[_tid]=(min(_mins) if _mins else None,max(_maxs) if _maxs else None)
            # One latest non-null source win-rate per profile, computed in PostgreSQL.
            _snapshot_ranked=select(
                pl_Snapshot.trader_id.label("trader_id"),
                pl_Snapshot.win_rate.label("win_rate"),
                func.row_number().over(partition_by=pl_Snapshot.trader_id,
                    order_by=[pl_Snapshot.captured_at.desc().nullslast()]).label("snapshot_rank")
            ).where(pl_Snapshot.trader_id.in_(tids),pl_Snapshot.win_rate.is_not(None)).subquery()
            source_snapshot_wr={_tid:_wr for _tid,_wr in db.execute(select(
                _snapshot_ranked.c.trader_id,_snapshot_ranked.c.win_rate
            ).where(_snapshot_ranked.c.snapshot_rank==1))}
        else:
            source_snapshot_wr={}
'''
    app = replace_once(app, old_collect, new_collect, "memory-bounded multi-trader data collection")

    # The upstream stability patch inserted the Spot-period filter before reasons=[]
    # in _mt_report; that caused an UnboundLocalError on every Spot evaluation.
    early_spot_block = '''            if market_type=="SPOT":
                # Verified Spot source supports 30D/90D/180D/365D, not a verified 7D metric.
                # Evaluate Spot on 30D fields rather than excluding every Spot profile.
                reasons=[r for r in reasons if r not in ("MISSING_SOURCE_7D_ROI","MISSING_SOURCE_7D_MDD","RECENT_ROI_BELOW_FLOOR","7D_MDD_LIMIT_EXCEEDED")]
                if roi30 is None:
                    reasons.append("MISSING_SOURCE_30D_ROI")
                elif roi30 < min_roi_7d:
                    reasons.append("RECENT_30D_ROI_BELOW_FLOOR")
            evidence_gaps=[]
'''
    app = replace_once(app, early_spot_block, "            evidence_gaps=[]\\n", "move Spot criteria after reason initialization")
    spot_reason_anchor = '''            elif pf<min_profit_factor: reasons.append("PROFIT_FACTOR_BELOW_FLOOR")
            score=50+max(-20,min(20,roi7 or 0))*.7+max(-30,min(30,roi30 or 0))*.35+max(-50,min(50,roi90 or 0))*.1
'''
    spot_reason_new = '''            elif pf<min_profit_factor: reasons.append("PROFIT_FACTOR_BELOW_FLOOR")
            # Apply Spot's supported 30-day evidence after reasons has been initialized.
            if market_type=="SPOT":
                reasons=[r for r in reasons if r not in ("MISSING_SOURCE_7D_ROI","MISSING_SOURCE_7D_MDD","RECENT_ROI_BELOW_FLOOR","7D_MDD_LIMIT_EXCEEDED")]
                if roi30 is None:
                    reasons.append("MISSING_SOURCE_30D_ROI")
                elif roi30 < min_roi_7d:
                    reasons.append("RECENT_30D_ROI_BELOW_FLOOR")
            score=50+max(-20,min(20,roi7 or 0))*.7+max(-30,min(30,roi30 or 0))*.35+max(-50,min(50,roi90 or 0))*.1
'''
    app = replace_once(app, spot_reason_anchor, spot_reason_new, "apply Spot screening after reasons initialization")

    audit_old = '''            audit_fields=(
                sum(1 for p in all_positions if p.opened_ms is not None)
                +sum(1 for p in all_positions if p.closed_ms is not None)
                +sum(1 for p in all_positions if p.entry_price is not None)
                +sum(1 for p in all_positions if p.exit_price is not None)
                +sum(1 for p in all_positions if p.close_pnl is not None)
                +sum(1 for p in all_positions if p.mae_pct is not None and p.mfe_pct is not None)
            )
            audit_coverage_pct=(100.0*audit_fields/(6.0*len(all_positions))) if all_positions else None
'''
    audit_new = '''            audit_fields=audit_field_counts.get(t.id,0)
            audit_denominator=6.0*position_counts.get(t.id,0)
            audit_coverage_pct=(100.0*audit_fields/audit_denominator) if audit_denominator else None
'''
    app = replace_once(app, audit_old, audit_new, "calculate audit coverage over full history")

    app = replace_once(
        app,
        '            path_coverage_pct=(100.0*len(path_rows)/len(all_positions)) if all_positions else None',
        '            path_coverage_pct=(100.0*len(path_rows)/position_counts.get(t.id,len(all_positions))) if position_counts.get(t.id,len(all_positions))>0 else None',
        "path coverage denominator"
    )
    app = replace_once(
        app,
        '            history_coverage_pct=(min(100.0,100.0*len(all_positions)/source_total) if source_total and source_total>0 else None)',
        '            history_coverage_pct=(min(100.0,100.0*position_counts.get(t.id,len(all_positions))/source_total) if source_total and source_total>0 else None)',
        "full history coverage denominator"
    )
    old_times = '''            now_ms=int(__import__("time").time()*1000)
            events=[int(p.closed_ms or p.opened_ms) for p in all_positions if p.closed_ms is not None or p.opened_ms is not None]
            trade_count_7d=sum(1 for ts in events if ts>=now_ms-7*86400000)
            trade_count_30d=sum(1 for ts in events if ts>=now_ms-30*86400000)
            trade_count_90d=sum(1 for ts in events if ts>=now_ms-90*86400000)
            trade_count_365d=sum(1 for ts in events if ts>=now_ms-365*86400000)
'''
    new_times = '''            trade_count_7d=period_counts[7].get(t.id,0)
            trade_count_30d=period_counts[30].get(t.id,0)
            trade_count_90d=period_counts[90].get(t.id,0)
            trade_count_365d=period_counts[365].get(t.id,0)
'''
    app = replace_once(app, old_times, new_times, "full position-period counts")
    app = replace_once(
        app,
        '            all_events=[v for p in all_positions for v in (p.opened_ms,p.closed_ms) if v is not None]\n            first_trade_ms=min(all_events) if all_events else None\n            last_trade_ms=max(all_events) if all_events else None',
        '            first_trade_ms,last_trade_ms=event_ranges.get(t.id,(None,None))',
        "full stored-history date range"
    )
    app = replace_once(
        app,
        '"stored_positions":len(all_positions),"source_total_positions":t.total_positions,"history_coverage_pct":history_coverage_pct,"audit_field_coverage_pct":audit_coverage_pct,',
        '"stored_positions":position_counts.get(t.id,len(all_positions)),"sampled_path_positions":len(all_positions),"source_total_positions":t.total_positions,"history_coverage_pct":history_coverage_pct,"audit_field_coverage_pct":audit_coverage_pct,',
        "exact stored-position count"
    )
    app = replace_once(
        app,
        '"stored_closed_trades":len(closed)',
        '"stored_closed_trades":closed_counts.get(t.id,len(closed)),"sampled_closed_trades":len(closed),"closed_trade_sample_limit":50',
        "sample versus total closed-trade count"
    )

    # Automatic full Multi-Trader evaluation after every scheduled path batch was
    # redundant and caused OOMs. The page can request the now-bounded evaluation on demand.
    auto_eval = '''                for mt in ("FUTURES", "SPOT"):
                    try: _persist_mt_report(_mt_report(mt), "AUTOMATIC")
                    except Exception as exc:
                        with SessionLocal() as db:
                            db.add(ScanRun(kind="MULTI_TRADER_EVALUATION",market_type=mt,status="FAILED",started_at=utcnow(),finished_at=utcnow(),error_count=1,message=f"Automatic evaluation failed: {str(exc)[:500]}")); db.commit()
'''
    if app.count(auto_eval) == 1:
        app = app.replace(auto_eval, '                # Multi-Trader evaluation is user-triggered; avoid duplicating the full scan in the monitor loop.\n', 1)
    elif app.count('RESOURCE_GUARD_V1') == 0:
        raise RuntimeError("Cannot remove automatic full-history Multi-Trader evaluations safely")

    app = app.replace(
        '"This mode does not place, copy, amend or close real orders. Allocations are illustrative paper weights."',
        '"This mode does not place, copy, amend or close real orders. Allocations are illustrative paper weights.","Stability uses up to the latest 50 verified closed trades per profile; MAE/MFE uses all stored analyzed paths. Counts and history dates are full database aggregates."',
        1
    )
    app += "\n# RESOURCE_GUARD_V1\n"
    app_path.write_text(app)

# Label win-rate and PnL sample sizes honestly in the Multi-Trader table.
js = js_path.read_text()
js = js.replace(
    "'<small>Closed PnL '+closedWR+' ('+n(t.stored_closed_trades,0)+' records)</small>'",
    "'<small>Closed PnL '+closedWR+' (latest '+n(t.sampled_closed_trades,0)+' of '+n(t.stored_closed_trades,0)+' total)</small>'",
    1
)
js = js.replace(
    "Rows with weak path coverage show that limitation rather than receiving invented MAE/MFE. Stability is evidence-weighted, not a guaranteed future result.",
    "Closed-trade win rate/PF use up to the latest 50 verified closes per profile; exact stored counts and period counts come from database aggregates. Weak path coverage remains visible. Stability is evidence-weighted, not a guaranteed future result.",
    1
)
js_path.write_text(js)

# Re-cache-bust the final JS after all edits in this patch.
html = html_path.read_text()
version = "bi-" + hashlib.sha256(js.encode("utf-8")).hexdigest()[:12]
cache_pattern = re.compile(
    r'(?P<prefix><script\b[^>]*\bsrc\s*=\s*)(?P<q>["\'])(?P<src>.*?app\.js.*?)(?:\?v=[^"\']*)?(?P=q)(?P<suffix>[^>]*>)',
    re.IGNORECASE | re.DOTALL
)
matches = list(cache_pattern.finditer(html))
if len(matches) != 1:
    raise RuntimeError(f"Expected one app.js script include after memory guard; found {len(matches)}")
m = matches[0]
html = html[:m.start()] + m.group("prefix") + m.group("q") + m.group("src") + "?v=" + version + m.group("q") + m.group("suffix") + html[m.end():]
html_path.write_text(html)
print(f"Memory guard installed: bounded Multi-Trader queries, full SQL aggregate counts, manual-only evaluations, JS cache key={version}")
