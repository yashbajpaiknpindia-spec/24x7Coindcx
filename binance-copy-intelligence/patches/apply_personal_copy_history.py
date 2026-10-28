"""Install a dedicated importer for the user's private Binance Copy Trading exports.

Official user-data API endpoints do not currently document a complete personal copier
portfolio-history feed. This patch ingests official exported CSVs, preserves original
rows for audit, avoids mistaking trade notional for realised PnL, and deduplicates rows.
"""
from pathlib import Path

ROOT = Path("/app")
APP = ROOT / "app.py"
HTML = ROOT / "templates" / "index.html"
JS = ROOT / "static" / "app.js"

app = APP.read_text()
if "BI_PERSONAL_COPY_HISTORY_IMPORT_V1" not in app:
    app += r'''

# BI_PERSONAL_COPY_HISTORY_IMPORT_V1
# Separate importer for Binance Copy Trading portfolio-history CSV exports.
# No browser session cookies, private website endpoints, or trading permissions are used.
import csv as _pc_csv
import hashlib as _pc_hashlib
import io as _pc_io
import json as _pc_json
import re as _pc_re

def _pc_norm(value):
    return _pc_re.sub(r"\s+", " ", _pc_re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()

def _pc_get(row, *names):
    names_norm = [_pc_norm(x) for x in names]
    for name in names_norm:
        if name in row and str(row.get(name) or "").strip():
            return str(row.get(name)).strip()
    for name in names_norm:
        for key, value in row.items():
            if name and name in key and str(value or "").strip():
                return str(value).strip()
    return None

def _pc_num(value):
    if value is None:
        return None
    raw = str(value).strip().replace(",", "").replace("$", "").replace("USDT", "").replace("USDⓈ", "").strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1].strip()
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    if not raw or raw in ("-", "—", "N/A", "n/a", "null", "None"):
        return None
    try:
        number = float(raw)
        return number if _it_math.isfinite(number) else None
    except Exception:
        return None

def _pc_import_records(reader, source_kind, market_type, strategy_name):
    kind = str(source_kind or "COPY_PORTFOLIO_HISTORY").upper()
    market = str(market_type or "FUTURES").upper()
    if kind == "FUTURES_COPY_TRADE_HISTORY":
        market = "FUTURES"
    elif kind == "SPOT_COPY_TRADE_HISTORY":
        market = "SPOT"
    source = {
        "ACCOUNT_PNL_CSV": "BINANCE_ACCOUNT_PNL_CSV",
        "FUTURES_COPY_TRADE_HISTORY": "BINANCE_FUTURES_COPY_HISTORY_CSV",
        "SPOT_COPY_TRADE_HISTORY": "BINANCE_SPOT_COPY_HISTORY_CSV",
        "COPY_PROFIT_SHARING": "BINANCE_COPY_PROFIT_SHARING_CSV",
        "COPY_BALANCE_HISTORY": "BINANCE_COPY_BALANCE_HISTORY_CSV",
        "COPY_PORTFOLIO_HISTORY": "BINANCE_COPY_PORTFOLIO_HISTORY_CSV",
    }.get(kind, "BINANCE_COPY_PORTFOLIO_HISTORY_CSV")
    strategy = str(strategy_name or "Imported Binance Copy Trading history").strip()[:100] or "Imported Binance Copy Trading history"
    out = []
    skipped = 0
    categories = {}
    supported_income_types = ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE")

    def add(row, typ, amount, pnl=0.0, commission=0.0, funding=0.0, asset="USDT", row_index=0, suffix=""):
        nonlocal out
        time_value = _pc_get(row, "time", "timestamp", "date", "datetime", "transaction time", "create time", "close time", "close date", "trade time", "order time", "open time")
        symbol = _pc_get(row, "symbol", "trading pair", "pair", "market")
        trade_id = _pc_get(row, "trade id", "tradeid", "tran id", "tranid", "transaction id", "order id", "orderid", "copy id", "portfolio id", "id") or ""
        asset_value = str(_pc_get(row, "asset", "income asset", "pnl asset", "settlement asset", "quote asset") or asset or "USDT").upper()
        amount_value = float(amount or 0.0)
        amount_usdt = amount_value if asset_value == "USDT" else None
        canonical = _pc_json.dumps({"kind": kind, "market": market, "row": row, "suffix": suffix}, sort_keys=True, ensure_ascii=False, default=str)
        fingerprint = _pc_hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        out.append({
            "external_id": "COPY_CSV:" + fingerprint,
            "strategy_name": strategy,
            "market_type": market,
            "symbol": str(symbol or ""),
            "trade_id": str(trade_id),
            "income_type": str(typ).upper(),
            "transaction_time": _it_clean_time(time_value),
            "asset": asset_value,
            "amount_asset": amount_value,
            "amount_usdt": amount_usdt,
            "realized_pnl_usdt": float(pnl or 0.0) if asset_value == "USDT" else 0.0,
            "commission_usdt": float(commission or 0.0) if asset_value == "USDT" else 0.0,
            "funding_usdt": float(funding or 0.0) if asset_value == "USDT" else 0.0,
            "source": source,
            "raw_json": _pc_json.dumps({"import_kind": kind, "original_row_number": row_index, "original_row": row}, ensure_ascii=False, default=str)[:12000],
        })

    for row_index, source_row in enumerate(reader, start=2):
        if not isinstance(source_row, dict):
            skipped += 1
            continue
        row = {_pc_norm(k): str(v or "").strip() for k, v in source_row.items() if k is not None}
        if not any(row.values()):
            skipped += 1
            continue

        raw_type = str(_pc_get(row, "income type", "incometype", "record type", "transaction type", "type", "event type") or "").upper()
        raw_type_norm = _pc_norm(raw_type)
        asset = str(_pc_get(row, "asset", "income asset", "pnl asset", "settlement asset", "quote asset") or "USDT").upper()
        income_raw = _pc_num(_pc_get(row, "income", "income amount", "amount of income"))
        pnl_raw = _pc_num(_pc_get(row,
            "realized pnl", "realised pnl", "realized pnl usdt", "realised pnl usdt",
            "realized profit", "realised profit", "closed pnl", "closed profit",
            "realized p l", "realised p l", "realized profit loss", "realised profit loss"))
        # A generic PnL column is considered only for a selected copy-trade history export,
        # and never when the row advertises an unrealised/open PnL value.
        if pnl_raw is None and ("COPY_TRADE_HISTORY" in kind or kind == "COPY_PORTFOLIO_HISTORY"):
            if not any("unrealized" in key or "unrealised" in key for key in row):
                pnl_raw = _pc_num(_pc_get(row, "pnl", "pnl usdt", "profit loss", "profit loss usdt", "profit/loss"))
        fee_raw = _pc_num(_pc_get(row, "commission", "commission usdt", "commission amount", "fee", "fees", "trading fee", "transaction fee"))
        funding_raw = _pc_num(_pc_get(row, "funding fee", "funding fee usdt", "funding payment", "funding"))
        share_raw = _pc_num(_pc_get(row, "shared amount", "profit sharing amount", "profit share amount", "profit sharing", "shared amount usdt"))
        delta_raw = _pc_num(_pc_get(row, "change amount", "balance change", "amount changed", "delta", "change", "transfer amount"))

        time_value = _pc_get(row, "time", "timestamp", "date", "datetime", "transaction time", "create time", "close time", "close date", "trade time", "order time", "open time")
        symbol = _pc_get(row, "symbol", "trading pair", "pair", "market")
        trade_id = _pc_get(row, "trade id", "tradeid", "tran id", "tranid", "transaction id", "order id", "orderid", "copy id", "portfolio id", "id")
        has_trade_fields = bool(symbol or trade_id or _pc_get(row, "side", "direction", "position side", "price", "entry price", "exit price", "quantity", "qty", "executed qty", "order type"))

        # Profit-sharing is a copier cost, not realised trading PnL.
        if kind == "COPY_PROFIT_SHARING" or "PROFIT_SHARING" in raw_type or "PROFIT SHARE" in raw_type:
            value = share_raw if share_raw is not None else income_raw
            if value is None:
                value = _pc_num(_pc_get(row, "amount", "amount usdt", "shared profit"))
            if value is not None:
                add(row, "PROFIT_SHARING", -abs(value), commission=-abs(value), asset=asset, row_index=row_index, suffix="profit-sharing")
                categories["PROFIT_SHARING"] = categories.get("PROFIT_SHARING", 0) + 1
                continue

        is_pnl_type = "REALIZED" in raw_type or "REALISED" in raw_type or "CLOSED PNL" in raw_type
        is_fee_type = "COMMISSION" in raw_type or raw_type_norm == "fee"
        is_funding_type = "FUNDING" in raw_type
        if is_pnl_type and pnl_raw is None:
            pnl_raw = income_raw
        if is_fee_type and fee_raw is None:
            fee_raw = income_raw
        if is_funding_type and funding_raw is None:
            funding_raw = income_raw

        row_added = False
        if pnl_raw is not None and (is_pnl_type or not raw_type or "COPY" in kind or "TRADE_HISTORY" in kind or "P&L" in raw_type):
            typ = "REALIZED_PNL"
            add(row, typ, pnl_raw, pnl=pnl_raw, asset=asset, row_index=row_index, suffix="realized-pnl")
            categories[typ] = categories.get(typ, 0) + 1
            row_added = True

        if fee_raw is not None:
            # Displayed fee columns are generally positive magnitudes; treat them as a cost.
            fee_value = fee_raw if is_fee_type and (income_raw is not None or fee_raw < 0) else -abs(fee_raw)
            add(row, "COMMISSION", fee_value, commission=fee_value, asset=asset, row_index=row_index, suffix="commission")
            categories["COMMISSION"] = categories.get("COMMISSION", 0) + 1
            row_added = True
        if funding_raw is not None:
            add(row, "FUNDING_FEE", funding_raw, funding=funding_raw, asset=asset, row_index=row_index, suffix="funding")
            categories["FUNDING_FEE"] = categories.get("FUNDING_FEE", 0) + 1
            row_added = True

        # Official Copy Trading trade-history exports can contain Spot fills without a
        # realised PnL value. Store those as fills for audit, but never count notional
        # value as profit. Cost basis is required to calculate Spot realised PnL.
        is_trade_export = kind in ("SPOT_COPY_TRADE_HISTORY", "FUTURES_COPY_TRADE_HISTORY", "COPY_PORTFOLIO_HISTORY")
        if not row_added and is_trade_export and has_trade_fields and not any(x in raw_type for x in ("BALANCE", "HOLDING", "SHARING", "FAILED")):
            quote_amount = _pc_num(_pc_get(row, "amount usdt", "quote amount", "total usdt", "notional usdt", "total", "value usdt"))
            if quote_amount is None:
                quote_amount = _pc_num(_pc_get(row, "amount"))
            # Notional is retained as an audit field only; its PnL contribution stays zero.
            add(row, "TRADE_HISTORY", quote_amount or 0.0, asset=asset, row_index=row_index, suffix="trade-row")
            categories["TRADE_HISTORY"] = categories.get("TRADE_HISTORY", 0) + 1
            row_added = True

        # Balance history is informational, not taxable PnL; preserve only rows that
        # actually disclose a balance delta or transfer amount.
        if not row_added and kind == "COPY_BALANCE_HISTORY" and delta_raw is not None:
            add(row, "BALANCE_EVENT", delta_raw, asset=asset, row_index=row_index, suffix="balance-event")
            categories["BALANCE_EVENT"] = categories.get("BALANCE_EVENT", 0) + 1
            row_added = True

        # Income-history CSV rows with explicit supported income type.
        if not row_added and raw_type and income_raw is not None:
            if "REALIZED" in raw_type or "REALISED" in raw_type:
                add(row, "REALIZED_PNL", income_raw, pnl=income_raw, asset=asset, row_index=row_index, suffix="income-realized")
                categories["REALIZED_PNL"] = categories.get("REALIZED_PNL", 0) + 1
                row_added = True
            elif "COMMISSION" in raw_type or "FEE" == raw_type_norm:
                fee_value = income_raw
                add(row, "COMMISSION", fee_value, commission=fee_value, asset=asset, row_index=row_index, suffix="income-commission")
                categories["COMMISSION"] = categories.get("COMMISSION", 0) + 1
                row_added = True
            elif "FUNDING" in raw_type:
                add(row, "FUNDING_FEE", income_raw, funding=income_raw, asset=asset, row_index=row_index, suffix="income-funding")
                categories["FUNDING_FEE"] = categories.get("FUNDING_FEE", 0) + 1
                row_added = True

        if row_added:
            continue
        skipped += 1

    return out, skipped, categories, source, market, kind

def _pc_api_it_tax_import():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Choose a Binance Copy Trading or account-history CSV export first."}), 400
    raw = f.read(10000001)
    if len(raw) > 10000000:
        return jsonify({"error": "CSV is larger than 10 MB. Export a shorter date range."}), 413
    try:
        decoded = raw.decode("utf-8-sig")
    except Exception:
        return jsonify({"error": "CSV must be UTF-8. Re-export it from Binance and try again."}), 400
    try:
        reader = _pc_csv.DictReader(_pc_io.StringIO(decoded))
        if not reader.fieldnames:
            return jsonify({"error": "CSV headers were not found."}), 400
        kind = str(request.form.get("source_kind") or "COPY_PORTFOLIO_HISTORY").upper()
        market = str(request.form.get("market_type") or "FUTURES").upper()
        if market not in ("SPOT", "FUTURES"):
            market = "FUTURES"
        strategy = str(request.form.get("strategy_name") or "Imported Binance Copy Trading history").strip()[:100]
        records, skipped, categories, source, used_market, used_kind = _pc_import_records(reader, kind, market, strategy)
        if not records:
            return jsonify({
                "error": "No Copy Trading history rows were recognised. Select the correct export type and use the CSV downloaded from Binance Copy Trading → Copy Overview / Portfolio History. Supported rows include realised/closed PnL, commission, funding, profit sharing, and trade history. Headers found: " + ", ".join(reader.fieldnames[:40]),
                "skipped_rows": skipped,
            }), 400
        inserted = _it_upsert(records)
        result = _it_summary_data()
        result["import"] = {
            "source": source,
            "source_kind": used_kind,
            "market_type": used_market,
            "recognised_records": len(records),
            "new_records_saved": inserted,
            "duplicates_ignored": max(0, len(records) - inserted),
            "rows_skipped": skipped,
            "categories": categories,
            "credentials_saved": False,
            "note": "Copy Trading export rows are stored separately from standard API income. Trade-history notional is retained for audit and is never counted as realised profit. Spot realised PnL requires transaction/cost-basis data.",
        }
        app.logger.info("binance_copy_history_csv_import market=%s kind=%s recognized=%s inserted=%s skipped=%s",
                        used_market, used_kind, len(records), inserted, skipped)
        return jsonify(result)
    except Exception as exc:
        app.logger.exception("binance_copy_history_csv_import_failed")
        return jsonify({"error": "Copy history CSV import failed: " + str(exc)[:300]}), 400

# Replace the generic importer behind the existing upload URL so the UI keeps its route.
app.view_functions["api_it_tax_import"] = _pc_api_it_tax_import

'''
    APP.write_text(app)

html = HTML.read_text()
html = html.replace("<h3>Upload realised-PnL CSV</h3>", "<h3>Upload Personal Copy History / PnL CSV</h3>")
old = '<div class="field-row"><label>Market<select id="pt-market-csv"><option value="FUTURES">Futures</option><option value="SPOT">Spot</option></select></label><label>Binance CSV file<input id="pt-csv" type="file" accept=".csv,text/csv"></label></div>'
new = '<div class="field-row"><label>Data source<select id="pt-source-kind"><option value="FUTURES_COPY_TRADE_HISTORY">Futures Copy Trading · trade history</option><option value="SPOT_COPY_TRADE_HISTORY">Spot Copy Trading · trade history</option><option value="COPY_PORTFOLIO_HISTORY" selected>Copy portfolio history · auto-detect</option><option value="COPY_PROFIT_SHARING">Copy profit sharing</option><option value="COPY_BALANCE_HISTORY">Copy balance history</option><option value="ACCOUNT_PNL_CSV">Standard account PnL / income</option></select></label><label>Market<select id="pt-market-csv"><option value="FUTURES">Futures</option><option value="SPOT">Spot</option></select></label><label>Binance CSV file<input id="pt-csv" type="file" accept=".csv,text/csv"></label></div>'
if old in html:
    html = html.replace(old, new, 1)
elif 'id="pt-source-kind"' not in html:
    raise RuntimeError("Could not find CSV upload field row to extend for Personal Copy History")
old_help = "Use a Binance realised PnL / income-history export with an income type and income amount, or a trade ledger that includes a realised/closed PnL column. Raw spot fills without acquisition cost and disposal proceeds are not enough for a reliable taxable-gain calculation. Duplicate rows are deduplicated."
new_help = "Import your personal Copy Trading exports here. In Binance, open Copy Trading → Copy Overview (Futures) or the Spot Copy Trading portfolio → Portfolio History, then export the Trade History, Profit Sharing, or Balance History available there. Choose the matching source type above. Copy Trading and standard-account history are separate. The API key still syncs standard Futures income; this importer handles your personal copy portfolio records. Spot trade fills without cost basis are stored but are not treated as realised profit. Duplicate rows are deduplicated."
if old_help in html:
    html = html.replace(old_help, new_help, 1)
# Also make the data-scope limitation visible rather than implying the key sync imports copy history.
if "BI_PERSONAL_COPY_HISTORY_IMPORT_V1" not in html:
    anchor = '<div class="notice-box">Only your imported/account-synced records appear here.'
    pos = html.find(anchor)
    if pos >= 0:
        end = html.find("</div>", pos)
        if end >= 0:
            insert = '<p class="help-text">Personal Copy Trading history status: export import available; the API key test verifies standard Spot/Futures account access, not a copy-portfolio history feed.</p>'
            html = html[:end] + insert + html[end:]
html = html.replace('id="BI_TAX_CENTRE_NAVIGATION_FAILSAFE_V2"', 'id="BI_TAX_CENTRE_NAVIGATION_FAILSAFE_V2"')
# Give app.js a new cache key after modifying its import handler.
script_pos = html.find("app.js")
if script_pos >= 0:
    q_start = html.rfind('"', 0, script_pos)
    q_end = html.find('"', script_pos)
    if q_start >= 0 and q_end > q_start:
        src = html[q_start + 1:q_end]
        if "app.js" in src:
            html = html[:q_start + 1] + src.split("?v=", 1)[0] + "?v=bi-copy-history-20261028" + html[q_end:]
HTML.write_text(html)

js = JS.read_text()
if "BI_PERSONAL_COPY_HISTORY_UI_V1" not in js:
    old = "form.append('market_type',$('#pt-market-csv').value);form.append('strategy_name',$('#pt-strategy-csv').value.trim());"
    new = "form.append('market_type',$('#pt-market-csv').value);form.append('source_kind',$('#pt-source-kind')?$('#pt-source-kind').value:'COPY_PORTFOLIO_HISTORY');form.append('strategy_name',$('#pt-strategy-csv').value.trim());"
    if old not in js:
        raise RuntimeError("Could not find CSV FormData builder in app.js")
    js = js.replace(old, new, 1)
    old_toast = "toast('Recognised '+n(d.import&&d.import.recognised_records,0)+' records; saved '+n(d.import&&d.import.new_records_saved,0)+' new rows.','success');"
    new_toast = "toast('Recognised '+n(d.import&&d.import.recognised_records,0)+' rows; saved '+n(d.import&&d.import.new_records_saved,0)+' new; duplicates '+n(d.import&&d.import.duplicates_ignored,0)+'.','success');"
    if old_toast in js:
        js = js.replace(old_toast, new_toast, 1)
    # Add category/status details in the warning area after import.
    marker = "function itBindTaxControls(){"
    helper = r"""
// BI_PERSONAL_COPY_HISTORY_UI_V1
(function(){
 const source=$('#pt-source-kind'), market=$('#pt-market-csv'), heading=document.querySelector('#view-profit-tax h3');
 if(source&&market){
   source.addEventListener('change',function(){
     if(source.value==='SPOT_COPY_TRADE_HISTORY')market.value='SPOT';
     if(source.value==='FUTURES_COPY_TRADE_HISTORY')market.value='FUTURES';
   });
 }
})();
"""
    if marker in js:
        js = js.replace(marker, helper + "\n" + marker, 1)
    js += "\n// BI_PERSONAL_COPY_HISTORY_IMPORT_V1\n"
    JS.write_text(js)

print("Installed Personal Copy History CSV ingestion, dedupe, source attribution, and a distinct UI path.")
