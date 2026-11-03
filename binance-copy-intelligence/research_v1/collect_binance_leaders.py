#!/usr/bin/env python3
"""Read-only Binance Futures Copy Trading public-data collector.

The Binance website endpoints used here are undocumented and may change.
No account credentials, private endpoints, or order endpoints are used.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://www.binance.com"
LIST_PATH = "/bapi/futures/v1/friendly/future/copy-trade/home-page/query-list"
HISTORY_PATH = "/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history"
PERIODS = ("30D", "90D", "180D", "365D")
METRICS = ("ROI", "PNL", "SHARP_RATIO", "WIN_RATE")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BinanceIntelResearch/1.0)",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "clienttype": "web",
    "Origin": BASE,
    "Referer": BASE + "/en/copy-trading",
}


class SourceError(RuntimeError):
    pass


def post_json(path: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    req = urllib.request.Request(BASE + path, data=body, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise SourceError(f"HTTP {response.status} from {path}")
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SourceError(f"request failed for {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("success") is False:
        raise SourceError(f"source rejected {path}: {str(data)[:500]}")
    return data


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")


def fetch_leaderboards(pages: int, page_size: int, delay: float) -> dict[str, dict[str, Any]]:
    portfolios: dict[str, dict[str, Any]] = {}
    for period in PERIODS:
        for metric in METRICS:
            for page in range(1, pages + 1):
                payload = {
                    "pageNumber": page,
                    "pageSize": min(page_size, 30),
                    "timeRange": period,
                    "dataType": metric,
                    "favoriteOnly": False,
                    "hideFull": False,
                    "nickname": "",
                    "order": "DESC",
                    "userAsset": 0,
                    "portfolioType": "PUBLIC",
                }
                result = post_json(LIST_PATH, payload)
                data = result.get("data") or {}
                rows = data.get("list") or []
                if not rows:
                    break
                fetched_at = datetime.now(timezone.utc).isoformat()
                for row in rows:
                    portfolio_id = str(row.get("leadPortfolioId") or "")
                    if not portfolio_id:
                        continue
                    key = portfolio_id
                    item = portfolios.setdefault(key, {
                        "portfolioId": key,
                        "leaderboardSnapshots": [],
                    })
                    item["leaderboardSnapshots"].append({
                        "period": period,
                        "metric": metric,
                        "fetchedAt": fetched_at,
                        "raw": row,
                    })
                if len(rows) < min(page_size, 30):
                    break
                time.sleep(delay + random.random() * delay * 0.25)
    return portfolios


def fetch_position_history(portfolio_id: str, max_pages: int, page_size: int, delay: float) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        result = post_json(HISTORY_PATH, {
            "portfolioId": portfolio_id,
            "pageNumber": page,
            "pageSize": min(page_size, 50),
        })
        data = result.get("data") or {}
        rows = data.get("list") or []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < min(page_size, 50):
            break
        time.sleep(delay + random.random() * delay * 0.25)
    return all_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Binance public Futures copy-trader research data")
    parser.add_argument("--out", default="data/binance_research", help="Output directory")
    parser.add_argument("--pages", type=int, default=2, help="Pages per leaderboard metric/period (max 30 rows/page)")
    parser.add_argument("--history-pages", type=int, default=10, help="Maximum closed-position history pages per portfolio")
    parser.add_argument("--max-leaders", type=int, default=120, help="Maximum unique leaders to collect histories for")
    parser.add_argument("--delay", type=float, default=0.8, help="Delay between requests in seconds")
    args = parser.parse_args()
    if min(args.pages, args.history_pages, args.max_leaders) < 1 or args.delay < 0.25:
        parser.error("pages/history-pages/max-leaders must be positive and delay must be >= 0.25s")

    out = Path(args.out)
    portfolios = fetch_leaderboards(args.pages, 30, args.delay)
    ranked = sorted(portfolios.values(), key=lambda p: len(p["leaderboardSnapshots"]), reverse=True)
    selected = ranked[:args.max_leaders]
    append_jsonl(out / "leaders.jsonl", selected)

    position_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, leader in enumerate(selected, start=1):
        pid = leader["portfolioId"]
        try:
            rows = fetch_position_history(pid, args.history_pages, 50, args.delay)
            fetched_at = datetime.now(timezone.utc).isoformat()
            for row in rows:
                position_rows.append({
                    "portfolioId": pid,
                    "fetchedAt": fetched_at,
                    "source": "binance_friendly_position_history",
                    "raw": row,
                })
        except SourceError as exc:
            failures.append({"portfolioId": pid, "error": str(exc)})
        if index % 10 == 0:
            append_jsonl(out / "positions.jsonl", position_rows)
            position_rows = []
            append_jsonl(out / "collection_errors.jsonl", failures)
            failures = []
        time.sleep(args.delay + random.random() * args.delay * 0.25)

    append_jsonl(out / "positions.jsonl", position_rows)
    append_jsonl(out / "collection_errors.jsonl", failures)
    manifest = {
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "leaderboards": list(PERIODS),
        "metrics": list(METRICS),
        "uniqueLeadersFound": len(portfolios),
        "leadersSelected": len(selected),
        "historyRowsCollectedThisRun": sum(1 for _ in (out / "positions.jsonl").open(encoding="utf-8")) if (out / "positions.jsonl").exists() else 0,
        "openPositions": {
            "status": "NOT_COLLECTED",
            "reason": "No stable, verified public per-leader open-position endpoint is included. Empty closed-history data must never be interpreted as no open positions.",
        },
        "warnings": [
            "Binance copy-trading website endpoints are undocumented and can change without notice.",
            "Leaderboard selection is survivor-biased; include lower-ranked/control portfolios before drawing conclusions.",
            "Position-history rows are closed/partially closed snapshots; deduplicate by portfolioId and stable position identifier/timestamps.",
            "Do not treat leader ROI as copier ROI or as net replicable return.",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
