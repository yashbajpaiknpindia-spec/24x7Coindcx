from pathlib import Path
import re

ROOT = Path("/app")
APP = ROOT / "app.py"
HTML = ROOT / "templates" / "index.html"
JS = ROOT / "static" / "app.js"

def replace_file_once(path, old, new, label):
    text = path.read_text()
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Cannot apply {label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1))

# 1. Tax sync must use service environment credentials; never require them in the browser.
app = APP.read_text()
if "BI_SERVER_ENV_TAX_SYNC_V2" not in app:
    old = '''    api_key = str(data.get("api_key") or "").strip()
    api_secret = str(data.get("api_secret") or "").strip()
    if not api_key or not api_secret: return jsonify({"error":"Enter a read-only Binance API key and secret for this request."}),400'''
    new = '''    # Prefer server-managed credentials. Request-body fallback is retained only for
    # backward compatibility; the browser UI never sends or displays secrets.
    api_key = str(__import__("os").getenv("BINANCE_API_KEY") or data.get("api_key") or "").strip()
    api_secret = str(__import__("os").getenv("BINANCE_API_SECRET") or data.get("api_secret") or "").strip()
    if not api_key or not api_secret:
        return jsonify({"error":"Server credentials are missing. Set BINANCE_API_KEY and BINANCE_API_SECRET in the Render service environment; secret values are never returned by this endpoint.","credentials_saved":False}),503'''
    if app.count(old) != 1:
        raise RuntimeError(f"Cannot apply server-environment tax sync: expected one credential gate, found {app.count(old)}")
    app = app.replace(old, new, 1) + "\n# BI_SERVER_ENV_TAX_SYNC_V2\n"
    APP.write_text(app)

# 2. Replace credential-entry controls with a status message; do not expose secrets.
html = HTML.read_text()
manual_fields = re.compile(
    r'\s*<label>Read-only API key<input id="pt-api-key".*?</label>\s*'
    r'<label>API secret \(used once, never saved\)<input id="pt-api-secret".*?</label>',
    re.S
)
if 'id="pt-api-key"' in html:
    html, n = manual_fields.subn(
        '\n          <div class="notice-box" id="pt-env-credentials"><strong>Server-managed Binance credentials</strong><p>The sync uses BINANCE_API_KEY and BINANCE_API_SECRET from the Render service environment. Secret values are not shown in this page or saved with your records.</p><span id="pt-env-status">Checking service configuration…</span></div>',
        html, count=1
    )
    if n != 1:
        raise RuntimeError("Could not remove manual Binance API key/secret inputs from Profit & Tax Centre")
html = html.replace(
    "Create an API key with read-only/Enable Reading and Futures access only. Do not enable trading, withdrawals, transfers, or universal transfer. The key and secret are sent only for this request; the app stores returned records, not the credentials.",
    "Configure a read-only API key with Futures income access in Render environment variables. Do not enable trading, withdrawals, transfers, or universal transfer. The server uses these credentials for this request; their values are never displayed or stored in the account ledger."
)
html = html.replace("Request Binance income history", "Fetch Binance Futures income using server credentials")
# Extend the navigation failsafe: it previously knew only the original eight pages.
marker = '<script id="BINANCE_INTEL_NAVIGATION_FAILSAFE_V2">'
if marker in html:
    start = html.index(marker)
    end = html.index("</script>", start) + len("</script>")
    nav = html[start:end]
    nav = nav.replace(
        '"multi-trader":"Multi-Trader Mode","history":"Trade behaviour",',
        '"multi-trader":"Multi-Trader Mode","profit-tax":"Profit & Tax Centre","strategy-watch":"Strategy Tax Watch","history":"Trade behaviour",'
    )
    if 'case "profit-tax":' not in nav:
        nav = nav.replace(
            '        case "history":',
            '''        case "profit-tax":
          called.push(await callRequired("Profit & Tax Centre",async function(){
            await Promise.all([itCheckEnvCredentials(),itLoadP2PRates()]);
            await itLoadProfitTax(true);
            return "server-managed account sync";
          }));
          break;
        case "strategy-watch":
          called.push(await callRequired("Strategy Tax Watch",function(){return itLoadProfitTax(true)}));
          break;
        case "history":''',
            1
        )
    if '"profit-tax":"Profit & Tax Centre"' not in nav or 'case "profit-tax":' not in nav or 'case "strategy-watch":' not in nav:
        raise RuntimeError("Navigation failsafe could not be extended for the two tax pages")
    html = html[:start] + nav + html[end:]
if 'id="view-profit-tax"' not in html or 'id="view-strategy-watch"' not in html:
    raise RuntimeError("Profit & Tax Centre / Strategy Tax Watch sections missing after page patch")
HTML.write_text(html)

# 3. Correct Multi-Trader API argument mapping after filters were expanded.
# The previous six-positional-argument calls accidentally treated max_selected as
# evaluation_period, silently ignoring the current period/win-rate/ranking controls.
app = APP.read_text()
mt_get = re.compile(
    r'@app\.get\("/api/multi-trader/candidates"\)\s*'
    r'def api_multi_trader_candidates\(\):.*?(?=\n@app\.post\("/api/multi-trader/evaluate"\))',
    re.S
)
mt_get_new = '''@app.get("/api/multi-trader/candidates")
def api_multi_trader_candidates():
    try:
        args = {
            "market_type": request.args.get("market_type", "FUTURES"),
            "min_closed_trades": request.args.get("min_closed_trades", 10),
            "min_profit_factor": request.args.get("min_profit_factor", 1.2),
            "max_mdd_pct": request.args.get("max_mdd_pct", 20),
            "min_roi_7d": request.args.get("min_roi_7d", -5),
            "evaluation_period": request.args.get("evaluation_period", "30D"),
            "min_win_rate_pct": request.args.get("min_win_rate_pct", 50),
            "ranking_priority": request.args.get("ranking_priority", "STABILITY"),
            "max_selected": request.args.get("max_selected", 5),
        }
        allowed = __import__("inspect").signature(_mt_report).parameters
        report = _mt_report(**{k: v for k, v in args.items() if k in allowed})
        return jsonify(report)
    except Exception as exc:
        app.logger.exception("multi_trader_candidates_failed")
        return jsonify({"error": "Multi-Trader analysis failed: " + str(exc)[:400]}), 500
'''
app, n = mt_get.subn(mt_get_new, app, count=1)
if n != 1 and "BI_MULTITRADER_ARGUMENT_MAPPING_V2" not in app:
    raise RuntimeError(f"Could not fix Multi-Trader candidate API argument mapping (matches={n})")
mt_post = re.compile(
    r'@app\.post\("/api/multi-trader/evaluate"\)\s*'
    r'def api_multi_trader_evaluate\(\):.*?(?=\n@app\.get\("/api/multi-trader/history"\))',
    re.S
)
mt_post_new = '''@app.post("/api/multi-trader/evaluate")
def api_multi_trader_evaluate():
    data = request.get_json(silent=True) or {}
    try:
        args = {
            "market_type": data.get("market_type", "FUTURES"),
            "min_closed_trades": data.get("min_closed_trades", 10),
            "min_profit_factor": data.get("min_profit_factor", 1.2),
            "max_mdd_pct": data.get("max_mdd_pct", 20),
            "min_roi_7d": data.get("min_roi_7d", -5),
            "evaluation_period": data.get("evaluation_period", "30D"),
            "min_win_rate_pct": data.get("min_win_rate_pct", 50),
            "ranking_priority": data.get("ranking_priority", "STABILITY"),
            "max_selected": data.get("max_selected", 5),
        }
        allowed = __import__("inspect").signature(_mt_report).parameters
        report = _mt_report(**{k: v for k, v in args.items() if k in allowed})
        report["evaluation_id"] = _persist_mt_report(report, "MANUAL")
        return jsonify(report)
    except Exception as exc:
        app.logger.exception("multi_trader_evaluate_failed")
        return jsonify({"error": "Multi-Trader evaluation failed: " + str(exc)[:400]}), 500
'''
app, n = mt_post.subn(mt_post_new, app, count=1)
if n != 1 and "BI_MULTITRADER_ARGUMENT_MAPPING_V2" not in app:
    raise RuntimeError(f"Could not fix Multi-Trader evaluate API argument mapping (matches={n})")
if "BI_MULTITRADER_ARGUMENT_MAPPING_V2" not in app:
    app += "\n# BI_MULTITRADER_ARGUMENT_MAPPING_V2\n"
APP.write_text(app)

# 4. Replace client tax functions so the page uses environment-managed credentials,
# reports whether they are present (booleans only), and does one first-visit sync.
js = JS.read_text()
if "BI_PAGE_RELIABILITY_FIXES_V2" not in js:
    new_p2p = r'''async function itLoadP2PRates(){
 try{
   const r=await api('/api/profit-tax/rates');
   $('#pt-buy-rate').value=r.buy_quote_inr_per_usdt||'';
   $('#pt-sell-rate').value=r.sell_quote_inr_per_usdt||'';
   $('#pt-rate-status').textContent=r.sell_quote_inr_per_usdt?'Binance P2P quote · '+String(r.as_of_utc||'').slice(0,19)+' UTC':'P2P source unavailable · enter a rate manually';
   if(!$('#pt-rate').dataset.manual&&r.sell_quote_inr_per_usdt)$('#pt-rate').value=r.sell_quote_inr_per_usdt;
   $('#pt-rate-status').title=r.note||r.source||'';
 }catch(e){
   const status=$('#pt-rate-status');if(status)status.textContent='P2P source unavailable · enter a rate manually';
 }
}
async function itCheckEnvCredentials(){
 try{
   const c=await api('/api/config-status');
   const ready=!!(c.binance_api_key_configured&&c.binance_api_secret_configured);
   const el=$('#pt-env-status');
   if(el)el.textContent=ready?'Configured on the server · values hidden':'Missing BINANCE_API_KEY or BINANCE_API_SECRET in Render service environment';
   const button=$('#pt-sync');
   if(button){button.disabled=!ready;button.title=ready?'Uses server environment credentials; no key is sent from this browser':'Add the two credential variables in Render environment settings';}
   return c;
 }catch(e){
   const el=$('#pt-env-status');if(el)el.textContent='Could not verify server configuration: '+e.message;
   return null;
 }
}
'''
    # Replace the old implementations as complete function blocks, avoiding
    # partial edits to nested callback bodies.
    p2p_re = re.compile(r'async function itLoadP2PRates\(\)\s*\{.*?(?=\nasync function itLoadProfitTax\()', re.S)
    js, c1 = p2p_re.subn(new_p2p + "\n", js, count=1)
    if c1 != 1:
        raise RuntimeError(f"Could not replace P2P client function (matches={c1})")
    tax_re = re.compile(r'async function itLoadProfitTax\(\)\s*\{.*?(?=\nasync function itSyncBinance\(\))', re.S)
    js, c2 = tax_re.subn("async function itLoadProfitTax(autoSync=false){\n  try{const d=await api('/api/profit-tax/summary');itRenderTax(d);await itCheckEnvCredentials();if(autoSync&&!window.__biTaxEnvSyncAttempted){window.__biTaxEnvSyncAttempted=true;const c=await api('/api/config-status').catch(()=>null);if(c&&c.binance_api_key_configured&&c.binance_api_secret_configured){const b=$('#pt-sync');if(b){b.disabled=true;b.textContent='Fetching Binance income from server credentials…'}try{const r=await api('/api/profit-tax/sync',{method:'POST',body:JSON.stringify({lookback_days:Number($('#pt-days').value||30),strategy_name:($('#pt-strategy-sync').value||'Unattributed Binance Futures').trim()})});itRenderTax(r);toast('Server sync complete: '+n(r.sync&&r.sync.fetched_supported_income_records,0)+' income records fetched; '+n(r.sync&&r.sync.new_records_saved,0)+' new records saved.','success')}catch(err){const w=$('#pt-warning');if(w)w.textContent='Automatic Binance sync failed: '+err.message+'. The server variables are configured; check read-only/Futures permissions, IP restrictions and API validity.'}finally{if(b){b.disabled=false;b.textContent='Fetch Binance Futures income using server credentials'}}}else{const w=$('#pt-warning');if(w)w.textContent='Set BINANCE_API_KEY and BINANCE_API_SECRET in Render environment settings; do not paste credentials into this page.'}}}catch(e){$('#pt-warning').textContent='Unable to load Profit & Tax Centre: '+e.message;$('#pt-ledger-status').textContent='Data load failed'}\n}\n", js, count=1)
    if c2 != 1:
        raise RuntimeError(f"Could not replace Profit & Tax client function (matches={c2})")
    sync_re = re.compile(r'async function itSyncBinance\(\)\s*\{.*?(?=\nasync function itImportTaxCsv\(\))', re.S)
    js, c3 = sync_re.subn(new_p2p.split("async function itCheckEnvCredentials")[0] + new_p2p[new_p2p.index("async function itSyncBinance"): ] if False else r'''async function itSyncBinance(){
 const days=Number($('#pt-days').value||30),label=($('#pt-strategy-sync').value||'Unattributed Binance Futures').trim(),b=$('#pt-sync');
 if(b){b.disabled=true;b.textContent='Fetching Binance income from server credentials…'}
 try{
   const cfg=await api('/api/config-status');
   if(!cfg.binance_api_key_configured||!cfg.binance_api_secret_configured)throw new Error('BINANCE_API_KEY and BINANCE_API_SECRET must be configured in Render environment settings.');
   const d=await api('/api/profit-tax/sync',{method:'POST',body:JSON.stringify({lookback_days:days,strategy_name:label})});
   itRenderTax(d);toast('Binance income fetched: '+n(d.sync&&d.sync.fetched_supported_income_records,0)+'; new records saved: '+n(d.sync&&d.sync.new_records_saved,0)+'.','success');
 }catch(e){toast('Binance sync failed: '+e.message,'error');const warning=$('#pt-warning');if(warning)warning.textContent='Binance sync failed: '+e.message}
 finally{if(b){b.disabled=false;b.textContent='Fetch Binance Futures income using server credentials'}}
}
''', js, count=1)
    if c3 != 1:
        raise RuntimeError(f"Could not replace credential-posting client function (matches={c3})")

    # Make Portfolio Lab always initialise its data and forecast, with visible empty/error
    # states instead of leaving stale placeholders when insufficient history is the issue.
    pl_loader = r'''async function loadPortfolioLab(autoForecast=true){
 try{
   if(!pl)throw new Error('Portfolio Lab state is unavailable in this JavaScript bundle.');
   pl.market=$('#pl-market').value||'FUTURES';
   const body=$('#pl-profile-rows');if(body)body.innerHTML='<tr><td colspan="9" class="empty-state">Loading stored portfolios…</td></tr>';
   const d=await api('/api/portfolio-lab/portfolios?market_type='+encodeURIComponent(pl.market));
   if(d&&d.error)throw new Error(d.error);
   pl.portfolios=Array.isArray(d.items)?d.items:[];
   if(typeof plRenderPortfolios==='function')plRenderPortfolios();
   if(pl.selected&&pl.portfolios.some(t=>Number(t.id)===Number(pl.selected))&&typeof plLoadPortfolio==='function')await plLoadPortfolio(pl.selected,pl.offset||0);
   else pl.selected=null;
   if(!pl.portfolios.length&&pl.market==='SPOT'){
     const note=$('#pl-rank-note');if(note)note.textContent='Spot raw activity is available, but there are no verified closed Spot PnL records to support a reliable forecast. No gains are invented.';
   }
   if(autoForecast!==false&&typeof plRunForecast==='function')await plRunForecast();
 }catch(e){
   const msg='Portfolio Lab initialisation failed: '+String(e&&e.message||e);
   for(const id of ['pl-rank-note','pl-model-notes']){const el=$('#'+id);if(el)el.textContent=msg}
   const rows=$('#pl-profile-rows');if(rows)rows.innerHTML='<tr><td colspan="9" class="empty-state">'+esc(msg)+'</td></tr>';
   const rank=$('#pl-rank-rows');if(rank)rank.innerHTML='<tr><td colspan="10" class="empty-state">'+esc(msg)+'</td></tr>';
   const unready=$('#pl-unready-rows');if(unready)unready.innerHTML='<tr><td colspan="5" class="empty-state">'+esc(msg)+'</td></tr>';
   console.error('BI_PORTFOLIO_LAB_INIT_FAILED',e);
 }
}
'''
    # Keep existing detailed PnL renderer; only ensure the forecast is requested whenever a user opens the page.
    js += "\n" + pl_loader + "\n"
    # Improve Trade Behaviour's zero-row filter behavior and consistent failure messaging.
    tb_loader = r'''async function loadTradeBehaviour(){
 const market=$('#tb-market').value||'FUTURES',period=$('#tb-period').value||'30';
 const minWr=Number($('#tb-min-win-rate').value||0),sortBy=$('#tb-sort').value||'STABILITY';
 const q=new URLSearchParams({market_type:market,period_days:period,min_win_rate_pct:String(minWr),sort_by:sortBy,limit:'250'});
 const note=$('#tb-note'),body=$('#tb-rows');
 if(note)note.textContent='Loading recorded trade behaviour and evidence coverage…';
 if(body)body.innerHTML='<tr><td colspan="7" class="empty-state">Loading verified trade statistics…</td></tr>';
 try{
   let d=await api('/api/trade-behaviour?'+q.toString());
   if(d&&d.error)throw new Error(d.error);
   if(!Array.isArray(d.items))throw new Error('Trade Behaviour API returned an unexpected response.');
   if(!d.items.length&&minWr>0){
     q.set('min_win_rate_pct','0');
     d=await api('/api/trade-behaviour?'+q.toString());
     if(d&&d.error)throw new Error(d.error);
     if(note)note.textContent='No profile met the selected minimum win rate; showing the complete stored universe without that filter. '+(d.note||'');
   }
   $('#tb-profiles').textContent=Number(d.profile_count||0).toLocaleString();
   $('#tb-activities').textContent=Number(d.activity_records||0).toLocaleString();
   $('#tb-closed').textContent=Number(d.verified_closed_trades||0).toLocaleString();
   $('#tb-paths').textContent=Number(d.analysed_paths||0).toLocaleString();
   $('#tb-meta').textContent=Number(d.profiles_displayed||0)+' shown · '+String(d.effective_period||period+'D')+' · '+String(d.sort_by||sortBy);
   if(note&&!note.textContent.startsWith('No profile met'))note.textContent=(d.note||'Ranking uses stored database evidence.')+(Number(d.minimum_win_rate_pct||0)>0?' Minimum effective win rate '+d.minimum_win_rate_pct+'% applied.':' No minimum win-rate filter applied.');
   const rows=d.items||[];
   body.innerHTML=rows.length?rows.map(t=>'<tr><td><b>'+esc(t.nickname||'Unknown')+'</b><small style="display:block">'+esc(t.portfolio_id||'')+' · '+esc(t.market_type||market)+'</small><a target="_blank" rel="noopener noreferrer" href="'+esc(t.profile_url||'#')+'">Open Binance ↗</a></td><td>'+Number(t.activity_records||0)+' / '+Number(t.verified_closed_trades||0)+' / '+Number(t.analysed_paths||0)+'</td><td>Source '+tbPct(t.source_win_rate_pct)+'<small style="display:block">Closed '+tbPct(t.closed_win_rate_pct)+'</small><small>'+esc(t.win_rate_basis||'NOT_CAPTURED')+'</small></td><td>'+(t.profit_factor==='INF'?'∞':(t.profit_factor==null?'—':Number(t.profit_factor).toFixed(2)))+'<small style="display:block">'+tbMoney(t.net_realized_pnl_usd)+'</small><small>'+Number(t.wins||0)+' W / '+Number(t.losses||0)+' L</small></td><td>Median '+tbPct(t.median_mae_pct)+'<small style="display:block">P90 '+tbPct(t.p90_mae_pct)+' · MFE '+tbPct(t.median_mfe_pct)+'</small><small>Paths '+Number(t.path_sample_size||0)+'</small></td><td>ROI '+tbPct(t.period_roi_pct)+'<small style="display:block">MDD '+tbPct(t.period_mdd_pct)+'</small><small>'+tbStamp(t.first_trade_ms)+' → '+tbStamp(t.last_trade_ms)+'</small></td><td><b>'+(t.stability_score==null?'—':Number(t.stability_score).toFixed(1)+'/100')+'</b><small style="display:block">'+Number(t.stability_confidence_pct||0).toFixed(0)+'% evidence confidence</small></td></tr>').join(''):'<tr><td colspan="7" class="empty-state">No portfolio rows were returned. Confirm the database connection and choose a longer period or remove filters. Raw Spot fills without verified realised PnL remain unranked.</td></tr>';
 }catch(e){
   if($('#tb-meta'))$('#tb-meta').textContent='Load failed';
   if(note)note.textContent='Trade Behaviour failed: '+String(e&&e.message||e);
   if(body)body.innerHTML='<tr><td colspan="7" class="empty-state">'+esc(String(e&&e.message||e))+'</td></tr>';
   console.error('BI_TRADE_BEHAVIOUR_LOAD_FAILED',e);
 }
}
'''
    js += "\n" + tb_loader + "\n"
    # Robust Multi-Trader request helper. renderMT() remains the canonical table renderer.
    mt_loader = r'''async function loadMultiTrader(persist=false){
 try{
   const d=persist?await api('/api/multi-trader/evaluate',{method:'POST',body:JSON.stringify(mtFilters())}):await api('/api/multi-trader/candidates?'+mtQuery());
   if(d&&d.error)throw new Error(d.error);
   if(!Array.isArray(d.candidates))throw new Error('Multi-Trader API response is missing its candidate list.');
   renderMT(d);
   if(typeof loadMTHistory==='function')await loadMTHistory();
   if(persist)toast('Evaluation saved #'+d.evaluation_id+': '+Number(d.selected_count||0)+' selected; '+Number(d.blocked_count||0)+' blocked/incomplete.','success');
   if(!d.eligible_count&&d.monitored_count){
     const note=$('#mt-note');if(note)note.textContent='All '+d.monitored_count+' stored profiles are currently blocked by the configured evidence/risk gates. This is a populated evaluation, not a blank result. Check each row’s missing-history, drawdown, copier PnL and duration reasons.';
   }
 }catch(e){
   const msg='Multi-Trader analysis failed: '+String(e&&e.message||e);
   const note=$('#mt-note');if(note)note.textContent=msg;
   const rows=$('#mt-rows');if(rows)rows.innerHTML='<tr><td colspan="14" class="empty-state">'+esc(msg)+'</td></tr>';
   console.error('BI_MULTI_TRADER_LOAD_FAILED',e);
 }
}
'''
    js += "\n" + mt_loader + "\n// BI_PAGE_RELIABILITY_FIXES_V2\n"
    JS.write_text(js)

print("Installed page reliability fixes: server-managed tax credentials, expanded page routing, corrected Multi-Trader argument mapping, and robust page loaders.")
