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
