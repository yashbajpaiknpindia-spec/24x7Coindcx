from pathlib import Path
import re
import hashlib

root = Path("/app")
app_path = root / "app.py"
html_path = root / "templates" / "index.html"
app = app_path.read_text()

helper = r'''

# COPIER_SAFETY_RANKING_V1
# Conservative copy-screen: use fresh public copier-PnL periods and source account age.
# Missing/stale source evidence blocks eligibility; no order/copy actions are performed.
from datetime import datetime as _bi_datetime, timezone as _bi_timezone, timedelta as _bi_timedelta
from sqlalchemy import func as _bi_func, select as _bi_select
from models import TraderSnapshot as _bi_Snapshot

def _bi_copier_metrics(db, traders, minimum_track_record_days=90, max_snapshot_age_hours=72):
    if not traders:
        return {}
    now = utcnow()
    if getattr(now, "tzinfo", None) is not None:
        now = now.replace(tzinfo=None)
    cutoff = now - _bi_timedelta(hours=max(1, min(int(max_snapshot_age_hours), 168)))
    ids = [t.id for t in traders]
    ranked = _bi_select(
        _bi_Snapshot.trader_id.label("trader_id"),
        _bi_Snapshot.time_range.label("period"),
        _bi_Snapshot.copier_pnl.label("copier_pnl"),
        _bi_Snapshot.captured_at.label("captured_at"),
        _bi_func.row_number().over(
            partition_by=(_bi_Snapshot.trader_id, _bi_Snapshot.time_range),
            order_by=(_bi_Snapshot.captured_at.desc(), _bi_Snapshot.id.desc())
        ).label("rank_no")
    ).where(
        _bi_Snapshot.trader_id.in_(ids),
        _bi_Snapshot.time_range.in_(("30D", "90D")),
        _bi_Snapshot.copier_pnl.is_not(None),
        _bi_Snapshot.captured_at >= cutoff
    ).subquery()

    snapshots = {}
    for tid, period, value, captured in db.execute(_bi_select(
        ranked.c.trader_id, ranked.c.period, ranked.c.copier_pnl, ranked.c.captured_at
    ).where(ranked.c.rank_no == 1)):
        snapshots.setdefault(tid, {})[str(period).upper()] = {
            "value": float(value) if value is not None else None,
            "captured_at": captured.isoformat() if captured else None,
            "basis": "FRESH_SOURCE_SNAPSHOT"
        }

    raw = {}
    now_ms = int(_bi_datetime.now(_bi_timezone.utc).timestamp() * 1000)
    min_days = max(30, min(int(minimum_track_record_days), 3650))
    max_seconds = max(1, min(int(max_snapshot_age_hours), 168)) * 3600

    for t in traders:
        periods = snapshots.get(t.id, {})
        p30 = periods.get("30D")
        p90 = periods.get("90D")
        profile_age_seconds = None
        seen = getattr(t, "last_seen", None)
        if seen is not None:
            if getattr(seen, "tzinfo", None) is not None:
                seen = seen.replace(tzinfo=None)
            try:
                profile_age_seconds = max(0.0, (now - seen).total_seconds())
            except Exception:
                profile_age_seconds = None

        # The profile-level copier_pnl field is used only when the profile says the
        # value is a 90D metric and the profile itself was refreshed recently.
        if p90 is None and getattr(t, "copier_pnl", None) is not None:
            metric_period = str(getattr(t, "metrics_period", "") or "").upper()
            if metric_period == "90D" and profile_age_seconds is not None and profile_age_seconds <= max_seconds:
                p90 = {
                    "value": float(t.copier_pnl),
                    "captured_at": seen.isoformat() if seen else None,
                    "basis": "FRESH_PROFILE_FIELD_90D"
                }

        age_days = None
        start_ms = getattr(t, "start_time_ms", None)
        try:
            if start_ms is not None and int(start_ms) > 0:
                age_days = (now_ms - int(start_ms)) / 86400000.0
        except Exception:
            age_days = None

        reasons = []
        if p30 is None or p30.get("value") is None:
            reasons.append("COPIER_PNL_30D_STALE_OR_UNAVAILABLE")
        elif p30["value"] < 0:
            reasons.append("COPIER_PNL_30D_NEGATIVE")
        if p90 is None or p90.get("value") is None:
            reasons.append("COPIER_PNL_90D_STALE_OR_UNAVAILABLE")
        elif p90["value"] < 0:
            reasons.append("COPIER_PNL_90D_NEGATIVE")
        if age_days is None:
            reasons.append("TRACK_RECORD_START_UNKNOWN")
        elif age_days < 0:
            reasons.append("TRACK_RECORD_START_IN_FUTURE")
        elif age_days < min_days:
            reasons.append("TRACK_RECORD_UNDER_" + str(min_days) + "_DAYS")

        raw[t.id] = {
            "id": t.id,
            "market_type": getattr(t, "market_type", None),
            "copier_pnl_30d": p30.get("value") if p30 else None,
            "copier_pnl_30d_captured_at": p30.get("captured_at") if p30 else None,
            "copier_pnl_30d_basis": p30.get("basis") if p30 else None,
            "copier_pnl_90d": p90.get("value") if p90 else None,
            "copier_pnl_90d_captured_at": p90.get("captured_at") if p90 else None,
            "copier_pnl_90d_basis": p90.get("basis") if p90 else None,
            "track_record_days": round(age_days, 1) if age_days is not None else None,
            "minimum_track_record_days": min_days,
            "copier_safety_reasons": reasons,
            "copy_eligible": not reasons
        }

    valid30 = sorted(
        x["copier_pnl_30d"] for x in raw.values()
        if x["copier_pnl_30d"] is not None and x["copier_pnl_30d"] >= 0
    )
    from bisect import bisect_left, bisect_right
    for item in raw.values():
        val = item["copier_pnl_30d"]
        if val is None or not valid30:
            pnl_score = None
        else:
            left = bisect_left(valid30, val)
            right = bisect_right(valid30, val)
            pnl_score = 100.0 * ((left + right) / 2.0) / len(valid30)
        age = item["track_record_days"]
        duration_score = min(100.0, max(0.0, 100.0 * age / 365.0)) if age is not None and age >= 0 else None
        item["copier_pnl_score"] = round(pnl_score, 2) if pnl_score is not None else None
        item["duration_score"] = round(duration_score, 2) if duration_score is not None else None
        if pnl_score is not None and duration_score is not None:
            item["copier_duration_score"] = round(0.65 * pnl_score + 0.35 * duration_score, 2)
        else:
            item["copier_duration_score"] = None
        item["copy_eligible"] = not item["copier_safety_reasons"]
    return raw


@app.get("/api/copier-safety/ranking")
def api_copier_safety_ranking():
    market = str(request.args.get("market_type", "FUTURES")).upper()
    if market not in ("FUTURES", "SPOT"):
        return jsonify({"error": "market_type must be FUTURES or SPOT"}), 400
    try:
        min_days = max(30, min(int(request.args.get("minimum_track_record_days", 90)), 3650))
        max_age_hours = max(1, min(int(request.args.get("max_snapshot_age_hours", 72)), 168))
        limit = max(10, min(int(request.args.get("limit", 250)), 500))
    except (TypeError, ValueError, OverflowError):
        return jsonify({"error": "invalid safety ranking filters"}), 400
    with SessionLocal() as db:
        traders = list(db.scalars(select(Trader).where(
            Trader.exchange == "BINANCE", Trader.market_type == market
        ).order_by(Trader.last_seen.desc().nullslast(), Trader.id.asc())))
        metrics = _bi_copier_metrics(db, traders, min_days, max_age_hours)
        out = []
        for t in traders:
            m = metrics.get(t.id, {})
            reasons = list(m.get("copier_safety_reasons", ["COPIER_SAFETY_EVIDENCE_UNAVAILABLE"]))
            out.append({
                "id": t.id,
                "nickname": t.nickname,
                "portfolio_id": t.portfolio_id,
                "market_type": t.market_type,
                "profile_url": t.profile_url or ("https://www.binance.com/en/copy-trading/" + ("spot" if market == "SPOT" else "futures") + "/lead-details/" + str(t.portfolio_id)),
                "source_roi": t.roi,
                "source_mdd": t.mdd,
                "source_win_rate_pct": t.win_rate,
                "copier_pnl_30d": m.get("copier_pnl_30d"),
                "copier_pnl_30d_captured_at": m.get("copier_pnl_30d_captured_at"),
                "copier_pnl_30d_basis": m.get("copier_pnl_30d_basis"),
                "copier_pnl_90d": m.get("copier_pnl_90d"),
                "copier_pnl_90d_captured_at": m.get("copier_pnl_90d_captured_at"),
                "copier_pnl_90d_basis": m.get("copier_pnl_90d_basis"),
                "track_record_days": m.get("track_record_days"),
                "minimum_track_record_days": min_days,
                "copier_pnl_score": m.get("copier_pnl_score"),
                "duration_score": m.get("duration_score"),
                "copier_duration_score": m.get("copier_duration_score"),
                "copy_eligible": bool(m.get("copy_eligible")),
                "block_reasons": reasons
            })
    out.sort(key=lambda x: (
        x["copy_eligible"],
        x["copier_duration_score"] is not None,
        x["copier_duration_score"] if x["copier_duration_score"] is not None else -1,
        x["copier_pnl_30d"] if x["copier_pnl_30d"] is not None else -1e99
    ), reverse=True)
    eligible = sum(1 for x in out if x["copy_eligible"])
    return jsonify({
        "market_type": market,
        "minimum_track_record_days": min_days,
        "max_snapshot_age_hours": max_age_hours,
        "profile_count": len(out),
        "eligible_count": eligible,
        "blocked_count": len(out) - eligible,
        "eligible_only_if": [
            "fresh source-reported 30D copier PnL is present and nonnegative",
            "fresh source-reported 90D copier PnL (or a fresh profile field explicitly marked 90D) is present and nonnegative",
            "source account start date is known and at least the configured minimum age"
        ],
        "ranking_method": "Eligible portfolios first. Within the eligible group, 65% source-reported 30D copier-PnL percentile + 35% source account age score (age score reaches 100 at 365 days). Missing evidence never passes.",
        "disclaimer": "Historical public copier PnL is not a guarantee for your own fills, fees, capital, leverage or future performance. This endpoint is read-only and places no orders.",
        "items": out[:limit]
    })
'''

if "COPIER_SAFETY_RANKING_V1" not in app:
    # Patch the existing Multi-Trader evaluator so unsafe/incomplete profiles are
    # actually marked BLOCKED, not merely displayed on a separate board.
    start = app.find("def _mt_report(")
    end = app.find("\ndef _persist_mt_report(", start)
    if start < 0 or end < 0:
        raise RuntimeError("Cannot locate Multi-Trader evaluator for copier safety guard")
    fn = app[start:end]

    anchor = "        now=utcnow(); rows=[]"
    if fn.count(anchor) != 1:
        raise RuntimeError("Cannot locate unique Multi-Trader evaluation loop anchor: " + str(fn.count(anchor)))
    fn = fn.replace(anchor, "        copier_metrics_by_id = _bi_copier_metrics(db, traders)\n" + anchor, 1)

    reason_anchor = "age=(now-seen).total_seconds()/86400 if seen else None; reasons=[]"
    if fn.count(reason_anchor) != 1:
        raise RuntimeError("Cannot locate unique Multi-Trader reason initialization: " + str(fn.count(reason_anchor)))
    fn = fn.replace(reason_anchor, reason_anchor + """
            copier_safety = copier_metrics_by_id.get(t.id, {})
            copier_safety_reasons = list(copier_safety.get("copier_safety_reasons", ["COPIER_SAFETY_EVIDENCE_UNAVAILABLE"]))
            reasons.extend(copier_safety_reasons)
""", 1)

    score_anchor = '            _adjusted_stability=(max(0,min(100,stability_score*(0.5+0.5*stability_confidence/100.0))) if stability_score is not None else None)'
    if fn.count(score_anchor) != 1:
        raise RuntimeError("Cannot locate unique Multi-Trader priority-score anchor: " + str(fn.count(score_anchor)))
    fn = fn.replace(score_anchor, score_anchor + """
            _base_priority = _priority_score
            _pnl_rank = copier_safety.get("copier_pnl_score")
            _duration_rank = copier_safety.get("duration_score")
            _safety_score = (0.45 * float(_base_priority) + 0.35 * float(_pnl_rank) + 0.20 * float(_duration_rank)) if (_base_priority is not None and _pnl_rank is not None and _duration_rank is not None) else None
            _priority_score = round(_safety_score, 2) if _safety_score is not None else None
""", 1)

    row_anchor = '"last_seen":_iso(t.last_seen),'
    if fn.count(row_anchor) != 1:
        raise RuntimeError("Cannot locate unique Multi-Trader row metrics anchor: " + str(fn.count(row_anchor)))
    fn = fn.replace(row_anchor, row_anchor + '"copier_pnl_30d":copier_safety.get("copier_pnl_30d"),"copier_pnl_30d_captured_at":copier_safety.get("copier_pnl_30d_captured_at"),"copier_pnl_90d":copier_safety.get("copier_pnl_90d"),"copier_pnl_90d_captured_at":copier_safety.get("copier_pnl_90d_captured_at"),"track_record_days":copier_safety.get("track_record_days"),"copier_pnl_score":copier_safety.get("copier_pnl_score"),"duration_score":copier_safety.get("duration_score"),"copier_safety_score":round(_safety_score,2) if _safety_score is not None else None,"copier_safety_reasons":copier_safety_reasons,', 1)
    app = app[:start] + fn + app[end:]
    app += helper
    app_path.write_text(app)
else:
    print("Copier safety API/helper already present; app patch skipped")

# Add an independent copier-safety table to each requested page. It renders from
# the explicit safety endpoint so a failure in the legacy page loader is visible.
html = html_path.read_text()
panels = {
    "multi-trader": r'''<article class="panel" id="cs-panel-multi"><div class="panel-header"><div><div class="eyebrow">COPIER-FIRST SCREEN · LIVE SOURCE EVIDENCE</div><h3>Copier PnL & track-record ranking</h3><p>Safety gate is applied before shortlisting, not just shown as a metric.</p></div><span class="tag blue">READ-ONLY</span></div><div class="kpi-grid"><article class="kpi-card"><div class="kpi-head"><span>Profiles</span></div><div id="cs-multi-total" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>Pass all gates</span></div><div id="cs-multi-pass" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>Blocked / missing</span></div><div id="cs-multi-blocked" class="kpi-value">—</div></article></div><div id="cs-multi-note" class="notice-box">Waiting for current source snapshots…</div><div class="table-scroll"><table class="compact-table"><thead><tr><th>Portfolio / Binance link</th><th>Track record age</th><th>Copier PnL 30D</th><th>Copier PnL 90D</th><th>PnL rank</th><th>Duration score</th><th>Copier gate</th><th>Reasons / data coverage</th></tr></thead><tbody id="cs-multi-rows"><tr><td colspan="8" class="empty-state">Loading copier-safety ranking…</td></tr></tbody></table></div></article>''',
    "portfolio-lab": r'''<article class="panel" id="cs-panel-pl"><div class="panel-header"><div><div class="eyebrow">BEFORE FORECASTING · COPIER PROTECTION</div><h3>Copier PnL & track-record eligibility</h3><p>Forecastable past trades alone are not enough; source copier losses or short track records block the profile.</p></div><span class="tag blue">READ-ONLY</span></div><div class="kpi-grid"><article class="kpi-card"><div class="kpi-head"><span>Profiles</span></div><div id="cs-pl-total" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>Pass all gates</span></div><div id="cs-pl-pass" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>Blocked / missing</span></div><div id="cs-pl-blocked" class="kpi-value">—</div></article></div><div id="cs-pl-note" class="notice-box">Waiting for current source snapshots…</div><div class="table-scroll"><table class="compact-table"><thead><tr><th>Portfolio / Binance link</th><th>Track record age</th><th>Copier PnL 30D</th><th>Copier PnL 90D</th><th>PnL rank</th><th>Duration score</th><th>Copier gate</th><th>Reasons / data coverage</th></tr></thead><tbody id="cs-pl-rows"><tr><td colspan="8" class="empty-state">Loading copier-safety ranking…</td></tr></tbody></table></div></article>''',
    "history": r'''<article class="panel" id="cs-panel-tb"><div class="panel-header"><div><div class="eyebrow">COPIER-FIRST SCREEN · VERIFIED PERIODS</div><h3>Copier profitability & trader longevity</h3><p>Compare source-reported copier outcomes and source track-record length before trusting trade-level behaviour.</p></div><span class="tag blue">READ-ONLY</span></div><div class="kpi-grid"><article class="kpi-card"><div class="kpi-head"><span>Profiles</span></div><div id="cs-tb-total" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>Pass all gates</span></div><div id="cs-tb-pass" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>Blocked / missing</span></div><div id="cs-tb-blocked" class="kpi-value">—</div></article></div><div id="cs-tb-note" class="notice-box">Waiting for current source snapshots…</div><div class="table-scroll"><table class="compact-table"><thead><tr><th>Portfolio / Binance link</th><th>Track record age</th><th>Copier PnL 30D</th><th>Copier PnL 90D</th><th>PnL rank</th><th>Duration score</th><th>Copier gate</th><th>Reasons / data coverage</th></tr></thead><tbody id="cs-tb-rows"><tr><td colspan="8" class="empty-state">Loading copier-safety ranking…</td></tr></tbody></table></div></article>'''
}

for view, panel in panels.items():
    opening = re.compile(r'(<section\b[^>]*\bid=["\']view-' + re.escape(view) + r'["\'][^>]*>)', re.I)
    matches = list(opening.finditer(html))
    if len(matches) != 1:
        raise RuntimeError("Expected one section for copier-safety panel " + view + ", found " + str(len(matches)))
    marker = 'id="cs-panel-' + ("multi" if view == "multi-trader" else "pl" if view == "portfolio-lab" else "tb") + '"'
    if marker not in html:
        m = matches[0]
        html = html[:m.end()] + "\n" + panel + "\n" + html[m.end():]

inline = r'''
<script id="COPIER_SAFETY_BOARD_V1">
(function(){
  "use strict";
  var configs=[
    {key:"multi",view:"view-multi-trader",market:"#mt-market",title:"Multi-Trader"},
    {key:"pl",view:"view-portfolio-lab",market:"#pl-market",title:"Portfolio Lab"},
    {key:"tb",view:"view-history",market:"#tb-market",title:"Trade Behaviour"}
  ];
  var busy={},last={},timer=null;
  function esc(v){return String(v===null||v===undefined?"—":v).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]})}
  function money(v){if(v===null||v===undefined||!Number.isFinite(Number(v)))return "—";return (Number(v)<0?"−$":"$")+Math.abs(Number(v)).toLocaleString("en-US",{maximumFractionDigits:2,minimumFractionDigits:2})}
  function num(v,d){return v===null||v===undefined||!Number.isFinite(Number(v))?"—":Number(v).toFixed(d===undefined?1:d)}
  function profileUrl(x){
    var u=String(x.profile_url||"");
    if(/^https:\/\/www\.binance\.com\//i.test(u))return u;
    return "https://www.binance.com/en/copy-trading/"+(String(x.market_type).toUpperCase()==="SPOT"?"spot":"futures")+"/lead-details/"+encodeURIComponent(x.portfolio_id||"");
  }
  function reasonText(x){
    var reasons=x.block_reasons||[];
    return reasons.length?reasons.join(", "):"Fresh 30D/90D copier PnL is nonnegative; source track record meets minimum.";
  }
  function render(cfg,data){
    var items=data.items||[], eligible=items.filter(function(x){return x.copy_eligible});
    var total=document.getElementById("cs-"+cfg.key+"-total"), pass=document.getElementById("cs-"+cfg.key+"-pass"), blocked=document.getElementById("cs-"+cfg.key+"-blocked");
    if(total)total.textContent=Number(data.profile_count||0).toLocaleString();
    if(pass)pass.textContent=Number(data.eligible_count||0).toLocaleString();
    if(blocked)blocked.textContent=Number(data.blocked_count||0).toLocaleString();
    var note=document.getElementById("cs-"+cfg.key+"-note");
    if(note)note.textContent=data.eligible_count+" of "+data.profile_count+" profiles pass the copier-first screen. "+data.ranking_method+" Missing or stale periods, negative 30D/90D copier PnL, and track records under "+data.minimum_track_record_days+" days are blocked. Source-reported past results do not guarantee your own outcome.";
    var rows=document.getElementById("cs-"+cfg.key+"-rows");
    if(!rows)return;
    // Show all qualifying profiles first, followed by blocked examples, without rendering thousands of rows.
    var shown=eligible.slice(0,40).concat(items.filter(function(x){return !x.copy_eligible}).slice(0,10));
    if(!shown.length){rows.innerHTML='<tr><td colspan="8" class="empty-state">No saved Binance profiles were returned. Check the source/system page and API response.</td></tr>';return}
    rows.innerHTML=shown.map(function(x){
      var ok=!!x.copy_eligible;
      var p30=x.copier_pnl_30d,p90=x.copier_pnl_90d;
      var cls=ok?"green":"red";
      var coverage=(x.copier_pnl_30d_basis||"30D unavailable")+" / "+(x.copier_pnl_90d_basis||"90D unavailable");
      return '<tr><td><strong>'+esc(x.nickname||"Unknown portfolio")+'</strong><small style="display:block">'+esc(x.portfolio_id||"")+' · '+esc(x.market_type)+'</small><a href="'+esc(profileUrl(x))+'" target="_blank" rel="noopener noreferrer">Open Binance ↗</a></td><td>'+esc(x.track_record_days===null?"Unknown":num(x.track_record_days,1)+" days")+'</td><td class="'+(p30!==null&&p30<0?"negative":p30===null?"": "positive")+'">'+money(p30)+'<small style="display:block">'+esc(x.copier_pnl_30d_captured_at||"No fresh snapshot")+'</small></td><td class="'+(p90!==null&&p90<0?"negative":p90===null?"":"positive")+'">'+money(p90)+'<small style="display:block">'+esc(x.copier_pnl_90d_captured_at||"No fresh snapshot")+'</small></td><td>'+esc(x.copier_pnl_score===null?"—":num(x.copier_pnl_score,1)+"/100")+'</td><td>'+esc(x.duration_score===null?"—":num(x.duration_score,1)+"/100")+'</td><td><span class="tag '+cls+'">'+(ok?"PASS":"BLOCKED")+'</span><small style="display:block">Combined "+esc(x.copier_duration_score===null?"—":num(x.copier_duration_score,1)+"/100")+'</small></td><td style="min-width:230px;white-space:normal">'+esc(reasonText(x))+'<small style="display:block;color:#8c98a8">'+esc(coverage)+'</small></td></tr>';
    }).join("");
  }
  async function load(cfg,force){
    var section=document.getElementById(cfg.view);
    if(!section||!section.classList.contains("active"))return;
    if(busy[cfg.key])return;
    var marketEl=document.querySelector(cfg.market),market=marketEl&&marketEl.value?marketEl.value:"FUTURES";
    var stamp=market+":"+Math.floor(Date.now()/60000);
    if(!force&&last[cfg.key]===stamp)return;
    busy[cfg.key]=true;
    var rows=document.getElementById("cs-"+cfg.key+"-rows");
    if(rows&&!last[cfg.key])rows.innerHTML='<tr><td colspan="8" class="empty-state">Checking fresh public copier metrics…</td></tr>';
    try{
      var response=await fetch("/api/copier-safety/ranking?market_type="+encodeURIComponent(market)+"&minimum_track_record_days=90&max_snapshot_age_hours=72&limit=250",{credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
      var data=await response.json();
      if(!response.ok)throw new Error(data.error||("HTTP "+response.status));
      render(cfg,data);last[cfg.key]=stamp;
    }catch(e){
      var note=document.getElementById("cs-"+cfg.key+"-note");
      if(note)note.textContent="Copier-safety load failed: "+String(e&&e.message||e)+". The board remains visible; no profiles are assumed safe.";
      if(rows)rows.innerHTML='<tr><td colspan="8" class="empty-state">Safety API failed: '+esc(e&&e.message||e)+'</td></tr>';
    }finally{busy[cfg.key]=false}
  }
  function tick(){configs.forEach(function(cfg){load(cfg,false)})}
  function start(){tick();if(!timer)timer=window.setInterval(tick,60000)}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",function(){setTimeout(start,250)},{once:true});else setTimeout(start,250);
  window.addEventListener("pageshow",function(){setTimeout(tick,250)});
  // The app has its own router/failsafe; polling the active view makes this board independent
  // of whichever legacy page loader is active and refreshes after market changes.
  window.__biCopierSafetyRefresh=tick;
})();
</script>
'''
if "COPIER_SAFETY_BOARD_V1" not in html:
    if "</body>" not in html:
        raise RuntimeError("Cannot install copier-safety UI: </body> is missing")
    html = html.replace("</body>", inline + "\n</body>", 1)
html_path.write_text(html)


# Apply the same copier gate and PnL/longevity ordering to the primary Trade Behaviour API,
# not only the independent safety panel at the top of that page.
app = app_path.read_text()
if "TRADE_BEHAVIOUR_COPIER_PRIORITY_V1" not in app:
    start = app.find("def api_trade_behaviour():")
    end = app.find("\n# COPIER_SAFETY_RANKING_V1", start)
    if start < 0 or end < 0:
        raise RuntimeError("Cannot locate Trade Behaviour API for copier-priority ranking")
    fn = app[start:end]

    anchor = "        ids=[t.id for t in traders]"
    if fn.count(anchor) != 1:
        raise RuntimeError("Trade Behaviour profile IDs anchor count=" + str(fn.count(anchor)))
    fn = fn.replace(anchor, "        copier_metrics_by_id = _bi_copier_metrics(db, traders, 90, 72)\n" + anchor, 1)

    anchor = "        for t in traders:\n            a=aggregates.get(t.id,"
    if fn.count(anchor) != 1:
        raise RuntimeError("Trade Behaviour portfolio loop anchor count=" + str(fn.count(anchor)))
    fn = fn.replace(anchor, "        for t in traders:\n            copier_safety = copier_metrics_by_id.get(t.id, {})\n            a=aggregates.get(t.id,", 1)

    anchor = '                "stability_score":round(stability,2) if stability is not None else None,'
    replacement = anchor + '''
                "copier_pnl_30d":copier_safety.get("copier_pnl_30d"),
                "copier_pnl_90d":copier_safety.get("copier_pnl_90d"),
                "copier_pnl_30d_captured_at":copier_safety.get("copier_pnl_30d_captured_at"),
                "copier_pnl_90d_captured_at":copier_safety.get("copier_pnl_90d_captured_at"),
                "track_record_days":copier_safety.get("track_record_days"),
                "copier_pnl_score":copier_safety.get("copier_pnl_score"),
                "duration_score":copier_safety.get("duration_score"),
                "copier_duration_score":copier_safety.get("copier_duration_score"),
                "copy_eligible":bool(copier_safety.get("copy_eligible")),
                "copy_block_reasons":copier_safety.get("copier_safety_reasons", ["COPIER_SAFETY_EVIDENCE_UNAVAILABLE"]),'''
    if fn.count(anchor) != 1:
        raise RuntimeError("Trade Behaviour stability output anchor count=" + str(fn.count(anchor)))
    fn = fn.replace(anchor, replacement, 1)

    old_sort = '    out.sort(key=lambda x:(metric(x),x.get("stability_confidence_pct",0),x.get("verified_closed_trades",0)),reverse=True)'
    new_sort = '''    # Copier eligibility is a hard first sort key. Within the safe group, rank by
    # source copier PnL percentile + source account longevity, then behaviour quality.
    out.sort(key=lambda x:(
        x.get("copy_eligible", False),
        x.get("copier_duration_score") is not None,
        x.get("copier_duration_score") if x.get("copier_duration_score") is not None else -1,
        metric(x),
        x.get("stability_confidence_pct", 0),
        x.get("verified_closed_trades", 0)
    ), reverse=True)'''
    if fn.count(old_sort) != 1:
        raise RuntimeError("Trade Behaviour sort anchor count=" + str(fn.count(old_sort)))
    fn = fn.replace(old_sort, new_sort, 1)

    note_anchor = '"note":"PF, closed win rate and realized PnL use verified closed records only. Spot raw activity is counted separately and is not treated as a completed trade."'
    note_new = '"note":"Copier eligibility is ranked first using fresh nonnegative 30D/90D copier PnL and a minimum 90-day source track record; the within-group rank uses copier-PnL percentile + account longevity, then selected trade-behaviour metric. PF, closed win rate and realized PnL use verified closed records only. Spot raw activity is not treated as a completed trade."'
    if fn.count(note_anchor) != 1:
        raise RuntimeError("Trade Behaviour note anchor count=" + str(fn.count(note_anchor)))
    fn = fn.replace(note_anchor, note_new, 1)

    app = app[:start] + fn + app[end:]
    app += "\n# TRADE_BEHAVIOUR_COPIER_PRIORITY_V1\n"
    app_path.write_text(app)

print("Copier-first safety gates installed for Multi-Trader and Portfolio Lab forecasts; independent ranking boards installed on all three pages.")
