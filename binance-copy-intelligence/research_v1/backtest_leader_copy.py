#!/usr/bin/env python3
"""Walk-forward paper replay of Binance lead positions using public Futures candles.

Input:
  positions.jsonl: collector output (one {"portfolioId", "raw": {...}} per row)
  candles/: <SYMBOL>.jsonl with one JSON object per 1m candle:
      {"openTime": 1730000000000, "open": 1, "high": 1, "low": 1, "close": 1}
No live orders are placed. This is a conservative follower replay, not a promise of future performance.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analyze_patterns import normalise_position, read_jsonl

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
FUNDING_PER_8H_ASSUMPTION = 0.0001


def load_candles(path: Path) -> list[dict[str, float]]:
    rows = read_jsonl(path)
    out = []
    for row in rows:
        try:
            t = float(row.get("openTime", row.get("t")))
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            if min(o, h, l, c) <= 0 or not all(math.isfinite(x) for x in (t, o, h, l, c)):
                continue
            out.append({"t": t, "o": o, "h": h, "l": l, "c": c})
        except (KeyError, TypeError, ValueError):
            continue
    return sorted({int(x["t"]): x for x in out}.values(), key=lambda x: x["t"])


def simulate_trade(pos: dict[str, Any], candles: list[dict[str, float]], stop_pct: float, risk_fraction: float, max_notional_multiple: float) -> dict[str, Any] | None:
    # Entry/exit at the first 1m candle open after the lead event: no same-candle look-ahead.
    entry_idx = next((i for i, c in enumerate(candles) if c["t"] >= pos["openedMs"]), None)
    if entry_idx is None:
        return None
    exit_idx = next((i for i in range(entry_idx + 1, len(candles)) if candles[i]["t"] >= pos["closedMs"]), None)
    if exit_idx is None:
        return None
    side = 1 if pos["side"] == "LONG" else -1
    entry = candles[entry_idx]["o"] * (1 + side * SLIPPAGE_PER_SIDE)
    stop = entry * (1 - side * stop_pct)
    exit_price = None
    exit_time = None
    exit_reason = "LEAD_EXIT"
    max_adverse = 0.0
    max_favourable = 0.0
    for i in range(entry_idx, exit_idx + 1):
        c = candles[i]
        adverse = (entry - c["l"]) / entry if side == 1 else (c["h"] - entry) / entry
        favourable = (c["h"] - entry) / entry if side == 1 else (entry - c["l"]) / entry
        max_adverse = max(max_adverse, adverse)
        max_favourable = max(max_favourable, favourable)
        stop_hit = c["l"] <= stop if side == 1 else c["h"] >= stop
        if stop_hit:
            exit_price = stop * (1 - side * SLIPPAGE_PER_SIDE)
            exit_time = c["t"]
            exit_reason = "FOLLOWER_STOP"
            break
    if exit_price is None:
        exit_price = candles[exit_idx]["o"] * (1 - side * SLIPPAGE_PER_SIDE)
        exit_time = candles[exit_idx]["t"]
    gross_return = side * (exit_price - entry) / entry
    held_hours = max(0.0, (exit_time - candles[entry_idx]["t"]) / 3_600_000)
    funding = math.floor(held_hours / 8) * FUNDING_PER_8H_ASSUMPTION
    net_return = gross_return - 2 * FEE_PER_SIDE - funding
    return {
        **pos, "entryTime": candles[entry_idx]["t"], "exitTime": exit_time,
        "followerEntry": entry, "followerExit": exit_price,
        "grossReturn": gross_return, "netReturn": net_return,
        "maxAdverseExcursion": max_adverse, "maxFavourableExcursion": max_favourable,
        "heldHours": held_hours, "fundingAssumption": funding,
        "exitReason": exit_reason,
    }


def run(positions: list[dict[str, Any]], candle_dir: Path, initial: float, train_cutoff_ms: int,
        min_train_trades: int, min_train_pf: float, stop_pct: float, risk_fraction: float,
        max_notional_multiple: float, max_concurrent: int, daily_loss_fraction: float,
        kill_drawdown_fraction: float) -> dict[str, Any]:
    normalised = [p for row in positions if (p := normalise_position(row))]
    train = [p for p in normalised if p["closedMs"] < train_cutoff_ms and p["reportedPnl"] is not None]
    by_leader: dict[str, list[float]] = defaultdict(list)
    for p in train:
        by_leader[p["portfolioId"]].append(p["reportedPnl"])
    eligible = set()
    for leader, pnls in by_leader.items():
        wins = sum(x for x in pnls if x > 0)
        losses = abs(sum(x for x in pnls if x < 0))
        pf = wins / losses if losses else (99.0 if wins > 0 else 0.0)
        if len(pnls) >= min_train_trades and pf >= min_train_pf and sum(pnls) > 0:
            eligible.add(leader)

    test = [p for p in normalised if p["openedMs"] >= train_cutoff_ms and p["portfolioId"] in eligible]
    candle_cache: dict[str, list[dict[str, float]]] = {}
    candidates = []
    missing_candles = set()
    for p in test:
        symbol = p["symbol"]
        if symbol not in candle_cache:
            candle_cache[symbol] = load_candles(candle_dir / f"{symbol}.jsonl")
        candles = candle_cache[symbol]
        if not candles:
            missing_candles.add(symbol)
            continue
        trade = simulate_trade(p, candles, stop_pct, risk_fraction, max_notional_multiple)
        if trade:
            candidates.append(trade)
        else:
            missing_candles.add(symbol + ":time_coverage")
    candidates.sort(key=lambda x: (x["entryTime"], x["portfolioId"]))

    # Event-driven equity ledger. All positions are marked to their conservative stop/exit outcome;
    # capital is allocated only when the position opens and exits are realised chronologically.
    events = []
    for t in candidates:
        events.append((t["entryTime"], 1, t))
        events.append((t["exitTime"], 0, t))
    events.sort(key=lambda e: (e[0], e[1]))  # close before new entries at same timestamp
    equity = peak = initial
    max_dd = 0.0
    active: dict[int, dict[str, Any]] = {}
    realised = []
    day = None
    day_start = initial
    halted_days: set[str] = set()
    killed = False
    for timestamp, kind, t in events:
        date = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat()
        if date != day:
            day = date
            day_start = equity
        key = id(t)
        if kind == 1:
            if killed or date in halted_days or len(active) >= max_concurrent:
                continue
            risk_cash = equity * risk_fraction
            open_risk = sum(p["riskCash"] for p in active.values())
            if open_risk + risk_cash > equity * risk_fraction * max_concurrent:
                continue
            notional = min(risk_cash / stop_pct, equity * max_notional_multiple)
            active[key] = {"trade": t, "notional": notional, "riskCash": notional * stop_pct}
        else:
            position = active.pop(key, None)
            if position is None:
                continue
            pnl = position["notional"] * t["netReturn"]
            equity += pnl
            realised.append({**t, "notional": position["notional"], "pnl": pnl, "equityAfter": equity})
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak else 0)
            if equity <= day_start * (1 - daily_loss_fraction):
                halted_days.add(date)
            if max_dd >= kill_drawdown_fraction:
                killed = True
                # No new trades after kill switch; already open trades keep their precomputed stop/exit.
    wins = [x for x in realised if x["pnl"] > 0]
    losses = [x for x in realised if x["pnl"] <= 0]
    gross_win = sum(x["pnl"] for x in wins)
    gross_loss = abs(sum(x["pnl"] for x in losses))
    return {
        "mode": "PAPER_ONLY_WALK_FORWARD",
        "initialEquity": initial, "finalEquity": equity, "netPnl": equity - initial,
        "returnPct": (equity / initial - 1) * 100 if initial else None,
        "maxDrawdownPct": max_dd * 100, "trades": len(realised),
        "eligibleTrainingLeaders": len(eligible), "testCandidates": len(candidates),
        "winRatePct": len(wins) / len(realised) * 100 if realised else None,
        "profitFactor": gross_win / gross_loss if gross_loss else (99.0 if gross_win else None),
        "bestTrade": max((x["pnl"] for x in realised), default=None),
        "worstTrade": min((x["pnl"] for x in realised), default=None),
        "dailyHaltDays": len(halted_days), "killSwitchTriggered": killed,
        "missingCandleCoverage": sorted(missing_candles),
        "assumptions": {
            "entryExit": "first 1m candle open at or after lead open/close timestamp",
            "stop": stop_pct, "riskPerTrade": risk_fraction,
            "maxNotionalMultiple": max_notional_multiple, "maxConcurrent": max_concurrent,
            "dailyLossLimit": daily_loss_fraction, "portfolioKillDrawdown": kill_drawdown_fraction,
            "feePerSide": FEE_PER_SIDE, "slippagePerSide": SLIPPAGE_PER_SIDE,
            "funding": "assumed 0.01% per 8 hours; replace with historical funding before promotion",
            "leaderSelection": f"prior-to-cutoff >= {min_train_trades} closes, positive reported PnL, PF >= {min_train_pf}",
            "limitations": "Survivorship bias, endpoint changes, public-history visibility and candle coverage can materially affect results.",
        },
        "trades": realised,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", default="data/binance_research/positions.jsonl")
    parser.add_argument("--candles", default="data/binance_research/candles")
    parser.add_argument("--out", default="data/binance_research/backtest_report.json")
    parser.add_argument("--train-cutoff", required=True, help="UTC timestamp, e.g. 2026-08-01T00:00:00Z")
    parser.add_argument("--capital", type=float, default=150.0)
    parser.add_argument("--min-train-trades", type=int, default=30)
    parser.add_argument("--min-train-pf", type=float, default=1.25)
    parser.add_argument("--stop-pct", type=float, default=0.01)
    parser.add_argument("--risk", type=float, default=0.0025)
    parser.add_argument("--max-notional", type=float, default=1.0)
    parser.add_argument("--max-concurrent", type=int, default=2)
    parser.add_argument("--daily-loss", type=float, default=0.0075)
    parser.add_argument("--kill-dd", type=float, default=0.025)
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.train_cutoff.replace("Z", "+00:00")).timestamp() * 1000
    report = run(read_jsonl(Path(args.positions)), Path(args.candles), args.capital, int(cutoff),
                 args.min_train_trades, args.min_train_pf, args.stop_pct, args.risk,
                 args.max_notional, args.max_concurrent, args.daily_loss, args.kill_dd)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "trades"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
