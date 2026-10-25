from pathlib import Path
import re

root = Path("/app")
app_path = root / "app.py"
js_path = root / "static" / "app.js"
html_path = root / "templates" / "index.html"

# Stable session signing avoids random-cookie invalidation across deploys/workers.
app = app_path.read_text()
if "BINANCE_INTEL_SESSION_STABILITY_V1" not in app:
    match = re.search(r"(?m)^app\.secret_key\s*=.*$", app)
    if not match:
        raise RuntimeError("Could not find Flask session-key assignment")
    stable = '''# BINANCE_INTEL_SESSION_STABILITY_V1
_session_password = os.getenv("APP_PASSWORD", "")
_session_key = os.getenv("APP_SECRET_KEY", "").strip()
if not _session_key and _session_password:
    _session_key = __import__("hashlib").sha256(
        ("binance-intelligence-session-v1:" + _session_password).encode("utf-8")
    ).hexdigest()
if not _session_key:
    _session_key = secrets.token_hex(32)
app.secret_key = _session_key
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
app.permanent_session_lifetime = __import__("datetime").timedelta(days=7)'''
    app = app[:match.start()] + stable + app[match.end():]
    app = re.sub(
        r'(?m)^([ \t]*)session\["authenticated"\]\s*=\s*True\s*$',
        r'\1session["authenticated"] = True\n\1session.permanent = True',
        app,
        count=1
    )
    app_path.write_text(app)
    print("Stable session signing and persistent login installed")

# Preserve same-origin cookies on every dashboard API call and avoid stale API caching.
js = js_path.read_text()
if "credentials:opts.credentials||'same-origin'" not in js:
    old_fetch = "fetch(url,{...opts,headers:{"
    new_fetch = "fetch(url,{...opts,credentials:opts.credentials||'same-origin',cache:'no-store',headers:{"
    if old_fetch not in js:
        raise RuntimeError("Could not patch authenticated fetch wrapper")
    js = js.replace(old_fetch, new_fetch, 1)

# Auto-run portfolio forecast on entry or refresh.
old_load = "plRenderPortfolios();await plLoadDailyHistory();if(!pl.portfolios.length"
new_load = "plRenderPortfolios();await plLoadDailyHistory();await plRunForecast();if(!pl.portfolios.length"
if new_load not in js:
    if js.count(old_load) != 1:
        raise RuntimeError(f"Portfolio Lab load anchor count={js.count(old_load)}")
    js = js.replace(old_load, new_load, 1)
js = js.replace(
    "$('#pl-refresh').addEventListener('click',async()=>{await loadPortfolioLab();await plRunForecast()});",
    "$('#pl-refresh').addEventListener('click',async()=>{await loadPortfolioLab()});"
)
js = js.replace(
    "$('#pl-market').addEventListener('change',async()=>{pl.selected=null;await loadPortfolioLab();await plRunForecast()});",
    "$('#pl-market').addEventListener('change',async()=>{pl.selected=null;await loadPortfolioLab()});"
)

# Add visible market + profile URL + both source and recorded-trade win rates to forecast rankings.
if "PL_FORENSICS_COLUMNS_V2" not in js:
    old_row = r"""function plRankRow(t,ranked){return '<tr><td>'+(ranked?t.forecast_rank:'—')+'</td><td><b>'+esc(t.nickname||'Unknown')+'</b><small style="display:block">'+esc(t.portfolio_id||'')+'</small>'+plLink(t.profile_url)+'</td><td>'+plUsd(t.expected_horizon_profit_usd)"""
    new_row = r"""function plRankRow(t,ranked){return '<tr><td>'+(ranked?t.forecast_rank:'—')+'</td><td><b>'+esc(t.nickname||'Unknown')+'</b><small style="display:block">'+esc((t.market_type||pl.market).toUpperCase())+' · '+esc(t.portfolio_id||'')+'</small>'+plLink(t.profile_url)+'</td><td>'+plPct(t.source_win_rate)+'</td><td>'+plPct(t.closed_trade_win_rate_pct)+'</td><td>'+plUsd(t.expected_horizon_profit_usd)"""
    if old_row in js:
        js = js.replace(old_row, new_row, 1)
    else:
        raise RuntimeError("Cannot patch Portfolio Lab ranking row: source anchor mismatch")
    js = js.replace(
        "const rows=[['Closed records',b.closed_pnl_records],['Closed-trade win rate',plPct(b.closed_trade_win_rate_pct)]",
        "const rows=[['Market',b.market_type||pl.market],['Source platform win rate',plPct(b.source_platform_win_rate_pct)],['Closed records',b.closed_pnl_records],['Closed-trade win rate',plPct(b.closed_trade_win_rate_pct)]",
        1
    )
    js = js.replace(
        "['Maximum leverage',b.max_observed_leverage===null?'—':Number(b.max_observed_leverage).toFixed(2)+'×'],['Average MAE'",
        "['Maximum leverage',b.market_type==='SPOT'?'Spot (not leveraged)':(b.max_observed_leverage===null?'Unknown':Number(b.max_observed_leverage).toFixed(2)+'×')],['Leverage data coverage',plPct(b.leverage_coverage_pct)],['Average MAE'",
        1
    )
    js = js.replace(
        "margin allocation per trade; individual position estimates do not account for overlapping capital use.",
        "margin allocation per trade; ROI is used as reported and is not multiplied by leverage twice. Observed leverage informs notional cost estimates; missing leverage is labelled as incomplete evidence."
    )
    # These are the Portfolio Lab's ten-column table placeholders; two win-rate columns are added.
    old_leverage_cell = "(t.observed_median_leverage===null?'—':Number(t.observed_median_leverage).toFixed(2)+'×')"
    new_leverage_cell = "(t.market_type==='SPOT'?'Spot · no leverage':(t.observed_median_leverage===null?'Unknown':Number(t.observed_median_leverage).toFixed(2)+'×'))"
    if js.count(old_leverage_cell) != 1:
        raise RuntimeError("Cannot label Portfolio Lab leverage cell: source anchor mismatch")
    js = js.replace(old_leverage_cell, new_leverage_cell, 1)
    # Keep forecast loading, empty, and error rows aligned with the 12-column ranking table.
    forecast_start = js.find("async function plRunForecast()")
    forecast_end = js.find("function plRenderDailyForecast()", forecast_start)
    if forecast_start < 0 or forecast_end < 0:
        raise RuntimeError("Cannot align Portfolio Lab forecast table placeholders")
    forecast_js = js[forecast_start:forecast_end].replace('colspan="10" class="empty-state"', 'colspan="12" class="empty-state"')
    js = js[:forecast_start] + forecast_js + js[forecast_end:]
    # Error-state text is rendered by JS and does not need a colspan rewrite.
    js += "\n// PL_FORENSICS_COLUMNS_V2\n"

# Multi-Trader: add a working external official portfolio link and closed-trade win rate.
if "MT_OFFICIAL_LINK_AND_WR_V2" not in js:
    old_mt = r"""'<tr><td><strong>'+esc(t.nickname||"Unknown")+'</strong><small style="display:block;color:#8c98a8">'+esc(t.market_type)+' · '+esc(t.portfolio_id)+'</small></td><td>'+n(t.score,1)+'</td><td class="'+colorNum(t.roi_7d)+'">'+n(t.roi_7d,2,'%')"""
    new_mt = r"""'<tr><td><strong>'+esc(t.nickname||"Unknown")+'</strong><small style="display:block;color:#8c98a8">'+esc(t.market_type)+' · '+esc(t.portfolio_id)+'</small><a target="_blank" rel="noopener noreferrer" href="'+esc(t.profile_url||('https://www.binance.com/en-IN/copy-trading/lead-details/'+t.portfolio_id+'?timeRange=90D'))+'">Open official Binance profile ↗</a></td><td>'+n(t.score,1)+'</td><td>'+n(t.win_rate_pct,2,'%')+'</td><td class="'+colorNum(t.roi_7d)+'">'+n(t.roi_7d,2,'%')"""
    if old_mt in js:
        js = js.replace(old_mt, new_mt, 1)
    else:
        raise RuntimeError("Cannot patch Multi-Trader row: source anchor mismatch")
    js += "\n// MT_OFFICIAL_LINK_AND_WR_V2\n"

js_path.write_text(js)

# Keep table headers aligned with the new columns and enlarge all dashboard typography for laptops.
html = html_path.read_text()
html = html.replace(
    '<tbody id="pl-rank-rows"><tr><td colspan="10" class="empty-state">Run a forecast to rank available evidence.</td></tr></tbody>',
    '<tbody id="pl-rank-rows"><tr><td colspan="12" class="empty-state">Run a forecast to rank available evidence.</td></tr></tbody>',
    1
)
html = html.replace(
    "<th>Portfolio / official page</th><th>Expected PnL</th>",
    "<th>Portfolio / official page · market shown</th><th>Source win rate</th><th>Closed-trade win rate</th><th>Expected PnL</th>",
    1
)
html = html.replace(
    "<th>Portfolio</th><th>Score</th><th>ROI 7D</th>",
    "<th>Portfolio / official Binance page</th><th>Score</th><th>Stored trade win rate</th><th>ROI 7D</th>",
    1
)
if "Source win rate</th><th>Closed-trade win rate</th>" not in html:
    raise RuntimeError("Portfolio Lab win-rate headers did not apply")
if "Stored trade win rate</th>" not in html:
    raise RuntimeError("Multi-Trader win-rate header did not apply")
if "BINANCE_INTEL_DESKTOP_READABILITY_V1" not in html:
    css = '''<style id="BINANCE_INTEL_DESKTOP_READABILITY_V1">
html{font-size:16px!important}
body{font-size:16px!important;line-height:1.5}
p,.help-text,.run-sub,.notice-box,.metric-explain,label{font-size:15.5px!important;line-height:1.5}
h1{font-size:32px!important;line-height:1.2}h2{font-size:28px!important;line-height:1.25}
h3{font-size:21px!important;line-height:1.3}
button,.btn,input,select,textarea{font-size:16px!important;min-height:42px}
table th,table td{font-size:15px!important;padding:12px 14px!important;line-height:1.45}
small,.eyebrow,.tag,.kpi-foot{font-size:13px!important}
.kpi-value{font-size:32px!important;line-height:1.15}
.nav-link{font-size:16px!important;min-height:44px}
.panel{padding:22px}
@media(min-width:1100px){body{font-size:17px!important}.help-text,p,.run-sub,.notice-box{font-size:16px!important}table th,table td{font-size:15.5px!important}.kpi-value{font-size:34px!important}}
</style>'''
    if "</head>" not in html:
        raise RuntimeError("Cannot increase typography: missing head close tag")
    html = html.replace("</head>", css + "\n</head>", 1)
html_path.write_text(html)

# Portfolio Lab forecast: use source ROI without multiplying it by leverage a second time.
# Show observed leverage and its coverage so the user can tell actual evidence from assumptions.
app = app_path.read_text()
if "PL_FORECAST_LEVERAGE_AND_WINRATE_V2" not in app:
    app = app.replace(
        "def pl_simulate_history(rows, capital, allocation_pct, extra_cost_bps):",
        "def pl_simulate_history(rows, capital, allocation_pct, extra_cost_bps, market_type='FUTURES'):",
        1
    )
    app = app.replace(
        "sim=pl_simulate_history(hist,capital,allocation,cost)",
        "sim=pl_simulate_history(hist,capital,allocation,cost,market)",
        1
    )
    app = app.replace(
        "ready=len(hist)>=15 and active>=10 and len(daily)>=10",
        "ready=len(hist)>=10 and active>=5 and len(daily)>=5",
        1
    )
    old_lev = "'observed_median_leverage':__import__('statistics').median([float(p.leverage) for p in hist if p.leverage is not None]) if any(p.leverage is not None for p in hist) else None,"
    new_lev = """'observed_median_leverage':(None if market=='SPOT' else (__import__('statistics').median([float(p.leverage) for p in hist if p.leverage is not None and float(p.leverage)>0]) if any(p.leverage is not None and float(p.leverage)>0 for p in hist) else None)),
                'observed_max_leverage':(None if market=='SPOT' else (max([float(p.leverage) for p in hist if p.leverage is not None and float(p.leverage)>0]) if any(p.leverage is not None and float(p.leverage)>0 for p in hist) else None)),
                'leverage_coverage_pct':(None if market=='SPOT' else (100.0*sum(1 for p in hist if p.leverage is not None and float(p.leverage)>0)/len(hist) if hist else 0.0)),
                'leverage_unknown_trades':(0 if market=='SPOT' else sum(1 for p in hist if p.leverage is None or float(p.leverage)<=0)),
                'closed_trade_win_rate_pct':(100.0*sum(1 for p in hist if p.close_pnl is not None and float(p.close_pnl)>0)/sum(1 for p in hist if p.close_pnl is not None) if any(p.close_pnl is not None for p in hist) else None),"""
    if old_lev in app:
        app = app.replace(old_lev, new_lev, 1)
    else:
        raise RuntimeError("Cannot patch forecast leverage fields: source anchor mismatch")
    app = app.replace(
        "'source_roi':t.roi,'source_pnl':t.pnl,'source_mdd':t.mdd,'source_win_rate':t.win_rate,",
        "'source_roi':t.roi,'source_pnl':t.pnl,'source_mdd':t.mdd,'source_win_rate':t.win_rate,'market_type':market,",
        1
    )
    app = app.replace(
        "'forecast_method':'350 bootstrap paths resampling recent daily results from stored closed trades in the last 120 days.',",
        "'forecast_method':'350 bootstrap paths resampling recent daily outcomes from stored closed trades in the last 120 days. ROI is used as reported on allocated margin and is not multiplied by leverage twice; observed leverage informs notional-cost assumptions.',",
        1
    )
    app = app.replace(
        "'This model is not actual copy-trader PnL and is not a promise of return.'],",
        "'For Futures trades with missing leverage, source ROI is retained and the additional execution-cost estimate uses a conservative 1x fallback; the leverage coverage column shows how much was actually reported.', 'This model is not actual copy-trader PnL and is not a promise of return.'],",
        1
    )
    app = app.replace(
        "# PORTFOLIO_LAB_DETAIL_V1",
        "# PL_FORECAST_LEVERAGE_AND_WINRATE_V2\n# PORTFOLIO_LAB_DETAIL_V1",
        1
    )
    app = app.replace(
        "behavior={'closed_trade_win_rate_pct':100*len(wins)/len(pnls) if pnls else None,",
        "behavior={'market_type':t.market_type,'source_platform_win_rate_pct':t.win_rate,'source_roi':t.roi,'source_mdd':t.mdd,'closed_trade_win_rate_pct':100*len(wins)/len(pnls) if pnls else None,",
        1
    )
    app = app.replace(
        "'extra_copy_cost_bps_of_notional':cost,'horizon_days':horizon,",
        "'extra_copy_cost_bps_of_notional':cost,'horizon_days':horizon,'investment_scenario_note':'The chosen investment is total capital; allocation_pct is the fraction reserved per concurrent position. Source ROI is the reported ROI and is not multiplied by leverage twice.',",
        1
    )
    app_path.write_text(app)

# Ensure Portfolio Lab fallback URLs use the same official detail URL format as stored profiles.
app = app_path.read_text()
app = app.replace(
    "'https://www.binance.com/en/copy-trading/'+('spot' if market=='SPOT' else 'futures')+'/lead-details/'+str(t.portfolio_id)",
    "'https://www.binance.com/en-IN/copy-trading/lead-details/'+str(t.portfolio_id)+'?timeRange=90D'"
)
app = app.replace(
    "'https://www.binance.com/en/copy-trading/'+('spot' if t.market_type=='SPOT' else 'futures')+'/lead-details/'+str(t.portfolio_id)",
    "'https://www.binance.com/en-IN/copy-trading/lead-details/'+str(t.portfolio_id)+'?timeRange=90D'"
)
app_path.write_text(app)

print("BINANCE_INTEL_FIXES: stable login sessions, authenticated fetch, automatic forecast, official profile links, win-rate/leverage fields, and desktop typography installed")
