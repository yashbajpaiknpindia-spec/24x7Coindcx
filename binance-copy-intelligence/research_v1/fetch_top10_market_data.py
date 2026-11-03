#!/usr/bin/env python3
"""Fetch a reproducible top-10 USDⓈ-M perpetual universe and 1m candles.

Public market-data endpoints only. Universe is re-ranked on collection day; no hard-coded coins.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

BASE = "https://fapi.binance.com"


def get_json(path: str, params: dict[str, Any] | None = None) -> Any:
    query = urllib.parse.urlencode(params or {})
    req = urllib.request.Request(BASE + path + ("?" + query if query else ""), headers={
        "User-Agent": "BinanceIntelResearch/1.0", "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/binance_research")
    parser.add_argument("--lookback-days", type=int, default=60)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--limit", type=int, default=1500)
    args = parser.parse_args()
    if not 1 <= args.lookback_days <= 180 or args.delay < 0.1 or not 1 <= args.limit <= 1500:
        parser.error("lookback-days must be 1..180, delay >=0.1s, limit 1..1500")

    exchange = get_json("/fapi/v1/exchangeInfo")
    server_ms = int(get_json("/fapi/v1/time")["serverTime"])
    tickers = get_json("/fapi/v1/ticker/24hr")
    cutoff = server_ms - 90 * 86_400_000
    metadata = {s["symbol"]: s for s in exchange["symbols"]}
    eligible = []
    for t in tickers:
        s = metadata.get(t.get("symbol"))
        if not s or s.get("status") != "TRADING" or s.get("contractType") != "PERPETUAL" or s.get("quoteAsset") != "USDT":
            continue
        if int(s.get("onboardDate", server_ms)) > cutoff:
            continue
        eligible.append(t)
    eligible.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
    universe = [{
        "symbol": t["symbol"], "quoteVolume24h": float(t["quoteVolume"]),
        "priceChangePct24h": float(t["priceChangePercent"]),
        "lastPrice": float(t["lastPrice"]), "onboardDate": metadata[t["symbol"]].get("onboardDate"),
    } for t in eligible[:10]]
    if len(universe) < 10:
        raise RuntimeError(f"Only {len(universe)} eligible contracts returned; refusing to silently reduce universe")

    out = Path(args.out)
    candle_dir = out / "candles"
    candle_dir.mkdir(parents=True, exist_ok=True)
    end_ms = server_ms
    start_ms = end_ms - args.lookback_days * 86_400_000
    total_rows = 0
    for item in universe:
        symbol = item["symbol"]
        path = candle_dir / f"{symbol}.jsonl"
        rows = []
        cursor = start_ms
        while cursor < end_ms:
            batch = get_json("/fapi/v1/klines", {
                "symbol": symbol, "interval": "1m", "startTime": cursor,
                "endTime": end_ms, "limit": args.limit,
            })
            if not batch:
                break
            for k in batch:
                rows.append({
                    "openTime": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                    "closeTime": int(k[6]), "quoteVolume": float(k[7]), "trades": int(k[8]),
                })
            next_cursor = int(batch[-1][0]) + 60_000
            if next_cursor <= cursor:
                raise RuntimeError(f"Pagination did not advance for {symbol}")
            cursor = next_cursor
            if len(batch) < args.limit:
                break
            time.sleep(args.delay)
        # Replace file atomically so repeated fetches do not append duplicate candles.
        temp = path.with_suffix(".jsonl.tmp")
        with temp.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        temp.replace(path)
        total_rows += len(rows)
        print(f"{symbol}: {len(rows)} one-minute candles")

    manifest = {
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "startTime": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        "endTime": datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat(),
        "interval": "1m", "universeRule": "Top 10 by 24h quote volume among trading USDT-M perpetual contracts listed at least 90 days",
        "universe": universe, "candleRows": total_rows,
    }
    (out / "market_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
