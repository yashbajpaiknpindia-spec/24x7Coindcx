from pathlib import Path

p=Path("/app/app.py")
s=p.read_text()
marker="COPIER_FORECAST_ELIGIBILITY_GATE_V1"
if marker not in s:
    start=s.find("def pl_forecast():")
    end=s.find("\n# COPIER_SAFETY_RANKING_V1", start)
    if start < 0 or end < 0:
        raise RuntimeError("Cannot locate Portfolio Lab forecast or copier-safety helper")
    fn=s[start:end]

    anchor="        rows=[]\n        for t in traders:"
    if fn.count(anchor)!=1:
        raise RuntimeError("Portfolio Lab forecast rows anchor not unique: "+str(fn.count(anchor)))
    fn=fn.replace(anchor,"        copier_metrics_by_id = _bi_copier_metrics(db, traders)\n"+anchor,1)

    anchor="            hist=[p for p in grouped.get(t.id,[]) if p.opened_ms is not None and p.closed_ms is not None and p.roi_pct is not None]\n"
    if fn.count(anchor)!=1:
        raise RuntimeError("Portfolio Lab history anchor not unique: "+str(fn.count(anchor)))
    fn=fn.replace(anchor,anchor+"            copier_safety = copier_metrics_by_id.get(t.id, {})\n",1)

    anchor="            ready=len(hist)>=15 and active>=10 and len(daily)>=10\n"
    if fn.count(anchor)!=1:
        raise RuntimeError("Portfolio Lab readiness anchor not unique: "+str(fn.count(anchor)))
    fn=fn.replace(anchor,"            ready=len(hist)>=15 and active>=10 and len(daily)>=10 and bool(copier_safety.get('copy_eligible'))\n",1)

    anchor="'forecast_status':'READY' if ready else 'INSUFFICIENT_HISTORY',"
    if fn.count(anchor)!=1:
        raise RuntimeError("Portfolio Lab forecast status anchor not unique: "+str(fn.count(anchor)))
    fn=fn.replace(anchor,"'forecast_status':'READY' if ready else ('BLOCKED_COPIER_RISK' if not copier_safety.get('copy_eligible') else 'INSUFFICIENT_HISTORY'),",1)

    anchor="'last_seen':t.last_seen.isoformat() if t.last_seen else None,'forecast_status':"
    if fn.count(anchor)!=1:
        raise RuntimeError("Portfolio Lab forecast row field anchor not unique: "+str(fn.count(anchor)))
    fn=fn.replace(anchor,"'last_seen':t.last_seen.isoformat() if t.last_seen else None,'copier_pnl_30d':copier_safety.get('copier_pnl_30d'),'copier_pnl_90d':copier_safety.get('copier_pnl_90d'),'track_record_days':copier_safety.get('track_record_days'),'copier_pnl_score':copier_safety.get('copier_pnl_score'),'duration_score':copier_safety.get('duration_score'),'copier_duration_score':copier_safety.get('copier_duration_score'),'copy_eligible':bool(copier_safety.get('copy_eligible')),'copier_safety_reasons':copier_safety.get('copier_safety_reasons',[]),'forecast_status':",1)

    anchor="'evidence_gap':None if ready else 'Need 15 recent usable trades and at least 10 non-zero close days across at least 10 daily observations.'"
    if fn.count(anchor)!=1:
        raise RuntimeError("Portfolio Lab evidence-gap anchor not unique: "+str(fn.count(anchor)))
    fn=fn.replace(anchor,"'evidence_gap':None if ready else (('Copier safety gate: '+', '.join(copier_safety.get('copier_safety_reasons',[]))) if not copier_safety.get('copy_eligible') else 'Need 15 recent usable trades and at least 10 non-zero close days across at least 10 daily observations.')",1)

    s=s[:start]+fn+s[end:]
    s += "\n# "+marker+"\n"
    p.write_text(s)
print("Portfolio Lab forecasts now require fresh nonnegative copier PnL for 30D and 90D plus the minimum source track record.")
