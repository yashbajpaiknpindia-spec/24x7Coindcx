from pathlib import Path
import re

ROOT=Path("/app")
html_path=ROOT/"templates"/"index.html"
app_path=ROOT/"app.py"
js_path=ROOT/"static"/"app.js"

def insert_before_once(text, anchor, payload, marker, label):
    if marker in text: return text
    if anchor not in text: raise RuntimeError("Cannot install "+label+": anchor not found")
    return text.replace(anchor,payload+anchor,1)

# Preserve existing Portfolio Lab, Multi-Trader and Trade Behaviour sections.
html=html_path.read_text()
if 'data-view="profit-tax"' not in html:
    nav='''    <button class="nav-link" data-view="profit-tax"><span class="nav-ico">₹</span> Profit & Tax Centre</button>
    <button class="nav-link" data-view="strategy-watch"><span class="nav-ico">◉</span> Strategy Tax Watch</button>
'''
    html=insert_before_once(html,'    <button class="nav-link" data-view="reports">',nav,'data-view="profit-tax"',"tax navigation")
if 'id="view-profit-tax"' not in html:
    tax_pages = r"""<section class="view" id="view-profit-tax">
      <div class="section-heading"><div><div class="eyebrow">PERSONAL ACCOUNT LEDGER</div><h2>Profit & Tax Centre</h2><p>Track imported Binance income records, visible losses, a conservative 30% tax reserve on positive realised-PnL records, and estimated INR cash-out value.</p></div><span class="tag blue">ACCOUNT DATA ONLY</span></div>
      <div class="notice-box">Only your imported/account-synced records appear here. Public lead-trader history and paper estimates are not your personal trades. This centre is a planning estimate, not a tax return. For futures/derivatives classification and filing, confirm with an Indian tax professional.</div>
      <div class="kpi-grid">
        <article class="kpi-card"><div class="kpi-head"><span>Gross positive realised PnL</span></div><div class="kpi-value" id="pt-positive">—</div><div class="kpi-foot" id="pt-positive-inr">INR: —</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Conservative tax reserve · 30%</span></div><div class="kpi-value" id="pt-tax">—</div><div class="kpi-foot" id="pt-tax-inr">INR: —</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Economic PnL before reserve</span></div><div class="kpi-value" id="pt-net">—</div><div class="kpi-foot" id="pt-net-inr">INR: —</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Estimated PnL after reserve</span></div><div class="kpi-value" id="pt-after">—</div><div class="kpi-foot" id="pt-after-inr">INR: —</div></article>
      </div>
      <div class="content-grid two-col">
        <article class="panel"><div class="panel-header"><div><div class="eyebrow">REQUEST ACCOUNT DATA</div><h3>Sync Binance Futures income</h3></div><span class="tag purple">READ ONLY</span></div>
          <label>Read-only API key<input id="pt-api-key" type="text" autocomplete="off" placeholder="Paste API key"></label>
          <label>API secret (used once, never saved)<input id="pt-api-secret" type="password" autocomplete="new-password" placeholder="Paste API secret"></label>
          <div class="field-row"><label>History range<select id="pt-days"><option value="7">7 days</option><option value="30" selected>30 days</option><option value="60">60 days</option><option value="90">90 days</option></select></label><label>Strategy label<input id="pt-strategy-sync" type="text" value="Unattributed Binance Futures" maxlength="100"></label></div>
          <button class="btn primary" id="pt-sync">Request Binance income history</button>
          <p class="help-text">Create an API key with read-only/Enable Reading and Futures access only. Do not enable trading, withdrawals, transfers, or universal transfer. The key and secret are sent only for this request; the app stores returned records, not the credentials. Futures income history may not identify which copy-trading leader caused each record.</p>
        </article>
        <article class="panel"><div class="panel-header"><div><div class="eyebrow">IMPORT ACCOUNT EXPORT</div><h3>Upload realised-PnL CSV</h3></div><span class="tag gray">SPOT / FUTURES</span></div>
          <label>Strategy or copy portfolio label<input id="pt-strategy-csv" type="text" value="Imported Binance records" maxlength="100"></label>
          <div class="field-row"><label>Market<select id="pt-market-csv"><option value="FUTURES">Futures</option><option value="SPOT">Spot</option></select></label><label>Binance CSV file<input id="pt-csv" type="file" accept=".csv,text/csv"></label></div>
          <button class="btn secondary" id="pt-import">Import CSV records</button>
          <p class="help-text">Use a Binance realised PnL / income-history export with an income type and income amount, or a trade ledger that includes a realised/closed PnL column. Raw spot fills without acquisition cost and disposal proceeds are not enough for a reliable taxable-gain calculation. Duplicate rows are deduplicated.</p>
        </article>
      </div>
      <article class="panel"><div class="panel-header"><div><div class="eyebrow">CONVERSION</div><h3>Current Binance P2P reference rate</h3></div><span class="tag gray" id="pt-rate-status">Rate not loaded</span></div>
        <div class="field-row"><label>Reference buy quote (INR per USDT)<input id="pt-buy-rate" type="number" step="0.01" min="0" readonly placeholder="Loading…"></label><label>Reference sell quote (INR per USDT)<input id="pt-sell-rate" type="number" step="0.01" min="0" readonly placeholder="Loading…"></label><label>Cash-out conversion rate (INR per USDT)<input id="pt-rate" type="number" step="0.01" min="0" value="" placeholder="Enter current P2P sell rate"></label></div>
        <div class="button-row"><button class="btn secondary" id="pt-refresh-rate">Refresh P2P rates</button><span class="help-text">Past trades are converted using the selected current rate, not a historical P2P price. P2P ads, payment method, order limits, and merchant spread affect the actual executed price.</span></div>
      </article>
      <article class="panel"><div class="panel-header"><div><div class="eyebrow">TAX & LOSS RESERVE</div><h3>Ledger totals and data gaps</h3></div><span class="tag gray" id="pt-ledger-status">No account records loaded</span></div><div id="pt-warning" class="notice-box">Import or sync your personal records to calculate the account ledger.</div><div class="table-scroll"><table><thead><tr><th>Strategy / label</th><th>Records</th><th>Positive realised PnL</th><th>Gross losses (not offset)</th><th>Fees</th><th>Funding</th><th>30% tax reserve (USDT)</th><th>Tax reserve (INR)</th><th>Economic PnL (USDT)</th><th>After-reserve PnL (USDT)</th><th>After-reserve PnL (INR)</th><th>Status</th></tr></thead><tbody id="pt-strategy-rows"><tr><td colspan="12" class="empty-state">No imported personal trade records.</td></tr></tbody></table></div></article>
      <article class="panel table-panel"><div class="panel-header"><div><div class="eyebrow">TRADE-LEVEL NET RESULTS</div><h3>Trade-level PnL after 30% reserve</h3></div><span class="tag gray">Fees/funding are attributed only when a trade ID matches</span></div><div class="table-scroll"><table><thead><tr><th>Time (UTC)</th><th>Strategy label</th><th>Market</th><th>Symbol</th><th>Group / Trade ID</th><th>Realised PnL</th><th>Fees</th><th>Funding</th><th>Tax reserve (USDT)</th><th>Tax reserve (INR)</th><th>Net after reserve (USDT)</th><th>Net after reserve (INR)</th><th>Status</th></tr></thead><tbody id="pt-trade-rows"><tr><td colspan="13" class="empty-state">No imported personal trade records.</td></tr></tbody></table></div></article>
      <article class="panel table-panel"><div class="panel-header"><div><div class="eyebrow">RECENT ACCOUNT RECORDS</div><h3>Trade / income entries with estimated tax reserve</h3></div><span class="tag gray" id="pt-row-count">0 records</span></div><div class="table-scroll"><table><thead><tr><th>Time (UTC)</th><th>Strategy label</th><th>Market</th><th>Symbol</th><th>Record type</th><th>Income asset / amount</th><th>Realised PnL (USDT)</th><th>Fees (USDT)</th><th>Funding (USDT)</th><th>Tax reserve</th><th>Entry net after reserve</th></tr></thead><tbody id="pt-ledger-rows"><tr><td colspan="13" class="empty-state">No imported personal trade records.</td></tr></tbody></table></div></article>
      <div class="notice-box">Tax method: the default conservative reserve applies 30% to each positive realised-PnL ledger record and does not use losing records to reduce that reserve. India’s Income-tax Act, 2025 section 194 specifies a 30% rate for income from transfer of a virtual digital asset and restricts loss set-off/carry-forward for that income. This simple reserve is not a legal conclusion that every futures PnL record is a VDA transfer; surcharge/cess, transaction classification, acquisition cost, TDS, and other facts require separate review. The conversion is a current P2P reference, not actual historic INR proceeds.</div>
    </section>

    <section class="view" id="view-strategy-watch">
      <div class="section-heading"><div><div class="eyebrow">AFTER-TAX STRATEGY DIAGNOSTICS</div><h2>Strategy Tax Watch</h2><p>Identify strategies where realised gains do not cover losses, fees, funding, and the conservative tax reserve.</p></div><span class="tag blue">NO PROFIT GUARANTEE</span></div>
      <div class="kpi-grid">
        <article class="kpi-card"><div class="kpi-head"><span>Strategies with records</span></div><div class="kpi-value" id="stw-count">—</div><div class="kpi-foot">From personal imports only</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Positive after reserve</span></div><div class="kpi-value" id="stw-positive">—</div><div class="kpi-foot">After recorded costs and reserve</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Non-positive / high-loss</span></div><div class="kpi-value" id="stw-risk">—</div><div class="kpi-foot">Review before new allocation</div></article>
        <article class="kpi-card"><div class="kpi-head"><span>Overall after-reserve PnL</span></div><div class="kpi-value" id="stw-net">—</div><div class="kpi-foot" id="stw-net-inr">INR: —</div></article>
      </div>
      <div id="stw-alert" class="notice-box">No personal strategy ledger imported yet. The app will not invent trades or project a guaranteed profit.</div>
      <article class="panel"><div class="panel-header"><div><div class="eyebrow">STRATEGY STATUS</div><h3>Warning list</h3></div><span class="tag gray">Recomputed from ledger</span></div><div class="table-scroll"><table><thead><tr><th>Strategy</th><th>Records</th><th>Positive realised gains</th><th>Gross losses</th><th>Loss / gain ratio</th><th>Fees + funding</th><th>Tax reserve (USDT)</th><th>Tax reserve (INR)</th><th>Economic PnL (USDT)</th><th>After-reserve PnL (USDT)</th><th>After-reserve PnL (INR)</th><th>Warning / next check</th></tr></thead><tbody id="stw-rows"><tr><td colspan="12" class="empty-state">Import personal trade records to begin.</td></tr></tbody></table></div></article>
      <div class="notice-box">A strategy can become unprofitable after fees, funding, slippage, and a tax reserve even when its headline ROI is positive. A warning is a reason to investigate or pause new allocation, not an automatic order action. No system can guarantee that you will always remain profitable.</div>
    </section>
"""
    html=insert_before_once(html,'    <section class="view" id="view-reports">',tax_pages,'id="view-profit-tax"',"tax pages")

# Extend the navigation failsafe used by the active app so both pages activate and load data.
if 'BI_TAX_CENTRE_ROUTES_V1' not in html:
    titles_old='"multi-trader":"Multi-Trader Mode","history":"Trade behaviour",'
    titles_new='"multi-trader":"Multi-Trader Mode","profit-tax":"Profit & Tax Centre","strategy-watch":"Strategy Tax Watch","history":"Trade behaviour",'
    if titles_old in html:
        html=html.replace(titles_old,titles_new,1)
    case_anchor='        case "reports":'
    tax_cases='''        case "profit-tax":
          if(typeof itLoadP2PRates==="function")called.push(await callRequired("Profit & Tax Centre",function(){return itLoadP2PRates()}));
          else if(typeof itLoadProfitTax==="function")called.push(await callRequired("Profit & Tax Centre",function(){return itLoadProfitTax()}));
          break;
        case "strategy-watch":
          called.push(await callRequired("Strategy Tax Watch",function(){return itLoadProfitTax()}));
          break;
'''
    if 'case "profit-tax":' not in html:
        if case_anchor in html: html=html.replace(case_anchor,tax_cases+case_anchor,1)
        elif 'BI_TAX_CENTRE_ROUTES_V1' not in html:
            # Some older bundles only use the original global view() router; add names there below.
            pass
    html=html.replace('id="BINANCE_INTEL_NAVIGATION_FAILSAFE_V2"','id="BINANCE_INTEL_NAVIGATION_FAILSAFE_V2" data-tax-centre="v1"')
    html += "\n<!-- BI_TAX_CENTRE_ROUTES_V1 -->\n"

html_path.write_text(html)

# Register the tax backend routes exactly once. Read-only credentials are never stored.
app=app_path.read_text()
if "PROFIT_TAX_CENTRE_V1" not in app:
    app += "\n\n"+r'''# PROFIT_TAX_CENTRE_V1
import csv as _it_csv
import hashlib as _it_hashlib
import hmac as _it_hmac
import io as _it_io
import json as _it_json
import math as _it_math
import time as _it_time
import datetime as _it_dt
import urllib.error as _it_urlerror
import urllib.parse as _it_urlparse
import urllib.request as _it_urlrequest
import sqlalchemy as _it_sa

_IT_TAX_RATE = 0.30

def _it_ensure_ledger():
    with SessionLocal() as db:
        dialect = db.get_bind().dialect.name
        id_type = "BIGSERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        ddl = """
        CREATE TABLE IF NOT EXISTS account_trade_ledger (
          id %s,
          external_id TEXT NOT NULL UNIQUE,
          strategy_name TEXT NOT NULL DEFAULT 'Unattributed Binance Futures',
          market_type TEXT NOT NULL DEFAULT 'FUTURES',
          symbol TEXT,
          trade_id TEXT,
          income_type TEXT NOT NULL DEFAULT 'REALIZED_PNL',
          transaction_time TEXT,
          asset TEXT NOT NULL DEFAULT 'USDT',
          amount_asset DOUBLE PRECISION,
          amount_usdt DOUBLE PRECISION,
          realized_pnl_usdt DOUBLE PRECISION NOT NULL DEFAULT 0,
          commission_usdt DOUBLE PRECISION NOT NULL DEFAULT 0,
          funding_usdt DOUBLE PRECISION NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT 'CSV_IMPORT',
          raw_json TEXT NOT NULL DEFAULT '{}',
          created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """ % id_type
        db.execute(_it_sa.text(ddl))
        db.execute(_it_sa.text("CREATE INDEX IF NOT EXISTS ix_account_trade_ledger_time ON account_trade_ledger(transaction_time)"))
        db.commit()

def _it_float(value, default=0.0):
    try:
        if value is None: return default
        raw = str(value).strip().replace(",", "").replace("$", "").replace("USDT", "").replace(" ", "")
        if not raw or raw in ("-", "—", "N/A", "null", "None"): return default
        number = float(raw)
        return number if _it_math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default

def _it_clean_time(value):
    raw = str(value or "").strip()
    if not raw: return None
    try:
        if raw.isdigit():
            n = int(raw)
            if n > 10**14: n = n / 1000.0
            if n > 10**11:
                return _it_dt.datetime.fromtimestamp(n / 1000.0, _it_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if n > 10**8:
                return _it_dt.datetime.fromtimestamp(n, _it_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parsed = _it_dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=_it_dt.timezone.utc)
        return parsed.astimezone(_it_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return raw[:80]

def _it_upsert(records):
    if not records: return 0
    _it_ensure_ledger()
    sql = _it_sa.text("""
      INSERT INTO account_trade_ledger
        (external_id,strategy_name,market_type,symbol,trade_id,income_type,transaction_time,asset,amount_asset,amount_usdt,realized_pnl_usdt,commission_usdt,funding_usdt,source,raw_json)
      VALUES
        (:external_id,:strategy_name,:market_type,:symbol,:trade_id,:income_type,:transaction_time,:asset,:amount_asset,:amount_usdt,:realized_pnl_usdt,:commission_usdt,:funding_usdt,:source,:raw_json)
      ON CONFLICT(external_id) DO NOTHING
    """)
    inserted = 0
    with SessionLocal() as db:
        for item in records:
            result = db.execute(sql, item)
            if result.rowcount and result.rowcount > 0: inserted += result.rowcount
        db.commit()
    return inserted

def _it_summary_data():
    with SessionLocal() as db:
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            exists = db.execute(_it_sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='account_trade_ledger')")).scalar()
        else:
            exists = db.execute(_it_sa.text("SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_trade_ledger')")).scalar()
        if not exists:
            return {"has_personal_records":False,"record_count":0,"included_usdt_record_count":0,"excluded_non_usdt_or_unconverted_count":0,
              "tax_method":"Conservative planning reserve: 30% of each positive realised-PnL ledger event; negative events do not reduce the reserve.",
              "ledger_table_available":False,
              "summary":{"record_count":0,"realized_pnl_usdt":0,"positive_realized_pnl_usdt":0,"gross_loss_usdt":0,"commission_usdt":0,"funding_usdt":0,
                "economic_net_pnl_usdt":0,"tax_rate":_IT_TAX_RATE,"tax_reserve_usdt":0,"net_after_tax_reserve_usdt":0},
              "by_strategy":[],"recent":[],"recent_trades":[],"generated_at_utc":_it_dt.datetime.now(_it_dt.timezone.utc).isoformat()}
        mappings = db.execute(_it_sa.text("""
          SELECT id,external_id,strategy_name,market_type,symbol,trade_id,income_type,transaction_time,asset,amount_asset,amount_usdt,
                 realized_pnl_usdt,commission_usdt,funding_usdt,source,created_at
          FROM account_trade_ledger ORDER BY transaction_time DESC NULLS LAST, id DESC LIMIT 20000
        """)).mappings().all()
    rows = [dict(x) for x in mappings]
    included = [r for r in rows if str(r.get("asset") or "").upper() == "USDT" and r.get("amount_usdt") is not None]
    def f(v): return _it_float(v, 0.0)
    def aggregate(items):
        pnl = sum(f(r.get("realized_pnl_usdt")) for r in items if str(r.get("income_type") or "").upper() == "REALIZED_PNL")
        positive = sum(max(0.0, f(r.get("realized_pnl_usdt"))) for r in items if str(r.get("income_type") or "").upper() == "REALIZED_PNL")
        loss = sum(abs(min(0.0, f(r.get("realized_pnl_usdt"))) ) for r in items if str(r.get("income_type") or "").upper() == "REALIZED_PNL")
        commission = sum(f(r.get("commission_usdt")) for r in items)
        funding = sum(f(r.get("funding_usdt")) for r in items)
        reserve = positive * _IT_TAX_RATE
        return {"record_count":len(items),"realized_pnl_usdt":round(pnl,8),"positive_realized_pnl_usdt":round(positive,8),
          "gross_loss_usdt":round(loss,8),"commission_usdt":round(commission,8),"funding_usdt":round(funding,8),
          "economic_net_pnl_usdt":round(pnl+commission+funding,8),"tax_rate":_IT_TAX_RATE,
          "tax_reserve_usdt":round(reserve,8),"net_after_tax_reserve_usdt":round(pnl+commission+funding-reserve,8)}
    overall = aggregate(included)
    by = {}
    for r in included: by.setdefault(str(r.get("strategy_name") or "Unlabelled"), []).append(r)
    strategies = []
    for name, group in by.items():
        v = aggregate(group); v["strategy_name"] = name
        v["loss_to_gain_ratio"] = round(v["gross_loss_usdt"] / v["positive_realized_pnl_usdt"],4) if v["positive_realized_pnl_usdt"] > 0 else None
        v["fee_funding_usdt"] = round(v["commission_usdt"] + v["funding_usdt"],8)
        if v["net_after_tax_reserve_usdt"] <= 0: v["status"] = "NON_POSITIVE_AFTER_RESERVE"
        elif v["gross_loss_usdt"] >= v["positive_realized_pnl_usdt"]: v["status"] = "LOSSES_MATCH_OR_EXCEED_GAINS"
        elif v["fee_funding_usdt"] < -v["positive_realized_pnl_usdt"] * 0.1: v["status"] = "HIGH_COST_DRAG"
        else: v["status"] = "POSITIVE_IN_IMPORTED_RECORDS"
        strategies.append(v)
    strategies.sort(key=lambda x:x["net_after_tax_reserve_usdt"])
    recent = []
    for r in rows[:500]:
        asset = str(r.get("asset") or "").upper()
        included_row = asset == "USDT" and r.get("amount_usdt") is not None
        pnl = f(r.get("realized_pnl_usdt")) if included_row and str(r.get("income_type") or "").upper() == "REALIZED_PNL" else 0.0
        commission = f(r.get("commission_usdt")) if included_row else 0.0
        funding = f(r.get("funding_usdt")) if included_row else 0.0
        reserve = max(0.0,pnl)*_IT_TAX_RATE
        recent.append({"id":r.get("id"),"time":r.get("transaction_time"),"strategy_name":r.get("strategy_name"),"market_type":r.get("market_type"),
          "symbol":r.get("symbol"),"trade_id":r.get("trade_id"),"income_type":r.get("income_type"),"asset":asset,"amount_asset":r.get("amount_asset"),
          "realized_pnl_usdt":round(pnl,8),"commission_usdt":round(commission,8),"funding_usdt":round(funding,8),
          "tax_reserve_usdt":round(reserve,8),"net_after_reserve_usdt":round(pnl+commission+funding-reserve,8),"source":r.get("source"),"included_in_usdt_totals":included_row})
    grouped = {}
    for r in included:
        typ=str(r.get("income_type") or "").upper()
        raw_trade_id=str(r.get("trade_id") or "").strip()
        has_trade_id=bool(raw_trade_id and raw_trade_id not in ("0","None","null"))
        # Only combine fees/funding with a realised event when Binance provides a trade ID.
        # Otherwise preserve each event as unattributed to avoid false attribution.
        key=(str(r.get("strategy_name") or "Unlabelled"),str(r.get("market_type") or "FUTURES"),str(r.get("symbol") or ""),raw_trade_id) if has_trade_id else ("UNATTRIBUTED",str(r.get("external_id") or r.get("id")))
        group=grouped.setdefault(key,{"time":r.get("transaction_time"),"strategy_name":str(r.get("strategy_name") or "Unlabelled"),
            "market_type":str(r.get("market_type") or "FUTURES"),"symbol":str(r.get("symbol") or ""),"trade_id":raw_trade_id if has_trade_id else "",
            "group_type":"TRADE" if has_trade_id else "UNATTRIBUTED_INCOME_EVENT","record_count":0,
            "realized_pnl_usdt":0.0,"commission_usdt":0.0,"funding_usdt":0.0,"tax_reserve_usdt":0.0,"has_realized_pnl":False})
        group["record_count"]+=1
        stamp=r.get("transaction_time")
        if stamp and (not group.get("time") or stamp>group["time"]): group["time"]=stamp
        if typ=="REALIZED_PNL":
            event_pnl=f(r.get("realized_pnl_usdt"))
            group["realized_pnl_usdt"]+=event_pnl
            # Losing events do not reduce the reserve.
            group["tax_reserve_usdt"]+=max(0.0,event_pnl)*_IT_TAX_RATE
            group["has_realized_pnl"]=True
        elif typ=="COMMISSION": group["commission_usdt"]+=f(r.get("commission_usdt"))
        elif typ=="FUNDING_FEE": group["funding_usdt"]+=f(r.get("funding_usdt"))
    recent_trades=[]
    for group in sorted(grouped.values(),key=lambda x:str(x.get("time") or ""),reverse=True)[:500]:
        for field in ("realized_pnl_usdt","commission_usdt","funding_usdt","tax_reserve_usdt"):
            group[field]=round(group[field],8)
        group["net_after_reserve_usdt"]=round(group["realized_pnl_usdt"]+group["commission_usdt"]+group["funding_usdt"]-group["tax_reserve_usdt"],8)
        if group["group_type"]=="TRADE":
            group["status"]="TRADE_AFTER_RESERVE_POSITIVE" if group["net_after_reserve_usdt"]>0 else "TRADE_AFTER_RESERVE_NON_POSITIVE"
        elif group["has_realized_pnl"]:
            group["status"]="UNATTRIBUTED_REALIZED_PNL"
        else:
            group["status"]="UNATTRIBUTED_COST_OR_INCOME"
        recent_trades.append(group)
    return {"has_personal_records":bool(rows),"ledger_table_available":True,"record_count":len(rows),"included_usdt_record_count":len(included),
      "excluded_non_usdt_or_unconverted_count":max(0,len(rows)-len(included)),"tax_method":"Conservative planning reserve: 30% of each positive realised-PnL ledger event; negative events do not reduce the reserve.",
      "summary":overall,"by_strategy":strategies,"recent":recent,"recent_trades":recent_trades,"generated_at_utc":_it_dt.datetime.now(_it_dt.timezone.utc).isoformat()}

def _it_p2p_quote(trade_type):
    # For a user buying USDT, query advertisers selling USDT; for selling USDT, query advertisers buying it.
    ad_trade_type = "SELL" if str(trade_type).upper() == "BUY" else "BUY"
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    body = {
        "fiat":"INR","page":1,"rows":10,"tradeType":ad_trade_type,"asset":"USDT",
        "countries":[],"proMerchantAds":False,"shieldMerchantAds":False,
        "filterType":"all","periods":[],"additionalKycVerifyFilter":0,
        "publisherType":None,"payTypes":[],"classify":"mass","adsNo":False,
        "shreddedAds":False,"transAmount":""
    }
    req = _it_urlrequest.Request(
        url, data=_it_json.dumps(body).encode("utf-8"), method="POST",
        headers={"User-Agent":"Mozilla/5.0","Accept":"application/json","Content-Type":"application/json"}
    )
    try:
        with _it_urlrequest.urlopen(req, timeout=5) as response:
            payload = _it_json.loads(response.read(700000).decode("utf-8","replace"))
        data = payload.get("data") if isinstance(payload,dict) else None
        prices=[]
        for row in (data if isinstance(data,list) else []):
            adv=row.get("adv") if isinstance(row,dict) else None
            price=_it_float((adv or {}).get("price"),0)
            if price>0: prices.append(price)
        if not prices: return None
        prices.sort()
        return float(prices[len(prices)//2]) if len(prices)%2 else float((prices[len(prices)//2-1]+prices[len(prices)//2])/2.0)
    except Exception:
        return None

@app.get("/api/profit-tax/rates")
def api_it_p2p_rates():
    buy = _it_p2p_quote("BUY")
    sell = _it_p2p_quote("SELL")
    return jsonify({"source":"Binance P2P public quote-price endpoint","fiat":"INR","asset":"USDT",
      "buy_quote_inr_per_usdt":buy,"sell_quote_inr_per_usdt":sell,"as_of_utc":_it_dt.datetime.now(_it_dt.timezone.utc).isoformat(),
      "note":"Reference quotes only. Actual P2P prices depend on payment method, advertisement, limits, and counterparty; the app does not place P2P orders."})

@app.get("/api/profit-tax/summary")
def api_it_tax_summary():
    try: return jsonify(_it_summary_data())
    except Exception as exc: return jsonify({"error":"Unable to read personal trade ledger: "+str(exc)[:300]}),500

def _it_parse_binance_income(row, strategy_name, market_type, source):
    typ = str(row.get("incomeType") or row.get("income_type") or "").upper()
    if typ not in ("REALIZED_PNL","COMMISSION","FUNDING_FEE"): return None
    asset = str(row.get("asset") or "USDT").upper()
    amount = _it_float(row.get("income"),0.0)
    amount_usdt = amount if asset == "USDT" else None
    realised = amount if typ == "REALIZED_PNL" and asset == "USDT" else 0.0
    commission = amount if typ == "COMMISSION" and asset == "USDT" else 0.0
    funding = amount if typ == "FUNDING_FEE" and asset == "USDT" else 0.0
    tran = str(row.get("tranId") or row.get("tradeId") or "")
    time_value = row.get("time")
    symbol = str(row.get("symbol") or "")
    ext = source + ":" + (tran or _it_hashlib.sha256(_it_json.dumps(row,sort_keys=True).encode()).hexdigest()) + ":" + typ
    return {"external_id":ext,"strategy_name":strategy_name,"market_type":market_type,"symbol":symbol,"trade_id":str(row.get("tradeId") or ""),
      "income_type":typ,"transaction_time":_it_clean_time(time_value),"asset":asset,"amount_asset":amount,"amount_usdt":amount_usdt,
      "realized_pnl_usdt":realised,"commission_usdt":commission,"funding_usdt":funding,"source":source,
      "raw_json":_it_json.dumps(row,ensure_ascii=False,default=str)[:12000]}

@app.post("/api/profit-tax/sync")
def api_it_tax_sync():
    data = request.get_json(silent=True) or {}
    api_key = str(data.get("api_key") or "").strip()
    api_secret = str(data.get("api_secret") or "").strip()
    if not api_key or not api_secret: return jsonify({"error":"Enter a read-only Binance API key and secret for this request."}),400
    try:
        days = max(1,min(90,int(data.get("lookback_days",30))))
    except Exception: days = 30
    strategy = str(data.get("strategy_name") or "Unattributed Binance Futures").strip()[:100] or "Unattributed Binance Futures"
    end_ms = int(_it_time.time()*1000)
    start_ms = end_ms - days*86400000
    records = []
    cursor = start_ms
    try:
        while cursor < end_ms:
            window_end = min(end_ms, cursor + 7*86400000 - 1)
            page_start = cursor
            page_loops = 0
            while page_start <= window_end and page_loops < 15:
                params = {"startTime":page_start,"endTime":window_end,"limit":1000,"timestamp":int(_it_time.time()*1000),"recvWindow":5000}
                query = _it_urlparse.urlencode(params)
                signature = _it_hmac.new(api_secret.encode("utf-8"),query.encode("utf-8"),_it_hashlib.sha256).hexdigest()
                url = "https://fapi.binance.com/fapi/v1/income?" + query + "&signature=" + signature
                req = _it_urlrequest.Request(url,headers={"X-MBX-APIKEY":api_key,"Accept":"application/json","User-Agent":"Binance-Intel-ReadOnly"})
                try:
                    with _it_urlrequest.urlopen(req,timeout=15) as response:
                        payload = _it_json.loads(response.read(4000000).decode("utf-8","replace"))
                except _it_urlerror.HTTPError as exc:
                    raise RuntimeError("Binance Futures income request failed (HTTP "+str(exc.code)+"). Check read-only/Futures permissions, IP restrictions, and the selected date range.")
                if isinstance(payload,dict) and payload.get("code") is not None and _it_float(payload.get("code"),0) < 0:
                    raise RuntimeError("Binance rejected the request: "+str(payload.get("msg") or "check API permissions and date range")[:180])
                if not isinstance(payload,list): raise RuntimeError("Binance returned an unexpected response format.")
                if not payload: break
                for row in payload:
                    item = _it_parse_binance_income(row,strategy,"FUTURES","BINANCE_FUTURES_INCOME_API")
                    if item: records.append(item)
                page_loops += 1
                if len(payload) < 1000: break
                max_time = max([int(x.get("time") or page_start) for x in payload])
                if max_time < page_start or max_time >= window_end: break
                page_start = max_time + 1
            cursor = window_end + 1
        inserted = _it_upsert(records)
        result = _it_summary_data()
        result["sync"] = {"fetched_supported_income_records":len(records),"new_records_saved":inserted,"lookback_days":days,
          "credentials_saved":False,"source":"Binance USD-M Futures income history","note":"Only realised PnL, commissions, and funding-fee entries are imported. Other assets are retained but excluded from USDT totals; copy-portfolio attribution is not guaranteed."}
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error":str(exc)[:500],"credentials_saved":False}),400

@app.post("/api/profit-tax/import")
def api_it_tax_import():
    f = request.files.get("file")
    if not f: return jsonify({"error":"Choose a Binance CSV export first."}),400
    raw = f.read(10000001)
    if len(raw) > 10000000: return jsonify({"error":"CSV is larger than 10 MB. Export a shorter date range."}),413
    try: decoded = raw.decode("utf-8-sig")
    except Exception: return jsonify({"error":"CSV must be UTF-8. Re-export it from Binance and try again."}),400
    try:
        reader = _it_csv.DictReader(_it_io.StringIO(decoded))
        if not reader.fieldnames: return jsonify({"error":"CSV headers were not found."}),400
        market = str(request.form.get("market_type") or "FUTURES").upper()
        if market not in ("SPOT","FUTURES"): market="FUTURES"
        strategy = str(request.form.get("strategy_name") or "Imported Binance records").strip()[:100] or "Imported Binance records"
        records = []
        for line_no, source_row in enumerate(reader, start=2):
            row = {str(k or "").strip().lower().replace("_"," ").replace("-"," "):str(v or "").strip() for k,v in source_row.items()}
            def value(*names):
                for name in names:
                    if row.get(name): return row.get(name)
                for name in names:
                    for k,v in row.items():
                        if name in k and v: return v
                return None
            typ = (value("income type","incometype","type","record type") or "").upper().replace(" ","_")
            pnl_raw = value("realized pnl","realised pnl","realized profit","realised profit","closed pnl","closed profit","pnl usdt","pnl","profit")
            income_raw = value("income")
            commission_raw = value("commission","commission usdt","fee","fees")
            funding_raw = value("funding fee","funding","funding usdt")
            if "UNREALIZED" in typ: continue
            if "REALIZED" in typ: typ="REALIZED_PNL"
            elif "COMMISSION" in typ: typ="COMMISSION"
            elif "FUNDING" in typ: typ="FUNDING_FEE"
            elif pnl_raw is not None: typ="REALIZED_PNL"
            elif commission_raw is not None or funding_raw is not None: typ="COST_ONLY"
            else: continue
            asset = str(value("asset","income asset","pnl asset","settlement asset") or "USDT").upper()
            commission_asset = str(value("commission asset","fee asset") or asset).upper()
            pnl = _it_float(pnl_raw if pnl_raw is not None else income_raw,0.0) if typ=="REALIZED_PNL" else 0.0
            commission = _it_float(income_raw if typ=="COMMISSION" else commission_raw,0.0) if commission_asset=="USDT" else 0.0
            funding = _it_float(income_raw if typ=="FUNDING_FEE" else funding_raw,0.0) if asset=="USDT" else 0.0
            if typ=="COMMISSION" and asset=="USDT" and commission_raw is None: commission=_it_float(income_raw,0.0)
            if typ=="FUNDING_FEE" and funding_raw is None: funding=_it_float(income_raw,0.0)
            if asset!="USDT": pnl=0.0
            if typ=="REALIZED_PNL" and pnl_raw is None and income_raw is None: continue
            stamp = value("time","timestamp","date","datetime","transaction time","create time")
            symbol = str(value("symbol","pair","market") or "")
            trade_id = str(value("trade id","tradeid","tran id","tranid","transaction id","order id","id") or "")
            fingerprint = _it_hashlib.sha256((_it_json.dumps(source_row,sort_keys=True,ensure_ascii=False)).encode("utf-8")).hexdigest()
            ext = "CSV_IMPORT:"+fingerprint
            if typ=="COST_ONLY":
                if commission != 0: typ="COMMISSION"
                elif funding != 0: typ="FUNDING_FEE"
                else: continue
            amount_asset = pnl if typ=="REALIZED_PNL" else (commission if typ=="COMMISSION" else funding)
            amount_usdt = amount_asset if asset=="USDT" else None
            records.append({"external_id":ext,"strategy_name":strategy,"market_type":market,"symbol":symbol,"trade_id":trade_id,"income_type":typ,
              "transaction_time":_it_clean_time(stamp),"asset":asset,"amount_asset":amount_asset,"amount_usdt":amount_usdt,
              "realized_pnl_usdt":pnl,"commission_usdt":commission,"funding_usdt":funding,"source":"CSV_IMPORT",
              "raw_json":_it_json.dumps(source_row,ensure_ascii=False,default=str)[:12000]})
        if not records:
            return jsonify({"error":"No supported realised-PnL, commission, or funding records were recognised. Headers found: "+", ".join(reader.fieldnames[:30])}),400
        inserted = _it_upsert(records)
        result = _it_summary_data()
        result["import"] = {"recognised_records":len(records),"new_records_saved":inserted,"duplicates_ignored":max(0,len(records)-inserted),"source":"CSV_IMPORT"}
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error":"CSV import failed: "+str(exc)[:300]}),400
'''+ "\n"
app_path.write_text(app)

# The older client router is still used by some bundle variants; patch it as a fallback.
js=js_path.read_text()
if 'BI_TAX_CENTRE_CLIENT_V1' not in js:
    old_route="const titles={overview:'Overview',traders:'Trader universe','multi-trader':'Multi-Trader Mode',history:'Trade behaviour',reports:'Reports & exports',data:'Data import',system:'Source & system'};$('#page-title').textContent=titles[name]||name;if(name==='traders')loadTraders();if(name==='multi-trader')loadMultiTrader(false);if(name==='history')loadPaths();if(name==='system')loadSystem();"
    new_route="const titles={overview:'Overview',traders:'Trader universe','portfolio-lab':'Portfolio Lab','multi-trader':'Multi-Trader Mode','profit-tax':'Profit & Tax Centre','strategy-watch':'Strategy Tax Watch',history:'Trade behaviour',reports:'Reports & exports',data:'Data import',system:'Source & system'};$('#page-title').textContent=titles[name]||name;if(name==='traders')loadTraders();if(name==='portfolio-lab')loadPortfolioLab();if(name==='multi-trader')loadMultiTrader(false);if(name==='profit-tax'){itLoadP2PRates();itLoadProfitTax()}if(name==='strategy-watch')itLoadProfitTax();if(name==='history'){loadTradeBehaviour();loadPaths()}if(name==='system')loadSystem();"
    if old_route in js: js=js.replace(old_route,new_route,1)
    else:
        # Update a close-equivalent legacy route without altering unrelated handlers.
        pattern=r"const titles=\\{overview:'Overview'.*?if\\(name==='system'\\)loadSystem\\(\\);"
        js,count=re.subn(pattern,new_route,js,count=1)
        if count==0: print("Tax UI uses the authenticated navigation failsafe; no legacy router replacement was required.")
    js += "\n// BI_TAX_CENTRE_CLIENT_V1\n"+r'''function itMoney(v, digits=2){const n=Number(v);return Number.isFinite(n)?n.toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'—'}
function itUsdt(v){const n=Number(v);return Number.isFinite(n)?itMoney(n,2)+' USDT':'—'}
function itInr(v){const n=Number(v);return Number.isFinite(n)?'₹'+itMoney(n,2):'—'}
function itSafeRate(){const n=Number($('#pt-rate')&&$('#pt-rate').value);return Number.isFinite(n)&&n>0?n:null}
function itLoadStrategyWatch(d){
 const rows=d.by_strategy||[];const rate=itSafeRate();const positive=rows.filter(x=>Number(x.net_after_tax_reserve_usdt)>0).length;const risk=rows.length-positive;
 $('#stw-count').textContent=String(rows.length);$('#stw-positive').textContent=String(positive);$('#stw-risk').textContent=String(risk);
 $('#stw-net').textContent=itUsdt(d.summary&&d.summary.net_after_tax_reserve_usdt);
 $('#stw-net-inr').textContent='INR: '+(rate?itInr(Number(d.summary&&d.summary.net_after_tax_reserve_usdt||0)*rate):'rate unavailable');
 $('#stw-alert').textContent=!rows.length?'No personal strategy records yet. Import or sync your Binance account ledger; public lead-trader positions are intentionally excluded.':(risk?'Warning: '+risk+' of '+rows.length+' strategy labels are non-positive after tax reserve or have losses at least as large as positive gains. Investigate before allocating more capital.':'All imported labels are positive after the conservative reserve in this recorded period; future profitability is not guaranteed.');
 $('#stw-rows').innerHTML=rows.length?rows.map(x=>{const ratio=x.loss_to_gain_ratio==null?'N/A':itMoney(x.loss_to_gain_ratio*100,1)+'%';const cost=Number(x.commission_usdt||0)+Number(x.funding_usdt||0);const warn=x.status==='POSITIVE_IN_IMPORTED_RECORDS'?'Monitor; no guarantee':x.status==='HIGH_COST_DRAG'?'WARNING: high cost drag':x.status==='LOSSES_MATCH_OR_EXCEED_GAINS'?'WARNING: losses match/exceed gains':'WARNING: non-positive after reserve';return '<tr><td><strong>'+esc(x.strategy_name)+'</strong></td><td>'+n(x.record_count,0)+'</td><td>'+itUsdt(x.positive_realized_pnl_usdt)+'</td><td class="negative">'+itUsdt(x.gross_loss_usdt)+'</td><td>'+ratio+'</td><td>'+itUsdt(cost)+'</td><td>'+itUsdt(x.tax_reserve_usdt)+'</td><td>'+(rate?itInr(Number(x.tax_reserve_usdt||0)*rate):'—')+'</td><td class="'+colorNum(x.economic_net_pnl_usdt)+'">'+itUsdt(x.economic_net_pnl_usdt)+'</td><td class="'+colorNum(x.net_after_tax_reserve_usdt)+'">'+itUsdt(x.net_after_tax_reserve_usdt)+'</td><td>'+(rate?itInr(Number(x.net_after_tax_reserve_usdt||0)*rate):'—')+'</td><td style="white-space:normal;min-width:220px">'+esc(warn)+'</td></tr>'}).join(''):'<tr><td colspan="12" class="empty-state">No imported personal strategy records.</td></tr>';
}
function itRenderTax(d){
 const s=d.summary||{};const rate=itSafeRate();const get=(k)=>Number(s[k]||0);
 $('#pt-positive').textContent=itUsdt(s.positive_realized_pnl_usdt);$('#pt-tax').textContent=itUsdt(s.tax_reserve_usdt);$('#pt-net').textContent=itUsdt(s.economic_net_pnl_usdt);$('#pt-after').textContent=itUsdt(s.net_after_tax_reserve_usdt);
 $('#pt-positive-inr').textContent='INR: '+(rate?itInr(get('positive_realized_pnl_usdt')*rate):'—');$('#pt-tax-inr').textContent='INR: '+(rate?itInr(get('tax_reserve_usdt')*rate):'—');$('#pt-net-inr').textContent='INR: '+(rate?itInr(get('economic_net_pnl_usdt')*rate):'—');$('#pt-after-inr').textContent='INR: '+(rate?itInr(get('net_after_tax_reserve_usdt')*rate):'—');
 $('#pt-ledger-status').textContent=d.record_count+' personal records · '+(d.included_usdt_record_count||0)+' USDT records counted';
 $('#pt-row-count').textContent=(d.recent||[]).length+' recent records shown';
 $('#pt-warning').textContent=!d.has_personal_records?'No personal trade ledger imported yet. Sync Binance Futures income history with a read-only key or upload a realised-PnL CSV. No public lead-trader PnL has been included.':(get('net_after_tax_reserve_usdt')<=0?'LOSS WARNING: economic PnL after the conservative tax reserve is non-positive. Review strategy performance, fees, funding and position sizing. ':'Imported-records result is positive after the reserve in this period, but this is not a guarantee. ')+(d.excluded_non_usdt_or_unconverted_count?' '+d.excluded_non_usdt_or_unconverted_count+' records use non-USDT assets or have no conversion and are excluded from USDT totals.':'')+' Tax estimate is provisional; futures classification must be reviewed.';
 const sr=d.by_strategy||[];$('#pt-strategy-rows').innerHTML=sr.length?sr.map(x=>'<tr><td><strong>'+esc(x.strategy_name)+'</strong></td><td>'+n(x.record_count,0)+'</td><td>'+itUsdt(x.positive_realized_pnl_usdt)+'</td><td class="negative">'+itUsdt(x.gross_loss_usdt)+'</td><td>'+itUsdt(x.commission_usdt)+'</td><td>'+itUsdt(x.funding_usdt)+'</td><td>'+itUsdt(x.tax_reserve_usdt)+'</td><td>'+(rate?itInr(Number(x.tax_reserve_usdt||0)*rate):'—')+'</td><td class="'+colorNum(x.economic_net_pnl_usdt)+'">'+itUsdt(x.economic_net_pnl_usdt)+'</td><td class="'+colorNum(x.net_after_tax_reserve_usdt)+'">'+itUsdt(x.net_after_tax_reserve_usdt)+'</td><td>'+(rate?itInr(Number(x.net_after_tax_reserve_usdt||0)*rate):'—')+'</td><td>'+esc(x.status)+'</td></tr>').join(''):'<tr><td colspan="12" class="empty-state">No imported personal trade records.</td></tr>';
  const groupedTrades=d.recent_trades||[];$('#pt-trade-rows').innerHTML=groupedTrades.length?groupedTrades.map(x=>'<tr><td>'+esc(x.time||'—')+'</td><td>'+esc(x.strategy_name||'—')+'</td><td>'+esc(x.market_type||'—')+'</td><td>'+esc(x.symbol||'—')+'</td><td>'+esc(x.group_type==='TRADE'?'Trade '+(x.trade_id||''):'Unattributed income event')+'</td><td class="'+colorNum(x.realized_pnl_usdt)+'">'+itUsdt(x.realized_pnl_usdt)+'</td><td>'+itUsdt(x.commission_usdt)+'</td><td>'+itUsdt(x.funding_usdt)+'</td><td>'+itUsdt(x.tax_reserve_usdt)+'</td><td>'+(rate?itInr(Number(x.tax_reserve_usdt||0)*rate):'—')+'</td><td class="'+colorNum(x.net_after_reserve_usdt)+'">'+itUsdt(x.net_after_reserve_usdt)+'</td><td>'+(rate?itInr(Number(x.net_after_reserve_usdt||0)*rate):'—')+'</td><td>'+esc(x.status||'—')+'</td></tr>').join(''):'<tr><td colspan="11" class="empty-state">No imported personal trade records.</td></tr>';
 const recent=d.recent||[];$('#pt-ledger-rows').innerHTML=recent.length?recent.map(x=>'<tr><td>'+esc(x.time||'—')+'</td><td>'+esc(x.strategy_name||'—')+'</td><td>'+esc(x.market_type||'—')+'</td><td>'+esc(x.symbol||'—')+'</td><td>'+esc(x.income_type||'—')+'</td><td>'+esc(x.asset||'—')+' '+itMoney(x.amount_asset,6)+'</td><td class="'+colorNum(x.realized_pnl_usdt)+'">'+itUsdt(x.realized_pnl_usdt)+'</td><td>'+itUsdt(x.commission_usdt)+'</td><td>'+itUsdt(x.funding_usdt)+'</td><td>'+itUsdt(x.tax_reserve_usdt)+'</td><td class="'+colorNum(x.net_after_reserve_usdt)+'">'+itUsdt(x.net_after_reserve_usdt)+'</td></tr>').join(''):'<tr><td colspan="11" class="empty-state">No imported personal trade records. Connect a read-only key or import CSV.</td></tr>';
 itLoadStrategyWatch(d);
}
async function itLoadP2PRates(){
 try{const r=await api('/api/profit-tax/rates');$('#pt-buy-rate').value=r.buy_quote_inr_per_usdt||'';$('#pt-sell-rate').value=r.sell_quote_inr_per_usdt||'';$('#pt-rate-status').textContent=r.sell_quote_inr_per_usdt?'Binance P2P quote · '+String(r.as_of_utc||'').slice(0,19)+' UTC':'P2P quote unavailable · enter a rate manually';if(!$('#pt-rate').dataset.manual&&r.sell_quote_inr_per_usdt)$('#pt-rate').value=r.sell_quote_inr_per_usdt;$('#pt-rate-status').title=r.note||r.source||'';if(typeof state!=='undefined'&&(state.view==='profit-tax'||state.view==='strategy-watch'))await itLoadProfitTax()}catch(e){$('#pt-rate-status').textContent='P2P source unavailable · enter rate manually'}
}
async function itLoadProfitTax(){
 try{const d=await api('/api/profit-tax/summary');itRenderTax(d)}catch(e){$('#pt-warning').textContent='Unable to load Profit & Tax Centre: '+e.message;$('#pt-ledger-status').textContent='Data load failed'}
}
async function itSyncBinance(){
 const key=$('#pt-api-key').value.trim(), secret=$('#pt-api-secret').value, days=Number($('#pt-days').value||30), label=$('#pt-strategy-sync').value.trim();
 if(!key||!secret){toast('Enter both API key and API secret for this one-time read-only request.','error');return}
 const b=$('#pt-sync');b.disabled=true;b.textContent='Requesting Binance records…';
 try{const d=await api('/api/profit-tax/sync',{method:'POST',body:JSON.stringify({api_key:key,api_secret:secret,lookback_days:days,strategy_name:label})});$('#pt-api-key').value='';$('#pt-api-secret').value='';$('#pt-api-secret').type='password';toast('Binance income records fetched: '+n(d.sync&&d.sync.fetched_supported_income_records,0)+'; new records saved: '+n(d.sync&&d.sync.new_records_saved,0)+'.','success');itRenderTax(d);await itLoadP2PRates()}catch(e){$('#pt-api-secret').value='';toast('Binance sync failed: '+e.message,'error')}finally{$('#pt-api-key').value='';$('#pt-api-secret').value='';b.disabled=false;b.textContent='Request Binance income history'}
}
async function itImportTaxCsv(){
 const file=$('#pt-csv').files&&$('#pt-csv').files[0];if(!file){toast('Choose a CSV file first.','error');return}
 const form=new FormData();form.append('file',file);form.append('market_type',$('#pt-market-csv').value);form.append('strategy_name',$('#pt-strategy-csv').value.trim());
 const b=$('#pt-import');b.disabled=true;b.textContent='Importing CSV…';
 try{const response=await fetch('/api/profit-tax/import',{method:'POST',body:form,credentials:'same-origin'});const d=await response.json();if(!response.ok||d.error)throw new Error(d.error||('HTTP '+response.status));toast('Recognised '+n(d.import&&d.import.recognised_records,0)+' records; saved '+n(d.import&&d.import.new_records_saved,0)+' new rows.','success');itRenderTax(d);$('#pt-csv').value=''}catch(e){toast('CSV import failed: '+e.message,'error')}finally{b.disabled=false;b.textContent='Import CSV records'}
}

function itBindTaxControls(){
 if($('#pt-sync'))$('#pt-sync').addEventListener('click',itSyncBinance);
 if($('#pt-import'))$('#pt-import').addEventListener('click',itImportTaxCsv);
 if($('#pt-refresh-rate'))$('#pt-refresh-rate').addEventListener('click',itLoadP2PRates);
 if($('#pt-rate'))$('#pt-rate').addEventListener('input',()=>{$('#pt-rate').dataset.manual='1';itLoadProfitTax()});
}
if(!window.__biTaxCentreControlsWired){window.__biTaxCentreControlsWired=true;itBindTaxControls();}

'''
js_path.write_text(js)
print("Installed Profit & Tax Centre and Strategy Tax Watch in the Binance Intel app.")
