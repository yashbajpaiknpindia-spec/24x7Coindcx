# Binance Futures Trader Pattern Research v1

This is an isolated, read-only research package for the Binance Intel application. It does not place orders, modify accounts, or require a Binance API key.

## What it does

1. Collects public Binance Futures copy-trading leaderboards over 30D/90D/180D/365D and ROI/PNL/Sharpe/win-rate rankings.
2. Collects each selected portfolio's published closed/partially-closed position history, including symbol, side, leverage, margin mode, open/close timestamps and source-reported PnL.
3. Deduplicates positions and reports trader-level, symbol/side, holding-time and leverage patterns.
4. Applies an anti-lottery screen: at least 30 observed trades, at least 5 independent traders, positive reported aggregate PnL and no single trader contributing over 60% of the positive aggregate.
5. Provides a chronological out-of-sample follower replay with delayed 1-minute candle-open entries/exits, stop-losses, capped exposure, fees, slippage and an explicit funding assumption.

## Important source limitations

- The Binance copy-trading website endpoints are undocumented, public web endpoints. They can change, rate-limit or block requests. Use conservative request pacing and stop on errors.
- Public closed-position history is not a complete real-time feed. A closed-history row cannot establish what the trader is holding now.
- We do **not** assume a stable public endpoint for every trader's open positions. The collector manifest explicitly records open positions as NOT_COLLECTED. Hidden/empty data must not be interpreted as flat.
- Leaderboard cohorts are survivor-biased. Rankings by ROI especially over-select recent winners. Collect lower-ranked controls and multiple time windows before drawing conclusions.
- Binance's published lead-trader PnL/ROI is not automatically equal to a follower's net result. Execution delay, slippage, fees, funding, leverage, copier sizing, and partial fills differ.
- Source fields such as `closingPnl` must be validated against live payload examples before calling them net-of-costs. Reports label them source-reported.
- MAE/MFE requires correctly time-aligned OHLC candles. This package's follower replay refuses to claim a result if candle coverage is missing.
- This is research tooling, not financial advice or a profit guarantee.

## Run

From this directory, Python 3.12+ is sufficient; the scripts use the standard library.

```bash
python collect_binance_leaders.py --pages 2 --history-pages 10 --max-leaders 120 --delay 0.8
python analyze_patterns.py
python -m unittest -v
```

For the walk-forward replay, first provide 1-minute Binance USDⓈ-M candles in `data/binance_research/candles/<SYMBOL>.jsonl`, one JSON object per line:

```json
{"openTime": 1760000000000, "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5}
```

Choose the train/test boundary **before** looking at test results:

```bash
python backtest_leader_copy.py --train-cutoff 2026-08-01T00:00:00Z --capital 150
```

The default replay is paper-only: 0.25% risk per trade, 1% stop, max 1x notional, two concurrent positions, one position per symbol, 0.75% daily loss pause and 2.5% closed-equity drawdown kill threshold. Daily loss and drawdown are based on realised equity only in v1; this limitation is explicitly reported and must be upgraded to mark-to-market portfolio risk before any live use. Fees are assumed 0.05% per side, slippage 0.02% per side and funding 0.01% per 8 hours. Replace assumptions with the actual fee tier and historical funding series before considering a strategy valid.

## Promotion gates

No strategy can be called validated unless it has:
- at least 200 out-of-sample executed trades across multiple market regimes;
- profit factor > 1.25 after realistic fees, slippage and historical funding;
- positive expectancy across more than one independent leader and more than one coin;
- concentration and correlated-exposure checks;
- walk-forward and parameter-stability checks;
- complete data-coverage reporting and a paper-forward test.

Live execution is intentionally absent from v1.
