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
import json as _bi_tax_json
import re as _bi_tax_re
import time as _bi_conn_time
import hmac as _bi_conn_hmac
import hashlib as _bi_conn_hashlib
import json as _bi_conn_json
import urllib.parse as _bi_conn_parse
import urllib.request as _bi_conn_request
import urllib.error as _bi_conn_error

_BI_TAX_SYNC_LOCK = _bi_tax_threading.RLock()
_BI_TAX_SYNC_STATE = {
    "status": "WAITING",
    "last_attempt_utc": None,
    "last_success_utc": None,
    "records_received": 0,
    "records_fetched": 0,
    "records_inserted": 0,
    "unsupported_income_type_counts": {},
    "lookback_days": 90,
    "error": None,
    "source": "Binance USD-M Futures income history",
    "connection_check": {
        "status": "NOT_RUN",
        "checked_at_utc": None,
        "spot_read": {"status": "NOT_RUN"},
        "futures_read": {"status": "NOT_RUN"},
        "api_restrictions": {"status": "NOT_RUN"},
        "copy_history": {"status": "NOT_VERIFIED",
                         "note": "Spot/Futures account authentication is not a Copy Trading portfolio-history feed."},
    },
}

def _bi_tax_utc_now():
    return _it_dt.datetime.now(_it_dt.timezone.utc).isoformat()

def _bi_tax_set_state(**values):
    with _BI_TAX_SYNC_LOCK:
        _BI_TAX_SYNC_STATE.update(values)

def _bi_tax_signed_probe(base_url, path, key, secret):
    """Call one signed read endpoint; return a minimal diagnostic, never raw account data."""
    params = {"timestamp": int(_bi_conn_time.time() * 1000), "recvWindow": 5000}
    query = _bi_conn_parse.urlencode(params)
    signature = _bi_conn_hmac.new(secret.encode("utf-8"), query.encode("utf-8"), _bi_conn_hashlib.sha256).hexdigest()
    url = base_url + path + "?" + query + "&signature=" + signature
    req = _bi_conn_request.Request(
        url,
        headers={"X-MBX-APIKEY": key, "Accept": "application/json", "User-Agent": "Binance-Intel-ReadOnly-Connection-Check"},
        method="GET",
    )
    status_code = None
    payload = None
    try:
        with _bi_conn_request.urlopen(req, timeout=10) as response:
            status_code = int(response.status)
            payload = _bi_conn_json.loads(response.read(2_000_000).decode("utf-8", "replace"))
    except _bi_conn_error.HTTPError as exc:
        status_code = int(exc.code)
        try:
            payload = _bi_conn_json.loads(exc.read(100_000).decode("utf-8", "replace"))
        except Exception:
            payload = None
    except Exception as exc:
        return {"status": "ERROR", "http_status": None, "api_code": None,
                "reason": "Network request failed (" + type(exc).__name__ + ")."}, None
    api_code = payload.get("code") if isinstance(payload, dict) else None
    try:
        code_int = int(api_code) if api_code is not None else None
    except Exception:
        code_int = None
    rejected = isinstance(payload, dict) and code_int is not None and code_int < 0
    if status_code is not None and 200 <= status_code < 300 and not rejected:
        return {"status": "PASS", "http_status": status_code, "api_code": None,
                "reason": "Authenticated read request succeeded."}, payload
    safe_reasons = {
        -2015: "Invalid API key, IP restriction, or endpoint permission.",
        -2014: "API key format was rejected.",
        -1022: "Signature verification failed. Check the API secret and request signing.",
        -1021: "Request timestamp was outside Binance recvWindow. Check server clock.",
        -1003: "Binance rate limit reached; retry later.",
    }
    reason = safe_reasons.get(code_int, "Binance rejected the signed request.")
    if status_code in (418, 429):
        reason = "Binance rate limit or temporary IP block; retry later."
    return {"status": "FAIL", "http_status": status_code, "api_code": code_int, "reason": reason}, None


def _bi_tax_verify_binance_connection():
    key = str(_bi_tax_os.getenv("BINANCE_API_KEY") or "").strip()
    secret = str(_bi_tax_os.getenv("BINANCE_API_SECRET") or "").strip()
    checked = _bi_tax_utc_now()
    if not key or not secret:
        result = {
            "status": "MISSING_CREDENTIALS", "checked_at_utc": checked,
            "spot_read": {"status": "SKIPPED", "reason": "Server credentials are missing."},
            "futures_read": {"status": "SKIPPED", "reason": "Server credentials are missing."},
            "api_restrictions": {"status": "SKIPPED", "reason": "Server credentials are missing."},
            "copy_history": {"status": "NOT_VERIFIED", "note": "Copy Trading portfolio history is a separate data scope."},
        }
        _bi_tax_set_state(connection_check=result)
        return result

    # Official signed account and key-permissions endpoints. Only tiny booleans are
    # extracted from payloads; balance arrays, positions and raw responses are discarded.
    restrictions, restriction_payload = _bi_tax_signed_probe(
        "https://api.binance.com", "/sapi/v1/account/apiRestrictions", key, secret
    )
    if restrictions.get("status") == "PASS" and isinstance(restriction_payload, dict):
        restrictions.update({
            "read_enabled": bool(restriction_payload.get("enableReading")),
            "ip_restricted": bool(restriction_payload.get("ipRestrict")),
            "spot_trading_permission_enabled": bool(restriction_payload.get("enableSpotAndMarginTrading")),
            "futures_trading_permission_enabled": bool(restriction_payload.get("enableFutures")),
            "withdrawal_permission_enabled": bool(restriction_payload.get("enableWithdrawals")),
            "internal_transfer_permission_enabled": bool(restriction_payload.get("enableInternalTransfer")),
            "universal_transfer_permission_enabled": bool(restriction_payload.get("permitsUniversalTransfer")),
        })
    spot, spot_payload = _bi_tax_signed_probe("https://api.binance.com", "/api/v3/account", key, secret)
    if spot.get("status") == "PASS":
        spot["account_read_verified"] = isinstance(spot_payload, dict) and ("balances" in spot_payload or "accountType" in spot_payload)
    futures, futures_payload = _bi_tax_signed_probe("https://fapi.binance.com", "/fapi/v2/account", key, secret)
    if futures.get("status") == "PASS":
        futures["account_read_verified"] = isinstance(futures_payload, dict) and ("assets" in futures_payload or "positions" in futures_payload)
    spot_ok = bool(spot.get("status") == "PASS" and spot.get("account_read_verified"))
    futures_ok = bool(futures.get("status") == "PASS" and futures.get("account_read_verified"))
    status = "VERIFIED" if spot_ok and futures_ok else ("PARTIAL" if spot_ok or futures_ok else "FAILED")
    risk_permissions = (
        "withdrawal_permission_enabled", "internal_transfer_permission_enabled",
        "universal_transfer_permission_enabled", "spot_trading_permission_enabled",
        "futures_trading_permission_enabled",
    )
    if restrictions.get("status") == "PASS":
        has_complete_permissions = all(k in restrictions for k in ("read_enabled",) + risk_permissions)
        if has_complete_permissions and restrictions.get("read_enabled") and not any(restrictions.get(k) for k in risk_permissions):
            security_posture = "READ_ONLY_CONFIRMED"
        elif has_complete_permissions and any(restrictions.get(k) for k in risk_permissions):
            security_posture = "REVIEW_REQUIRED"
        else:
            security_posture = "PERMISSIONS_INCOMPLETE"
    else:
        security_posture = "PERMISSIONS_UNVERIFIED"
    result = {
        "status": status, "security_posture": security_posture, "checked_at_utc": checked,
        "spot_read": spot, "futures_read": futures, "api_restrictions": restrictions,
        "copy_history": {
            "status": "NOT_VERIFIED",
            "note": "Successful Spot/Futures account reads do not prove that official API endpoints expose personal Copy Trading portfolio history. No undocumented browser-session endpoints are used.",
        },
    }
    _bi_tax_set_state(connection_check=result)
    app.logger.info("binance_connection_check status=%s security_posture=%s spot=%s futures=%s restrictions=%s copy_history=not_verified",
                    status, security_posture, spot.get("status"), futures.get("status"), restrictions.get("status"))
    return result


@app.post("/api/binance/connection-check")
def api_bi_binance_connection_check():
    return jsonify({"connection_check": _bi_tax_verify_binance_connection()})


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
        # Test signed Spot/Futures account reads first. The build smoke test stubs
        # this function so no external/private calls happen during image builds.
        _bi_tax_verify_binance_connection()
        # Supply environment secrets only to this in-process view call. They are not
        # sent to the browser, persisted, or logged by the sync worker.
        with app.test_request_context("/api/profit-tax/sync", method="POST", json={
            "api_key": key,
            "api_secret": secret,
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
            received = int(details.get("fetched_api_rows", details.get("fetched_supported_income_records", 0)) or 0)
            fetched = int(details.get("fetched_supported_income_records") or 0)
            inserted = int(details.get("new_records_saved") or 0)
            unsupported = details.get("unsupported_income_type_counts") or {}
            _bi_tax_set_state(status="SUCCEEDED" if received else "SUCCEEDED_NO_RECORDS",
                              last_attempt_utc=attempted, last_success_utc=attempted,
                              records_received=received, records_fetched=fetched, records_inserted=inserted,
                              unsupported_income_type_counts=unsupported,
                              lookback_days=days, error=None)
            app.logger.info("binance_personal_sync_completed trigger=%s lookback_days=%s rows_received=%s tax_relevant=%s inserted=%s unsupported_income_types=%s",
                            trigger, days, received, fetched, inserted, _bi_tax_json.dumps(unsupported, sort_keys=True))
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
    snapshot["credentials_validated_by_binance"] = snapshot.get("connection_check", {}).get("status") in ("VERIFIED", "PARTIAL")
    snapshot["scope_note"] = "Live diagnostic tests signed Spot and USD-M Futures account reads. Income history is separate and is not a complete personal Copy Trading history feed."
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
    diagnostic_ui = '<div class="button-row" style="margin-top:10px"><button type="button" class="btn secondary" id="bi-connection-check">Test live Binance connection</button><span id="bi-connection-result" class="help-text">Connection not yet verified.</span></div>'
    html = html.replace(anchor, anchor + '<p class="help-text">' + scope_note + '</p>' + diagnostic_ui, 1)
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
   const syncLabel=sync?(' · personal Futures sync: '+String(sync.status||'unknown').replaceAll('_',' ').toLowerCase()+(sync.records_received!==undefined?' · '+Number(sync.records_received||0)+' API rows / '+Number(sync.records_fetched||0)+' PnL-fee-funding rows':'')):'';
   if(el)el.textContent=(ready?'Configured on the server · values hidden':'Missing BINANCE_API_KEY or BINANCE_API_SECRET in Render service environment')+syncLabel;
   const cc=sync&&sync.connection_check;
   const result=$('#bi-connection-result');
   if(result&&cc)result.textContent='API access: '+String(cc.status||'unknown')+' · Spot read: '+String((cc.spot_read||{}).status||'unknown')+' · Futures read: '+String((cc.futures_read||{}).status||'unknown')+' · Copy history: not yet verified';
   if(sync&&sync.status==='FAILED'){
     const warning=$('#pt-warning');if(warning)warning.textContent='Automatic Binance Futures account sync failed: '+String(sync.error||'See Render logs')+'. Review the live connection test. Spot fills and Copy Trading portfolio history are separate data scopes.';
   }"""
    if js.count(old) != 1:
        raise RuntimeError("Cannot find unique credentials status client function anchor")
    js = js.replace(old, new, 1)
    js += r"""
// BI_TAX_SYNC_STATUS_UI_V2
async function biRunBinanceConnectionCheck(){
 const button=$('#bi-connection-check'), output=$('#bi-connection-result');
 if(!button||!output)return;
 button.disabled=true;button.textContent='Testing signed API access…';
 output.textContent='Checking signed API permissions, Spot read access and Futures read access. No trades or transfers are requested.';
 try{
   const response=await api('/api/binance/connection-check',{method:'POST',body:JSON.stringify({})});
   const c=response.connection_check||{};
   const reason=x=>String((x||{}).reason||((x||{}).status)||'unknown');
   output.textContent='Overall: '+String(c.status||'unknown')+
     ' | Key security: '+String(c.security_posture||'unknown')+
     ' | Spot read: '+String((c.spot_read||{}).status||'unknown')+' — '+reason(c.spot_read)+
     ' | Futures read: '+String((c.futures_read||{}).status||'unknown')+' — '+reason(c.futures_read)+
     ' | Permission lookup: '+String((c.api_restrictions||{}).status||'unknown')+
     ((c.api_restrictions||{}).status==='PASS'?' | Read enabled: '+String(!!c.api_restrictions.read_enabled)+' | Spot trading permission: '+String(!!c.api_restrictions.spot_trading_permission_enabled)+' | Futures trading permission: '+String(!!c.api_restrictions.futures_trading_permission_enabled)+' | Transfers: '+String(!!c.api_restrictions.internal_transfer_permission_enabled||!!c.api_restrictions.universal_transfer_permission_enabled)+' | Withdrawals: '+String(!!c.api_restrictions.withdrawal_permission_enabled):'')+
     ' | Personal Copy Trading history: NOT VERIFIED by these account endpoints.';
   if(typeof itCheckEnvCredentials==='function')await itCheckEnvCredentials();
   toast(c.status==='VERIFIED'?'Binance Spot and Futures read access verified; Copy Trading history is a separate check.':c.status==='PARTIAL'?'Partial Binance read access verified. Check endpoint details.':'Connection test completed; inspect the per-endpoint results.','info');
 }catch(e){output.textContent='Connection test could not complete: '+e.message;toast('Connection test failed: '+e.message,'error')}
 finally{button.disabled=false;button.textContent='Test live Binance connection'}
}
if(!window.__biConnectionCheckWired){
 window.__biConnectionCheckWired=true;
 document.addEventListener('click',function(event){
   const target=event.target&&event.target.closest?event.target.closest('#bi-connection-check'):null;
   if(target)biRunBinanceConnectionCheck();
 });
}
"""
    JS.write_text(js)

# The patches that add pages also rewrite the cache key before this patch runs.
# Bump it again after modifying app.js so browsers don't keep the old tax status UI.
html = HTML.read_text()
cache_count = 0
scan_from = 0
while True:
    script_start = html.find("<script", scan_from)
    if script_start < 0:
        break
    tag_end = html.find(">", script_start)
    src_pos = html.find("src=", script_start, tag_end)
    if tag_end < 0 or src_pos < 0:
        scan_from = tag_end + 1 if tag_end >= 0 else len(html)
        continue
    quote = html[src_pos + 4:src_pos + 5]
    value_start = src_pos + 5
    value_end = html.find(quote, value_start)
    if value_end < 0:
        raise RuntimeError("Malformed script src attribute while cache-busting app.js")
    src_value = html[value_start:value_end]
    if "app.js" in src_value:
        base_src = src_value.split("?v=", 1)[0].split("?", 1)[0]
        replacement_src = base_src + "?v=bi-frontend-20261028-connection-check2"
        html = html[:value_start] + replacement_src + html[value_end:]
        cache_count = 1
        break
    scan_from = tag_end + 1
if cache_count != 1:
    raise RuntimeError("Could not cache-bust final app.js asset after personal sync UI update")
HTML.write_text(html)

print("Installed scheduled server-environment Binance Futures income sync and visible sync diagnostics.")
