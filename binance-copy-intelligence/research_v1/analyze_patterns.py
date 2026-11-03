#!/usr/bin/env python3
"""Analyse Binance lead-trader closed-position snapshots without look-ahead claims."""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_no}: {exc}") from exc
    return rows


def num(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = (len(ordered) - 1) * q
    lo, hi = math.floor(idx), math.ceil(idx)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def duration_bucket(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    if hours < 1:
        return "<1h"
    if hours < 4:
        return "1-4h"
    if hours < 12:
        return "4-12h"
    if hours < 24:
        return "12-24h"
    if hours < 72:
        return "1-3d"
    if hours < 168:
        return "3-7d"
    return "7d+"


def normalise_position(record: dict[str, Any]) -> dict[str, Any] | None:
    raw = record.get("raw", record)
    pid = str(record.get("portfolioId") or raw.get("portfolioId") or "")
    opened = num(raw.get("opened") or raw.get("openedTime") or raw.get("openTime"))
    closed = num(raw.get("closed") or raw.get("closedTime") or raw.get("closeTime"))
    side = str(raw.get("side") or "").upper()
    if side not in {"LONG", "SHORT", "BUY", "SELL"}:
        return None
    side = "LONG" if side in {"LONG", "BUY"} else "SHORT"
    symbol = str(raw.get("symbol") or "").upper()
    if not pid or not symbol or opened is None or closed is None or closed <= opened:
        return None
    pnl = num(raw.get("closingPnl"))
    if pnl is None:
        pnl = num(raw.get("netPnl"))
    roi = num(raw.get("roi"))
    leverage = num(raw.get("leverage"))
    entry = num(raw.get("avgCost") or raw.get("entryPrice"))
    exit_price = num(raw.get("avgClosePrice") or raw.get("closePrice"))
    volume = num(raw.get("closedVolume") or raw.get("closedQty"))
    hours = (closed - opened) / 3_600_000 if max(opened, closed) > 10_000_000_000 else (closed - opened) / 3600
    return {
        "portfolioId": pid, "symbol": symbol, "side": side,
        "openedMs": int(opened), "closedMs": int(closed),
        "durationHours": hours, "durationBucket": duration_bucket(hours),
        "reportedPnl": pnl, "reportedRoi": roi, "leverage": leverage,
        "entryPrice": entry, "closePrice": exit_price, "closedVolume": volume,
        "marginMode": str(raw.get("isolated") or raw.get("marginMode") or "unknown"),
        "positionKey": str(raw.get("positionId") or f"{pid}:{symbol}:{side}:{int(opened)}:{int(closed)}"),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # Stable-key de-duplication; the same snapshot can recur across scrape runs.
    unique = {row["positionKey"]: row for row in rows}
    positions = list(unique.values())
    by_trader: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_symbol_side: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_duration: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in positions:
        by_trader[row["portfolioId"]].append(row)
        by_symbol_side[(row["symbol"], row["side"])].append(row)
        by_duration[row["durationBucket"]].append(row)

    trader_stats = []
    for trader, trades in by_trader.items():
        valid = [t for t in trades if t["reportedPnl"] is not None]
        pnls = [t["reportedPnl"] for t in valid]
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x < 0]
        gross_win, gross_loss = sum(wins), abs(sum(losses))
        trader_stats.append({
            "portfolioId": trader, "positions": len(trades), "pnlObservations": len(valid),
            "reportedPnlSum": sum(pnls) if pnls else None,
            "winRate": len(wins) / len(valid) if valid else None,
            "profitFactor": gross_win / gross_loss if gross_loss else (None if not gross_win else 99.0),
            "medianLeverage": median([t["leverage"] for t in trades if t["leverage"] is not None]) if any(t["leverage"] is not None for t in trades) else None,
            "medianDurationHours": median([t["durationHours"] for t in trades]),
        })
    trader_stats.sort(key=lambda x: (x["reportedPnlSum"] is not None, x["reportedPnlSum"] or -math.inf), reverse=True)

    symbol_stats = []
    for (symbol, side), trades in sorted(by_symbol_side.items()):
        valid = [t for t in trades if t["reportedPnl"] is not None]
        pnls = [t["reportedPnl"] for t in valid]
        wins = [x for x in pnls if x > 0]
        trader_pnl: dict[str, float] = defaultdict(float)
        for t in valid:
            trader_pnl[t["portfolioId"]] += t["reportedPnl"]
        total = sum(pnls)
        largest_share = max(trader_pnl.values()) / total if total > 0 and trader_pnl else None
        symbol_stats.append({
            "symbol": symbol, "side": side, "trades": len(trades),
            "independentTraders": len({t["portfolioId"] for t in trades}),
            "pnlObservations": len(valid), "reportedPnlSum": total if valid else None,
            "winRate": len(wins) / len(valid) if valid else None,
            "medianPnl": median(pnls) if pnls else None,
            "medianLeverage": median([t["leverage"] for t in trades if t["leverage"] is not None]) if any(t["leverage"] is not None for t in trades) else None,
            "largestSingleTraderShareOfPositiveAggregate": largest_share,
            "researchEligible": len(trades) >= 30 and len({t["portfolioId"] for t in trades}) >= 5 and total > 0 and (largest_share is None or largest_share <= 0.60),
        })
    duration_stats = []
    for bucket, trades in sorted(by_duration.items()):
        valid = [t for t in trades if t["reportedPnl"] is not None]
        pnls = [t["reportedPnl"] for t in valid]
        duration_stats.append({
            "durationBucket": bucket, "trades": len(trades),
            "reportedPnlSum": sum(pnls) if pnls else None,
            "winRate": sum(x > 0 for x in pnls) / len(pnls) if pnls else None,
            "medianPnl": median(pnls) if pnls else None,
            "medianLeverage": median([t["leverage"] for t in trades if t["leverage"] is not None]) if any(t["leverage"] is not None for t in trades) else None,
        })

    positive_total = sum(max(0, t["reportedPnl"] or 0) for t in positions)
    top5_positive = sum(max(0, t["reportedPnlSum"] or 0) for t in trader_stats[:5])
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "deduplicatedClosedPositions": len(positions),
        "tradersWithHistory": len(by_trader),
        "reportedPnlCoverage": sum(t["reportedPnl"] is not None for t in positions) / len(positions) if positions else 0,
        "symbolSide": symbol_stats,
        "duration": duration_stats,
        "traders": trader_stats,
        "top5TraderShareOfPositiveTradePnl": top5_positive / positive_total if positive_total else None,
        "eligibilityRule": ">=30 observed positions, >=5 independent traders, positive aggregate reported PnL, and no single trader >60% of positive aggregate; still requires out-of-sample validation.",
        "limitations": [
            "This is a selected leaderboard cohort, not a random sample of all traders; survivor and ranking bias remain.",
            "closingPnl/ROI semantics must be verified against source payload versions; this report labels them source-reported, not guaranteed copier-net.",
            "Closed position history does not reveal the contemporaneous open-position book.",
            "No candle-path MAE/MFE is claimed unless a separate time-aligned candle dataset is joined.",
            "A positive aggregate does not prove a reproducible edge or predict future returns.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/binance_research/positions.jsonl")
    parser.add_argument("--out", default="data/binance_research/pattern_report.json")
    args = parser.parse_args()
    normalised = []
    for row in read_jsonl(Path(args.input)):
        item = normalise_position(row)
        if item:
            normalised.append(item)
    report = aggregate(normalised)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
