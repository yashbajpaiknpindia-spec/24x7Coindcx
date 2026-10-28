from pathlib import Path

ROOT = Path("/app")
HTML_PATH = ROOT / "templates" / "index.html"
APP_PATH = ROOT / "app.py"

# Add a real navigation link without intercepting the existing SPA router.
html = HTML_PATH.read_text()
nav_marker = "href=\"/dual-investment\""
if nav_marker not in html:
    anchor = '    <button class="nav-link" data-view="reports">'
    link = '    <a class="nav-link" href="/dual-investment"><span class="nav-ico">◈</span> Dual Investment Lab</a>\n'
    if anchor not in html:
        raise RuntimeError("Cannot install Dual Investment Lab navigation: Reports nav anchor not found")
    html = html.replace(anchor, link + anchor, 1)
HTML_PATH.write_text(html)

app_source = APP_PATH.read_text()
if "BINANCE_DUAL_INVESTMENT_INTELLIGENCE_V1" not in app_source:
    app_source += r'''

# BINANCE_DUAL_INVESTMENT_INTELLIGENCE_V1
# Public market data + official Dual Investment product-list API.
# PAPER ONLY: there is intentionally no subscribe/order/transfer route in this patch.
import os as _di_os
import json as _di_json
import time as _di_time
import uuid as _di_uuid
import math as _di_math
import hmac as _di_hmac
import hashlib as _di_hashlib
import statistics as _di_stats
import urllib.parse as _di_parse
import urllib.request as _di_request
import urllib.error as _di_error
import datetime as _di_datetime
import sqlalchemy as _di_sa
from flask import Response as _di_Response, request as _di_request_obj, jsonify as _di_jsonify

_DI_PAIRS = [
    {"pair": "BTC/USDT", "base": "BTC", "quote": "USDT", "symbol": "BTCUSDT", "asset_group": "BTC"},
    {"pair": "BTC/USDC", "base": "BTC", "quote": "USDC", "symbol": "BTCUSDC", "asset_group": "BTC"},
    {"pair": "ETH/USDT", "base": "ETH", "quote": "USDT", "symbol": "ETHUSDT", "asset_group": "ETH"},
]
_DI_API = "https://api.binance.com"
_DI_TAXONOMY = {
    "BUY_LOW": {"optionType": "PUT", "deposit": "quote"},
    "SELL_HIGH": {"optionType": "CALL", "deposit": "base"},
}
_DI_VERSION = "dual-investment-intelligence-v1"


def _di_now_ms():
    return int(_di_time.time() * 1000)


def _di_utc_now():
    return _di_datetime.datetime.now(_di_datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _di_f(value, default=0.0):
    try:
        number = float(value)
        return number if _di_math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _di_jsonable(value):
    return _di_json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str, allow_nan=False)


def _di_db_init():
    with SessionLocal() as db:
        dialect = db.get_bind().dialect.name
        pk = "BIGSERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        db.execute(_di_sa.text("""
          CREATE TABLE IF NOT EXISTS dual_inv_scan_runs (
            scan_id TEXT PRIMARY KEY,
            started_at_utc TEXT NOT NULL,
            finished_at_utc TEXT,
            status TEXT NOT NULL,
            amount_usdt DOUBLE PRECISION NOT NULL,
            direction_filter TEXT NOT NULL,
            max_target_distance_pct DOUBLE PRECISION NOT NULL,
            max_tail_loss_pct DOUBLE PRECISION NOT NULL,
            products_fetched INTEGER NOT NULL DEFAULT 0,
            offers_recorded INTEGER NOT NULL DEFAULT 0,
            selected_count INTEGER NOT NULL DEFAULT 0,
            markets_json TEXT NOT NULL DEFAULT '{}',
            errors_json TEXT NOT NULL DEFAULT '[]'
          )
        """))
        db.execute(_di_sa.text("""
          CREATE TABLE IF NOT EXISTS dual_inv_offer_snapshots (
            id %s,
            scan_id TEXT NOT NULL,
            product_key TEXT NOT NULL,
            product_id TEXT,
            order_id TEXT,
            pair TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            deposit_currency TEXT,
            target_currency TEXT,
            target_price DOUBLE PRECISION,
            apr_rate DOUBLE PRECISION,
            settle_date_ms BIGINT,
            hours_to_settle DOUBLE PRECISION,
            spot_price DOUBLE PRECISION,
            quote_to_usdt DOUBLE PRECISION,
            target_distance_pct DOUBLE PRECISION,
            estimated_reward_usdt DOUBLE PRECISION,
            empirical_exercise_probability DOUBLE PRECISION,
            history_sample_count INTEGER NOT NULL DEFAULT 0,
            expected_pnl_usdt DOUBLE PRECISION,
            expected_edge_vs_hold_usdt DOUBLE PRECISION,
            p05_pnl_usdt DOUBLE PRECISION,
            score DOUBLE PRECISION,
            can_purchase BOOLEAN NOT NULL DEFAULT FALSE,
            selected BOOLEAN NOT NULL DEFAULT FALSE,
            decision TEXT NOT NULL,
            reasons_json TEXT NOT NULL DEFAULT '[]',
            min_amount DOUBLE PRECISION,
            max_amount DOUBLE PRECISION,
            raw_json TEXT NOT NULL DEFAULT '{}',
            created_at_utc TEXT NOT NULL,
            UNIQUE(scan_id, product_key)
          )
        """ % pk))
        db.execute(_di_sa.text("""
          CREATE INDEX IF NOT EXISTS ix_dual_inv_offer_scan ON dual_inv_offer_snapshots(scan_id)
        """))
        db.execute(_di_sa.text("""
          CREATE TABLE IF NOT EXISTS dual_inv_paper_decisions (
            id %s,
            offer_key TEXT NOT NULL UNIQUE,
            scan_id TEXT NOT NULL,
            product_id TEXT,
            pair TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            deposit_currency TEXT,
            target_currency TEXT,
            target_price DOUBLE PRECISION NOT NULL,
            apr_rate DOUBLE PRECISION NOT NULL,
            settle_date_ms BIGINT NOT NULL,
            hours_to_settle DOUBLE PRECISION NOT NULL,
            entry_spot DOUBLE PRECISION NOT NULL,
            quote_to_usdt DOUBLE PRECISION NOT NULL DEFAULT 1,
            amount_usdt DOUBLE PRECISION NOT NULL,
            estimated_reward_usdt DOUBLE PRECISION NOT NULL,
            expected_pnl_usdt DOUBLE PRECISION NOT NULL,
            expected_edge_vs_hold_usdt DOUBLE PRECISION NOT NULL,
            exercise_probability DOUBLE PRECISION NOT NULL,
            p05_pnl_usdt DOUBLE PRECISION,
            score DOUBLE PRECISION,
            sample_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            fixing_price_proxy DOUBLE PRECISION,
            settlement_value_usdt DOUBLE PRECISION,
            paper_pnl_usdt DOUBLE PRECISION,
            benchmark_value_usdt DOUBLE PRECISION,
            edge_vs_hold_usdt DOUBLE PRECISION,
            settlement_source TEXT,
            settlement_note TEXT,
            created_at_utc TEXT NOT NULL,
            settled_at_utc TEXT
          )
        """ % pk))
        db.execute(_di_sa.text("""
          CREATE INDEX IF NOT EXISTS ix_dual_inv_paper_status ON dual_inv_paper_decisions(status, settle_date_ms)
        """))
        db.commit()


def _di_http_json(url, headers=None, timeout=14):
    req = _di_request.Request(url, headers=headers or {"User-Agent": "DualInvestmentIntelligence/1.0"})
    try:
        with _di_request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            if len(raw) > 8_000_000:
                raise RuntimeError("Binance response exceeded the safety size limit")
            return _di_json.loads(raw.decode("utf-8"))
    except _di_error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(1200).decode("utf-8", "replace")
        except Exception:
            pass
        raise RuntimeError("Binance HTTP " + str(exc.code) + (": " + detail[:500] if detail else ""))
    except _di_error.URLError as exc:
        raise RuntimeError("Binance network request failed: " + str(getattr(exc, "reason", exc))[:250])
    except _di_json.JSONDecodeError:
        raise RuntimeError("Binance returned a non-JSON response")


def _di_signed_dual_list(params):
    api_key = (_di_os.environ.get("BINANCE_API_KEY") or "").strip()
    api_secret = (_di_os.environ.get("BINANCE_API_SECRET") or "").strip()
    query_params = dict(params)
    headers = {"User-Agent": "DualInvestmentIntelligence/1.0"}
    if api_key and api_secret:
        query_params["recvWindow"] = 5000
        query_params["timestamp"] = _di_now_ms()
        payload = _di_parse.urlencode(query_params)
        signature = _di_hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), _di_hashlib.sha256).hexdigest()
        url = _DI_API + "/sapi/v1/dci/product/list?" + payload + "&signature=" + signature
        headers["X-MBX-APIKEY"] = api_key
        try:
            return _di_http_json(url, headers=headers), "SIGNED_READ_ONLY_API"
        except Exception as signed_error:
            # The endpoint is catalogued under product market data. Try its unsigned form
            # if the account key is not authorised, but retain a visible diagnostic.
            unsigned_url = _DI_API + "/sapi/v1/dci/product/list?" + _di_parse.urlencode(params)
            try:
                result = _di_http_json(unsigned_url, headers={"User-Agent": "DualInvestmentIntelligence/1.0"})
                return result, "UNSIGNED_API_FALLBACK_AFTER_SIGNED_ERROR"
            except Exception:
                raise RuntimeError(str(signed_error)[:500])
    url = _DI_API + "/sapi/v1/dci/product/list?" + _di_parse.urlencode(params)
    return _di_http_json(url), "UNSIGNED_API"


def _di_get_products(option_type, exercised_coin, invest_coin):
    all_items = []
    method = None
    for page in range(1, 4):
        params = {
            "optionType": option_type,
            "exercisedCoin": exercised_coin,
            "investCoin": invest_coin,
            "pageSize": 100,
            "pageIndex": page,
        }
        payload, used = _di_signed_dual_list(params)
        method = used
        if not isinstance(payload, dict):
            raise RuntimeError("Dual Investment product-list response has an unexpected shape")
        if "code" in payload and int(_di_f(payload.get("code"), 0)) < 0:
            raise RuntimeError("Dual Investment API rejected the request: " + str(payload.get("msg", payload.get("code")))[:300])
        items = payload.get("list") or []
        if not isinstance(items, list):
            raise RuntimeError("Dual Investment product-list field was not a list")
        all_items.extend(items)
        total = int(_di_f(payload.get("total"), len(all_items)))
        if not items or len(all_items) >= total or len(items) < 100:
            break
    return all_items, method


def _di_market_snapshot(pair):
    symbol = pair["symbol"]
    ticker = _di_http_json(_DI_API + "/api/v3/ticker/price?" + _di_parse.urlencode({"symbol": symbol}))
    spot = _di_f(ticker.get("price") if isinstance(ticker, dict) else None, 0)
    if spot <= 0:
        raise RuntimeError("No positive spot price returned for " + symbol)
    raw_klines = _di_http_json(_DI_API + "/api/v3/klines?" + _di_parse.urlencode({
        "symbol": symbol, "interval": "1h", "limit": 1000
    }), timeout=20)
    if not isinstance(raw_klines, list):
        raise RuntimeError("Hourly candle response was not a list for " + symbol)
    closes = []
    for candle in raw_klines:
        try:
            close = _di_f(candle[4], 0)
            if close > 0:
                closes.append(close)
        except (TypeError, IndexError):
            continue
    if len(closes) < 100:
        raise RuntimeError("Only " + str(len(closes)) + " usable hourly closes for " + symbol + "; historical proxy needs at least 100")
    returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]
    recent_returns = returns[-24:]
    vol24 = (_di_stats.pstdev(recent_returns) * _di_math.sqrt(24) * 100) if len(recent_returns) >= 2 else None
    trend24 = (closes[-1] / closes[-25] - 1) * 100 if len(closes) >= 25 else None
    return {
        "symbol": symbol,
        "spot": spot,
        "closes": closes,
        "candle_count": len(closes),
        "volatility_24h_pct": vol24,
        "trend_24h_pct": trend24,
        "market_source": "Binance Spot ticker + 1h klines",
        "retrieved_at_utc": _di_utc_now(),
    }


def _di_quote_to_usdt(quote, factor_map):
    if quote == "USDT":
        return 1.0
    if quote == "USDC":
        return factor_map.get("USDCUSDT", 1.0)
    return 1.0


def _di_percentile(values, percentile):
    if not values:
        return None
    values = sorted(values)
    position = max(0, min(len(values) - 1, int(_di_math.floor((len(values) - 1) * percentile))))
    return values[position]


def _di_evaluate_offer(product, pair, direction, market, quote_factor, amount_usdt, max_distance, max_tail_loss_pct):
    now = _di_now_ms()
    target = _di_f(product.get("strikePrice"), 0)
    apr_raw = _di_f(product.get("apr"), 0)
    # API examples encode 60.76% as 0.6076. Tolerate a percent-form field too.
    apr_rate = apr_raw / 100.0 if apr_raw > 10 else apr_raw
    settle_ms = int(_di_f(product.get("settleDate"), 0))
    hours = (settle_ms - now) / 3_600_000.0
    spot = market["spot"]
    distance = abs((target / spot) - 1) * 100 if target > 0 and spot > 0 else None
    is_buy = direction == "BUY_LOW"
    can_purchase = bool(product.get("canPurchase", False))
    min_amount = _di_f(product.get("minAmount"), 0)
    max_amount = _di_f(product.get("maxAmount"), 0)
    if is_buy:
        deposit_currency = pair["quote"]
        target_currency = pair["base"]
        subscription_units = amount_usdt / quote_factor
    else:
        deposit_currency = pair["base"]
        target_currency = pair["quote"]
        subscription_units = amount_usdt / (spot * quote_factor)
    reward_rate = max(0.0, apr_rate) * max(0.0, hours / 24.0) / 365.0
    reward_usdt = amount_usdt * reward_rate
    reasons = []
    if not can_purchase:
        reasons.append("API says this product cannot currently be purchased")
    if target <= 0 or spot <= 0:
        reasons.append("Missing target/spot price")
    if hours <= 0:
        reasons.append("Settlement time is not in the future")
    if apr_rate <= 0:
        reasons.append("APR is not positive")
    if distance is None or distance > max_distance:
        reasons.append("Target is outside the configured %.2f%% distance limit" % max_distance)
    if is_buy and target >= spot:
        reasons.append("Buy Low target must be below the current spot price")
    if not is_buy and target <= spot:
        reasons.append("Sell High target must be above the current spot price")
    if min_amount > 0 and subscription_units < min_amount:
        reasons.append("Paper amount is below product minimum " + str(min_amount) + " " + deposit_currency)
    if max_amount > 0 and subscription_units > max_amount:
        reasons.append("Paper amount exceeds product maximum " + str(max_amount) + " " + deposit_currency)

    closes = market.get("closes") or []
    horizon = max(1, min(len(closes) - 2, int(_di_math.ceil(hours))))
    ratios = []
    for i in range(0, max(0, len(closes) - horizon)):
        start = closes[i]
        end = closes[i + horizon]
        if start > 0 and end > 0:
            ratios.append(end / start)
    if len(ratios) < 100:
        reasons.append("Insufficient same-horizon hourly samples (need at least 100)")
    target_ratio = target / spot if spot > 0 else 0
    exercised = [(r <= target_ratio) if is_buy else (r >= target_ratio) for r in ratios]
    p_exercise = (sum(1 for x in exercised if x) / len(exercised)) if exercised else None

    # Simulate terminal-value outcomes from observed historical same-horizon returns.
    # This is a historical proxy distribution, not a forecast or a calibrated probability.
    pnl_samples = []
    edge_samples = []
    if ratios and target > 0 and apr_rate > 0 and hours > 0:
        if is_buy:
            deposit_quote = amount_usdt / quote_factor
            reward_quote = deposit_quote * reward_rate
            for ratio, did_exercise in zip(ratios, exercised):
                future_price = spot * ratio
                terminal_quote = ((deposit_quote + reward_quote) * future_price / target
                                  if did_exercise else deposit_quote + reward_quote)
                final_usdt = terminal_quote * quote_factor
                pnl = final_usdt - amount_usdt
                pnl_samples.append(pnl)
                edge_samples.append(pnl)  # baseline is staying in stablecoin
        else:
            deposit_base = amount_usdt / (spot * quote_factor)
            reward_base = deposit_base * reward_rate
            for ratio, did_exercise in zip(ratios, exercised):
                future_price = spot * ratio
                terminal_quote = ((deposit_base + reward_base) * target
                                  if did_exercise else (deposit_base + reward_base) * future_price)
                final_usdt = terminal_quote * quote_factor
                baseline_hold_usdt = deposit_base * future_price * quote_factor
                pnl_samples.append(final_usdt - amount_usdt)
                edge_samples.append(final_usdt - baseline_hold_usdt)
    expected_pnl = (sum(pnl_samples) / len(pnl_samples)) if pnl_samples else None
    expected_edge = (sum(edge_samples) / len(edge_samples)) if edge_samples else None
    p05_pnl = _di_percentile(pnl_samples, 0.05)
    sample_count = len(ratios)
    if expected_edge is None:
        reasons.append("Expected-value estimate unavailable")
    elif expected_edge <= 0:
        reasons.append("Modelled edge versus the natural hold/cash benchmark is not positive")
    if p05_pnl is not None and p05_pnl < -(amount_usdt * max_tail_loss_pct / 100.0):
        reasons.append("Historical 5th-percentile simulated PnL breaches the %.2f%% loss gate" % max_tail_loss_pct)

    selected_gate = not reasons
    expected_edge_pct = (expected_edge / amount_usdt * 100.0) if expected_edge is not None and amount_usdt else -999.0
    tail_penalty = max(0.0, (-(p05_pnl or 0.0) / amount_usdt * 100.0)) if amount_usdt else 100.0
    score = (50.0 + expected_edge_pct * 10.0 - tail_penalty * 2.0 + min(sample_count / 500.0, 1.0) * 5.0) if expected_edge is not None else -999.0
    product_id = str(product.get("id") or "")
    order_id = str(product.get("orderId") or "")
    product_key = "|".join([pair["symbol"], direction, str(target), str(settle_ms), product_id or order_id])
    return {
        "product_key": product_key,
        "product_id": product_id,
        "order_id": order_id,
        "pair": pair["pair"],
        "symbol": pair["symbol"],
        "asset_group": pair["asset_group"],
        "direction": direction,
        "deposit_currency": deposit_currency,
        "target_currency": target_currency,
        "target_price": target,
        "apr_rate": apr_rate,
        "apr_pct": apr_rate * 100.0,
        "settle_date_ms": settle_ms,
        "hours_to_settle": hours,
        "spot_price": spot,
        "quote_to_usdt": quote_factor,
        "target_distance_pct": distance,
        "estimated_reward_usdt": reward_usdt,
        "empirical_exercise_probability": p_exercise,
        "history_sample_count": sample_count,
        "expected_pnl_usdt": expected_pnl,
        "expected_edge_vs_hold_usdt": expected_edge,
        "p05_pnl_usdt": p05_pnl,
        "score": score,
        "can_purchase": can_purchase,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "subscription_units": subscription_units,
        "decision": "ELIGIBLE_PENDING_RANK" if selected_gate else "REJECTED",
        "selected": False,
        "reasons": reasons,
        "raw": product,
    }


def _di_settle_matured():
    _di_db_init()
    now = _di_now_ms()
    with SessionLocal() as db:
        rows = db.execute(_di_sa.text("""
          SELECT id,offer_key,pair,symbol,direction,target_price,apr_rate,settle_date_ms,
                 hours_to_settle,entry_spot,quote_to_usdt,amount_usdt,created_at_utc
          FROM dual_inv_paper_decisions
          WHERE status='OPEN' AND settle_date_ms < :ready_before
          ORDER BY settle_date_ms ASC LIMIT 50
        """), {"ready_before": now - 3_600_000}).mappings().all()
    settled = 0
    for row in rows:
        settle_ms = int(row["settle_date_ms"])
        start_ms = settle_ms - 30 * 60_000
        try:
            candles = _di_http_json(_DI_API + "/api/v3/klines?" + _di_parse.urlencode({
                "symbol": row["symbol"], "interval": "1m",
                "startTime": start_ms, "endTime": settle_ms, "limit": 30
            }), timeout=12)
            closes = [_di_f(c[4], 0) for c in candles if isinstance(c, list) and len(c) > 4 and _di_f(c[4], 0) > 0] if isinstance(candles, list) else []
            if len(closes) < 25:
                raise RuntimeError("Fewer than 25 one-minute closes were returned for the fixing window")
            fixing = sum(closes) / len(closes)
            target = _di_f(row["target_price"], 0)
            apr_rate = _di_f(row["apr_rate"], 0)
            hours = _di_f(row["hours_to_settle"], 0)
            amount_usdt = _di_f(row["amount_usdt"], 0)
            entry = _di_f(row["entry_spot"], 0)
            quote_factor = _di_f(row["quote_to_usdt"], 1)
            days = max(0, hours / 24.0)
            reward_rate = apr_rate * days / 365.0
            direction = row["direction"]
            if direction == "BUY_LOW":
                deposit_quote = amount_usdt / quote_factor
                reward_quote = deposit_quote * reward_rate
                if fixing <= target:
                    final_quote = (deposit_quote + reward_quote) * fixing / target
                else:
                    final_quote = deposit_quote + reward_quote
                final_value = final_quote * quote_factor
                benchmark = amount_usdt
            else:
                deposit_base = amount_usdt / (entry * quote_factor)
                reward_base = deposit_base * reward_rate
                if fixing >= target:
                    final_quote = (deposit_base + reward_base) * target
                else:
                    final_quote = (deposit_base + reward_base) * fixing
                final_value = final_quote * quote_factor
                benchmark = deposit_base * fixing * quote_factor
            pnl = final_value - amount_usdt
            edge = final_value - benchmark
            note = "Simulated fixing proxy: mean of Binance 1m candle close prices in the 30-minute pre-settlement window. Not the official product fixing price."
            with SessionLocal() as db:
                db.execute(_di_sa.text("""
                  UPDATE dual_inv_paper_decisions
                  SET status='SETTLED_PROXY', fixing_price_proxy=:fixing,
                      settlement_value_usdt=:final_value, paper_pnl_usdt=:pnl,
                      benchmark_value_usdt=:benchmark, edge_vs_hold_usdt=:edge,
                      settlement_source='BINANCE_1M_CLOSE_PROXY', settlement_note=:note,
                      settled_at_utc=:settled_at
                  WHERE offer_key=:offer_key AND status='OPEN'
                """), {
                    "fixing": fixing, "final_value": final_value, "pnl": pnl,
                    "benchmark": benchmark, "edge": edge, "note": note,
                    "settled_at": _di_utc_now(), "offer_key": row["offer_key"]
                })
                db.commit()
            settled += 1
        except Exception as exc:
            with SessionLocal() as db:
                db.execute(_di_sa.text("""
                  UPDATE dual_inv_paper_decisions SET settlement_note=:note
                  WHERE offer_key=:offer_key AND status='OPEN'
                """), {"note": ("Settlement data pending: " + str(exc))[:500], "offer_key": row["offer_key"]})
                db.commit()
    return settled


def _di_read_state(limit=100):
    _di_db_init()
    limit = max(1, min(int(limit), 300))
    with SessionLocal() as db:
        scans = db.execute(_di_sa.text("""
          SELECT * FROM dual_inv_scan_runs ORDER BY started_at_utc DESC LIMIT 20
        """)).mappings().all()
        latest_id = scans[0]["scan_id"] if scans else None
        offer_rows = []
        if latest_id:
            offer_rows = db.execute(_di_sa.text("""
              SELECT * FROM dual_inv_offer_snapshots WHERE scan_id=:scan_id
              ORDER BY selected DESC, score DESC, target_distance_pct ASC
            """), {"scan_id": latest_id}).mappings().all()
        paper = db.execute(_di_sa.text("""
          SELECT * FROM dual_inv_paper_decisions ORDER BY created_at_utc DESC LIMIT :lim
        """), {"lim": limit}).mappings().all()
        counts = db.execute(_di_sa.text("""
          SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) AS open_count,
            SUM(CASE WHEN status='SETTLED_PROXY' THEN 1 ELSE 0 END) AS settled_count,
            SUM(CASE WHEN status='SETTLED_PROXY' THEN COALESCE(paper_pnl_usdt,0) ELSE 0 END) AS settled_pnl,
            SUM(CASE WHEN status='SETTLED_PROXY' THEN COALESCE(edge_vs_hold_usdt,0) ELSE 0 END) AS settled_edge
          FROM dual_inv_paper_decisions
        """)).mappings().first()
    def clean(row):
        result = dict(row)
        for key in ("markets_json", "errors_json", "raw_json", "reasons_json"):
            if key in result:
                try:
                    result[key.removesuffix("_json")] = _di_json.loads(result[key] or ("[]" if key == "errors_json" or key == "reasons_json" else "{}"))
                except Exception:
                    result[key.removesuffix("_json")] = result[key]
        return result
    return {
        "version": _DI_VERSION,
        "paper_only": True,
        "pairs": [{"pair": p["pair"], "symbol": p["symbol"], "asset": p["asset_group"]} for p in _DI_PAIRS],
        "latest_scan": clean(scans[0]) if scans else None,
        "scans": [clean(r) for r in scans],
        "offers": [clean(r) for r in offer_rows],
        "paper": [clean(r) for r in paper],
        "stats": {
            "total_paper_decisions": int(_di_f((counts or {}).get("total"), 0)),
            "open_paper_decisions": int(_di_f((counts or {}).get("open_count"), 0)),
            "settled_proxy_decisions": int(_di_f((counts or {}).get("settled_count"), 0)),
            "settled_pnl_usdt": _di_f((counts or {}).get("settled_pnl"), 0),
            "settled_edge_vs_hold_usdt": _di_f((counts or {}).get("settled_edge"), 0),
        }
    }


def _di_scan(amount_usdt, direction_filter, max_distance, max_tail_loss_pct):
    _di_db_init()
    scan_id = str(_di_uuid.uuid4())
    started = _di_utc_now()
    amount_usdt = max(1.0, min(100000.0, _di_f(amount_usdt, 150.0)))
    max_distance = max(0.1, min(25.0, _di_f(max_distance, 5.0)))
    max_tail_loss_pct = max(0.1, min(20.0, _di_f(max_tail_loss_pct, 3.0)))
    if direction_filter not in ("both", "buy_low", "sell_high"):
        direction_filter = "both"
    directions = ["BUY_LOW", "SELL_HIGH"] if direction_filter == "both" else (["BUY_LOW"] if direction_filter == "buy_low" else ["SELL_HIGH"])
    errors = []
    markets = {}
    product_candidates = []
    api_methods = set()
    factor_map = {"USDCUSDT": 1.0}
    try:
        price_payload = _di_http_json(_DI_API + "/api/v3/ticker/price?symbol=USDCUSDT", timeout=10)
        rate = _di_f(price_payload.get("price") if isinstance(price_payload, dict) else None, 0)
        if rate > 0:
            factor_map["USDCUSDT"] = rate
    except Exception as exc:
        errors.append("USDC/USDT conversion reference unavailable; USDC treated as 1.0 USDT only for indicative estimates: " + str(exc)[:180])
    for pair in _DI_PAIRS:
        try:
            markets[pair["symbol"]] = _di_market_snapshot(pair)
        except Exception as exc:
            errors.append(pair["symbol"] + " market data: " + str(exc)[:250])
    for pair in _DI_PAIRS:
        if pair["symbol"] not in markets:
            continue
        for direction in directions:
            option_type = "PUT" if direction == "BUY_LOW" else "CALL"
            exercised_coin = pair["base"] if direction == "BUY_LOW" else pair["quote"]
            invest_coin = pair["quote"] if direction == "BUY_LOW" else pair["base"]
            try:
                products, method = _di_get_products(option_type, exercised_coin, invest_coin)
                api_methods.add(method)
                quote_factor = _di_quote_to_usdt(pair["quote"], factor_map)
                for product in products:
                    try:
                        if str(product.get("investCoin", invest_coin)).upper() != invest_coin or str(product.get("exercisedCoin", exercised_coin)).upper() != exercised_coin:
                            continue
                        row = _di_evaluate_offer(product, pair, direction, markets[pair["symbol"]], quote_factor,
                                                 amount_usdt, max_distance, max_tail_loss_pct)
                        if row["settle_date_ms"] <= _di_now_ms():
                            row["decision"] = "EXPIRED"
                            row["reasons"] = ["Settlement time is not in the future"]
                            row["selected"] = False
                        product_candidates.append(row)
                    except Exception as exc:
                        errors.append(pair["symbol"] + " " + direction + " product parse: " + str(exc)[:180])
            except Exception as exc:
                errors.append(pair["symbol"] + " " + direction + " product API: " + str(exc)[:250])
    # At most one selected offer per underlying asset; no forced pick if every offer fails a gate.
    eligible = [r for r in product_candidates if r["decision"] == "ELIGIBLE_PENDING_RANK" and not r["reasons"]]
    best_by_asset = {}
    for candidate in eligible:
        key = candidate["asset_group"]
        if key not in best_by_asset or candidate["score"] > best_by_asset[key]["score"]:
            best_by_asset[key] = candidate
    for candidate in best_by_asset.values():
        candidate["selected"] = True
        candidate["decision"] = "PAPER_SELECTED"
        candidate["reasons"] = ["Highest risk-adjusted score for this underlying asset among offers passing every configured gate."]
    for candidate in product_candidates:
        if not candidate["selected"] and candidate["decision"] == "ELIGIBLE_PENDING_RANK":
            candidate["decision"] = "NOT_SELECTED"
            candidate["reasons"] = ["Passed basic gates but ranked below the selected offer for the same underlying asset."]
    status = "OK" if product_candidates and markets else ("PARTIAL" if markets or product_candidates else "API_ERROR")
    market_payload = {
        key: {k: v for k, v in value.items() if k != "closes"}
        for key, value in markets.items()
    }
    market_payload["quote_to_usdt"] = factor_map
    market_payload["api_methods"] = sorted(api_methods)
    with SessionLocal() as db:
        db.execute(_di_sa.text("""
          INSERT INTO dual_inv_scan_runs
            (scan_id,started_at_utc,status,amount_usdt,direction_filter,max_target_distance_pct,
             max_tail_loss_pct,products_fetched,offers_recorded,selected_count,markets_json,errors_json)
          VALUES
            (:scan_id,:started,:status,:amount,:direction,:distance,:tail,:fetched,:recorded,:selected,:markets,:errors)
        """), {
            "scan_id": scan_id, "started": started, "status": status,
            "amount": amount_usdt, "direction": direction_filter,
            "distance": max_distance, "tail": max_tail_loss_pct,
            "fetched": len(product_candidates), "recorded": len(product_candidates),
            "selected": sum(1 for x in product_candidates if x["selected"]),
            "markets": _di_jsonable(market_payload), "errors": _di_jsonable(errors)
        })
        for row in product_candidates:
            db.execute(_di_sa.text("""
              INSERT INTO dual_inv_offer_snapshots
                (scan_id,product_key,product_id,order_id,pair,symbol,direction,deposit_currency,target_currency,
                 target_price,apr_rate,settle_date_ms,hours_to_settle,spot_price,quote_to_usdt,target_distance_pct,
                 estimated_reward_usdt,empirical_exercise_probability,history_sample_count,expected_pnl_usdt,
                 expected_edge_vs_hold_usdt,p05_pnl_usdt,score,can_purchase,selected,decision,reasons_json,
                 min_amount,max_amount,raw_json,created_at_utc)
              VALUES
                (:scan_id,:product_key,:product_id,:order_id,:pair,:symbol,:direction,:deposit_currency,:target_currency,
                 :target_price,:apr_rate,:settle_date_ms,:hours_to_settle,:spot_price,:quote_to_usdt,:distance,
                 :reward,:probability,:samples,:pnl,:edge,:p05,:score,:can_purchase,:selected,:decision,:reasons,
                 :min_amount,:max_amount,:raw,:created)
              ON CONFLICT(scan_id,product_key) DO NOTHING
            """), {
                "scan_id": scan_id, "product_key": row["product_key"], "product_id": row["product_id"],
                "order_id": row["order_id"], "pair": row["pair"], "symbol": row["symbol"],
                "direction": row["direction"], "deposit_currency": row["deposit_currency"],
                "target_currency": row["target_currency"], "target_price": row["target_price"],
                "apr_rate": row["apr_rate"], "settle_date_ms": row["settle_date_ms"],
                "hours_to_settle": row["hours_to_settle"], "spot_price": row["spot_price"],
                "quote_to_usdt": row["quote_to_usdt"], "distance": row["target_distance_pct"],
                "reward": row["estimated_reward_usdt"], "probability": row["empirical_exercise_probability"],
                "samples": row["history_sample_count"], "pnl": row["expected_pnl_usdt"],
                "edge": row["expected_edge_vs_hold_usdt"], "p05": row["p05_pnl_usdt"],
                "score": row["score"], "can_purchase": row["can_purchase"], "selected": row["selected"],
                "decision": row["decision"], "reasons": _di_jsonable(row["reasons"]),
                "min_amount": row["min_amount"], "max_amount": row["max_amount"],
                "raw": _di_jsonable(row["raw"]), "created": started
            })
            if row["selected"]:
                offer_key = row["product_key"]
                db.execute(_di_sa.text("""
                  INSERT INTO dual_inv_paper_decisions
                    (offer_key,scan_id,product_id,pair,symbol,direction,deposit_currency,target_currency,
                     target_price,apr_rate,settle_date_ms,hours_to_settle,entry_spot,quote_to_usdt,amount_usdt,
                     estimated_reward_usdt,expected_pnl_usdt,expected_edge_vs_hold_usdt,exercise_probability,
                     p05_pnl_usdt,score,sample_count,status,created_at_utc)
                  VALUES
                    (:offer_key,:scan_id,:product_id,:pair,:symbol,:direction,:deposit,:target_currency,
                     :target,:apr,:settle,:hours,:spot,:quote_factor,:amount,:reward,:pnl,:edge,:probability,
                     :p05,:score,:samples,'OPEN',:created)
                  ON CONFLICT(offer_key) DO NOTHING
                """), {
                    "offer_key": offer_key, "scan_id": scan_id, "product_id": row["product_id"],
                    "pair": row["pair"], "symbol": row["symbol"], "direction": row["direction"],
                    "deposit": row["deposit_currency"], "target_currency": row["target_currency"],
                    "target": row["target_price"], "apr": row["apr_rate"], "settle": row["settle_date_ms"],
                    "hours": row["hours_to_settle"], "spot": row["spot_price"],
                    "quote_factor": row["quote_to_usdt"], "amount": amount_usdt,
                    "reward": row["estimated_reward_usdt"], "pnl": row["expected_pnl_usdt"],
                    "edge": row["expected_edge_vs_hold_usdt"],
                    "probability": _di_f(row["empirical_exercise_probability"], 0),
                    "p05": row["p05_pnl_usdt"], "score": row["score"],
                    "samples": row["history_sample_count"], "created": started
                })
        db.execute(_di_sa.text("""
          UPDATE dual_inv_scan_runs SET finished_at_utc=:finished WHERE scan_id=:scan_id
        """), {"finished": _di_utc_now(), "scan_id": scan_id})
        db.commit()
    settled_now = _di_settle_matured()
    return {
        "scan_id": scan_id, "status": status, "started_at_utc": started,
        "finished_at_utc": _di_utc_now(), "amount_usdt": amount_usdt,
        "direction_filter": direction_filter, "products_fetched": len(product_candidates),
        "selected_count": sum(1 for x in product_candidates if x["selected"]),
        "settled_proxy_updates": settled_now, "errors": errors,
        "markets": market_payload, "offers": [
            {k: v for k, v in row.items() if k not in ("raw", "asset_group", "subscription_units")}
            for row in sorted(product_candidates, key=lambda x: (not x["selected"], -(x["score"] if x["score"] is not None else -999)))
        ]
    }


_DI_PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dual Investment Lab | Binance Intelligence</title>
<style>
:root{color-scheme:dark;--bg:#080d18;--panel:#111a2a;--line:#26364e;--text:#edf3ff;--muted:#9caec8;--accent:#82b4ff;--good:#60d6a2;--bad:#ff8c91;--warn:#f4c46b}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(160deg,#09101d,#080d18 50%);color:var(--text);font:15px/1.5 Inter,system-ui,-apple-system,Segoe UI,sans-serif}header{padding:20px clamp(16px,3vw,42px);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;background:#0c1423}a{color:var(--accent);text-decoration:none}.brand{font-weight:800;letter-spacing:.12em}.sub{color:var(--muted);font-size:13px}.wrap{max-width:1800px;margin:auto;padding:24px clamp(12px,2.4vw,36px) 50px}.hero{display:flex;justify-content:space-between;gap:18px;align-items:start;flex-wrap:wrap;margin-bottom:20px}.eyebrow{font-size:11px;letter-spacing:.15em;color:var(--accent);font-weight:800}.hero h1{font-size:clamp(25px,3vw,38px);line-height:1.15;margin:6px 0 10px}.hero p{color:var(--muted);max-width:950px;margin:0}.badge{border:1px solid #27674f;background:#0f2b24;color:#7fe0b6;border-radius:999px;padding:7px 12px;font-size:12px;font-weight:800;white-space:nowrap}.notice{border:1px solid #70572b;background:#241e12;color:#ead8ae;border-radius:12px;padding:14px 16px;margin:18px 0}.grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin:18px 0}.card,.panel{background:linear-gradient(140deg,#121d30,#101726);border:1px solid var(--line);border-radius:14px;box-shadow:0 10px 24px #0003}.card{padding:15px}.card .label{font-size:12px;color:var(--muted)}.value{font-size:25px;font-weight:800;font-variant-numeric:tabular-nums;margin-top:6px;overflow-wrap:anywhere}.small{font-size:12px;color:var(--muted);margin-top:4px}.panel{margin-top:16px;padding:16px;min-width:0}.panel-head{display:flex;align-items:start;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px}.panel h2{font-size:19px;margin:0 0 4px}.panel p{font-size:13px;color:var(--muted);margin:0}.controls{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr)) auto;gap:12px;align-items:end}.field label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px}.field input,.field select{width:100%;min-width:0;background:#09111e;border:1px solid #354760;color:var(--text);padding:11px;border-radius:9px;font:inherit}.btn{border:1px solid #3c6daa;background:#17355c;color:#e7f1ff;border-radius:9px;padding:11px 15px;font:700 14px inherit;cursor:pointer;white-space:nowrap}.btn:disabled{opacity:.5;cursor:wait}.btn.secondary{border-color:#34465f;background:#182438}.status{color:var(--muted);font-size:13px;margin:12px 0 0;overflow-wrap:anywhere}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:10px}table{width:100%;border-collapse:collapse;min-width:1500px;font-size:13px}th,td{border-bottom:1px solid #233149;padding:10px 11px;text-align:left;white-space:nowrap;vertical-align:top}th{position:sticky;top:0;background:#172238;color:#bcd0ed;font-size:11px;letter-spacing:.04em;text-transform:uppercase;z-index:1}tbody tr:hover{background:#162238}.pill{display:inline-block;padding:3px 7px;border-radius:999px;font-size:11px;font-weight:800;background:#242e40;color:#c5d0e2}.pill.good{background:#12382c;color:#77e0b7}.pill.bad{background:#401e2a;color:#ff9faa}.pill.warn{background:#3d2e16;color:#ffd58d}.detail{max-width:330px;white-space:normal;color:var(--muted);font-size:12px}.two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}.metrics{display:flex;gap:8px;flex-wrap:wrap}.metric{padding:8px 10px;background:#0a1321;border:1px solid var(--line);border-radius:9px;font-size:12px;color:var(--muted)}.metric b{color:var(--text)}.empty{padding:24px;color:var(--muted);text-align:center;white-space:normal}.green{color:var(--good)}.red{color:var(--bad)}footer{padding:22px 0;color:var(--muted);font-size:12px}@media(max-width:1150px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}.controls{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}}@media(max-width:600px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.controls{grid-template-columns:1fr}.btn{width:100%}.value{font-size:21px}header{align-items:start}}
</style></head><body>
<header><div><div class="brand">BI / BINANCE INTEL</div><div class="sub">Dual Investment Intelligence · API-driven paper research</div></div><a href="/">← Back to workspace</a></header>
<main class="wrap">
<section class="hero"><div><div class="eyebrow">LIVE PRODUCT SCANNER · RESEARCH MODE</div><h1>Dual Investment Lab</h1><p>Fetches Binance Dual Investment offers and Spot candles for BTC/USDT, BTC/USDC and ETH/USDT, ranks only candidates passing explicit risk gates, and tracks hypothetical settlement outcomes. The requested reverse pair USDC/BTC is represented by Binance's BTC/USDC quote convention; duplicate ETH/USDT was removed.</p></div><span class="badge">PAPER ONLY · NO SUBSCRIPTIONS</span></section>
<div class="notice"><strong>Important:</strong> this page never places subscriptions or moves funds. The product-list API is read-only, while market history estimates are historical proxies—not calibrated probabilities, exchange fixing prices, or a profit guarantee. If no offer passes the gates, the correct selection is zero offers.</div>
<section class="grid">
<div class="card"><div class="label">Latest scan</div><div class="value" id="di-scan-status">—</div><div class="small" id="di-scan-time">No scan yet</div></div>
<div class="card"><div class="label">Offers evaluated</div><div class="value" id="di-offer-count">—</div><div class="small">All returned offers for supported pairs</div></div>
<div class="card"><div class="label">Shortlisted for paper test</div><div class="value" id="di-selected-count">—</div><div class="small">Maximum one per underlying asset</div></div>
<div class="card"><div class="label">Open paper decisions</div><div class="value" id="di-open-count">—</div><div class="small">No actual subscription</div></div>
<div class="card"><div class="label">Settled paper PnL</div><div class="value" id="di-paper-pnl">—</div><div class="small">USDT-equivalent, proxy settlement</div></div>
<div class="card"><div class="label">Edge vs hold benchmark</div><div class="value" id="di-paper-edge">—</div><div class="small">Recorded simulated outcomes</div></div>
</section>
<section class="panel"><div class="panel-head"><div><h2>Scan settings</h2><p>Use public market candles and the official Dual Investment product-list API. Paper capital is assumed, not taken from your Binance balance.</p></div></div>
<div class="controls">
<div class="field"><label for="di-amount">Paper notional (USDT)</label><input id="di-amount" type="number" min="1" max="100000" step="10" value="150"></div>
<div class="field"><label for="di-direction">Directions to evaluate</label><select id="di-direction"><option value="both">Buy Low + Sell High</option><option value="buy_low">Buy Low only</option><option value="sell_high">Sell High only</option></select></div>
<div class="field"><label for="di-distance">Max target distance (%)</label><input id="di-distance" type="number" min="0.1" max="25" step="0.1" value="5"></div>
<div class="field"><label for="di-tail">Max historical P05 loss (%)</label><input id="di-tail" type="number" min="0.1" max="20" step="0.1" value="3"></div>
<button class="btn" id="di-scan">Scan live offers</button>
</div><div class="status" id="di-status">Loading recorded scans…</div><div class="metrics" id="di-market-chips"></div></section>
<section class="panel"><div class="panel-head"><div><h2>Ranked live offers</h2><p>Ranking considers same-horizon historical price outcomes, estimated reward, conversion risk, product limits, and expected edge versus remaining in USDT/holding the asset.</p></div><span class="pill" id="di-offer-source">Awaiting API response</span></div>
<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Pair / symbol</th><th>Direction</th><th>Target</th><th>Spot</th><th>Distance</th><th>APR</th><th>Time to settlement</th><th>Reward / 150 USDT</th><th>Historical exercise proxy</th><th>Expected PnL vs deposit</th><th>Expected edge vs hold</th><th>P05 simulated PnL</th><th>History windows</th><th>Decision / gate reason</th></tr></thead><tbody id="di-offer-rows"><tr><td class="empty" colspan="15">No API scan recorded yet.</td></tr></tbody></table></div></section>
<div class="two">
<section class="panel"><div class="panel-head"><div><h2>Paper test ledger</h2><p>A selected offer is recorded as a hypothetical subscription at its first observed APR. Repeated scans do not create duplicate positions for the same product key.</p></div></div>
<div class="table-wrap"><table style="min-width:1150px"><thead><tr><th>Started (UTC)</th><th>Pair</th><th>Direction</th><th>Target</th><th>Entry spot</th><th>APR</th><th>Paper notional</th><th>Estimated reward</th><th>Expected PnL</th><th>Status</th><th>Fixing proxy</th><th>Settled PnL</th><th>Edge vs hold</th></tr></thead><tbody id="di-paper-rows"><tr><td colspan="13" class="empty">No paper selections yet.</td></tr></tbody></table></div></section>
<section class="panel"><div class="panel-head"><div><h2>Scan and API history</h2><p>Each scan stores returned product data, price/volatility snapshots, filters, selected/rejected reasons, and any API errors.</p></div></div>
<div class="table-wrap"><table style="min-width:750px"><thead><tr><th>Started (UTC)</th><th>Status</th><th>Offers</th><th>Selected</th><th>Direction filter</th><th>Market data</th><th>API diagnostics</th></tr></thead><tbody id="di-scan-rows"><tr><td colspan="7" class="empty">No scans recorded yet.</td></tr></tbody></table></div></section>
</div>
<section class="panel"><div class="panel-head"><div><h2>How to interpret this model</h2><p>These are screening statistics, not a guaranteed strategy.</p></div></div>
<div class="detail" style="max-width:none;font-size:13px">
<strong>Buy Low:</strong> the notional is modelled in USDT/USDC; on exercise, coin received is valued using the fixing proxy. The natural benchmark is keeping the stablecoin.<br>
<strong>Sell High:</strong> the notional represents the same USDT-equivalent value of BTC/ETH; on exercise the asset is converted at the target. The benchmark is simply holding that asset through settlement. A Sell High offer is not selected if the modeled edge versus holding is not positive.<br>
<strong>Historic exercise proxy:</strong> rolling hourly close-to-close returns of the same estimated duration are tested against the current target/spot ratio. This ignores the exact 30-minute fixing mechanics, fees/spreads, structural market changes, and execution constraints. The P05 result is an empirical lower-tail proxy, not a worst-case bound.<br>
<strong>Paper settlement:</strong> after settlement, the service averages Binance one-minute candle close prices from the 30-minute window before 08:00 UTC. It clearly labels this as a proxy, because it is not Binance's official product fixing price. Do not interpret paper PnL as real Binance PnL.
</div></section>
<footer>Sources: Binance Dual Investment product-list API and Binance Spot market-data API. Each live scan and raw product snapshot is stored through the configured application database. The page has no subscription endpoint and does not require trading permissions.</footer>
</main>
<script>
(function(){
const $=function(id){return document.getElementById(id)};
function esc(v){return String(v===null||v===undefined?"—":v).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function num(v,d){if(v===null||v===undefined||v==="")return "—";const n=Number(v);return Number.isFinite(n)?n.toLocaleString("en-US",{minimumFractionDigits:d||0,maximumFractionDigits:d===undefined?2:d}):"—"}
function pct(v){return v===null||v===undefined?"—":num(Number(v)*100,1)+"%"}
function money(v){return v===null||v===undefined?"—":(Number(v)>=0?"+":"")+num(v,4)+" USDT"}
function ts(ms){if(!ms)return "—";try{return new Date(Number(ms)).toLocaleString("en-GB",{timeZone:"UTC",hour12:false})+" UTC"}catch(e){return "—"}}
function timeHours(v){if(v===null||v===undefined)return "—";const h=Math.max(0,Number(v));return h<24?num(h,1)+" h":num(h/24,2)+" d"}
function htmlCell(v){return "<td>"+esc(v)+"</td>"}
function setStatus(v){$("di-status").textContent=v}
async function req(url,opts){const res=await fetch(url,opts||{});const data=await res.json().catch(function(){return {error:"The service returned an unreadable response"}});if(!res.ok||data.error)throw new Error(data.error||("HTTP "+res.status));return data}
function drawMarkets(markets){const host=$("di-market-chips");const entries=Object.keys(markets||{}).filter(function(k){return markets[k]&&markets[k].spot});host.innerHTML=entries.map(function(k){const m=markets[k];return '<span class="metric"><b>'+esc(k)+'</b> '+num(m.spot,6)+' · 24h '+num(m.trend_24h_pct,2)+'% · vol '+num(m.volatility_24h_pct,2)+'%</span>'}).join("")}
function drawOffers(rows){
 const host=$("di-offer-rows");
 if(!rows||!rows.length){host.innerHTML='<tr><td colspan="15" class="empty">No product rows returned for the supported pairs. Check the API diagnostics below; this is not mock data.</td></tr>';return}
 host.innerHTML=rows.map(function(r,i){
 const selected=r.selected;const reasons=Array.isArray(r.reasons)?r.reasons:(Array.isArray(r.reasons_json)?r.reasons_json:[]);
 const decision=r.decision||"—";const badge=selected?'<span class="pill good">PAPER SELECTED</span>':decision==="REJECTED"||decision==="EXPIRED"?'<span class="pill bad">'+esc(decision)+'</span>':'<span class="pill warn">'+esc(decision)+'</span>';
 const edge=r.expected_edge_vs_hold_usdt;
 const pnl=r.expected_pnl_usdt;
 return '<tr>'+htmlCell(i+1)+htmlCell(r.pair+" · "+r.symbol)+htmlCell(r.direction==="BUY_LOW"?"Buy Low":"Sell High")+htmlCell(num(r.target_price,6)+" "+(r.direction==="BUY_LOW"?"quote target":"target"))+htmlCell(num(r.spot_price,6))+htmlCell(num(r.target_distance_pct,3)+"%")+htmlCell(num(Number(r.apr_rate)*100,2)+"%")+htmlCell(timeHours(r.hours_to_settle))+htmlCell(money(r.estimated_reward_usdt))+htmlCell(pct(r.empirical_exercise_probability))+htmlCell(money(pnl))+htmlCell(money(edge))+htmlCell(money(r.p05_pnl_usdt))+htmlCell(num(r.history_sample_count,0))+('<td>'+badge+'<div class="detail">'+esc(reasons.join("; ")||"Top eligible score for this underlying asset.")+'</div></td>')+'</tr>'
 }).join("")
}
function drawPaper(rows){
 const host=$("di-paper-rows");
 if(!rows||!rows.length){host.innerHTML='<tr><td colspan="13" class="empty">No offer has passed all selection gates yet. Scans remain stored even when nothing is selected.</td></tr>';return}
 host.innerHTML=rows.map(function(r){return '<tr>'+htmlCell(r.created_at_utc)+htmlCell(r.pair)+htmlCell(r.direction==="BUY_LOW"?"Buy Low":"Sell High")+htmlCell(num(r.target_price,6))+htmlCell(num(r.entry_spot,6))+htmlCell(num(Number(r.apr_rate)*100,2)+"%")+htmlCell(money(r.amount_usdt))+htmlCell(money(r.estimated_reward_usdt))+htmlCell(money(r.expected_pnl_usdt))+'<td><span class="pill '+(r.status==="SETTLED_PROXY"?"good":"warn")+'">'+esc(r.status)+'</span>'+(r.settlement_note?'<div class="detail">'+esc(r.settlement_note)+'</div>':'')+'</td>'+htmlCell(num(r.fixing_price_proxy,6))+htmlCell(money(r.paper_pnl_usdt))+htmlCell(money(r.edge_vs_hold_usdt))+'</tr>'}).join("")
}
function drawScans(rows){
 const host=$("di-scan-rows");
 if(!rows||!rows.length){host.innerHTML='<tr><td colspan="7" class="empty">No scans recorded yet.</td></tr>';return}
 host.innerHTML=rows.map(function(r){const markets=typeof r.markets==="object"&&r.markets?r.markets:{};const errors=Array.isArray(r.errors)?r.errors:[];return '<tr>'+htmlCell(r.started_at_utc)+('<td><span class="pill '+(r.status==="OK"?"good":"warn")+'">'+esc(r.status)+'</span></td>')+htmlCell(r.offers_recorded)+htmlCell(r.selected_count)+htmlCell(r.direction_filter)+htmlCell(Object.keys(markets).filter(function(k){return markets[k]&&markets[k].spot}).length+" pairs")+'<td class="detail">'+esc(errors.join(" | ")||"No API errors recorded")+'</td></tr>'}).join("")
}
function render(state){
 const scan=state.latest_scan;const stats=state.stats||{};
 $("di-scan-status").textContent=scan?scan.status:"—";
 $("di-scan-time").textContent=scan?scan.started_at_utc:"No scan yet";
 $("di-offer-count").textContent=scan?num(scan.offers_recorded,0):"0";
 $("di-selected-count").textContent=scan?num(scan.selected_count,0):"0";
 $("di-open-count").textContent=num(stats.open_paper_decisions,0);
 $("di-paper-pnl").textContent=money(stats.settled_pnl_usdt);
 $("di-paper-edge").textContent=money(stats.settled_edge_vs_hold_usdt);
 $("di-offer-source").textContent=scan?"Stored from live API scan":"Awaiting first scan";
 drawMarkets(scan?scan.markets:{});
 drawOffers(state.offers||[]);
 drawPaper(state.paper||[]);
 drawScans(state.scans||[]);
 if(scan&&Array.isArray(scan.errors)&&scan.errors.length){setStatus("Latest scan completed with "+scan.errors.length+" diagnostic(s). Read the scan-history table for exact errors.");}
 else if(scan){setStatus("Last scan: "+scan.status+". All returned rows and diagnostics are persisted; no subscription action is available.");}
 else{setStatus("No scan is stored yet. The page will request the API on first load.");}
}
async function load(){
 try{const state=await req("/api/dual-investment/state");render(state);
 if(!state.latest_scan){await scanNow(true)}
 }catch(e){setStatus("Could not load stored paper state: "+e.message+". Attempting an API scan.");await scanNow(true)}
}
async function scanNow(silent){
 const button=$("di-scan");if(button.disabled)return;button.disabled=true;const old=button.textContent;button.textContent="Requesting Binance APIs…";if(!silent)setStatus("Fetching product offers and historical spot candles; first scan may take a little longer.");
 const payload={amount_usdt:Number($("di-amount").value||150),direction_filter:$("di-direction").value,max_target_distance_pct:Number($("di-distance").value||5),max_tail_loss_pct:Number($("di-tail").value||3)};
 try{const result=await req("/api/dual-investment/scan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});render({latest_scan:result,offers:result.offers||[],paper:[],scans:[],stats:{}});const state=await req("/api/dual-investment/state");render(state);if(result.errors&&result.errors.length)setStatus("Scan stored with "+result.errors.length+" API/data diagnostic(s). No data has been fabricated.");else setStatus("Live API scan recorded: "+result.products_fetched+" offers evaluated, "+result.selected_count+" candidates entered into paper testing. No real subscription was placed.");}
 catch(e){setStatus("Scan failed: "+e.message+". The failed attempt is shown in the service logs if the API was unreachable.");}
 finally{button.disabled=false;button.textContent=old}
}
$("di-scan").addEventListener("click",function(){scanNow(false)});
load();
setInterval(function(){load()},300000);
})();
</script></body></html>'''


@app.get("/dual-investment")
def api_dual_investment_page():
    return _di_Response(_DI_PAGE, mimetype="text/html")


@app.get("/api/dual-investment/health")
def api_dual_investment_health():
    return _di_jsonify({
        "version": _DI_VERSION,
        "paper_only": True,
        "api_key_configured": bool((_di_os.environ.get("BINANCE_API_KEY") or "").strip()),
        "api_secret_configured": bool((_di_os.environ.get("BINANCE_API_SECRET") or "").strip()),
        "pairs": [{"pair": p["pair"], "symbol": p["symbol"]} for p in _DI_PAIRS],
        "subscription_enabled": False,
        "supported_sources": ["Binance Dual Investment product list", "Binance Spot ticker", "Binance Spot hourly/minute klines"]
    })


@app.get("/api/dual-investment/state")
def api_dual_investment_state():
    try:
        return _di_jsonify(_di_read_state())
    except Exception as exc:
        app.logger.exception("dual_investment_state_failed")
        return _di_jsonify({"error": "Unable to read Dual Investment paper database: " + str(exc)[:400]}), 500


@app.get("/api/dual-investment/history")
def api_dual_investment_history():
    try:
        return _di_jsonify(_di_read_state(_di_request_obj.args.get("limit", 100)))
    except Exception as exc:
        app.logger.exception("dual_investment_history_failed")
        return _di_jsonify({"error": "Unable to load Dual Investment history: " + str(exc)[:400]}), 500


@app.route("/api/dual-investment/scan", methods=["GET", "POST"])
def api_dual_investment_scan():
    try:
        body = _di_request_obj.get_json(silent=True) or {}
        args = body if _di_request_obj.method == "POST" else _di_request_obj.args
        result = _di_scan(
            args.get("amount_usdt", 150),
            str(args.get("direction_filter", "both")).lower(),
            args.get("max_target_distance_pct", 5),
            args.get("max_tail_loss_pct", 3)
        )
        return _di_jsonify(result)
    except Exception as exc:
        app.logger.exception("dual_investment_scan_failed")
        try:
            _di_db_init()
        except Exception:
            pass
        return _di_jsonify({"error": "Dual Investment scan failed: " + str(exc)[:500], "paper_only": True}), 500
'''
    APP_PATH.write_text(app_source)

print("Installed Binance Dual Investment Intelligence v1 (page + API-driven paper scanner + persistent scan/paper ledger; no subscription endpoint).")
