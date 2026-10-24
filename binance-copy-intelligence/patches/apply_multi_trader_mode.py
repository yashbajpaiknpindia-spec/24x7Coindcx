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
<form method="post"><label for="password">Workspace password</label><input id="password" name="password" type="password" autocomplete="current-password" placeholder="Enter your password" required autofocus><button class="primary" type="submit">Unlock workspace →</button></form>
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
