"""Automatically sync personal Binance Futures income from server env credentials.

No secret values are exposed. The worker records only last sync status and counts.
This is an account-income sync, separate from the public lead-trader crawler.
"""
from pathlib import Path

ROOT = Path("/app")
APP = ROOT / "app.py"
JS = ROOT / "static" / "app.js"
HTML = ROOT / "templates" / "index.html"

app_text = APP.read_text()
if "BI_TAX_AUTO_SYNC_WORKER_V1" not in app_text:
    worker = r'''

# BI_TAX_AUTO_SYNC_WORKER_V1
# Environment-key presence is not permission validation: the signed API call below
# is the actual test. This sync is read-only and imports supported USD-M Futures
# income events; it does not place orders or fetch all Spot per-symbol fills.
import threading as _bi_tax_threading
import time as _bi_tax_worker_time
import os as _bi_tax_os

_BI_TAX_SYNC_LOCK = _bi_tax_threading.RLock()
_BI_TAX_SYNC_STATE = {
    "status": "WAITING",
    "last_attempt_utc": None,
    "last_success_utc": None,
    "records_fetched": 0,
    "records_inserted": 0,
    "lookback_days": 90,
    "error": None,
    "source": "Binance USD-M Futures income history",
}

def _bi_tax_utc_now():
    return _it_dt.datetime.now(_it_dt.timezone.utc).isoformat()

def _bi_tax_set_state(**values):
    with _BI_TAX_SYNC_LOCK:
        _BI_TAX_SYNC_STATE.update(values)

def _bi_tax_sync_from_environment(trigger="startup"):
    key = str(_bi_tax_os.getenv("BINANCE_API_KEY") or "").strip()
    secret = str(_bi_tax_os.getenv("BINANCE_API_SECRET") or "").strip()
    attempted = _bi_tax_utc_now()
    if not key or not secret:
        _bi_tax_set_state(status="SKIPPED_MISSING_CREDENTIALS", last_attempt_utc=attempted,
                          error="BINANCE_API_KEY or BINANCE_API_SECRET is missing in the running process.")
        app.logger.warning("binance_personal_sync_skipped trigger=%s api_key_configured=%s api_secret_configured=%s",
                           trigger, bool(key), bool(secret))
        return
    if not _BI_TAX_SYNC_LOCK.acquire(blocking=False):
        app.logger.info("binance_personal_sync_skipped trigger=%s reason=sync_already_running", trigger)
        return
    _bi_tax_set_state(status="RUNNING", last_attempt_utc=attempted, error=None)
    try:
        days = max(1, min(90, int(_bi_tax_os.getenv("BI_TAX_SYNC_LOOKBACK_DAYS", "90"))))
        # Exercise the same signed route used by the page. The endpoint prefers the
        # environment values and accepts no credentials from this internal request.
        # Call the same Flask view directly inside a request context. Using
        # app.test_client() here runs the browser-login before_request gate and
        # returns the app's own HTTP 401 before Binance is contacted.
        with app.test_request_context("/api/profit-tax/sync", method="POST", json={
            "lookback_days": days,
            "strategy_name": "Unattributed Binance Futures",
            "trigger": trigger,
        }):
            route_result = api_it_tax_sync()
            response = app.make_response(route_result)
            payload = response.get_json(silent=True) or {}
        attempted = _bi_tax_utc_now()
        if response.status_code == 200 and not payload.get("error"):
            details = payload.get("sync") or {}
            fetched = int(details.get("fetched_supported_income_records") or 0)
            inserted = int(details.get("new_records_saved") or 0)
            _bi_tax_set_state(status="SUCCEEDED" if fetched else "SUCCEEDED_NO_RECORDS",
                              last_attempt_utc=attempted, last_success_utc=attempted,
                              records_fetched=fetched, records_inserted=inserted,
                              lookback_days=days, error=None)
            app.logger.info("binance_personal_sync_completed trigger=%s lookback_days=%s fetched=%s inserted=%s",
                            trigger, days, fetched, inserted)
        else:
            reason = str(payload.get("error") or "Binance sync endpoint returned HTTP " + str(response.status_code))[:240]
            _bi_tax_set_state(status="FAILED", last_attempt_utc=attempted,
                              lookback_days=days, error=reason)
            app.logger.error("binance_personal_sync_failed trigger=%s status_code=%s reason=%s",
                             trigger, response.status_code, reason)
    except Exception as exc:
        reason = str(exc)[:240]
        _bi_tax_set_state(status="FAILED", last_attempt_utc=_bi_tax_utc_now(), error=reason)
        app.logger.exception("binance_personal_sync_failed trigger=%s reason=%s", trigger, reason)
    finally:
        _BI_TAX_SYNC_LOCK.release()

@app.get("/api/profit-tax/sync-status")
def api_it_tax_sync_status():
    with _BI_TAX_SYNC_LOCK:
        snapshot = dict(_BI_TAX_SYNC_STATE)
    snapshot["api_key_configured"] = bool(_bi_tax_os.getenv("BINANCE_API_KEY"))
    snapshot["api_secret_configured"] = bool(_bi_tax_os.getenv("BINANCE_API_SECRET"))
    snapshot["credentials_validated_by_binance"] = snapshot["status"] in ("SUCCEEDED", "SUCCEEDED_NO_RECORDS")
    snapshot["scope_note"] = "Read-only USD-M Futures income events only; Spot per-symbol fills are not included in this API sync."
    return jsonify(snapshot)

def _bi_tax_sync_worker_loop():
    # Give the web process and database startup probes time to finish first.
    _bi_tax_worker_time.sleep(30)
    while True:
        try:
            _bi_tax_sync_from_environment("startup_or_scheduled")
        except Exception:
            app.logger.exception("binance_personal_sync_worker_unhandled_failure")
        # Refresh account income every six hours. Reimporting is idempotent due to
        # the ledger's unique external_id constraint.
        _bi_tax_worker_time.sleep(6 * 60 * 60)

if not getattr(app, "_bi_tax_sync_worker_started", False):
    app._bi_tax_sync_worker_started = True
    _bi_tax_worker = _bi_tax_threading.Thread(
        target=_bi_tax_sync_worker_loop, name="binance-personal-income-sync", daemon=True
    )
    _bi_tax_worker.start()
    app.logger.info("binance_personal_sync_worker_started cadence_hours=6 first_run_delay_seconds=30")

'''
    APP.write_text(app_text + worker)

# Add the account-specific scope and visible status to the tax panel.
html = HTML.read_text()
scope_note = "This read-only sync imports USD-M Futures income events. It does not import all Spot fills or identify which copy-trading leader caused each event; use Binance account CSV exports for Spot records and any missing periods."
if "This read-only sync imports USD-M Futures income events." not in html:
    anchor = '<span id="pt-env-status">Checking service configuration…</span>'
    if html.count(anchor) != 1:
        raise RuntimeError("Cannot find unique tax credential status element for sync-scope note")
    html = html.replace(anchor, anchor + '<p class="help-text">' + scope_note + '</p>', 1)
# The background worker now owns automatic sync; page navigation only reads
# status and summaries to avoid launching a second, concurrent signed request.
html = html.replace("await itLoadProfitTax(true);", "await itLoadProfitTax(false);")
html = html.replace("function(){return itLoadProfitTax(true)}", "function(){return itLoadProfitTax(false)}")
HTML.write_text(html)

js = JS.read_text()
if "BI_TAX_SYNC_STATUS_UI_V1" not in js:
    old = """   const c=await api('/api/config-status');
   const ready=!!(c.binance_api_key_configured&&c.binance_api_secret_configured);
   const el=$('#pt-env-status');
   if(el)el.textContent=ready?'Configured on the server · values hidden':'Missing BINANCE_API_KEY or BINANCE_API_SECRET in Render service environment';"""
    new = """   const c=await api('/api/config-status');
   const sync=await api('/api/profit-tax/sync-status').catch(()=>null);
   const ready=!!(c.binance_api_key_configured&&c.binance_api_secret_configured);
   const el=$('#pt-env-status');
   const syncLabel=sync?(' · personal Futures sync: '+String(sync.status||'unknown').replaceAll('_',' ').toLowerCase()+(sync.records_fetched!==undefined?' · '+Number(sync.records_fetched||0)+' records fetched':'')):'';
   if(el)el.textContent=(ready?'Configured on the server · values hidden':'Missing BINANCE_API_KEY or BINANCE_API_SECRET in Render service environment')+syncLabel;
   if(sync&&sync.status==='FAILED'){
     const warning=$('#pt-warning');if(warning)warning.textContent='Automatic Binance Futures account sync failed: '+String(sync.error||'See Render logs')+'. Credentials are present, but Binance must accept their signature and permissions. Spot fills are outside this sync.';
   }"""
    if js.count(old) != 1:
        raise RuntimeError("Cannot find unique credentials status client function anchor")
    js = js.replace(old, new, 1) + "\n// BI_TAX_SYNC_STATUS_UI_V1\n"
    JS.write_text(js)

print("Installed scheduled server-environment Binance Futures income sync and visible sync diagnostics.")
