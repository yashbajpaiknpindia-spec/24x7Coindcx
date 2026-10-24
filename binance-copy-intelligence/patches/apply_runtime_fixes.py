from pathlib import Path

# Build-time, idempotent hotfixes applied after restoring the source bundle.
root = Path("/app")
collector = root / "collector.py"
s = collector.read_text()
s = s.replace('(("30D", "90D", "180D", "365D") if include_older else ("90D",))',
              '(("7D", "30D", "90D", "180D", "365D") if include_older else ("7D", "30D", "365D"))')
# Binance leaderboard page size is 30; stopping at 10 silently skipped valid rows/pages.
s = s.replace("if len(rows) < 10: break", "if len(rows) < 30: break")
old = '"spot_list_endpoint": client.spot_list_path if market_type == "SPOT" else None'
new = old + ', "periods_requested": sorted({r for r, _ in modes}), "data_quality": "SOURCE_VERIFIED" if total_new + total_updated else ("SOURCE_ERROR" if errors else "EMPTY_SOURCE_RESPONSE")'
s = s.replace(old, new)
collector.write_text(s)

app = root / "app.py"
s = app.read_text()
s = s.replace('td=_trader_dict(t)\n        # bounded detail endpoint;',
'''td=_trader_dict(t)
        try: td["period_metrics"] = json.loads(t.period_metrics or "{}")
        except Exception: td["period_metrics"] = {}
        # bounded detail endpoint;''')
s = s.replace(
    'snapshot_out=[{"captured_at":_iso(s.captured_at),"roi":s.roi,"pnl":s.pnl,"mdd":s.mdd,"win_rate":s.win_rate,"aum":s.aum,"copier_pnl":s.copier_pnl} for s in snapshots[-500:]]',
    'snapshot_out=[{"captured_at":_iso(s.captured_at),"time_range":s.time_range,"roi":s.roi,"pnl":s.pnl,"mdd":s.mdd,"win_rate":s.win_rate,"aum":s.aum,"copier_pnl":s.copier_pnl,"raw_json":s.raw_json} for s in snapshots[-1000:]]')
s = s.replace(
    '"spot_source_note":"Spot collector is auto-probed against undocumented website routes; if no route validates, the run shows an error instead of claiming Spot data was collected."',
    '"spot_source_note":"Spot collector is auto-probed against undocumented website routes; if no route validates, the run shows an error instead of claiming Spot data was collected.", "mdd_periods_required":["7D","30D","365D"], "mdd_periods_note":"Period values are source-reported when available; missing periods remain null and must not be inferred from another period."')
app.write_text(s)

js = root / "static" / "app.js"
s = js.read_text()
s = s.replace(
    "state.refreshTimer=setInterval(()=>{refreshStatus();loadRunsOnly();if(state.view==='traders')loadTraders();if(state.view==='history')loadPaths();},8000)",
    "state.refreshTimer=setInterval(()=>{refreshStatus();loadRunsOnly();},30000)")
old = "const pairs=[['ROI',n(t.roi,2,'%')],['PnL',n(t.pnl,2)],['MDD',n(t.mdd,2,'%')],['Platform win rate',n(t.win_rate,2,'%')],"
new = "const periods=t.period_metrics||{};const mddFor=k=>periods[k]&&periods[k].mdd!==undefined?n(periods[k].mdd,2,'%'):'Not reported';const pairs=[['MDD · 7 day',mddFor('7D')],['MDD · 30 day',mddFor('30D')],['MDD · 365 day',mddFor('365D')],['ROI',n(t.roi,2,'%')],['PnL',n(t.pnl,2)],['MDD · profile default',n(t.mdd,2,'%')],['Platform win rate',n(t.win_rate,2,'%')],"
s = s.replace(old, new)
js.write_text(s)


# Optional Binance API credentials: expose only whether keys exist, never key material.
# Portfolio discovery and leader-trade history still use Binance's public copy-trading
# endpoints; credentials do not guarantee access to private leader history.
app = root / "app.py"
s = app.read_text()
if "BINANCE_API_CREDENTIALS_CONFIGURED" not in s:
    s += '''

# Readiness-only endpoint: no API key/secret values are ever returned.
try:
    @app.get("/api/config-status")
    def binance_config_status():
        import os
        from flask import jsonify
        configured = bool(os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"))
        return jsonify({
            "binance_api_key_configured": bool(os.getenv("BINANCE_API_KEY")),
            "binance_api_secret_configured": bool(os.getenv("BINANCE_API_SECRET")),
            "binance_api_credentials_configured": configured,
            "credential_use": "optional; no private trading actions are enabled",
        })
except Exception:
    pass
'''
    app.write_text(s)


# Expose an auditable coverage report so "missing" is distinguishable from zero.
app = root / "app.py"
s = app.read_text()
if '@app.get("/api/coverage")' not in s:
    s += '''

@app.get("/api/coverage")
def api_coverage():
    from sqlalchemy import or_
    periods = ("7D", "30D", "365D")
    markets = {}
    latest_runs = {}
    with SessionLocal() as db:
        for market in ("FUTURES", "SPOT"):
            traders = list(db.scalars(select(Trader).where(
                Trader.exchange == "BINANCE", Trader.market_type == market
            )))
            missing_mdd = {period: 0 for period in periods}
            for trader in traders:
                try:
                    pm = json.loads(trader.period_metrics or "{}")
                except Exception:
                    pm = {}
                for period in periods:
                    value = pm.get(period)
                    if not isinstance(value, dict) or value.get("mdd") is None:
                        missing_mdd[period] += 1
            trader_filter = (Trader.exchange == "BINANCE", Trader.market_type == market)
            position_filter = (Trader.market_type == market,)
            profile_count = len(traders)
            history_pending = sum(
                1 for t in traders
                if t.history_synced_at is None or t.history_status in ("NOT_SYNCED", "ERROR")
            )
            position_rows = db.scalar(
                select(func.count(Position.id)).join(Trader).where(*position_filter)
            ) or 0
            path_analyzed = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter, Position.path_status == "ANALYZED"
                )
            ) or 0
            path_eligible_pending = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter,
                    Position.path_status != "ANALYZED",
                    Position.path_status != "UNPAIRED_SPOT_ACTIVITY",
                    Position.opened_ms.is_not(None),
                    Position.closed_ms.is_not(None),
                    Position.entry_price.is_not(None)
                )
            ) or 0
            path_missing_requirements = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter,
                    Position.path_status != "ANALYZED",
                    Position.path_status != "UNPAIRED_SPOT_ACTIVITY",
                    or_(Position.opened_ms.is_(None), Position.closed_ms.is_(None), Position.entry_price.is_(None))
                )
            ) or 0
            unpaired_spot = db.scalar(
                select(func.count(Position.id)).join(Trader).where(
                    *position_filter, Position.path_status == "UNPAIRED_SPOT_ACTIVITY"
                )
            ) or 0
            history_errors = sum(1 for t in traders if t.history_status == "ERROR")
            markets[market] = {
                "profiles": profile_count,
                "history_needing_sync_or_retry": history_pending,
                "history_errors": history_errors,
                "stored_positions": int(position_rows),
                "paths_analyzed": int(path_analyzed),
                "path_eligible_pending": int(path_eligible_pending),
                "path_missing_required_timestamps_or_entry": int(path_missing_requirements),
                "spot_unpaired_activity": int(unpaired_spot),
                "profiles_missing_source_reported_mdd": missing_mdd,
            }
        for kind in ("DISCOVERY", "HISTORY_SYNC", "PATH_ANALYSIS", "SCHEDULER"):
            row = db.scalar(select(ScanRun).where(ScanRun.kind == kind).order_by(ScanRun.id.desc()).limit(1))
            latest_runs[kind] = _run_dict(row) if row else None
    return jsonify({
        "markets": markets,
        "latest_runs": latest_runs,
        "scheduler_enabled": os.getenv("ENABLE_SCHEDULER", "false").lower() in ("1", "true", "yes"),
        "monitor_interval_minutes": max(15, int(os.getenv("MONITOR_INTERVAL_MINUTES", "30"))),
        "analysis_scope": "All stored source records are queued in bounded batches; unavailable or incomplete source history cannot be inferred."
    })
'''
    app.write_text(s)

# Surface the coverage counts and optional credential readiness on the existing System page.
js = root / "static" / "app.js"
s = js.read_text()
s = s.replace(
    "const [s,notes]=await Promise.all([api('/api/status'),api('/api/system/source-notes')]);",
    "const [s,notes,cov,config,h]=await Promise.all([api('/api/status'),api('/api/system/source-notes'),api('/api/coverage'),api('/api/config-status'),fetch('/health').then(r=>r.json()).catch(()=>({database:'unavailable'}))]);"
)
s = s.replace(
    "$('#system-health-tag').className='tag green';$('#system-health-tag').textContent='DATABASE CONNECTED';",
    "const pg=String(s.database_backend||'').startsWith('PostgreSQL');$('#system-health-tag').className='tag '+(h.database==='connected'?(pg?'green':'gray'):'red');$('#system-health-tag').textContent=h.database!=='connected'?'DATABASE UNAVAILABLE':(pg?'POSTGRESQL CONNECTED':'SQLITE · LOCAL / NON-DURABLE');"
)
s = s.replace(
    "['Automatic monitor',s.scheduler_enabled?'Enabled while awake':'Disabled'],['7D MDD not source-reported · Futures',cov.markets.FUTURES.profiles_missing_source_reported_mdd['7D']],['30D MDD not source-reported · Futures',cov.markets.FUTURES.profiles_missing_source_reported_mdd['30D']],['365D MDD not source-reported · Futures',cov.markets.FUTURES.profiles_missing_source_reported_mdd['365D']],['Profiles needing history sync/retry · Futures',cov.markets.FUTURES.history_needing_sync_or_retry],['Trades eligible but awaiting path analysis · Futures',cov.markets.FUTURES.path_eligible_pending],['Trades missing path timestamps/entry · Futures',cov.markets.FUTURES.path_missing_required_timestamps_or_entry],['Profiles needing history sync/retry · Spot',cov.markets.SPOT.history_needing_sync_or_retry],['Trades eligible but awaiting path analysis · Spot',cov.markets.SPOT.path_eligible_pending],['Binance API key',config.binance_api_key_configured?'Configured':'Not set'],['Binance API secret',config.binance_api_secret_configured?'Configured':'Not set']].map",
    "['Automatic monitor',s.scheduler_enabled?'Enabled while instance is awake':'Disabled'],['7D MDD not source-reported · Futures',cov.markets.FUTURES.profiles_missing_source_reported_mdd['7D']],['30D MDD not source-reported · Futures',cov.markets.FUTURES.profiles_missing_source_reported_mdd['30D']],['365D MDD not source-reported · Futures',cov.markets.FUTURES.profiles_missing_source_reported_mdd['365D']],['Profiles needing history sync/retry · Futures',cov.markets.FUTURES.history_needing_sync_or_retry],['Trades eligible but awaiting path analysis · Futures',cov.markets.FUTURES.path_eligible_pending],['Trades missing path timestamps/entry · Futures',cov.markets.FUTURES.path_missing_required_timestamps_or_entry],['Profiles needing history sync/retry · Spot',cov.markets.SPOT.history_needing_sync_or_retry],['Trades eligible but awaiting path analysis · Spot',cov.markets.SPOT.path_eligible_pending],['Binance API key',config.binance_api_key_configured?'Configured':'Not set'],['Binance API secret',config.binance_api_secret_configured?'Configured':'Not set']].map"
)
js.write_text(s)
