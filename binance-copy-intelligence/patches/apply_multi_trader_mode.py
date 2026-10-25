from pathlib import Path
import json

root = Path("/app")

def patch(path, old, new, label):
    s = path.read_text()
    if new in s:
        return
    if s.count(old) != 1:
        raise RuntimeError(f"Cannot patch {label}: anchor count={s.count(old)}")
    path.write_text(s.replace(old, new, 1))

# Dedicated navigation and page.
html = root / "templates" / "index.html"
patch(html,
'    <button class="nav-link" data-view="traders"><span class="nav-ico">◎</span> Trader universe</button>\n',
'    <button class="nav-link" data-view="traders"><span class="nav-ico">◎</span> Trader universe</button>\n    <button class="nav-link" data-view="multi-trader"><span class="nav-ico">⇄</span> Multi-Trader Mode</button>\n',
"navigation")
page = '''    <section class="view" id="view-multi-trader">
      <div class="section-heading"><div><div class="eyebrow">PORTFOLIO SELECTION & RISK CONTROL</div><h2>Multi-Trader Mode</h2><p>Evaluate every discovered portfolio, screen deteriorating behaviour, and build a diversified paper shortlist.</p></div><span class="tag blue">PAPER ONLY · NO ORDERS</span></div>
      <div class="kpi-grid">
        <article class="kpi-card"><div class="kpi-head"><span>Portfolios evaluated</span></div><div class="kpi-value" id="mt-total">—</div><div class="kpi-foot">Stored profiles in selected market</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Passed risk filters</span></div><div class="kpi-value" id="mt-eligible">—</div><div class="kpi-foot">Not a guarantee of profit</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Blocked / incomplete</span></div><div class="kpi-value" id="mt-blocked">—</div><div class="kpi-foot">Reasons recorded per portfolio</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Selected shortlist</span></div><div class="kpi-value" id="mt-selected-count">—</div><div class="kpi-foot">Multiple portfolios, overlap-aware</div></article>
      </div>
      <div class="content-grid two-col">
        <article class="panel"><div class="panel-header"><div><div class="eyebrow">RISK POLICY</div><h3>Selection thresholds</h3></div><span class="tag purple">CONFIGURABLE</span></div>
          <div class="field-row"><label>Market<select id="mt-market"><option value="FUTURES">Futures</option><option value="SPOT">Spot</option></select></label><label>Shortlist size<select id="mt-max-selected"><option>3</option><option selected>5</option><option>8</option><option>10</option></select></label></div>
          <div class="field-row"><label>Minimum stored closed trades<input id="mt-min-trades" type="number" min="1" max="500" value="10"></label><label>Minimum profit factor<input id="mt-min-pf" type="number" min="0.5" max="10" step="0.1" value="1.2"></label></div>
          <div class="field-row"><label>Maximum 7D/30D MDD (%)<input id="mt-max-mdd" type="number" min="1" max="100" value="20"></label><label>Minimum 7D ROI (%)<input id="mt-min-roi7" type="number" min="-100" max="100" value="-5"></label></div>
          <div class="button-row"><button id="mt-evaluate" class="btn primary">▶ Evaluate & save snapshot</button><button id="mt-refresh" class="btn secondary">↻ Refresh analysis</button></div>
          <p class="help-text">Requires recent data, source-reported 7D ROI and 7D/30D MDD, enough stored closed trades, and a computable historical profit factor. Missing periods are never inferred.</p>
        </article>
        <article class="panel"><div class="panel-header"><div><div class="eyebrow">GUARDRAILS</div><h3>What this mode does</h3></div><span class="tag blue">SIMULATION ONLY</span></div>
          <div class="metric-explain"><div><b>Deterioration filter</b><p>Recent loss or drawdown can block new-copy eligibility even when older PnL is strong.</p></div><div><b>Trade-behaviour analysis</b><p>Calculates win/loss distribution, net recorded PnL and profit factor from stored closed positions. Incomplete history remains visible.</p></div><div><b>Multi-trader diversification</b><p>Penalises overlap in historically traded symbols. This is a proxy, not proof of current exposure diversification.</p></div><div><b>Safe exit limits</b><p>Public profile data is not a guaranteed live signal feed. This page places no order and cannot guarantee profit or exact exit prices.</p></div></div>
        </article>
      </div>
      <article class="panel"><div class="panel-header"><div><div class="eyebrow">CURRENT SHORTLIST</div><h3>Selected paper portfolios</h3></div><span class="tag green" id="mt-asof">Not evaluated yet</span></div><div id="mt-picked" class="run-list"><div class="empty-state">Run an evaluation to build the shortlist.</div></div><div id="mt-note" class="notice-box">Only profiles already discovered or added to the database can be evaluated. Run profile discovery first if this is empty.</div></article>
      <article class="panel table-panel"><div class="panel-header"><div><div class="eyebrow">EVERY STORED PORTFOLIO</div><h3>Per-portfolio decision and evidence</h3></div><span class="tag gray" id="mt-table-meta">Stored data only</span></div><div class="table-scroll"><table><thead><tr><th>Portfolio</th><th>Score</th><th>ROI 7D</th><th>ROI 30D</th><th>ROI 90D</th><th>MDD 7D</th><th>MDD 30D</th><th>MDD 365D</th><th>Closed trades</th><th>PF</th><th>Decision</th><th>Block reasons / evidence gaps</th><th>Paper allocation</th><th>Inspect</th></tr></thead><tbody id="mt-rows"><tr><td colspan="14" class="empty-state">No evaluation yet.</td></tr></tbody></table></div></article>
      <article class="panel table-panel"><div class="panel-header"><div><div class="eyebrow">PERSISTED DECISIONS</div><h3>Evaluation history</h3></div><span class="tag gray">Last 20 snapshots</span></div><div class="table-scroll"><table><thead><tr><th>Evaluated at (UTC)</th><th>Market</th><th>Profiles</th><th>Eligible</th><th>Blocked</th><th>Selected</th><th>Trigger</th><th>Summary</th></tr></thead><tbody id="mt-history"><tr><td colspan="8" class="empty-state">No saved evaluations yet.</td></tr></tbody></table></div></article>
    </section>

'''
patch(html, '    <section class="view" id="view-reports">\n', page + '    <section class="view" id="view-reports">\n', "page section")

# Store decisions in the existing ScanRun table; no new database migration is needed.
app = root / "app.py"
backend = '''

def _mt_num(value):
    try:
        if value in (None, ""): return None
        x=float(value)
        return x if __import__("math").isfinite(x) else None
    except (TypeError, ValueError, OverflowError): return None

def _mt_report(market_type="FUTURES", min_closed_trades=10, min_profit_factor=1.2, max_mdd_pct=20, min_roi_7d=-5, max_selected=5):
    market_type=(market_type or "FUTURES").upper()
    if market_type not in ("FUTURES","SPOT"): raise ValueError("market_type must be FUTURES or SPOT")
    min_closed_trades=max(1,min(int(min_closed_trades),500)); min_profit_factor=max(.5,min(float(min_profit_factor),10))
    max_mdd_pct=max(1,min(float(max_mdd_pct),100)); min_roi_7d=max(-100,min(float(min_roi_7d),100)); max_selected=max(1,min(int(max_selected),10))
    with SessionLocal() as db:
        traders=list(db.scalars(select(Trader).where(Trader.exchange=="BINANCE",Trader.market_type==market_type).order_by(Trader.last_seen.desc().nullslast(),Trader.id.asc())))
        tids=[t.id for t in traders]; grouped={i:[] for i in tids}
        if tids:
            for p in db.scalars(select(Position).where(Position.trader_id.in_(tids),Position.close_pnl.is_not(None)).order_by(Position.closed_ms.desc().nullslast(),Position.id.desc())):
                grouped.setdefault(p.trader_id,[]).append(p)
        now=utcnow(); rows=[]
        for t in traders:
            try: periods=json.loads(t.period_metrics or "{}")
            except Exception: periods={}
            def pm(period,metric):
                group=periods.get(period,{}) if isinstance(periods,dict) else {}
                return _mt_num(group.get(metric)) if isinstance(group,dict) else None
            roi7,roi30,roi90,roi365=[pm(k,"roi") for k in ("7D","30D","90D","365D")]
            mdd7,mdd30,mdd365=[pm(k,"mdd") for k in ("7D","30D","365D")]
            closed=grouped.get(t.id,[]); stats=trade_statistics(closed); pf=_mt_num(stats.get("profit_factor"))
            seen=t.last_seen
            if seen and getattr(seen,"tzinfo",None) is not None: seen=seen.replace(tzinfo=None)
            age=(now-seen).total_seconds()/86400 if seen else None; reasons=[]
            if age is None or age>7: reasons.append("STALE_PROFILE_OVER_7_DAYS")
            if roi7 is None: reasons.append("MISSING_SOURCE_7D_ROI")
            if mdd7 is None: reasons.append("MISSING_SOURCE_7D_MDD")
            if mdd30 is None: reasons.append("MISSING_SOURCE_30D_MDD")
            if roi7 is not None and roi7<min_roi_7d: reasons.append("RECENT_ROI_BELOW_FLOOR")
            if mdd7 is not None and abs(mdd7)>max_mdd_pct: reasons.append("7D_MDD_LIMIT_EXCEEDED")
            if mdd30 is not None and abs(mdd30)>max_mdd_pct: reasons.append("30D_MDD_LIMIT_EXCEEDED")
            if len(closed)<min_closed_trades: reasons.append("INSUFFICIENT_STORED_CLOSED_TRADES")
            if pf is None: reasons.append("PROFIT_FACTOR_NOT_ESTIMABLE_FROM_STORED_TRADES")
            elif pf<min_profit_factor: reasons.append("PROFIT_FACTOR_BELOW_FLOOR")
            score=50+max(-20,min(20,roi7 or 0))*.7+max(-30,min(30,roi30 or 0))*.35+max(-50,min(50,roi90 or 0))*.1
            score+=(min(pf,3)-1)*10 if pf is not None else -12
            score-=abs(mdd30)*.45 if mdd30 is not None else 15
            symbols=[]
            for p in closed[:60]:
                if p.symbol and p.symbol not in symbols: symbols.append(p.symbol)
            rows.append({"id":t.id,"nickname":t.nickname,"portfolio_id":t.portfolio_id,"profile_url":t.profile_url,"market_type":t.market_type,
                "last_seen":_iso(t.last_seen),"age_days":round(age,2) if age is not None else None,"roi_7d":roi7,"roi_30d":roi30,"roi_90d":roi90,"roi_365d":roi365,
                "mdd_7d":mdd7,"mdd_30d":mdd30,"mdd_365d":mdd365,"stored_closed_trades":len(closed),"source_total_positions":t.total_positions,
                "profit_factor":pf,"win_rate_pct":stats.get("win_rate_pct"),"net_realized_pnl":stats.get("net_realized_pnl"),
                "average_win":stats.get("average_win"),"average_loss":stats.get("average_loss"),"stored_path_coverage_pct":stats.get("path_coverage_pct"),
                "symbols":symbols,"score":round(max(0,min(100,score)),2),"eligible":not reasons,"reasons":reasons,"selected":False,"allocation_pct":0})
    rows.sort(key=lambda x:(x["eligible"],x["score"],x["stored_closed_trades"]),reverse=True)
    eligible=[x for x in rows if x["eligible"]]; chosen=[]
    while eligible and len(chosen)<max_selected:
        best=None; best_score=-1e9
        for x in eligible:
            syms=set(x["symbols"]); overlap=0
            for y in chosen:
                ys=set(y["symbols"]); overlap=max(overlap,len(syms & ys)/len(syms | ys) if syms or ys else 0)
            adjusted=x["score"]-overlap*18
            if adjusted>best_score: best,best_score=x,adjusted
        if best is None: break
        best["selected"]=True; best["selection_reason"]="Score penalised for historical-symbol overlap" if chosen else "Top eligible risk-screen score"; chosen.append(best); eligible.remove(best)
    if chosen:
        weights={x["id"]:max(1,x["score"])/max(5,abs(x["mdd_30d"] or max_mdd_pct)) for x in chosen}
        total=sum(weights.values()) or 1
        for x in chosen: x["allocation_pct"]=round(min(35,100*weights[x["id"]]/total),2)
    ids={x["id"] for x in chosen}
    for x in rows:
        x["decision"]="SELECTED_FOR_PAPER_MODE" if x["id"] in ids else ("ELIGIBLE_NOT_SELECTED" if x["eligible"] else "BLOCKED")
        if x["eligible"] and not x["selected"]: x["selection_reason"]="Eligible but not selected within shortlist size"
    return {"mode":"PAPER_ONLY_NO_ORDERS","market_type":market_type,"evaluated_at_utc":utcnow().isoformat()+"Z",
        "monitored_count":len(rows),"eligible_count":sum(x["eligible"] for x in rows),"blocked_count":sum(not x["eligible"] for x in rows),
        "selected_count":len(chosen),"selected_portfolios":[{k:x.get(k) for k in ("id","nickname","portfolio_id","profile_url","score","allocation_pct","mdd_30d","profit_factor","stored_closed_trades","symbols","selection_reason")} for x in chosen],
        "candidates":rows[:1000],"candidate_rows_returned":min(1000,len(rows)),"candidates_omitted_from_response":max(0,len(rows)-1000),
        "settings":{"min_closed_trades":min_closed_trades,"min_profit_factor":min_profit_factor,"max_mdd_pct":max_mdd_pct,"min_roi_7d":min_roi_7d,"max_selected":max_selected},
        "limitations":["Only discovered/manual database profiles are evaluated, not a proven complete Binance universe.","Stored public profile data is not a guaranteed real-time lead-trader order feed.","Trade-history PF uses stored closed positions and is not adjusted for your fills, fees, slippage or funding.","Symbol overlap uses historical closed positions; current open exposure may be unavailable.","This mode does not place, copy, amend or close real orders. Allocations are illustrative paper weights."]}

def _persist_mt_report(report, trigger="MANUAL"):
    with SessionLocal() as db:
        now=utcnow()
        run=ScanRun(kind="MULTI_TRADER_EVALUATION",market_type=report["market_type"],status="COMPLETED",started_at=now,finished_at=now,
            found_count=report["monitored_count"],updated_count=report["eligible_count"],error_count=report["blocked_count"],
            message=f"{trigger} paper-only evaluation: {report['selected_count']} selected from {report['monitored_count']} stored profiles; {report['blocked_count']} blocked/incomplete.",
            details_json=json.dumps({**report,"trigger":trigger},ensure_ascii=False,default=str))
        db.add(run); db.commit(); db.refresh(run); rid=run.id
        for old in db.scalars(select(ScanRun).where(ScanRun.kind=="MULTI_TRADER_EVALUATION").order_by(ScanRun.id.desc()).offset(40)): db.delete(old)
        db.commit()
    return rid

@app.get("/api/multi-trader/candidates")
def api_multi_trader_candidates():
    try: return jsonify(_mt_report(request.args.get("market_type","FUTURES"),request.args.get("min_closed_trades",10),request.args.get("min_profit_factor",1.2),request.args.get("max_mdd_pct",20),request.args.get("min_roi_7d",-5),request.args.get("max_selected",5)))
    except Exception as exc: return jsonify({"error":str(exc)}),400

@app.post("/api/multi-trader/evaluate")
def api_multi_trader_evaluate():
    data=request.get_json(silent=True) or {}
    try:
        report=_mt_report(data.get("market_type","FUTURES"),data.get("min_closed_trades",10),data.get("min_profit_factor",1.2),data.get("max_mdd_pct",20),data.get("min_roi_7d",-5),data.get("max_selected",5))
        report["evaluation_id"]=_persist_mt_report(report,"MANUAL")
        return jsonify(report)
    except Exception as exc: return jsonify({"error":str(exc)}),400

@app.get("/api/multi-trader/history")
def api_multi_trader_history():
    with SessionLocal() as db: runs=list(db.scalars(select(ScanRun).where(ScanRun.kind=="MULTI_TRADER_EVALUATION").order_by(ScanRun.id.desc()).limit(20)))
    out=[]
    for r in runs:
        try: d=json.loads(r.details_json or "{}")
        except Exception: d={}
        out.append({"id":r.id,"started_at":_iso(r.started_at),"market_type":r.market_type,"status":r.status,"found_count":r.found_count,
            "eligible_count":r.updated_count,"blocked_count":r.error_count,"selected_count":d.get("selected_count",0),"trigger":d.get("trigger","UNKNOWN"),"message":r.message})
    return jsonify({"items":out,"count":len(out)})

'''
patch(app, 'def _run_scheduled_task(kind, market_type, target, args):\n', backend + 'def _run_scheduled_task(kind, market_type, target, args):\n', "backend")
patch(app,
'                _run_scheduled_task("PATH_ANALYSIS","SPOT",run_path_batch,(None,max(1,min(int(os.getenv("SCHEDULED_PATH_BATCH","10")),25)),True,"SPOT"))\n            else:',
'                _run_scheduled_task("PATH_ANALYSIS","SPOT",run_path_batch,(None,max(1,min(int(os.getenv("SCHEDULED_PATH_BATCH","10")),25)),True,"SPOT"))\n                for mt in ("FUTURES", "SPOT"):\n                    try: _persist_mt_report(_mt_report(mt), "AUTOMATIC")\n                    except Exception as exc:\n                        with SessionLocal() as db:\n                            db.add(ScanRun(kind="MULTI_TRADER_EVALUATION",market_type=mt,status="FAILED",started_at=utcnow(),finished_at=utcnow(),error_count=1,message=f"Automatic evaluation failed: {str(exc)[:500]}")); db.commit()\n            else:',
"automatic evaluation")

js = root / "static" / "app.js"
patch(js,
"const titles={overview:'Overview',traders:'Trader universe',history:'Trade behaviour',reports:'Reports & exports',data:'Data import',system:'Source & system'};$('#page-title').textContent=titles[name]||name;if(name==='traders')loadTraders();if(name==='history')loadPaths();if(name==='system')loadSystem();",
"const titles={overview:'Overview',traders:'Trader universe','multi-trader':'Multi-Trader Mode',history:'Trade behaviour',reports:'Reports & exports',data:'Data import',system:'Source & system'};$('#page-title').textContent=titles[name]||name;if(name==='traders')loadTraders();if(name==='multi-trader')loadMultiTrader(false);if(name==='history')loadPaths();if(name==='system')loadSystem();",
"view router")
code = '''
function mtFilters(){const v=(id,def)=>{const raw=$(id).value;const x=Number(raw);return raw!==""&&Number.isFinite(x)?x:def};return {market_type:$("#mt-market").value,max_selected:v("#mt-max-selected",5),min_closed_trades:v("#mt-min-trades",10),min_profit_factor:v("#mt-min-pf",1.2),max_mdd_pct:v("#mt-max-mdd",20),min_roi_7d:v("#mt-min-roi7",-5)}}
function mtQuery(){return new URLSearchParams(mtFilters()).toString()}
function renderMT(d){
 $("#mt-total").textContent=n(d.monitored_count,0);$("#mt-eligible").textContent=n(d.eligible_count,0);$("#mt-blocked").textContent=n(d.blocked_count,0);$("#mt-selected-count").textContent=n(d.selected_count,0);
 $("#mt-asof").textContent="As of "+(d.evaluated_at_utc||"unknown")+(d.evaluation_id?" · saved #"+d.evaluation_id:"");
 $("#mt-table-meta").textContent=n(d.candidate_rows_returned,0)+" shown"+(d.candidates_omitted_from_response?" · "+d.candidates_omitted_from_response+" omitted from table":"");
 $("#mt-note").textContent=(d.monitored_count===0?"No profiles found for this market. Run discovery first. ":d.selected_count+" selected for PAPER MODE; "+d.blocked_count+" blocked/incomplete. ")+"Missing source periods are not inferred. This is not live copying or a guarantee of profit.";
 const picked=d.selected_portfolios||[];$("#mt-picked").innerHTML=picked.length?picked.map(t=>'<div class="run-item"><div><div class="run-title">'+esc(t.nickname||t.portfolio_id)+' · score '+n(t.score,1)+'</div><div class="run-sub">'+esc(t.portfolio_id)+' · paper weight '+n(t.allocation_pct,1,'%')+' · PF '+n(t.profit_factor,2)+' · 30D MDD '+n(t.mdd_30d,2,'%')+'</div><div class="run-sub">'+esc(t.selection_reason||"Selected by risk screen")+'</div></div><span class="run-badge completed">PAPER ONLY</span></div>').join(""):'<div class="empty-state">No portfolio passed every filter. Missing or inadequate data is not treated as a pass.</div>';
 const rows=d.candidates||[];$("#mt-rows").innerHTML=rows.length?rows.map(t=>{const reason=(t.reasons||[]).join("; ")||t.selection_reason||"No block reasons";return '<tr><td><strong>'+esc(t.nickname||"Unknown")+'</strong><small style="display:block;color:#8c98a8">'+esc(t.market_type)+' · '+esc(t.portfolio_id)+'</small></td><td>'+n(t.score,1)+'</td><td class="'+colorNum(t.roi_7d)+'">'+n(t.roi_7d,2,'%')+'</td><td class="'+colorNum(t.roi_30d)+'">'+n(t.roi_30d,2,'%')+'</td><td class="'+colorNum(t.roi_90d)+'">'+n(t.roi_90d,2,'%')+'</td><td>'+n(t.mdd_7d,2,'%')+'</td><td>'+n(t.mdd_30d,2,'%')+'</td><td>'+n(t.mdd_365d,2,'%')+'</td><td>'+n(t.stored_closed_trades,0)+'</td><td>'+n(t.profit_factor,2)+'</td><td><span class="status-chip">'+esc(t.decision)+'</span></td><td style="white-space:normal;min-width:210px">'+esc(reason)+'</td><td>'+(t.selected?n(t.allocation_pct,1,'%'):"—")+'</td><td><button class="icon-button" data-mt-inspect="'+Number(t.id)+'">Inspect</button></td></tr>'}).join(""):'<tr><td colspan="14" class="empty-state">No candidates. Run discovery first or check source health.</td></tr>';
 $$("[data-mt-inspect]").forEach(b=>b.addEventListener("click",()=>{view("traders");openTrader(Number(b.dataset.mtInspect))}));
}
async function loadMTHistory(){try{const d=await api("/api/multi-trader/history");const rows=d.items||[];$("#mt-history").innerHTML=rows.length?rows.map(r=>'<tr><td>'+esc(r.started_at||"—")+'</td><td>'+esc(r.market_type||"—")+'</td><td>'+n(r.found_count,0)+'</td><td>'+n(r.eligible_count,0)+'</td><td>'+n(r.blocked_count,0)+'</td><td>'+n(r.selected_count,0)+'</td><td>'+esc(r.trigger||"—")+'</td><td style="white-space:normal">'+esc(r.message||"")+'</td></tr>').join(""):'<tr><td colspan="8" class="empty-state">No saved evaluations yet.</td></tr>'}catch(e){$("#mt-history").innerHTML='<tr><td colspan="8" class="empty-state">'+esc(e.message)+'</td></tr>'}}
async function loadMultiTrader(persist){try{const d=persist?await api("/api/multi-trader/evaluate",{method:"POST",body:JSON.stringify(mtFilters())}):await api("/api/multi-trader/candidates?"+mtQuery());renderMT(d);await loadMTHistory();if(persist)toast("Evaluation saved #"+d.evaluation_id+": "+d.selected_count+" selected; "+d.blocked_count+" blocked/incomplete.","success")}catch(e){$("#mt-note").textContent="Analysis failed: "+e.message;toast("Multi-Trader analysis failed: "+e.message,"error")}}
$("#mt-evaluate").addEventListener("click",()=>loadMultiTrader(true));$("#mt-refresh").addEventListener("click",()=>loadMultiTrader(false));$("#mt-market").addEventListener("change",()=>loadMultiTrader(false));
'''
patch(js, 'async function loadSystem(){', code + '\nasync function loadSystem(){', "client controls")
s=js.read_text()
s=s.replace("state.refreshTimer=setInterval(()=>{refreshStatus();loadRunsOnly();if(state.view==='traders')loadTraders();if(state.view==='history')loadPaths();},8000)", "state.refreshTimer=setInterval(()=>{refreshStatus();loadRunsOnly();if(state.view==='multi-trader')loadMultiTrader(false);if(state.view==='traders')loadTraders();if(state.view==='history')loadPaths();},30000)")
s=s.replace("state.refreshTimer=setInterval(()=>{refreshStatus();loadRunsOnly();},30000)", "state.refreshTimer=setInterval(()=>{refreshStatus();loadRunsOnly();if(state.view===\'multi-trader\')loadMultiTrader(false);},30000)")
js.write_text(s)
print("Multi-Trader Mode installed")


# Rebrand the sign-in screen to match the reference layout while keeping the new Binance app identity.
login = root / "templates" / "login.html"
login.write_text(r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · Binance Copy Intelligence</title>
<style>
:root{color-scheme:dark;--bg:#080d14;--panel:#111a25;--muted:#91a0b4;--line:#273546;--green:#62e4b3;--blue:#7cb8ff;--text:#edf3fa}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 15% 10%,#162a39 0,transparent 45%),linear-gradient(135deg,#080d14,#0b111a 55%,#0c1720);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.shell{min-height:100vh;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(360px,.8fr);max-width:1440px;margin:auto;padding:42px;gap:44px;align-items:stretch}
.hero{display:flex;flex-direction:column;position:relative;overflow:hidden;border:1px solid #273847;border-radius:28px;padding:36px;background:linear-gradient(145deg,rgba(22,40,54,.92),rgba(10,19,29,.76));min-height:680px}
.brand{display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:.09em;font-size:14px}.mark{display:grid;place-items:center;width:44px;height:44px;border-radius:14px;background:linear-gradient(145deg,#70f0c2,#72b9ff);color:#06111a;font-size:15px;font-weight:900;letter-spacing:-.04em;box-shadow:0 0 28px #62e4b328}.brand small{display:block;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.19em;margin-top:3px}
.hero-copy{position:relative;z-index:1;margin-top:95px;max-width:670px}.eyebrow{font-size:11px;font-weight:800;letter-spacing:.2em;color:var(--green)}h1{font-size:clamp(39px,4.5vw,66px);line-height:1.05;letter-spacing:-.055em;margin:18px 0 20px;font-weight:800}h1 em{font-style:normal;color:var(--green)}.hero-copy p{font-size:16px;line-height:1.75;color:#b8c6d5;max-width:560px}
.chart{width:110%;height:200px;margin:48px -5% 0;opacity:.9}.chart path{fill:none;stroke:var(--green);stroke-width:2.4;filter:drop-shadow(0 0 7px #62e4b330)}.chart .grid{stroke:#2e4553;stroke-width:1;opacity:.55;filter:none}
.badges{display:flex;gap:10px;flex-wrap:wrap;margin-top:auto;padding-top:22px}.badge{border:1px solid #314655;background:#0c1721a8;padding:9px 12px;border-radius:999px;color:#c2d2df;font-size:12px}.badge b{color:var(--green);margin-right:7px}
.form-side{display:flex;align-items:center;justify-content:center}.card{width:min(100%,440px);padding:36px;border:1px solid var(--line);border-radius:26px;background:rgba(15,23,34,.94);box-shadow:0 25px 80px #0005}.mobile-brand{display:none}.card .eyebrow{color:var(--blue)}h2{font-size:29px;letter-spacing:-.04em;margin:12px 0 10px}.sub{color:var(--muted);line-height:1.65;margin:0 0 28px;font-size:14px}label{display:block;color:#c8d4e0;font-size:12px;font-weight:700;margin:0 0 9px}input{width:100%;border:1px solid #324355;border-radius:12px;background:#09111a;color:#eef5fb;padding:15px 14px;font-size:15px;outline:none}input:focus{border-color:#74bbff;box-shadow:0 0 0 3px #74bbff18}.primary{border:0;width:100%;border-radius:12px;margin-top:15px;padding:15px 18px;font-weight:800;color:#07131c;background:linear-gradient(90deg,#63e5b5,#82c9ff);font-size:14px;cursor:pointer}.primary:hover{filter:brightness(1.06)}.error{border:1px solid #723d50;background:#331e2b;color:#ffb6c7;border-radius:12px;padding:12px 14px;margin-bottom:16px;font-size:13px}.security{display:flex;gap:10px;align-items:flex-start;color:var(--muted);font-size:12px;line-height:1.6;margin-top:24px;padding-top:18px;border-top:1px solid #263341}.dot{flex:0 0 8px;width:8px;height:8px;border-radius:50%;background:var(--green);margin-top:5px;box-shadow:0 0 12px #62e4b355}.footer{color:#617387;text-align:center;font-size:11px;margin-top:22px;line-height:1.7}
@media(max-width:850px){.shell{grid-template-columns:1fr;padding:16px;gap:18px}.hero{min-height:unset;padding:24px;border-radius:22px}.hero-copy{margin-top:44px}h1{font-size:40px}.chart{height:110px;margin-top:14px}.badges{margin-top:14px}.form-side{padding:8px 0 22px}.card{padding:27px;border-radius:22px}.mobile-brand{display:flex;margin-bottom:26px}.hero-copy p{font-size:14px}}
@media(max-width:420px){.shell{padding:10px}.hero{padding:20px}.card{padding:23px}.hero-copy{margin-top:35px}h1{font-size:34px}.chart{height:85px}}
</style></head>
<body><main class="shell">
<section class="hero">
<div class="brand"><span class="mark">BI</span><span>BINANCE COPY<small>INTELLIGENCE WORKSPACE</small></span></div>
<div class="hero-copy"><div class="eyebrow">PORTFOLIO RESEARCH & RISK AUDIT</div><h1>Measure the edge.<br><em>Respect the risk.</em></h1><p>Monitor copy-trading portfolios, audit accessible trade histories, compare drawdowns across periods, and evaluate risk-controlled multi-trader paper strategies.</p></div>
<svg class="chart" viewBox="0 0 700 200" preserveAspectRatio="none" aria-hidden="true"><path class="grid" d="M0 30H700M0 80H700M0 130H700M0 180H700"/><path d="M0 157 C46 153 38 125 83 138 S134 144 168 113 S211 137 252 104 S298 127 335 91 S389 110 425 71 S473 103 513 49 S565 81 599 44 S658 57 700 20"/></svg>
<div class="badges"><span class="badge"><b>✓</b>Read-only research</span><span class="badge"><b>✓</b>Historical trade audit</span><span class="badge"><b>✓</b>Paper-only selection</span></div>
</section>
<section class="form-side"><div class="card">
<div class="mobile-brand brand"><span class="mark">BI</span><span>BINANCE COPY<small>INTELLIGENCE WORKSPACE</small></span></div>
<div class="eyebrow">PRIVATE WORKSPACE</div><h2>Welcome back</h2><p class="sub">Sign in to your copy-trader analysis console.</p>
{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
<form method="post"><label for="username">Username</label><input id="username" name="username" type="text" autocomplete="username" value="admin" placeholder="admin" required><label for="password" style="margin-top:16px">Password</label><input id="password" name="password" type="password" autocomplete="current-password" placeholder="Enter your password" required autofocus><button class="primary" type="submit">Unlock workspace →</button></form>
<div class="security"><span class="dot"></span><span><b style="color:#dce8f2">Analysis-only access.</b> This app does not submit orders, withdraw funds, or change your Binance account. API key values are never displayed in this interface.</span></div>
<div class="footer">Binance Copy Intelligence · Research evidence first<br>Missing source history is reported, never invented.</div>
</div></section>
</main></body></html>""")

# Emit structured audit logs to Render stdout/stderr as well as persisting run results in PostgreSQL.
app_path = root / "app.py"
s = app_path.read_text()
if "logging.basicConfig(level=logging.INFO" not in s:
    s = s.replace(
        "import csv, io, json, os, threading, secrets, time",
        "import csv, io, json, os, threading, secrets, time, logging", 1)
    s = s.replace(
        "app = Flask(__name__)",
        "logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')\napp = Flask(__name__)", 1)
if "async_job_failed run_id=" not in s:
    old = '''        except Exception as exc:
            with SessionLocal() as db:
                r=db.get(ScanRun,jid)
                if r: r.status="FAILED"; r.finished_at=utcnow(); r.error_count=(r.error_count or 0)+1; r.message=str(exc)[:2000]; db.commit()
'''
    new = '''        except Exception as exc:
            app.logger.exception("async_job_failed run_id=%s job=%s", jid, getattr(target, "__name__", str(target)))
            with SessionLocal() as db:
                r=db.get(ScanRun,jid)
                if r: r.status="FAILED"; r.finished_at=utcnow(); r.error_count=(r.error_count or 0)+1; r.message=str(exc)[:2000]; db.commit()
'''
    if s.count(old) != 1:
        raise RuntimeError(f"Cannot instrument asynchronous job failures, anchor count={s.count(old)}")
    s = s.replace(old,new,1)

start = s.index("def _run_scheduled_task(kind, market_type, target, args):")
end = s.index("\ndef _monitor_loop():", start)
scheduled = '''def _run_scheduled_task(kind, market_type, target, args):
    with SessionLocal() as db:
        r=ScanRun(kind=kind,market_type=market_type,status="RUNNING",started_at=utcnow(),message="Scheduled monitor task")
        db.add(r);db.commit();db.refresh(r);rid=r.id
    app.logger.info("scheduled_task_started run_id=%s kind=%s market=%s target=%s", rid, kind, market_type, getattr(target, "__name__", str(target)))
    try:
        target(rid,*args)
    except Exception as exc:
        app.logger.exception("scheduled_task_crashed run_id=%s kind=%s market=%s", rid, kind, market_type)
        with SessionLocal() as db:
            r=db.get(ScanRun,rid)
            if r:
                r.status="FAILED"; r.finished_at=utcnow(); r.error_count=(r.error_count or 0)+1
                r.message=f"Scheduled task crashed: {str(exc)[:1600]}"
                db.commit()
        raise
    with SessionLocal() as db:
        r=db.get(ScanRun,rid)
        if r:
            if r.status in ("FAILED","PARTIAL") or (r.error_count or 0)>0:
                app.logger.error("scheduled_task_completed_with_errors run_id=%s kind=%s market=%s status=%s found=%s updated=%s errors=%s message=%s details=%s",
                    rid,kind,market_type,r.status,r.found_count,r.updated_count,r.error_count,r.message,(r.details_json or "")[:1200])
            else:
                app.logger.info("scheduled_task_completed run_id=%s kind=%s market=%s status=%s found=%s updated=%s message=%s",
                    rid,kind,market_type,r.status,r.found_count,r.updated_count,r.message)
    return rid
'''
s = s[:start] + scheduled + s[end:]
if 'app.logger.exception("monitor_cycle_failed")' not in s:
    old = '''        except Exception as e:
            try:
                with SessionLocal() as db:
                    r=ScanRun(kind="SCHEDULER",market_type="ALL",status="FAILED",started_at=utcnow(),finished_at=utcnow(),error_count=1,message=str(e)[:2000])
                    db.add(r);db.commit()
            except Exception: pass
'''
    new = '''        except Exception as e:
            app.logger.exception("monitor_cycle_failed")
            try:
                with SessionLocal() as db:
                    r=ScanRun(kind="SCHEDULER",market_type="ALL",status="FAILED",started_at=utcnow(),finished_at=utcnow(),error_count=1,message=str(e)[:2000])
                    db.add(r);db.commit()
            except Exception:
                app.logger.exception("monitor_cycle_error_could_not_be_persisted")
'''
    if s.count(old) != 1:
        raise RuntimeError(f"Cannot instrument monitor cycle failure, anchor count={s.count(old)}")
    s = s.replace(old,new,1)
app_path.write_text(s)

# Persist failed position-path attempts so one repeatedly failing recent trade cannot starve older audit rows.
analytics = root / "analytics.py"
s = analytics.read_text()
s = s.replace(
    'if only_unanalyzed: stmt = stmt.where(Position.path_status != "ANALYZED")',
    'if only_unanalyzed: stmt = stmt.where(Position.path_status.in_(["NOT_ANALYZED", "PENDING"]))'
)
old = '        except Exception as e: bad+=1; errors.append(f"position {pid}: {str(e)[:180]}")'
new = '''        except Exception as e:
            bad+=1; errors.append(f"position {pid}: {str(e)[:180]}")
            with SessionLocal() as db:
                failed = db.get(Position, pid)
                if failed and failed.path_status != "ANALYZED":
                    failed.path_status = "ANALYSIS_ERROR"
                    db.commit()
            import logging
            logging.getLogger("binance_intel.audit").exception("trade_path_analysis_failed position_id=%s", pid)'''
if new not in s:
    if s.count(old) != 1:
        raise RuntimeError(f"Cannot persist failed trade-path attempt, anchor count={s.count(old)}")
    s = s.replace(old,new,1)
analytics.write_text(s)

# Surface failed path analyses as a separate coverage count.
app_path = root / "app.py"
s = app_path.read_text()
if 'path_errors = db.scalar(' not in s and '@app.get("/api/coverage")' in s:
    anchor = '''            path_analyzed = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter, Position.path_status == "ANALYZED"
                )
            ) or 0
'''
    addition = anchor + '''            path_errors = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter, Position.path_status == "ANALYSIS_ERROR"
                )
            ) or 0
'''
    if s.count(anchor) != 1:
        raise RuntimeError(f"Cannot add path error coverage, anchor count={s.count(anchor)}")
    s = s.replace(anchor,addition,1)
    s = s.replace(
        '"paths_analyzed": int(path_analyzed),',
        '"paths_analyzed": int(path_analyzed), "path_analysis_errors": int(path_errors),', 1)
    s = s.replace(
        'Position.path_status != "ANALYZED",\n                    Position.path_status != "UNPAIRED_SPOT_ACTIVITY",\n                    Position.opened_ms.is_not(None),',
        'Position.path_status.in_(["NOT_ANALYZED", "PENDING"]),\n                    Position.opened_ms.is_not(None),', 1)
    app_path.write_text(s)

js = root / "static" / "app.js"
s = js.read_text()
if "'Failed trade-path analyses · Futures'" not in s:
    s = s.replace(
        "['Trades missing path timestamps/entry · Futures',cov.markets.FUTURES.path_missing_required_timestamps_or_entry],",
        "['Trades missing path timestamps/entry · Futures',cov.markets.FUTURES.path_missing_required_timestamps_or_entry],['Failed trade-path analyses · Futures',cov.markets.FUTURES.path_analysis_errors],"
    )
    js.write_text(s)


# Log backend/key readiness without ever emitting secrets, and verify database connectivity at boot.
app_path = root / "app.py"
s = app_path.read_text()
marker = 'app.logger.info("startup_config database_backend='
if marker not in s:
    anchor = 'app = Flask(__name__)\n'
    block = '''app = Flask(__name__)
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
APP_USERNAME = os.getenv("APP_USERNAME", "admin").strip()
_startup_database_url = os.getenv("DATABASE_URL", "").strip()
_startup_db_backend = "PostgreSQL" if _startup_database_url.startswith(("postgres://", "postgresql://", "postgresql+")) else "SQLite local fallback"
app.logger.info("startup_config database_backend=%s database_url_configured=%s binance_api_key_configured=%s binance_api_secret_configured=%s api_permissions_verified=%s live_order_capability=disabled",
    _startup_db_backend, bool(_startup_database_url), bool(os.getenv("BINANCE_API_KEY")), bool(os.getenv("BINANCE_API_SECRET")), False)
try:
    with SessionLocal() as _startup_db:
        _startup_db.execute(select(func.count(Trader.id))).scalar_one()
    app.logger.info("startup_database_probe status=connected backend=%s", _startup_db_backend)
except Exception:
    app.logger.exception("startup_database_probe status=failed backend=%s", _startup_db_backend)
'''
    if s.count(anchor) != 1:
        raise RuntimeError(f"Cannot add safe startup diagnostics, anchor count={s.count(anchor)}")
    s=s.replace(anchor,block,1)
    app_path.write_text(s)


# Rate-limit protection for Binance candles: HTTP 418 means this IP was auto-banned
# after rate-limit violations. Respect Retry-After, serialize requests, and stop a batch
# at the first ban rather than hammering the API and logging nine more identical failures.
analytics = root / "analytics.py"
s = analytics.read_text()
if "_MARKET_API_COOLDOWN_UNTIL" not in s:
    s = s.replace("import os, time\nimport requests", "import os, time, threading\nimport requests")
    anchor = 'FUTURES_BASE = "https://fapi.binance.com"\n'
    globals_block = anchor + '''
# Process-wide request gate shared by scheduled and manual path audits.
_MARKET_API_LOCK = threading.Lock()
_MARKET_API_NEXT_AT = 0.0
_MARKET_API_COOLDOWN_UNTIL = 0.0
'''
    if s.count(anchor) != 1:
        raise RuntimeError(f"Cannot add market-data request gate: anchor count={s.count(anchor)}")
    s = s.replace(anchor, globals_block, 1)
    old_req = '''            r = session.get(base+path, params=params, timeout=timeout)
            r.raise_for_status(); data = r.json()'''
    new_req = '''            global _MARKET_API_NEXT_AT, _MARKET_API_COOLDOWN_UNTIL
            with _MARKET_API_LOCK:
                now = time.time()
                if now < _MARKET_API_COOLDOWN_UNTIL:
                    wait = max(1, int(_MARKET_API_COOLDOWN_UNTIL - now))
                    raise MarketDataError(f"RATE_LIMIT_COOLDOWN_ACTIVE: Binance market-data cooldown remains {wait}s; request skipped.")
                pause = max(1.0, float(os.getenv("MARKET_DATA_PAUSE", "1.0")))
                nap = max(0.0, _MARKET_API_NEXT_AT - time.time())
                if nap:
                    time.sleep(nap)
                r = session.get(base+path, params=params, timeout=timeout)
                _MARKET_API_NEXT_AT = time.time() + pause
                if r.status_code in (418, 429):
                    retry_after = r.headers.get("Retry-After")
                    try:
                        wait = max(60.0, float(retry_after))
                    except (TypeError, ValueError):
                        wait = 300.0 if r.status_code == 418 else 60.0
                    _MARKET_API_COOLDOWN_UNTIL = time.time() + wait
                    _MARKET_API_NEXT_AT = _MARKET_API_COOLDOWN_UNTIL
                    raise MarketDataError(f"RATE_LIMITED_HTTP_{r.status_code}: Binance throttled/banned this service IP; Retry-After={retry_after or 'unspecified'}, cooldown={int(wait)}s. Remaining batch deferred.")
                r.raise_for_status()
                data = r.json()'''
    if s.count(old_req) != 1:
        raise RuntimeError(f"Cannot add Retry-After/backoff logic: request anchor count={s.count(old_req)}")
    s = s.replace(old_req, new_req, 1)
# Make a cooldown visible to every batch in this process, including jobs started after an HTTP 418.
old_def = '''def run_path_batch(run_id: int, trader_id: int | None = None, limit: int = 20, only_unanalyzed: bool = True, market_type: str = "FUTURES"):
    with SessionLocal() as db:'''
new_def = '''def run_path_batch(run_id: int, trader_id: int | None = None, limit: int = 20, only_unanalyzed: bool = True, market_type: str = "FUTURES"):
    if only_unanalyzed and time.time() < _MARKET_API_COOLDOWN_UNTIL:
        wait=max(1,int(_MARKET_API_COOLDOWN_UNTIL-time.time()))
        with SessionLocal() as db:
            run=db.get(ScanRun,run_id)
            if run:
                run.status="DEFERRED"; run.finished_at=utcnow(); run.found_count=0; run.updated_count=0; run.error_count=0
                run.message=f"Trade-path batch deferred due Binance HTTP rate-limit cooldown ({wait}s remaining); no retry attempted."
                run.details_json=__import__("json").dumps({"deferred":True,"reason":"RATE_LIMIT_COOLDOWN_ACTIVE","cooldown_remaining_seconds":wait})
                db.commit()
        return {"deferred":True,"reason":"RATE_LIMIT_COOLDOWN_ACTIVE","cooldown_remaining_seconds":wait}
    with SessionLocal() as db:'''
if new_def not in s:
    if s.count(old_def) != 1:
        raise RuntimeError(f"Cannot add pre-batch cooldown check: anchor count={s.count(old_def)}")
    s = s.replace(old_def,new_def,1)
# Resume deferred rows after cooldown; give the oldest deferred attempt priority so all queued trades can be retried.
s = s.replace(
    'if only_unanalyzed: stmt = stmt.where(Position.path_status.in_(["NOT_ANALYZED", "PENDING"]))',
    'if only_unanalyzed: stmt = stmt.where(Position.path_status.in_(["NOT_ANALYZED", "PENDING", "RATE_LIMIT_DEFERRED"]))'
)
old_order = 'rows = list(db.scalars(stmt.order_by(Position.closed_ms.desc()).limit(max(1,min(limit,100)))))'
new_order = 'stmt = stmt.order_by((Position.path_status == "RATE_LIMIT_DEFERRED").desc(), Position.path_analyzed_at.asc().nullsfirst(), Position.closed_ms.asc().nullsfirst())\n        rows = list(db.scalars(stmt.limit(max(1,min(limit,100)))))'
if new_order not in s:
    if s.count(old_order) != 1:
        raise RuntimeError(f"Cannot prioritize deferred audit rows: anchor count={s.count(old_order)}")
    s = s.replace(old_order,new_order,1)
# A rate limit is a deferred task, not a bad-data analysis error. Stop after the first HTTP ban.
old_catch = '''        except Exception as e:
            bad+=1; errors.append(f"position {pid}: {str(e)[:180]}")
            with SessionLocal() as db:
                failed = db.get(Position, pid)
                if failed and failed.path_status != "ANALYZED":
                    failed.path_status = "ANALYSIS_ERROR"
                    db.commit()
            import logging
            logging.getLogger("binance_intel.audit").exception("trade_path_analysis_failed position_id=%s", pid)'''
new_catch = '''        except Exception as e:
            bad+=1; errors.append(f"position {pid}: {str(e)[:180]}")
            rate_limited = "RATE_LIMIT" in str(e) or "HTTP 418" in str(e) or "HTTP 429" in str(e)
            with SessionLocal() as db:
                failed = db.get(Position, pid)
                if failed and failed.path_status != "ANALYZED":
                    failed.path_status = "RATE_LIMIT_DEFERRED" if rate_limited else "ANALYSIS_ERROR"
                    failed.path_analyzed_at = utcnow()
                    db.commit()
            import logging
            logging.getLogger("binance_intel.audit").exception("trade_path_analysis_%s position_id=%s", "deferred_by_rate_limit" if rate_limited else "failed", pid)
            if rate_limited:
                break'''
if new_catch not in s:
    if s.count(old_catch) != 1:
        raise RuntimeError(f"Cannot change rate-limited audit failure handling: anchor count={s.count(old_catch)}")
    s = s.replace(old_catch,new_catch,1)
analytics.write_text(s)

# Expose rate-limited/deferred paths separately from malformed/incomplete trades in the coverage endpoint.
app_path = root / "app.py"
s = app_path.read_text()
anchor = '''            path_errors = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter, Position.path_status == "ANALYSIS_ERROR"
                )
            ) or 0
'''
if 'path_rate_limit_deferred = db.scalar(' not in s and anchor in s:
    s = s.replace(anchor, anchor + '''            path_rate_limit_deferred = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter, Position.path_status == "RATE_LIMIT_DEFERRED"
                )
            ) or 0
''', 1)
    s = s.replace('"path_analysis_errors": int(path_errors),', '"path_analysis_errors": int(path_errors), "path_rate_limit_deferred": int(path_rate_limit_deferred),', 1)
    app_path.write_text(s)

js = root / "static" / "app.js"
s = js.read_text()
if "'Trade paths deferred by Binance rate limit · Futures'" not in s:
    s = s.replace(
        "['Failed trade-path analyses · Futures',cov.markets.FUTURES.path_analysis_errors],",
        "['Failed trade-path analyses · Futures',cov.markets.FUTURES.path_analysis_errors],['Trade paths deferred by Binance rate limit · Futures',cov.markets.FUTURES.path_rate_limit_deferred],"
    )
    js.write_text(s)


# Rate-limit protection for Binance candles: HTTP 418 means this IP was auto-banned
# after rate-limit violations. Respect Retry-After, serialize requests, and stop a batch
# at the first ban rather than hammering the API and logging nine more identical failures.
analytics = root / "analytics.py"
s = analytics.read_text()
if "_MARKET_API_COOLDOWN_UNTIL" not in s:
    s = s.replace("import os, time\nimport requests", "import os, time, threading\nimport requests")
    anchor = 'FUTURES_BASE = "https://fapi.binance.com"\n'
    globals_block = anchor + '''
# Process-wide request gate shared by scheduled and manual path audits.
_MARKET_API_LOCK = threading.Lock()
_MARKET_API_NEXT_AT = 0.0
_MARKET_API_COOLDOWN_UNTIL = 0.0
'''
    if s.count(anchor) != 1:
        raise RuntimeError(f"Cannot add market-data request gate: anchor count={s.count(anchor)}")
    s = s.replace(anchor, globals_block, 1)
    old_req = '''            r = session.get(base+path, params=params, timeout=timeout)
            r.raise_for_status(); data = r.json()'''
    new_req = '''            global _MARKET_API_NEXT_AT, _MARKET_API_COOLDOWN_UNTIL
            with _MARKET_API_LOCK:
                now = time.time()
                if now < _MARKET_API_COOLDOWN_UNTIL:
                    wait = max(1, int(_MARKET_API_COOLDOWN_UNTIL - now))
                    raise MarketDataError(f"RATE_LIMIT_COOLDOWN_ACTIVE: Binance market-data cooldown remains {wait}s; request skipped.")
                pause = max(1.0, float(os.getenv("MARKET_DATA_PAUSE", "1.0")))
                nap = max(0.0, _MARKET_API_NEXT_AT - time.time())
                if nap:
                    time.sleep(nap)
                r = session.get(base+path, params=params, timeout=timeout)
                _MARKET_API_NEXT_AT = time.time() + pause
                if r.status_code in (418, 429):
                    retry_after = r.headers.get("Retry-After")
                    try:
                        wait = max(60.0, float(retry_after))
                    except (TypeError, ValueError):
                        wait = 300.0 if r.status_code == 418 else 60.0
                    _MARKET_API_COOLDOWN_UNTIL = time.time() + wait
                    _MARKET_API_NEXT_AT = _MARKET_API_COOLDOWN_UNTIL
                    raise MarketDataError(f"RATE_LIMITED_HTTP_{r.status_code}: Binance throttled/banned this service IP; Retry-After={retry_after or 'unspecified'}, cooldown={int(wait)}s. Remaining batch deferred.")
                r.raise_for_status()
                data = r.json()'''
    if s.count(old_req) != 1:
        raise RuntimeError(f"Cannot add Retry-After/backoff logic: request anchor count={s.count(old_req)}")
    s = s.replace(old_req, new_req, 1)
# Make a cooldown visible to every batch in this process, including jobs started after an HTTP 418.
old_def = '''def run_path_batch(run_id: int, trader_id: int | None = None, limit: int = 20, only_unanalyzed: bool = True, market_type: str = "FUTURES"):
    with SessionLocal() as db:'''
new_def = '''def run_path_batch(run_id: int, trader_id: int | None = None, limit: int = 20, only_unanalyzed: bool = True, market_type: str = "FUTURES"):
    if only_unanalyzed and time.time() < _MARKET_API_COOLDOWN_UNTIL:
        wait=max(1,int(_MARKET_API_COOLDOWN_UNTIL-time.time()))
        with SessionLocal() as db:
            run=db.get(ScanRun,run_id)
            if run:
                run.status="DEFERRED"; run.finished_at=utcnow(); run.found_count=0; run.updated_count=0; run.error_count=0
                run.message=f"Trade-path batch deferred due Binance HTTP rate-limit cooldown ({wait}s remaining); no retry attempted."
                run.details_json=__import__("json").dumps({"deferred":True,"reason":"RATE_LIMIT_COOLDOWN_ACTIVE","cooldown_remaining_seconds":wait})
                db.commit()
        return {"deferred":True,"reason":"RATE_LIMIT_COOLDOWN_ACTIVE","cooldown_remaining_seconds":wait}
    with SessionLocal() as db:'''
if new_def not in s:
    if s.count(old_def) != 1:
        raise RuntimeError(f"Cannot add pre-batch cooldown check: anchor count={s.count(old_def)}")
    s = s.replace(old_def,new_def,1)
# Resume deferred rows after cooldown; give the oldest deferred attempt priority so all queued trades can be retried.
s = s.replace(
    'if only_unanalyzed: stmt = stmt.where(Position.path_status.in_(["NOT_ANALYZED", "PENDING"]))',
    'if only_unanalyzed: stmt = stmt.where(Position.path_status.in_(["NOT_ANALYZED", "PENDING", "RATE_LIMIT_DEFERRED"]))'
)
old_order = 'rows = list(db.scalars(stmt.order_by(Position.closed_ms.desc()).limit(max(1,min(limit,100)))))'
new_order = 'stmt = stmt.order_by((Position.path_status == "RATE_LIMIT_DEFERRED").desc(), Position.path_analyzed_at.asc().nullsfirst(), Position.closed_ms.asc().nullsfirst())\n        rows = list(db.scalars(stmt.limit(max(1,min(limit,100)))))'
if new_order not in s:
    if s.count(old_order) != 1:
        raise RuntimeError(f"Cannot prioritize deferred audit rows: anchor count={s.count(old_order)}")
    s = s.replace(old_order,new_order,1)
# A rate limit is a deferred task, not a bad-data analysis error. Stop after the first HTTP ban.
old_catch = '''        except Exception as e:
            bad+=1; errors.append(f"position {pid}: {str(e)[:180]}")
            with SessionLocal() as db:
                failed = db.get(Position, pid)
                if failed and failed.path_status != "ANALYZED":
                    failed.path_status = "ANALYSIS_ERROR"
                    db.commit()
            import logging
            logging.getLogger("binance_intel.audit").exception("trade_path_analysis_failed position_id=%s", pid)'''
new_catch = '''        except Exception as e:
            bad+=1; errors.append(f"position {pid}: {str(e)[:180]}")
            rate_limited = "RATE_LIMIT" in str(e) or "HTTP 418" in str(e) or "HTTP 429" in str(e)
            with SessionLocal() as db:
                failed = db.get(Position, pid)
                if failed and failed.path_status != "ANALYZED":
                    failed.path_status = "RATE_LIMIT_DEFERRED" if rate_limited else "ANALYSIS_ERROR"
                    failed.path_analyzed_at = utcnow()
                    db.commit()
            import logging
            logging.getLogger("binance_intel.audit").exception("trade_path_analysis_%s position_id=%s", "deferred_by_rate_limit" if rate_limited else "failed", pid)
            if rate_limited:
                break'''
if new_catch not in s:
    if s.count(old_catch) != 1:
        raise RuntimeError(f"Cannot change rate-limited audit failure handling: anchor count={s.count(old_catch)}")
    s = s.replace(old_catch,new_catch,1)
analytics.write_text(s)

# Expose rate-limited/deferred paths separately from malformed/incomplete trades in the coverage endpoint.
app_path = root / "app.py"
s = app_path.read_text()
anchor = '''            path_errors = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter, Position.path_status == "ANALYSIS_ERROR"
                )
            ) or 0
'''
if 'path_rate_limit_deferred = db.scalar(' not in s and anchor in s:
    s = s.replace(anchor, anchor + '''            path_rate_limit_deferred = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter, Position.path_status == "RATE_LIMIT_DEFERRED"
                )
            ) or 0
''', 1)
    s = s.replace('"path_analysis_errors": int(path_errors),', '"path_analysis_errors": int(path_errors), "path_rate_limit_deferred": int(path_rate_limit_deferred),', 1)
    app_path.write_text(s)

js = root / "static" / "app.js"
s = js.read_text()
if "'Trade paths deferred by Binance rate limit · Futures'" not in s:
    s = s.replace(
        "['Failed trade-path analyses · Futures',cov.markets.FUTURES.path_analysis_errors],",
        "['Failed trade-path analyses · Futures',cov.markets.FUTURES.path_analysis_errors],['Trade paths deferred by Binance rate limit · Futures',cov.markets.FUTURES.path_rate_limit_deferred],"
    )
    js.write_text(s)


# Fail closed on persistence: do not claim automatic scanning/history retention while the
# service is actually writing to per-instance SQLite. The UI remains readable and explains
# which Render configuration is missing; all writes/scans resume automatically with Postgres.
app_path = root / "app.py"
s = app_path.read_text()
if "def _durable_database_configured():" not in s:
    anchor = 'app = Flask(__name__)\n'
    helper = '''app = Flask(__name__)

def _durable_database_configured():
    url = os.getenv("DATABASE_URL", "").strip()
    return url.startswith(("postgres://", "postgresql://", "postgresql+"))

'''
    if s.count(anchor) != 1:
        raise RuntimeError(f"Cannot add persistence readiness check: anchor count={s.count(anchor)}")
    s = s.replace(anchor,helper,1)

old_gate = '''@app.before_request
def access_gate():
    if not APP_PASSWORD:
        return None
    if request.endpoint in ("login", "health", "static"):
        return None
    if session.get("authenticated"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error":"Authentication required"}), 401
    return redirect(url_for("login", next=request.path))
'''
new_gate = '''@app.before_request
def access_gate():
    if request.endpoint == "login" and request.method == "POST" and request.form.get("username", "admin").strip() != APP_USERNAME:
        return render_template("login.html", error="Username or password did not match."), 401
    if request.endpoint in ("login", "logout", "health", "static"):
        return None
    if not APP_PASSWORD:
        message = "APP_PASSWORD is not configured. Set a strong workspace password in the Render Environment before using the application."
        if request.path.startswith("/api/"):
            return jsonify({"error": message, "error_code": "APP_PASSWORD_NOT_CONFIGURED"}), 503
        return render_template("login.html", error=message), 503
    if not _durable_database_configured() and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        message = "Persistent PostgreSQL is not connected. This action is blocked so scans and audit records are not written to ephemeral per-instance SQLite. Link DATABASE_URL to this app's PostgreSQL database in Render, then redeploy."
        if request.path.startswith("/api/"):
            return jsonify({"error": message, "error_code": "DURABLE_DATABASE_REQUIRED", "database_backend": "SQLite local fallback"}), 503
        return Response(message, status=503, mimetype="text/plain")
    if session.get("authenticated"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error":"Authentication required"}), 401
    return redirect(url_for("login", next=request.path))
'''
if new_gate not in s:
    if s.count(old_gate) != 1:
        raise RuntimeError(f"Cannot make login/storage access gates fail-closed: anchor count={s.count(old_gate)}")
    s = s.replace(old_gate,new_gate,1)

old_login = '''def login():
    error=None
    if request.method=="POST":'''
new_login = '''def login():
    if not APP_PASSWORD:
        return render_template("login.html", error="Sign-in is locked until APP_PASSWORD is set in the Render Environment."), 503
    error=None
    if request.method=="POST":'''
if new_login not in s:
    if s.count(old_login) != 1:
        raise RuntimeError(f"Cannot lock sign-in when password is missing: anchor count={s.count(old_login)}")
    s = s.replace(old_login,new_login,1)

status_anchor = '"scheduler_enabled":os.getenv("ENABLE_SCHEDULER","false").lower() in ("1","true","yes")'
status_new = '"durable_storage":_durable_database_configured(),"storage_warning":(None if _durable_database_configured() else "Persistent PostgreSQL is not connected; mutating operations and automatic scans are blocked to prevent data loss."),"scheduler_requested":os.getenv("ENABLE_SCHEDULER","false").lower() in ("1","true","yes"),"scheduler_enabled":(_durable_database_configured() and os.getenv("ENABLE_SCHEDULER","false").lower() in ("1","true","yes"))'
if status_new not in s:
    if s.count(status_anchor) != 1:
        raise RuntimeError(f"Cannot show persistence/scheduler readiness: anchor count={s.count(status_anchor)}")
    s = s.replace(status_anchor,status_new,1)
old_health = '''        return jsonify({"status":"ok" if db_ok else "degraded","database":"connected" if db_ok else "unavailable","app":"Binance Copy Trader Intelligence","analysis_only":True,"time_utc":utcnow().isoformat()+"Z"}), 200 if db_ok else 503'''
new_health = '''        durable=_durable_database_configured()
        return jsonify({"status":"ok" if db_ok and durable else "degraded","database":"connected" if db_ok else "unavailable","durable_storage":durable,"database_backend":"PostgreSQL" if durable else "SQLite local fallback","app":"Binance Copy Trader Intelligence","analysis_only":True,"time_utc":utcnow().isoformat()+"Z"}), 200 if db_ok else 503'''
# Older bundled app revisions differ slightly in /health formatting. If this exact
# optional decoration anchor is absent, retain the existing health route; /api/status
# independently exposes durable_storage and the scheduler's fail-closed reason.
if new_health not in s and s.count(old_health) == 1:
    s = s.replace(old_health,new_health,1)

# The in-process monitor must not run on ephemeral SQLite; it emits a durable log entry instead.
old_monitor = '''def _monitor_loop():
    # This loop runs only while the web instance is awake. Render free instances sleep,
    # so reliable 24/7 monitoring requires a non-sleeping service and persistent database.
    interval=max(15,int(os.getenv("MONITOR_INTERVAL_MINUTES","30")))*60'''
new_monitor = '''def _monitor_loop():
    # This loop runs only while the web instance is awake. Render free instances sleep,
    # so reliable 24/7 monitoring requires a non-sleeping service and persistent database.
    if not _durable_database_configured():
        app.logger.error("scheduler_blocked reason=DATABASE_URL_NOT_POSTGRES; automatic scans are paused to avoid losing data in local SQLite")
        try:
            with SessionLocal() as db:
                r=ScanRun(kind="SCHEDULER",market_type="ALL",status="BLOCKED",started_at=utcnow(),finished_at=utcnow(),error_count=1,
                    message="Automatic scans paused: DATABASE_URL is not configured for persistent PostgreSQL. Link this app to a dedicated Postgres database in Render; no scan batch was started.")
                db.add(r); db.commit()
        except Exception:
            app.logger.exception("could_not_persist_scheduler_block_reason")
        return
    interval=max(15,int(os.getenv("MONITOR_INTERVAL_MINUTES","30")))*60'''
if new_monitor not in s:
    if s.count(old_monitor) != 1:
        raise RuntimeError(f"Cannot require durable DB before automatic scans: anchor count={s.count(old_monitor)}")
    s = s.replace(old_monitor,new_monitor,1)

# Report APP_PASSWORD presence only; never emit password/API-key values.
s=s.replace(
    'api_permissions_verified=%s live_order_capability=disabled",',
    'api_permissions_verified=%s app_password_configured=%s scheduler_requested=%s live_order_capability=disabled",'
)
s=s.replace(
    'bool(os.getenv("BINANCE_API_KEY")), bool(os.getenv("BINANCE_API_SECRET")), False)',
    'bool(os.getenv("BINANCE_API_KEY")), bool(os.getenv("BINANCE_API_SECRET")), False, bool(APP_PASSWORD), os.getenv("ENABLE_SCHEDULER","false").lower() in ("1","true","yes"))'
)
app_path.write_text(s)

# Make the readiness gate self-documenting for deployment setup.
env_example = root / ".env.example"
if env_example.exists():
    e = env_example.read_text()
    if "APP_PASSWORD=" not in e:
        e = e.replace("# Optional Binance API credentials.", "# Required login secret for the private dashboard (use a strong unique value).\nAPP_PASSWORD=\n\n# Optional Binance API credentials.")
    if "DATABASE_URL=\\n" not in e:
        e += "\n# Required for persistent data; automatic scans are paused until PostgreSQL is connected.\nDATABASE_URL=\n"
    env_example.write_text(e)


# --- live progress and millisecond timestamp schema patch ---
# Binance website timestamps are Unix milliseconds, which do not fit PostgreSQL INTEGER.
models_path = root / "models.py"
models_src = models_path.read_text()
models_src = models_src.replace(
    "from sqlalchemy import create_engine, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, UniqueConstraint, Index",
    "from sqlalchemy import create_engine, String, Integer, BigInteger, Float, Boolean, DateTime, Text, ForeignKey, UniqueConstraint, Index"
)
for col in ("start_time_ms", "last_trade_ms", "opened_ms", "closed_ms"):
    models_src = models_src.replace(
        f"{col}: Mapped[int | None] = mapped_column(Integer, nullable=True)",
        f"{col}: Mapped[int | None] = mapped_column(BigInteger, nullable=True)"
    )
models_path.write_text(models_src)

# DB-backed progress checkpoints are polled by the UI and survive browser refreshes.
collector_path = root / "collector.py"
collector_src = collector_path.read_text()
if "def _update_scan_progress(" not in collector_src:
    helper = '''def _update_scan_progress(run_id, message, details, found_count=None, updated_count=None, error_count=None):
    try:
        with SessionLocal() as db:
            run = db.get(ScanRun, int(run_id))
            if not run or run.status not in ("RUNNING", "QUEUED"):
                return
            run.message = str(message)[:2000]
            run.details_json = _json(details)
            if found_count is not None: run.found_count = int(found_count)
            if updated_count is not None: run.updated_count = int(updated_count)
            if error_count is not None: run.error_count = int(error_count)
            db.commit()
    except Exception:
        import logging
        logging.getLogger("binance_intel.progress").exception("could_not_persist_scan_progress run_id=%s", run_id)

_DISCOVERY_COOLDOWN_UNTIL = 0.0

'''
    collector_src = collector_src.replace("def run_discovery(", helper + "def run_discovery(", 1)

# Explicit request/page progress and prompt stop on Binance 418/429, preserving already saved pages.
start = collector_src.index("def run_discovery(")
end = collector_src.index("\ndef sync_positions_for_trader(", start)
discovery = r'''def run_discovery(run_id: int, pages_per_mode: int = 2, include_older: bool = True, market_type: str = "FUTURES"):
    """Discover the union of public leaderboard pages and persist live progress."""
    global _DISCOVERY_COOLDOWN_UNTIL
    import logging
    log = logging.getLogger("binance_intel.discovery")
    remaining = int(_DISCOVERY_COOLDOWN_UNTIL - time.time())
    if remaining > 0:
        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if run:
                run.status = "DEFERRED"; run.finished_at = utcnow(); run.error_count = 0
                run.message = f"Discovery deferred: Binance rate-limit cooldown active for {remaining}s; no requests sent."
                run.details_json = _json({"phase":"DEFERRED","progress_pct":0,"cooldown_remaining_seconds":remaining,"current_action":"Waiting for Binance cooldown"})
                db.commit()
        return

    client = BinancePublicClient()
    total_new = total_updated = errors = 0
    requests_done = success_responses = 0
    halted_by_limit = False
    modes = [(r, t) for r in (("7D", "30D", "90D", "180D", "365D") if include_older else ("7D", "30D", "365D")) for t in ("ROI", "PNL", "SHARP_RATIO", "WIN_RATE", "AUM")]
    pages_limit = max(1, min(int(pages_per_mode), 30))
    estimated = len(modes) * pages_limit
    notes = []
    snapshot_seen = set()
    started = time.monotonic()
    _update_scan_progress(run_id, f"{market_type} discovery starting · {len(modes)} rankings · up to {estimated} page requests.", {
        "phase":"DISCOVERY","progress_pct":0,"ranking_count":len(modes),"rankings_completed":0,
        "requests_completed":0,"requests_estimated":estimated,"pages_per_ranking":pages_limit,
        "profiles_found":0,"observations_updated":0,"source_errors":0,"current_action":"Preparing public Binance leaderboard"
    }, 0, 0, 0)
    try:
        for mode_index, (time_range, data_type) in enumerate(modes, start=1):
            if halted_by_limit: break
            mode_has_rows = False
            for page in range(1, pages_limit + 1):
                action = f"{time_range} / {data_type} ranking, page {page}/{pages_limit}"
                _update_scan_progress(run_id, f"{market_type} discovery · ranking {mode_index}/{len(modes)} · {action} · {requests_done}/{estimated} requests.", {
                    "phase":"DISCOVERY","progress_pct":min(99, int(requests_done*100/max(1,estimated))),
                    "ranking_index":mode_index,"ranking_count":len(modes),"rankings_completed":mode_index-1,
                    "time_range":time_range,"data_type":data_type,"page":page,"pages_per_ranking":pages_limit,
                    "requests_completed":requests_done,"requests_estimated":estimated,"profiles_found":total_new,
                    "observations_updated":total_updated,"source_errors":errors,"current_action":"Requesting "+action
                }, total_new, total_updated, errors)
                try:
                    resp = client.list_futures(page, time_range, data_type) if market_type == "FUTURES" else client.list_spot(page, time_range, data_type)
                    requests_done += 1
                    success_responses += 1
                    rows, data = _data_list(resp)
                    if not rows:
                        notes.append(f"{time_range}/{data_type} p{page}: empty response")
                        break
                    page_new = page_updated = 0
                    with SessionLocal() as db:
                        for row in rows:
                            trader, is_new = _upsert_trader(db, row, market_type, time_range, snapshot_seen)
                            if trader:
                                total_new += int(is_new); total_updated += int(not is_new)
                                page_new += int(is_new); page_updated += int(not is_new)
                        db.commit()
                    mode_has_rows = True
                    pct = min(99, int(requests_done*100/max(1,estimated)))
                    elapsed = int(time.monotonic()-started)
                    message = f"{market_type} discovery {pct}% · {mode_index}/{len(modes)} rankings · {requests_done}/{estimated} requests · {total_new} new profiles · {total_updated} refreshed observations · {elapsed}s elapsed."
                    _update_scan_progress(run_id, message, {
                        "phase":"DISCOVERY","progress_pct":pct,"ranking_index":mode_index,"ranking_count":len(modes),
                        "rankings_completed":mode_index-1,"time_range":time_range,"data_type":data_type,"page":page,
                        "rows_returned":len(rows),"new_profiles_in_page":page_new,"updated_profiles_in_page":page_updated,
                        "requests_completed":requests_done,"requests_estimated":estimated,"profiles_found":total_new,
                        "observations_updated":total_updated,"source_errors":errors,"elapsed_seconds":elapsed,
                        "current_action":f"Saved page: {len(rows)} rows ({page_new} new profiles)"
                    }, total_new, total_updated, errors)
                    if len(rows) < 30: break
                    time.sleep(max(0.1, float(os.getenv("BINANCE_REQUEST_PAUSE", "0.8"))))
                except Exception as exc:
                    requests_done += 1
                    errors += 1
                    err = str(exc)[:220]
                    notes.append(f"{time_range}/{data_type} p{page}: {err[:180]}")
                    response = getattr(exc, "response", None)
                    code = getattr(response, "status_code", None)
                    limited = code in (418,429) or "HTTP 418" in err or "HTTP 429" in err or "418 Client Error" in err or "429 Client Error" in err
                    if limited:
                        retry = response.headers.get("Retry-After") if response is not None else None
                        try: cooldown = max(60, int(float(retry))) if retry else (300 if code == 418 or "418" in err else 60)
                        except (ValueError, TypeError): cooldown = 300 if code == 418 or "418" in err else 60
                        _DISCOVERY_COOLDOWN_UNTIL = time.time() + cooldown
                        halted_by_limit = True
                        log.error("discovery_rate_limited run_id=%s status=%s cooldown_seconds=%s", run_id, code, cooldown)
                    else:
                        log.exception("discovery_request_failed run_id=%s market=%s period=%s metric=%s page=%s",run_id,market_type,time_range,data_type,page)
                    _update_scan_progress(run_id, f"{market_type} discovery failed on {action}: {err}. {'Pausing on rate limit.' if limited else 'Advancing to the next ranking.'}", {
                        "phase":"RATE_LIMITED" if limited else "DISCOVERY","progress_pct":min(99,int(requests_done*100/max(1,estimated))),
                        "ranking_index":mode_index,"ranking_count":len(modes),"rankings_completed":mode_index-1,
                        "time_range":time_range,"data_type":data_type,"page":page,"requests_completed":requests_done,
                        "requests_estimated":estimated,"profiles_found":total_new,"observations_updated":total_updated,
                        "source_errors":errors,"cooldown_seconds":cooldown if limited else 0,
                        "current_action":"Rate-limit cooldown" if limited else "Request error"
                    },total_new,total_updated,errors)
                    break
            if market_type == "SPOT" and not client.spot_list_path: break
            if mode_has_rows and not halted_by_limit:
                _update_scan_progress(run_id, f"{market_type} discovery · completed ranking {mode_index}/{len(modes)} ({time_range}/{data_type}).", {
                    "phase":"DISCOVERY","progress_pct":min(99,int(requests_done*100/max(1,estimated))),
                    "ranking_index":mode_index,"ranking_count":len(modes),"rankings_completed":mode_index,
                    "time_range":time_range,"data_type":data_type,"requests_completed":requests_done,
                    "requests_estimated":estimated,"profiles_found":total_new,"observations_updated":total_updated,
                    "source_errors":errors,"current_action":"Ranking complete"
                },total_new,total_updated,errors)
        elapsed = int(time.monotonic()-started)
        if halted_by_limit:
            status="DEFERRED"; phase="RATE_LIMITED"; pct=min(99,int(requests_done*100/max(1,estimated)))
            message=f"{market_type} discovery paused after Binance rate limiting. Saved partial data: {total_new} new profiles and {total_updated} refreshed observations; {errors} errors. Cooldown active."
        elif errors and (total_new+total_updated or success_responses):
            status="PARTIAL"; phase="PARTIAL"; pct=min(99,int(requests_done*100/max(1,estimated)))
            message=f"{market_type} discovery partially completed: {total_new} new profiles, {total_updated} refreshed observations, {errors} source errors, {requests_done}/{estimated} requests ({elapsed}s)."
        elif errors:
            status="FAILED"; phase="FAILED"; pct=0
            message=f"{market_type} discovery failed: {errors} source errors, {requests_done}/{estimated} requests ({elapsed}s)."
        elif total_new+total_updated:
            status="COMPLETED"; phase="COMPLETED"; pct=100
            message=f"{market_type} discovery finished: {total_new} new profiles, {total_updated} refreshed observations, 0 source errors, {requests_done}/{estimated} requests ({elapsed}s). This is the union of returned public leaderboard pages, not all Binance portfolios."
        else:
            status="EMPTY"; phase="EMPTY"; pct=100
            message=f"{market_type} discovery returned no profile rows after {requests_done}/{estimated} requests ({elapsed}s); check source notes."
        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if run:
                run.status=status; run.finished_at=utcnow(); run.found_count=total_new; run.updated_count=total_updated
                run.error_count=errors; run.message=message
                run.details_json=_json({"phase":phase,"progress_pct":pct,"ranking_count":len(modes),
                    "pages_per_mode":pages_limit,"requests_completed":requests_done,"requests_estimated":estimated,
                    "profiles_found":total_new,"observations_updated":total_updated,"source_errors":errors,
                    "elapsed_seconds":elapsed,"rate_limit_cooldown_seconds":max(0,int(_DISCOVERY_COOLDOWN_UNTIL-time.time())) if halted_by_limit else 0,
                    "notes":notes[:150],"spot_list_endpoint":client.spot_list_path if market_type=="SPOT" else None,
                    "data_quality":"SOURCE_ERROR" if errors and not (total_new+total_updated) else ("PARTIAL_SOURCE" if errors else ("SOURCE_VERIFIED" if total_new+total_updated else "EMPTY_SOURCE_RESPONSE"))})
            db.commit()
    except Exception as exc:
        log.exception("discovery_crashed run_id=%s market=%s",run_id,market_type)
        with SessionLocal() as db:
            run=db.get(ScanRun,run_id)
            if run:
                run.status="FAILED";run.finished_at=utcnow();run.error_count=errors+1
                run.message=f"Discovery crashed: {str(exc)[:1800]}"
                run.details_json=_json({"phase":"FAILED","progress_pct":0,"requests_completed":requests_done,
                    "requests_estimated":estimated,"profiles_found":total_new,"observations_updated":total_updated,
                    "source_errors":errors+1,"notes":notes[-50:]})
            db.commit()
'''
collector_src = collector_src[:start] + discovery + collector_src[end:]
collector_src = collector_src.replace(
    "def sync_positions_for_trader(trader_id: int, max_pages: int = 40):",
    "def sync_positions_for_trader(trader_id: int, max_pages: int = 40, run_id: int | None = None):", 1
)
collector_src = collector_src.replace(
'''        for page in range(1, pages + 1):
            resp = client.history_futures(portfolio_id, page, 50) if market_type == "FUTURES" else client.history_spot(portfolio_id, page, 50)''',
'''        for page in range(1, pages + 1):
            if run_id is not None:
                _update_scan_progress(run_id, f"History sync · {market_type} profile {trader_id} · fetching page {page}/{pages}.",
                    {"phase":"HISTORY_SYNC","market_type":market_type,"trader_id":trader_id,"portfolio_id":portfolio_id,"page":page,
                     "pages_estimated":pages,"progress_pct":min(99,int((page-1)*100/max(1,pages))),
                     "current_action":f"Fetching closed-position history page {page}/{pages}"})
            resp = client.history_futures(portfolio_id, page, 50) if market_type == "FUTURES" else client.history_spot(portfolio_id, page, 50)''', 1
)
collector_src = collector_src.replace(
'''    for tid in ids:
        try:
            r = sync_positions_for_trader(tid)''',
'''    for index, tid in enumerate(ids, start=1):
        _update_scan_progress(run_id, f"History batch {index}/{len(ids)} · syncing profile #{tid}.",
            {"phase":"HISTORY_SYNC","profile_index":index,"profiles_total":len(ids),
             "progress_pct":min(99,int((index-1)*100/max(1,len(ids)))),"current_action":f"Syncing profile #{tid}"},
            good, positions, bad)
        try:
            r = sync_positions_for_trader(tid, run_id=run_id)''', 1
)
collector_path.write_text(collector_src)

# Repair already-created PostgreSQL columns in-place at app startup.
app_path = root / "app.py"
app_src = app_path.read_text()
app_src = app_src.replace(
    "from models import SessionLocal, Trader, Position, TraderSnapshot, ScanRun, utcnow",
    "from models import SessionLocal, Trader, Position, TraderSnapshot, ScanRun, utcnow, engine", 1
)
if "def _repair_postgres_timestamp_columns():" not in app_src:
    repair = '''def _repair_postgres_timestamp_columns():
    if engine.dialect.name != "postgresql":
        return
    statements = (
        "ALTER TABLE traders ALTER COLUMN start_time_ms TYPE BIGINT",
        "ALTER TABLE traders ALTER COLUMN last_trade_ms TYPE BIGINT",
        "ALTER TABLE positions ALTER COLUMN opened_ms TYPE BIGINT",
        "ALTER TABLE positions ALTER COLUMN closed_ms TYPE BIGINT",
    )
    try:
        with engine.begin() as migration_db:
            for statement in statements:
                migration_db.exec_driver_sql(statement)
        print("database_schema_migration_ok: millisecond timestamp columns are BIGINT")
    except Exception:
        import logging
        logging.getLogger("binance_intel.schema").exception("database_schema_migration_failed")
        raise

_repair_postgres_timestamp_columns()

'''
    app_src = app_src.replace("app = Flask(__name__)", repair + "app = Flask(__name__)", 1)
app_src = app_src.replace("result=sync_positions_for_trader(tid)", "result=sync_positions_for_trader(tid, run_id=runid)", 1)
if '@app.get("/api/runs/<int:run_id>")' not in app_src:
    route = '''@app.get("/api/runs/<int:run_id>")
def api_run_status(run_id):
    with SessionLocal() as db:
        run = db.get(ScanRun, run_id)
        if not run:
            return jsonify({"error":"Run not found"}), 404
        payload = _run_dict(run)
    return jsonify(payload), 200

'''
    app_src = app_src.replace('@app.post("/api/scan")', route + '@app.post("/api/scan")', 1)
app_path.write_text(app_src)

# Report a per-position heartbeat during candle-path analysis.
analytics_path = root / "analytics.py"
analytics_src = analytics_path.read_text()
old_loop = '''    for pid in ids:
        try: analyze_position_path(pid); good+=1'''
new_loop = '''    for index, pid in enumerate(ids, start=1):
        with SessionLocal() as progress_db:
            progress_run = progress_db.get(ScanRun, run_id)
            if progress_run and progress_run.status in ("RUNNING", "QUEUED"):
                progress_pct = min(99, int((index-1)*100/max(1,len(ids))))
                progress_run.message = f"{market_type} path analysis {index-1}/{len(ids)} · processing position #{pid}."
                progress_run.details_json = __import__("json").dumps({"phase":"PATH_ANALYSIS","progress_pct":progress_pct,"position_index":index,
                    "positions_total":len(ids),"current_position_id":pid,"updated":good,"errors":bad,"current_action":f"Analyzing trade path {index}/{len(ids)}"})
                progress_run.updated_count = good; progress_run.error_count = bad; progress_db.commit()
        try: analyze_position_path(pid); good+=1'''
if old_loop in analytics_src:
    analytics_src = analytics_src.replace(old_loop, new_loop, 1)
analytics_path.write_text(analytics_src)

# Visible progress loader and button activity while an exact run ID is being processed.
css_path = root / "static" / "app.css"
css = css_path.read_text()
if ".activity-progress{" not in css:
    css += """
/* Live action progress */
.activity-progress{position:sticky;top:8px;z-index:80;margin:10px 0 16px;padding:14px 16px;border:1px solid #344b61;border-radius:14px;background:rgba(12,22,34,.97);box-shadow:0 14px 40px #0003;color:#e9f1fa;backdrop-filter:blur(10px)}
.activity-progress.hidden{display:none}.activity-progress-head{display:flex;align-items:center;gap:12px}.activity-progress-copy{min-width:0;flex:1}.activity-progress-title{font-weight:800;font-size:13px}.activity-progress-message{margin-top:4px;color:#a9bbcc;font-size:12px;line-height:1.45;overflow-wrap:anywhere}.activity-progress-state{font-size:10px;letter-spacing:.08em;font-weight:800;color:#8fe8c3;border:1px solid #315d52;padding:5px 8px;border-radius:999px}.activity-progress-dismiss{border:0;background:transparent;color:#a9bbcc;cursor:pointer;font-size:20px;padding:2px 6px}.activity-spinner{width:22px;height:22px;flex:0 0 22px;border:2px solid #2b4758;border-top-color:#69e5b7;border-radius:50%;animation:activity-spin .8s linear infinite}.activity-progress-track{height:5px;margin-top:12px;border-radius:99px;background:#233545;overflow:hidden}.activity-progress-fill{width:0;height:100%;border-radius:99px;background:linear-gradient(90deg,#65e5b7,#83c7ff);transition:width .3s ease}.activity-progress-fill.indeterminate{width:38%;animation:activity-runner 1.3s ease-in-out infinite}.activity-progress-foot{display:flex;justify-content:space-between;gap:12px;margin-top:7px;color:#8da4b9;font-size:10px}.activity-mini-spin{display:inline-block;animation:activity-spin .8s linear infinite}@keyframes activity-spin{to{transform:rotate(360deg)}}@keyframes activity-runner{0%{transform:translateX(-120%)}100%{transform:translateX(360%)}}
@media(max-width:600px){.activity-progress{top:4px;margin:6px 0 10px;padding:11px}.activity-progress-state{display:none}.activity-progress-message{font-size:11px}}
"""
    css_path.write_text(css)

js_path = root / "static" / "app.js"
js = js_path.read_text()
new_action = r'''function ensureActivityProgress(){
  let panel=$('#activity-progress');if(panel)return panel;
  panel=document.createElement('section');panel.id='activity-progress';panel.className='activity-progress hidden';panel.setAttribute('role','status');panel.setAttribute('aria-live','polite');
  panel.innerHTML='<div class="activity-progress-head"><span class="activity-spinner" id="activity-spinner"></span><div class="activity-progress-copy"><div class="activity-progress-title" id="activity-progress-title">Working…</div><div class="activity-progress-message" id="activity-progress-message">Waiting for the server…</div></div><span class="activity-progress-state" id="activity-progress-state">RUNNING</span><button class="activity-progress-dismiss" id="activity-progress-dismiss" type="button" aria-label="Dismiss progress">×</button></div><div class="activity-progress-track"><div class="activity-progress-fill indeterminate" id="activity-progress-fill"></div></div><div class="activity-progress-foot"><span id="activity-progress-detail">Live server status</span><span id="activity-progress-percent">In progress</span></div>';
  document.body.insertBefore(panel,document.body.firstChild);
  $('#activity-progress-dismiss').addEventListener('click',()=>panel.classList.add('hidden'));
  return panel;
}
function showActivityProgress(title,message,pct=null,status='RUNNING',detail='Live server status'){
  ensureActivityProgress();$('#activity-progress').classList.remove('hidden');$('#activity-progress-title').textContent=title;$('#activity-progress-message').textContent=message||'Working…';$('#activity-progress-state').textContent=status||'RUNNING';$('#activity-progress-detail').textContent=detail||'';
  const fill=$('#activity-progress-fill');const valid=pct!==null&&pct!==''&&Number.isFinite(Number(pct));
  if(valid){fill.classList.remove('indeterminate');fill.style.width=Math.max(0,Math.min(100,Number(pct)))+'%';$('#activity-progress-percent').textContent=Math.round(Math.max(0,Math.min(100,Number(pct))) )+'%';}
  else{fill.classList.add('indeterminate');fill.style.width='38%';$('#activity-progress-percent').textContent='In progress';}
  $('#activity-spinner').style.display=['COMPLETED','PARTIAL','FAILED','EMPTY','DEFERRED','BLOCKED','SKIPPED'].includes(String(status).toUpperCase())?'none':'block';
}
function parseRunDetails(run){try{return JSON.parse(run.details_json||'{}')}catch{return {}}}
async function watchActionRun(runId,what){
  const started=Date.now();let lastRun=null;
  while(Date.now()-started<45*60*1000){
    const run=await api('/api/runs/'+runId);lastRun=run;const d=parseRunDetails(run);const status=String(run.status||'RUNNING').toUpperCase();
    const pct=Object.prototype.hasOwnProperty.call(d,'progress_pct')?d.progress_pct:(['COMPLETED','PARTIAL','EMPTY'].includes(status)?100:null);
    const elapsed=Math.round((Date.now()-started)/1000);
    const detail=d.requests_completed!==undefined?d.requests_completed+'/'+(d.requests_estimated||'?')+' requests · '+elapsed+'s elapsed':d.position_index!==undefined?Math.max(0,d.position_index-1)+'/'+(d.positions_total||'?')+' trades · '+elapsed+'s elapsed':d.profile_index!==undefined?Math.max(0,d.profile_index-1)+'/'+(d.profiles_total||'?')+' profiles · '+elapsed+'s elapsed':'Run #'+runId+' · '+elapsed+'s elapsed';
    showActivityProgress(what,run.message||d.current_action||'Processing…',pct,status,detail);
    if(['COMPLETED','PARTIAL','FAILED','EMPTY','DEFERRED','BLOCKED','SKIPPED'].includes(status))break;
    await new Promise(resolve=>setTimeout(resolve,1200));
  }
  if(!lastRun)return null;
  const status=String(lastRun.status||'RUNNING').toUpperCase();
  if(status==='COMPLETED')toast(what+' completed: '+(lastRun.message||'Finished.'),'success');
  else if(['PARTIAL','EMPTY','DEFERRED','BLOCKED','SKIPPED','FAILED'].includes(status))toast(what+': '+(lastRun.message||status),'error');
  setTimeout(()=>{const el=$('#activity-progress-state');if(el&&String(el.textContent).toUpperCase()===status)$('#activity-progress').classList.add('hidden')},12000);
  await refreshStatus();loadRunsOnly();loadTradersMaybe();if(state.view==='history')loadPaths();if(state.view==='system')loadSystem();
  return lastRun;
}
async function runAction(path,body,what,button=null){
  const btn=button||((document.activeElement instanceof HTMLElement&&document.activeElement.tagName==='BUTTON')?document.activeElement:null);
  const original=btn?btn.innerHTML:null;
  if(btn){btn.disabled=true;btn.setAttribute('aria-busy','true');btn.innerHTML='<span class="activity-mini-spin">⟳</span> Working…';}
  showActivityProgress(what,'Submitting action to the server…',0,'QUEUED','Waiting for run ID');
  try{const r=await api(path,{method:'POST',body:JSON.stringify(body)});showActivityProgress(what,what+' started · run #'+r.run_id,0,'RUNNING','Run #'+r.run_id+' · waiting for live progress');toast(what+' started (run #'+r.run_id+'). Live progress is shown above.','success');await watchActionRun(r.run_id,what);}
  catch(e){showActivityProgress(what,e.message,null,'FAILED','Request failed');toast(what+' failed: '+e.message,'error');setTimeout(()=>$('#activity-progress')?.classList.add('hidden'),12000);}
  finally{if(btn){btn.disabled=false;btn.removeAttribute('aria-busy');btn.innerHTML=original;}}
}'''
if "async function runAction(path,body,what){" in js:
    start_js=js.index("async function runAction(path,body,what){")
    end_js=js.index("\nfunction loadTradersMaybe",start_js)
    js=js[:start_js]+new_action+js[end_js:]
js = js.replace("'Discovery'));", "'Discovery',$('#btn-scan')));")
js = js.replace("'History sync'));", "'History sync',$('#btn-history')));")
js = js.replace("'Path analysis'));", "'Path analysis',$('#btn-paths')));")
js = js.replace("only_unanalyzed:true},'Path analysis',$('#btn-paths')));", "only_unanalyzed:true},'Path analysis',$('#btn-paths-2')));", 1)
js = js.replace("'Trader history sync');$('#detail-paths'", "'Trader history sync',$('#detail-sync'));$('#detail-paths'")
js = js.replace("'Trader path analysis');$('#trader-detail'", "'Trader path analysis',$('#detail-paths'));$('#trader-detail'")
js_path.write_text(js)

# Default to a quick breadth-first pass; the checkbox enables older/expanded ranking coverage.
html_path = root / "templates" / "index.html"
html = html_path.read_text()
html = html.replace('id="scan-pages" type="number" min="1" max="30" value="2"', 'id="scan-pages" type="number" min="1" max="30" value="1"')
html = html.replace('id="scan-older" checked', 'id="scan-older"')
html_path.write_text(html)


# --- futures-only automatic monitor guard ---
# Spot website route probing is still unverified and can make a scheduled cycle wait through
# multiple endpoint timeouts. Keep automatic cycles focused on Futures unless explicitly opted in.
app_path = root / "app.py"
app_src = app_path.read_text()
for market_line in (
    '_run_scheduled_task("DISCOVERY","SPOT",run_discovery,(pages,True,"SPOT"))',
    '_run_scheduled_task("HISTORY_SYNC","SPOT",run_history_batch,(max(1,min(int(os.getenv("SCHEDULED_HISTORY_BATCH","5")),20)),False,"SPOT"))',
    '_run_scheduled_task("PATH_ANALYSIS","SPOT",run_path_batch,(None,max(1,min(int(os.getenv("SCHEDULED_PATH_BATCH","10")),25)),True,"SPOT"))',
):
    guarded = 'if os.getenv("ENABLE_SPOT_MONITOR","false").lower() in ("1","true","yes"): ' + market_line
    app_src = app_src.replace("                " + market_line, "                " + guarded, 1)
app_path.write_text(app_src)

# Ensure each path-analysis button controls its own busy state.
js_path = root / "static" / "app.js"
js = js_path.read_text()
js = js.replace(",'Path analysis',$('#btn-paths-2')));", ",'Path analysis',$('#btn-paths')));", 1)
lines = []
for line in js.splitlines():
    if line.startswith("$('#btn-paths-2').addEventListener"):
        line = line.replace(",'Path analysis',$('#btn-paths')));", ",'Path analysis',$('#btn-paths-2')));")
    lines.append(line)
js_path.write_text("\n".join(lines) + "\n")


# --- deep trader details, dated trade ledger, and honest paper status ---
# The public Futures lead detail endpoint includes lastTradeTime and portfolio status.
# Probe Spot listing and open-position endpoints once; never manufacture missing positions.
collector_path = root / "collector.py"
collector_src = collector_path.read_text()
if "def run_trader_detail_batch(" not in collector_src:
    collector_src += r'''

def run_trader_detail_batch(run_id: int, limit: int = 20):
    import json, logging, time, requests
    from datetime import datetime
    from sqlalchemy import text
    from models import SessionLocal, ScanRun, utcnow
    log = logging.getLogger("binance_intel.lead_detail")
    limit = max(1, min(int(limit), 40))
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "clienttype": "web",
        "Origin": "https://www.binance.com",
        "Referer": "https://www.binance.com/en/copy-trading/futures",
    }
    endpoint = "https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/detail"
    with SessionLocal() as db:
        candidates = db.execute(text("""
            SELECT id, portfolio_id, raw_json
            FROM traders
            WHERE market_type='FUTURES' AND portfolio_id IS NOT NULL AND portfolio_id<>''
              AND (lead_detail_synced_at IS NULL OR lead_detail_synced_at < CURRENT_TIMESTAMP - INTERVAL '24 hours')
            ORDER BY lead_detail_synced_at ASC NULLS FIRST, id ASC
            LIMIT :lim
        """), {"lim": limit}).mappings().all()
    good = errors = last_time_updates = 0
    notes = []
    started = time.monotonic()
    _update_scan_progress(run_id, f"Lead-profile detail sync starting · {len(candidates)} profiles queued.", {
        "phase":"TRADER_DETAIL_SYNC","profiles_total":len(candidates),"profiles_completed":0,"progress_pct":0,
        "current_action":"Loading last-trade time, portfolio status, margin and visibility flags"
    }, 0, 0, 0)
    for index, item in enumerate(candidates, start=1):
        pid = str(item["portfolio_id"])
        profile_id = int(item["id"])
        try:
            response = requests.get(endpoint, params={"portfolioId":pid}, headers=headers, timeout=(4, 10))
            if response.status_code in (418, 429):
                wait_header = response.headers.get("Retry-After", "")
                message = f"Binance HTTP {response.status_code}; profile-detail batch stopped to respect rate limits (Retry-After={wait_header or 'not supplied'})."
                with SessionLocal() as db:
                    run = db.get(ScanRun, run_id)
                    if run:
                        run.status="DEFERRED"; run.finished_at=utcnow(); run.message=message
                        run.error_count=errors; run.found_count=good; run.updated_count=last_time_updates
                        run.details_json=json.dumps({"phase":"RATE_LIMITED","progress_pct":min(99,int((index-1)*100/max(1,len(candidates)))),
                            "profiles_total":len(candidates),"profiles_completed":index-1,"source_errors":errors,
                            "last_trade_times_updated":last_time_updates,"current_action":"Binance rate-limit cooldown"})
                        db.commit()
                log.error("lead_detail_rate_limited status=%s profile_id=%s", response.status_code, profile_id)
                return
            response.raise_for_status()
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and isinstance(data.get("data"), dict):
                data = data["data"]
            if not isinstance(data, dict) or not data or body.get("success") is False:
                raise ValueError("Detail endpoint returned no recognized profile object: " + json.dumps(body)[:240])
            last_time = None
            for key in ("lastTradeTime", "lastTradeTimeMs", "last_trade_time", "lastTradeTimestamp"):
                value = data.get(key)
                if value not in (None, "", 0, "0"):
                    try:
                        last_time = int(float(value))
                        if last_time < 10_000_000_000:
                            last_time *= 1000
                        break
                    except (TypeError, ValueError, OverflowError):
                        pass
            status = data.get("status")
            checked_at = utcnow()
            with SessionLocal() as db:
                oldrow = db.execute(text("SELECT raw_json, last_trade_ms, portfolio_status FROM traders WHERE id=:id"), {"id":profile_id}).mappings().first()
                if not oldrow:
                    continue
                try:
                    raw = json.loads(oldrow["raw_json"] or "{}")
                except Exception:
                    raw = {}
                if not isinstance(raw, dict):
                    raw = {"source_record":raw}
                raw["_lead_detail"] = data
                raw["_lead_detail_checked_at_utc"] = checked_at.isoformat() + "Z"
                raw["_lead_detail_source"] = "Binance public lead-portfolio/detail"
                new_last = last_time if last_time is not None else oldrow["last_trade_ms"]
                new_status = str(status)[:80] if status not in (None, "") else oldrow["portfolio_status"]
                db.execute(text("""
                    UPDATE traders SET raw_json=:raw, last_trade_ms=:last_time, portfolio_status=:status,
                    lead_detail_synced_at=:checked WHERE id=:id
                """), {"raw":json.dumps(raw, ensure_ascii=False), "last_time":new_last, "status":new_status,
                      "checked":checked_at, "id":profile_id})
                db.commit()
            good += 1
            last_time_updates += int(last_time is not None)
            if data.get("positionShow") is False:
                notes.append(f"{pid}: public detail says positionShow=false")
        except Exception as exc:
            errors += 1
            notes.append(f"{pid}: {str(exc)[:180]}")
            log.warning("lead_detail_request_failed trader_id=%s portfolio_id=%s error=%s", profile_id, pid, str(exc)[:220])
        elapsed = int(time.monotonic()-started)
        _update_scan_progress(run_id, f"Lead-profile detail sync {index}/{len(candidates)} · {good} profiles updated · {last_time_updates} last-trade timestamps found · {errors} errors.", {
            "phase":"TRADER_DETAIL_SYNC","profile_index":index,"profiles_total":len(candidates),
            "profiles_completed":index,"progress_pct":min(99,int(index*100/max(1,len(candidates)))),
            "profiles_updated":good,"last_trade_times_updated":last_time_updates,"source_errors":errors,
            "elapsed_seconds":elapsed,"current_action":f"Fetched portfolio detail {index}/{len(candidates)}"
        }, good, last_time_updates, errors)
        time.sleep(max(0.5, float(os.getenv("BINANCE_DETAIL_PAUSE", "1.0"))))
    with SessionLocal() as db:
        run = db.get(ScanRun, run_id)
        if run:
            run.status = "COMPLETED" if not errors else ("PARTIAL" if good else "FAILED")
            run.finished_at = utcnow(); run.found_count = good; run.updated_count = last_time_updates; run.error_count = errors
            run.message = f"Lead detail sync: {good}/{len(candidates)} profiles updated; {last_time_updates} last-trade timestamps found; {errors} errors."
            run.details_json = json.dumps({"phase":"COMPLETED" if not errors else "PARTIAL","progress_pct":100 if not errors else min(99,int(good*100/max(1,len(candidates)))),
                "profiles_total":len(candidates),"profiles_updated":good,"last_trade_times_updated":last_time_updates,
                "source_errors":errors,"elapsed_seconds":int(time.monotonic()-started),"notes":notes[:50],
                "current_action":"Lead profile detail sync complete"})
            db.commit()


def run_public_feed_probe(run_id: int, _unused: int = 0):
    import json, logging, requests
    from sqlalchemy import text
    from models import SessionLocal, ScanRun, utcnow
    log = logging.getLogger("binance_intel.public_feed_probe")
    headers = {
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept":"application/json, text/plain, */*","Content-Type":"application/json",
        "clienttype":"web","Origin":"https://www.binance.com","Referer":"https://www.binance.com/en-IN/copy-trading/spot",
    }
    list_body = {"pageNumber":1,"pageSize":30,"timeRange":"30D","dataType":"ROI","favoriteOnly":False,
                 "hideFull":True,"nickname":"","order":"DESC","userAsset":0,"portfolioType":"PUBLIC"}
    spot_candidates = [
        "/bapi/spot/v1/friendly/spot/copy-trade/home-page/query-list",
        "/bapi/spot/v1/friendly/spot/copy-trade/home-page/list",
        "/bapi/spot/v1/friendly/spot/copy-trade/lead-portfolio/list",
    ]
    spot_result = {"verified":False,"endpoint":None,"rows":0,"attempts":[]}
    for path in spot_candidates:
        try:
            response = requests.post("https://www.binance.com"+path, json=list_body, headers=headers, timeout=(3,6))
            note = {"path":path,"status_code":response.status_code}
            try: payload = response.json()
            except Exception: payload = {}
            data = payload.get("data") if isinstance(payload,dict) else None
            rows = []
            if isinstance(data,dict):
                for key in ("list","rows","portfolioList","leadPortfolioList","items"):
                    if isinstance(data.get(key),list):
                        rows = data[key]; break
            elif isinstance(data,list):
                rows = data
            if response.ok and rows and isinstance(rows[0],dict) and any(k in rows[0] for k in ("leadPortfolioId","portfolioId","portfolio_id")):
                note["recognized_list_payload"] = True
                spot_result = {"verified":True,"endpoint":path,"rows":len(rows),"attempts":spot_result["attempts"]+[note]}
                os.environ["BINANCE_SPOT_LIST_ENDPOINT"] = path
                os.environ["ENABLE_SPOT_MONITOR"] = "true"
                log.info("spot_public_listing_endpoint_verified endpoint=%s rows=%s; spot monitor enabled for this process",path,len(rows))
                break
            note["code"] = payload.get("code") if isinstance(payload,dict) else None
            note["message"] = str((payload or {}).get("message",""))[:180] if isinstance(payload,dict) else ""
            note["payload_keys"] = list(payload.keys())[:15] if isinstance(payload,dict) else []
            spot_result["attempts"].append(note)
        except Exception as exc:
            spot_result["attempts"].append({"path":path,"error":str(exc)[:180]})
    # Public Futures position-history is closed-trade history. Probe a small set of public
    # current-position route candidates once; a response is only accepted if it contains rows.
    open_result = {"verified":False,"endpoint":None,"rows":0,"attempts":[]}
    try:
        with SessionLocal() as db:
            row = db.execute(text("SELECT portfolio_id FROM traders WHERE market_type='FUTURES' AND portfolio_id IS NOT NULL AND portfolio_id<>'' ORDER BY id LIMIT 1")).first()
        portfolio_id = str(row[0]) if row else None
    except Exception:
        portfolio_id = None
    if portfolio_id:
        candidates = [
            ("/bapi/futures/v1/friendly/future/copy-trade/lead-data/positions","POST"),
            ("/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/positions","POST"),
            ("/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-list","POST"),
            ("/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/current-position","POST"),
            ("/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/open-positions","POST"),
        ]
        body = {"portfolioId":portfolio_id,"pageNumber":1,"pageSize":20}
        for path, method in candidates:
            try:
                response = requests.post("https://www.binance.com"+path,json=body,headers=headers,timeout=(3,5))
                note = {"path":path,"method":method,"status_code":response.status_code}
                try: payload = response.json()
                except Exception: payload = {}
                data = payload.get("data") if isinstance(payload,dict) else None
                rows = []
                if isinstance(data,dict):
                    for key in ("list","rows","positions","positionList","items"):
                        if isinstance(data.get(key),list):
                            rows=data[key]; break
                elif isinstance(data,list):
                    rows=data
                if response.ok and rows and isinstance(rows[0],dict):
                    note["recognized_position_rows"]=len(rows)
                    open_result={"verified":True,"endpoint":path,"rows":len(rows),"attempts":open_result["attempts"]+[note]}
                    log.info("public_lead_open_positions_endpoint_verified endpoint=%s rows=%s",path,len(rows))
                    break
                note["code"] = payload.get("code") if isinstance(payload,dict) else None
                note["message"] = str((payload or {}).get("message",""))[:150] if isinstance(payload,dict) else ""
                open_result["attempts"].append(note)
            except Exception as exc:
                open_result["attempts"].append({"path":path,"error":str(exc)[:150]})
    report = {"spot_listing":spot_result,"futures_open_positions":open_result,
              "verified_at_utc":utcnow().isoformat()+"Z",
              "important":"A successful HTTP status alone is not sufficient; source must return recognized, non-empty profile/position rows."}
    status = "COMPLETED" if spot_result["verified"] or open_result["verified"] else "BLOCKED"
    message = ("Public feed probe verified " + ("Spot listing. " if spot_result["verified"] else "") +
               ("Futures open positions." if open_result["verified"] else "") if status=="COMPLETED" else
               "No recognized public Spot listing or current Futures lead-position feed was found in the tested endpoints. Futures closed-position history remains usable; open lead positions are not currently observable from these routes.")
    with SessionLocal() as db:
        run = db.get(ScanRun,run_id)
        if run:
            run.status=status;run.finished_at=utcnow();run.found_count=int(spot_result["rows"])+int(open_result["rows"])
            run.updated_count=0;run.error_count=0 if status=="COMPLETED" else 1
            run.message=message;run.details_json=json.dumps(report)
            db.commit()
    if status=="BLOCKED":
        log.warning("public_feed_probe_blocked details=%s",json.dumps(report)[:2200])
    return report
'''
collector_path.write_text(collector_src)

# Add timestamped portfolio-detail sync marker and timestamp columns remain BIGINT.
app_path = root / "app.py"
app_src = app_path.read_text()
if "lead_detail_synced_at TIMESTAMP" not in app_src:
    marker = "_repair_postgres_timestamp_columns()\n"
    ensure = '''_repair_postgres_timestamp_columns()

def _ensure_lead_detail_sync_schema():
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as schema_db:
        schema_db.exec_driver_sql("ALTER TABLE traders ADD COLUMN IF NOT EXISTS lead_detail_synced_at TIMESTAMP NULL")
    print("database_schema_migration_ok: lead detail sync checkpoint column ready")

_ensure_lead_detail_sync_schema()
'''
    if app_src.count(marker) != 1:
        raise RuntimeError(f"Cannot add lead detail sync schema: anchor count={app_src.count(marker)}")
    app_src = app_src.replace(marker,ensure,1)

# Schedule a bounded profile-detail batch. History batches cover discovered profiles over subsequent cycles.
if 'run_trader_detail_batch' not in app_src:
    lines = app_src.splitlines()
    out = []
    in_monitor = False
    inserted = False
    for line in lines:
        if line.startswith("def _monitor_loop():"):
            in_monitor = True
        if in_monitor and 'run_history_batch' in line and '"FUTURES"' in line and '_run_scheduled_task' in line and not inserted:
            out.append(line)
            out.append('                _run_scheduled_task("TRADER_DETAIL_SYNC","FUTURES",run_trader_detail_batch,(max(1,min(int(os.getenv("SCHEDULED_DETAIL_BATCH","20")),40)),))')
            inserted = True
            continue
        out.append(line)
        if in_monitor and line.startswith("def ") and line != "def _monitor_loop():":
            in_monitor = False
    if not inserted:
        # Fallback: attach detail sync to the Futures discovery completion path inside the monitor loop.
        app_src = "\n".join(lines) + "\n"
        start = app_src.index("def _monitor_loop():")
        pos = app_src.find("while True:",start)
        if pos < 0:
            raise RuntimeError("Cannot schedule profile-detail sync: monitor loop anchor missing")
        newline = app_src.find("\n",pos)
        app_src = app_src[:newline+1] + '            _run_scheduled_task("TRADER_DETAIL_SYNC","FUTURES",run_trader_detail_batch,(max(1,min(int(os.getenv("SCHEDULED_DETAIL_BATCH","20")),40)),))\n' + app_src[newline+1:]
    else:
        app_src = "\n".join(out) + "\n"

# Probe whether Spot listings and a current public Futures position feed are actually available.
if 'PUBLIC_FEED_PROBE' not in app_src:
    monitor_start = app_src.index("def _monitor_loop():")
    while_pos = app_src.find("while True:", monitor_start)
    if while_pos < 0:
        raise RuntimeError("Cannot schedule one-time public feed probe: monitor loop anchor missing")
    newline = app_src.find("\n",while_pos)
    probe = '''            try:
                with SessionLocal() as _probe_db:
                    _probe_done = _probe_db.scalar(select(ScanRun.id).where(ScanRun.kind=="PUBLIC_FEED_PROBE").limit(1))
                if not _probe_done:
                    _run_scheduled_task("PUBLIC_FEED_PROBE","ALL",run_public_feed_probe,(0,))
            except Exception:
                app.logger.exception("public_feed_probe_schedule_failed")
'''
    app_src = app_src[:newline+1] + probe + app_src[newline+1:]

# Restore a previously verified Spot endpoint after restarts, using an exact line anchor.
# Do not splice by character offset near the loop: that can split time.sleep(...) and break boot.
if "spot_probe_restore_attempted" not in app_src:
    restore = '''    try:
        with SessionLocal() as _restore_db:
            _probe = _restore_db.scalar(select(ScanRun).where(ScanRun.kind=="PUBLIC_FEED_PROBE").order_by(ScanRun.id.desc()).limit(1))
        if _probe and _probe.details_json:
            _probe_data=json.loads(_probe.details_json or "{}")
            _spot_data=_probe_data.get("spot_listing",{})
            if _spot_data.get("verified") and _spot_data.get("endpoint"):
                os.environ.setdefault("BINANCE_SPOT_LIST_ENDPOINT", _spot_data["endpoint"])
                os.environ["ENABLE_SPOT_MONITOR"]="true"
                app.logger.info("spot_probe_restore_attempted endpoint=%s",_spot_data["endpoint"])
    except Exception:
        app.logger.exception("spot_probe_restore_failed")
'''
    monitor_anchor = '    interval=max(15,int(os.getenv("MONITOR_INTERVAL_MINUTES","30")))*60\n'
    if app_src.count(monitor_anchor) == 1:
        app_src = app_src.replace(monitor_anchor, monitor_anchor + restore, 1)
    else:
        raise RuntimeError(f"Cannot restore Spot probe safely: interval anchor count={app_src.count(monitor_anchor)}")


app_path.write_text(app_src)

# Expose lead detail fields via existing trader serializers without changing old response keys.
app_src = app_path.read_text()
if "def _trader_dict_with_lead_detail(" not in app_src:
    wrapper = '''
_original_trader_dict = _trader_dict
def _trader_dict_with_lead_detail(t):
    d = _original_trader_dict(t)
    d["last_trade_ms"] = getattr(t, "last_trade_ms", None)
    d["portfolio_status"] = getattr(t, "portfolio_status", None)
    d["lead_detail_synced_at"] = None
    if engine.dialect.name == "postgresql":
        try:
            from sqlalchemy import text
            with engine.connect() as detail_conn:
                v=detail_conn.execute(text("SELECT lead_detail_synced_at FROM traders WHERE id=:id"),{"id":t.id}).scalar()
                d["lead_detail_synced_at"] = v.isoformat()+"Z" if v else None
        except Exception:
            pass
    try:
        _raw=json.loads(t.raw_json or "{}")
        d["lead_detail"] = _raw.get("_lead_detail") if isinstance(_raw,dict) else None
    except Exception:
        d["lead_detail"] = None
    return d
_trader_dict = _trader_dict_with_lead_detail

'''
    app_src += "\n" + wrapper

# Dated trade ledger: use source timestamps as supplied; missing close time is NOT labelled as an open position.
if '@app.get("/api/trade-ledger")' not in app_src:
    ledger_route = r'''

@app.get("/api/trade-ledger")
def api_trade_ledger():
    from sqlalchemy import select, func, or_
    from datetime import datetime, timezone
    market = (request.args.get("market_type","FUTURES") or "FUTURES").upper()
    if market not in ("FUTURES","SPOT","ALL"): market="FUTURES"
    raw_days=(request.args.get("days","30") or "30").upper()
    days=None if raw_days in ("ALL","0","LIFETIME") else max(1,min(int(raw_days),3650))
    limit=max(1,min(int(request.args.get("limit",200)),500))
    offset=max(0,min(int(request.args.get("offset",0)),100000))
    since_ms=int((datetime.now(timezone.utc).timestamp()-(days*86400 if days else 0))*1000) if days else None
    where=[]
    if market!="ALL": where.append(Trader.market_type==market)
    date_col=func.coalesce(Position.closed_ms,Position.opened_ms)
    if since_ms is not None: where.append(date_col>=since_ms)
    with SessionLocal() as db:
        stmt=select(Position,Trader).join(Trader,Trader.id==Position.trader_id)
        count_stmt=select(func.count(Position.id)).join(Trader,Trader.id==Position.trader_id)
        if where:
            stmt=stmt.where(*where);count_stmt=count_stmt.where(*where)
        total=int(db.scalar(count_stmt) or 0)
        rows=db.execute(stmt.order_by(date_col.desc().nullslast(),Position.id.desc()).limit(limit).offset(offset)).all()
        pnl_sum=0.0;gross_win=0.0;gross_loss=0.0;wins=losses=0;missing_close=0;durations=[]
        items=[]
        def iso_ms(value):
            return datetime.fromtimestamp(value/1000,timezone.utc).isoformat().replace("+00:00","Z") if value is not None else None
        for pos,t in rows:
            pnl=float(pos.close_pnl or 0.0)
            pnl_sum+=pnl
            if pnl>0: wins+=1;gross_win+=pnl
            elif pnl<0: losses+=1;gross_loss+=abs(pnl)
            if pos.closed_ms is None: missing_close+=1
            duration=(max(0,pos.closed_ms-pos.opened_ms)/60000) if pos.closed_ms is not None and pos.opened_ms is not None else None
            if duration is not None: durations.append(duration)
            items.append({
                "id":pos.id,"trader_id":t.id,"nickname":t.nickname,"portfolio_id":t.portfolio_id,
                "profile_url":t.profile_url,"market_type":t.market_type,"symbol":pos.symbol,"side":pos.side,
                "leverage":pos.leverage,"margin_mode":pos.margin_mode,"size":pos.size,
                "entry_price":pos.entry_price,"exit_price":pos.exit_price,"close_pnl":pos.close_pnl,"roi_pct":pos.roi_pct,
                "opened_ms":pos.opened_ms,"closed_ms":pos.closed_ms,"opened_at_utc":iso_ms(pos.opened_ms),
                "closed_at_utc":iso_ms(pos.closed_ms),"duration_minutes":duration,
                "state":"CLOSED_HISTORY" if (pos.source_kind or "")=="CLOSED_POSITION_HISTORY" else (pos.path_status or "UNKNOWN"),
                "time_quality":"CLOSE_TIME_MISSING" if pos.closed_ms is None else "TIMESTAMPS_AVAILABLE",
                "source_kind":pos.source_kind,"path_status":pos.path_status,"candles_covered":pos.candles_covered,
                "coverage_pct":pos.coverage_pct,"mae_pct":pos.mae_pct,"mfe_pct":pos.mfe_pct,
                "time_to_mae_min":pos.time_to_mae_min,"time_to_mfe_min":pos.time_to_mfe_min,
                "went_adverse_first":pos.went_adverse_first
            })
    return jsonify({
        "market_type":market,"days":raw_days,"since_ms":since_ms,"limit":limit,"offset":offset,"total":total,
        "returned":len(items),"positions":items,
        "summary":{"realized_pnl_reported":round(pnl_sum,8),"wins":wins,"losses":losses,
            "win_rate_pct":round(wins*100/max(1,wins+losses),2),"profit_factor":round(gross_win/gross_loss,4) if gross_loss else (None if gross_win==0 else "infinite"),
            "missing_close_time_rows":missing_close,"avg_duration_minutes":round(sum(durations)/len(durations),2) if durations else None},
        "open_positions_available":False,
        "disclaimer":"This is the stored Binance closed-position-history feed, filtered by opened/closed timestamp. It is not a current open-position feed and it is not the paper portfolio P&L."
    })

@app.get("/api/feed-diagnostics")
def api_feed_diagnostics():
    with SessionLocal() as db:
        runs=list(db.scalars(select(ScanRun).where(ScanRun.kind.in_(["PUBLIC_FEED_PROBE","TRADER_DETAIL_SYNC"])).order_by(ScanRun.id.desc()).limit(12)))
        by_market={}
        for market in ("FUTURES","SPOT"):
            profile_count=int(db.scalar(select(func.count(Trader.id)).where(Trader.market_type==market)) or 0)
            synced_count=int(db.scalar(select(func.count(Trader.id)).where(Trader.market_type==market,Trader.history_synced_at.is_not(None))) or 0)
            position_count=int(db.scalar(select(func.count(Position.id)).join(Trader).where(Trader.market_type==market)) or 0)
            by_market[market]={"profiles":profile_count,"profiles_history_synced":synced_count,"stored_position_rows":position_count}
        out=[]
        for r in runs:
            try: details=json.loads(r.details_json or "{}")
            except Exception: details={}
            out.append({"id":r.id,"kind":r.kind,"market_type":r.market_type,"status":r.status,"started_at":_iso(r.started_at),
                        "finished_at":_iso(r.finished_at),"message":r.message,"details":details})
    return jsonify({"markets":by_market,"checks":out,"scheduler_requested":os.getenv("ENABLE_SCHEDULER","false").lower() in ("1","true","yes"),
                    "spot_monitor_enabled":os.getenv("ENABLE_SPOT_MONITOR","false").lower() in ("1","true","yes"),
                    "paper_trading_active":False,
                    "paper_trading_reason":"This release has shortlist scoring only; no persisted cash/equity/open-paper-position ledger or verified public lead open-position feed."})

'''
    app_src += ledger_route
app_path.write_text(app_src)

# Full Trade Ledger page with date-window controls and legible trade timestamps.
html_path = root / "templates" / "index.html"
html = html_path.read_text()
if 'data-view="ledger"' not in html:
    html = html.replace(
        '    <button class="nav-link" data-view="multi-trader"><span class="nav-ico">⇄</span> Multi-Trader Mode</button>\n',
        '    <button class="nav-link" data-view="multi-trader"><span class="nav-ico">⇄</span> Multi-Trader Mode</button>\n    <button class="nav-link" data-view="ledger"><span class="nav-ico">◷</span> Full Trade Ledger</button>\n',1)
if 'id="view-ledger"' not in html:
    ledger_page = r'''    <section class="view" id="view-ledger">
      <div class="section-heading"><div><div class="eyebrow">SOURCE TRADE HISTORY</div><h2>Full Trade Ledger</h2><p>Inspect the exact reported open/close timestamps of stored historical position rows, with date-window filters. These are source-reported trades—not simulated account positions.</p></div><span class="tag blue">READ-ONLY · HISTORICAL</span></div>
      <div class="filter-bar ledger-filters">
        <label>Market<select id="ledger-market"><option value="FUTURES" selected>Futures</option><option value="SPOT">Spot</option><option value="ALL">All markets</option></select></label>
        <label>Time window<select id="ledger-days"><option value="7">Last 7 days</option><option value="30" selected>Last 30 days</option><option value="90">Last 90 days</option><option value="180">Last 180 days</option><option value="365">Last 365 days</option><option value="ALL">All stored history</option></select></label>
        <button class="primary-button" id="ledger-refresh">Refresh ledger</button>
      </div>
      <div class="kpi-grid">
        <article class="kpi-card"><div class="kpi-head"><span>Historical rows in window</span></div><div class="kpi-value" id="ledger-count">—</div><div class="kpi-foot">From stored source history only</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Reported realized PnL</span></div><div class="kpi-value" id="ledger-pnl">—</div><div class="kpi-foot">Sum of source-reported closed PnL</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Win rate</span></div><div class="kpi-value" id="ledger-winrate">—</div><div class="kpi-foot">Among rows with positive/negative reported PnL</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Closing timestamp missing</span></div><div class="kpi-value" id="ledger-missing">—</div><div class="kpi-foot">Not classified as open positions</div></article>
      </div>
      <article class="panel">
        <div class="panel-header"><div><div class="eyebrow">DATA VISIBILITY</div><h3>What this feed can and cannot show</h3></div></div>
        <div class="notice-box" id="ledger-source-note">Loading source diagnostics…</div>
        <div class="notice-box" id="ledger-paper-note">Paper-trading is not active in this build: portfolio selection weights are not capital, positions, or returns.</div>
      </article>
      <article class="panel table-panel">
        <div class="panel-header"><div><div class="eyebrow">TIME-STAMPED POSITION HISTORY</div><h3>Reported trades</h3><p id="ledger-meta">Loading…</p></div></div>
        <div class="table-scroll"><table class="ledger-table"><thead><tr><th>Trader / portfolio</th><th>Symbol / side</th><th>Opened (IST)</th><th>Closed (IST)</th><th>Duration</th><th>Entry</th><th>Exit</th><th>Leverage</th><th>Size</th><th>Reported PnL</th><th>ROI</th><th>Path audit</th></tr></thead><tbody id="ledger-rows"><tr><td colspan="12" class="empty-state">Loading trade history…</td></tr></tbody></table></div>
      </article>
    </section>
'''
    html = html.replace('    <section class="view" id="view-multi-trader">', ledger_page+'    <section class="view" id="view-multi-trader">',1)
# Avoid implying the shortlist is a funded or running paper portfolio.
html = html.replace("Selected paper portfolios","Selected shortlist · illustrative weights only")
html = html.replace("PAPER ONLY · NO ORDERS","SCREEN ONLY · NO ORDERS")
html = html.replace(
    '<div id="mt-note" class="notice-box">Only profiles already discovered or added to the database can be evaluated. Run profile discovery first if this is empty.</div>',
    '<div id="mt-note" class="notice-box">Only discovered profiles can be evaluated. These selection weights are illustrative; no virtual orders or account balance are created.</div><div id="paper-ledger-status" class="notice-box warning">PAPER PORTFOLIO NOT ACTIVE — this build has no configured cash balance, equity curve, virtual order ledger or open paper positions. The current feature ranks traders and suggests weights only. A public current-position feed must be verified before instant leader-entry mirroring can be simulated.</div>'
)
html_path.write_text(html)

# Router, polling and ledger rendering.
js_path = root / "static" / "app.js"
js = js_path.read_text()
js = js.replace("if(name==='multi-trader')loadMultiTrader(false);if(name==='history')loadPaths();",
                "if(name==='multi-trader')loadMultiTrader(false);if(name==='ledger')loadLedger();if(name==='history')loadPaths();")
js = js.replace("traders:'Trader universe','multi-trader':'Multi-Trader Mode',history:",
                "traders:'Trader universe','multi-trader':'Multi-Trader Mode',ledger:'Full Trade Ledger',history:")
js = js.replace("setInterval(()=>{refreshStatus();loadRunsOnly();if(state.view==='multi-trader')loadMultiTrader(false);},30000)",
                "setInterval(()=>{refreshStatus();loadRunsOnly();if(state.view==='multi-trader')loadMultiTrader(false);if(state.view==='ledger')loadLedger();},30000)")
if "async function loadLedger()" not in js:
    js += r'''
function ledgerFmtTime(ms){if(ms===null||ms===undefined||ms==="")return '<span class="na">Timestamp unavailable</span>';return esc(new Date(Number(ms)).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}));}
function ledgerFmtDuration(m){if(m===null||m===undefined||!Number.isFinite(Number(m)))return '—';m=Number(m);if(m<60)return Math.round(m)+'m';if(m<1440)return (m/60).toFixed(1)+'h';return (m/1440).toFixed(1)+'d';}
async function loadLedger(){
  const body=$('#ledger-rows');if(!body)return;
  body.innerHTML='<tr><td colspan="12" class="empty-state">Loading timestamped source records…</td></tr>';
  $('#ledger-refresh').disabled=true;
  try{
    const market=$('#ledger-market').value;const days=$('#ledger-days').value;
    const d=await api('/api/trade-ledger?market_type='+encodeURIComponent(market)+'&days='+encodeURIComponent(days)+'&limit=500&offset=0');
    const summary=d.summary||{};
    $('#ledger-count').textContent=Number(d.total||0).toLocaleString('en-IN');
    $('#ledger-pnl').textContent=summary.realized_pnl_reported===null?'N/A':Number(summary.realized_pnl_reported||0).toLocaleString('en-IN',{maximumFractionDigits:2});
    $('#ledger-winrate').textContent=summary.win_rate_pct===null||summary.win_rate_pct===undefined?'N/A':Number(summary.win_rate_pct).toFixed(1)+'%';
    $('#ledger-missing').textContent=Number(summary.missing_close_time_rows||0).toLocaleString('en-IN');
    $('#ledger-meta').textContent='Showing '+Number(d.returned||0).toLocaleString('en-IN')+' of '+Number(d.total||0).toLocaleString('en-IN')+' rows · source timestamps shown in Asia/Kolkata · window '+days;
    body.innerHTML=(d.positions||[]).map(p=>{
      const pnl=Number(p.close_pnl||0);const pc=pnl>0?'positive':pnl<0?'negative':'';
      return '<tr><td><strong>'+esc(p.nickname||'Unknown')+'</strong><small>'+esc(p.portfolio_id||'')+'</small><small>'+esc(p.market_type||'')+' · '+esc(p.time_quality||'')+'</small></td>'+
      '<td><strong>'+esc(p.symbol||'—')+'</strong><small>'+esc(p.side||'—')+'</small></td>'+
      '<td>'+ledgerFmtTime(p.opened_ms)+'</td><td>'+ledgerFmtTime(p.closed_ms)+'</td><td>'+ledgerFmtDuration(p.duration_minutes)+'</td>'+
      '<td>'+n(p.entry_price,6)+'</td><td>'+n(p.exit_price,6)+'</td><td>'+n(p.leverage,1,'x')+'</td><td>'+n(p.size,4)+'</td>'+
      '<td class="'+pc+'">'+n(p.close_pnl,2)+'</td><td class="'+colorNum(p.roi_pct)+'">'+n(p.roi_pct,3,'%')+'</td>'+
      '<td><strong>'+esc(p.path_status||'Not audited')+'</strong><small>Coverage '+n(p.coverage_pct,1,'%')+' · MAE '+n(p.mae_pct,2,'%')+' · MFE '+n(p.mfe_pct,2,'%')+'</small></td></tr>';
    }).join('')||'<tr><td colspan="12" class="empty-state">No source position rows exist for this market/window. Spot currently has no discovered profiles or trade history.</td></tr>';
    const diag=await api('/api/feed-diagnostics');
    const f=diag.markets||{};const spot=f.SPOT||{};const futures=f.FUTURES||{};
    const checks=diag.checks||[];const probe=checks.find(x=>x.kind==='PUBLIC_FEED_PROBE');
    const spotState=spot.profiles>0?'Spot profiles: '+spot.profiles+', history-synced: '+spot.profiles_history_synced+', stored rows: '+spot.stored_position_rows:
      (probe?'Spot listing probe: '+(probe.status||'UNKNOWN')+' — '+(probe.message||'No detail'):'Spot listing source has not been verified yet.');
    const futState='Futures: '+(futures.profiles||0)+' profiles, '+(futures.profiles_history_synced||0)+' history-synced, '+(futures.stored_position_rows||0)+' stored position rows.';
    $('#ledger-source-note').textContent=spotState+' '+futState+' Detail sync fills last-trade timestamps when Binance returns them. Closed-position history does not prove current open positions.';
    $('#ledger-paper-note').textContent=diag.paper_trading_active?'Paper portfolio engine reports active; inspect its independent ledger before trusting PnL.':'PAPER PORTFOLIO NOT ACTIVE: no cash/equity or virtual open-position ledger is maintained. Multi-Trader Mode weights are recommendations only, not entered trades.';
  }catch(e){body.innerHTML='<tr><td colspan="12" class="empty-state">'+esc(e.message)+'</td></tr>';}
  finally{$('#ledger-refresh').disabled=false;}
}
$('#ledger-refresh')?.addEventListener('click',loadLedger);
$('#ledger-market')?.addEventListener('change',loadLedger);
$('#ledger-days')?.addEventListener('change',loadLedger);
'''
js_path.write_text(js)

# Increase visual hierarchy, text size and table readability throughout the app.
css_path = root / "static" / "app.css"
css = css_path.read_text()
if ".ledger-table{" not in css:
    css += r"""
/* Readable research UI and full trade ledger */
body{font-size:15px}
p,.muted,.subtle,.kpi-foot,.run-sub,.section-heading p,.field-row label{font-size:14px}
h1{font-size:30px}h2{font-size:25px!important}h3{font-size:18px!important}
.kpi-value{font-size:36px!important;line-height:1.12;letter-spacing:-.025em}
.kpi-head{font-size:13px!important;font-weight:700}
.panel-header p{font-size:13px;color:#91a0b4}
.nav-link{font-size:14px!important;padding-top:12px;padding-bottom:12px}
button,select,input{font-size:14px}
.table-scroll th{font-size:12px!important;padding:13px 14px!important;letter-spacing:.03em}
.table-scroll td{font-size:13.5px!important;line-height:1.55;padding:13px 14px!important;vertical-align:top}
.table-scroll td small{font-size:12px!important;line-height:1.5;display:block;color:#91a0b4;overflow-wrap:anywhere;margin-top:3px}
.ledger-filters{display:flex;gap:14px;align-items:end;flex-wrap:wrap;margin:12px 0 18px}
.ledger-filters label{display:flex;flex-direction:column;gap:7px;color:#b5c5d4;font-size:13px;min-width:150px}
.ledger-filters select{background:#111a25;color:#edf3fa;border:1px solid #304354;border-radius:9px;padding:10px 12px;min-height:42px}
.ledger-filters .primary-button{min-height:42px;padding:10px 18px}
.ledger-table{min-width:1500px;border-collapse:separate;border-spacing:0}
.ledger-table td:nth-child(3),.ledger-table td:nth-child(4){min-width:170px;white-space:nowrap}
.ledger-table td:nth-child(12){min-width:185px}
.ledger-table td:first-child{min-width:205px}
.ledger-table .na{color:#e4af69;font-weight:700}
.notice-box.warning{border:1px solid #745630;background:#2a2116;color:#f2d4a1;border-radius:12px;padding:16px;font-size:14px;line-height:1.65}
.view .kpi-grid{gap:14px}
@media(max-width:760px){.kpi-value{font-size:30px!important}.table-scroll td{font-size:12.5px!important}.ledger-filters label{min-width:125px;flex:1}.ledger-filters .primary-button{width:100%}}
"""
    css_path.write_text(css)


# --- import newly added collector tasks before monitor startup ---
app_path = root / "app.py"
app_src = app_path.read_text()
task_import = "from collector import run_trader_detail_batch, run_public_feed_probe"
if task_import not in app_src:
    model_import = "from models import SessionLocal, Trader, Position, TraderSnapshot, ScanRun, utcnow, engine"
    if app_src.count(model_import) == 1:
        app_src = app_src.replace(model_import, task_import + "\n" + model_import, 1)
    else:
        fallback = "from models import SessionLocal"
        if app_src.count(fallback) < 1:
            raise RuntimeError("Cannot add collector task imports: model import anchor missing")
        app_src = app_src.replace(fallback, task_import + "\n" + fallback, 1)
app_path.write_text(app_src)
