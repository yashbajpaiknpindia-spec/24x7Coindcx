import unittest

from analyze_patterns import aggregate, normalise_position
from backtest_leader_copy import simulate_trade


class ResearchEngineTests(unittest.TestCase):
    def test_normalise_position_uses_real_open_close_and_side(self):
        row = {
            "portfolioId": "leader-1",
            "raw": {
                "symbol": "BTCUSDT", "side": "LONG", "opened": 1_760_000_000_000,
                "closed": 1_760_003_600_000, "closingPnl": "12.5",
                "leverage": "5", "avgCost": "100000", "avgClosePrice": "101000",
            },
        }
        parsed = normalise_position(row)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["side"], "LONG")
        self.assertAlmostEqual(parsed["durationHours"], 1.0)
        self.assertEqual(parsed["reportedPnl"], 12.5)

    def test_aggregate_deduplicates_and_requires_independent_traders(self):
        base = {
            "symbol": "BTCUSDT", "side": "LONG", "opened": 1_760_000_000_000,
            "closed": 1_760_003_600_000, "closingPnl": "10", "leverage": "3",
        }
        rows = []
        for i in range(5):
            rows.append({"portfolioId": f"leader-{i}", "raw": {**base, "opened": base["opened"] + i * 10_000}})
        rows.append(rows[0])
        normalised = [normalise_position(x) for x in rows]
        report = aggregate([x for x in normalised if x])
        self.assertEqual(report["deduplicatedClosedPositions"], 5)
        self.assertEqual(report["tradersWithHistory"], 5)
        self.assertFalse(report["symbolSide"][0]["researchEligible"])  # <30 trades

    def test_follower_stop_is_applied_before_lead_close(self):
        pos = {
            "portfolioId": "leader", "symbol": "BTCUSDT", "side": "LONG",
            "openedMs": 1000, "closedMs": 180_000, "reportedPnl": -100,
        }
        candles = [
            {"t": 1000, "o": 100.0, "h": 100.2, "l": 99.9, "c": 100.0},
            {"t": 61_000, "o": 100.0, "h": 100.1, "l": 98.8, "c": 99.0},
            {"t": 121_000, "o": 99.0, "h": 99.2, "l": 98.9, "c": 99.1},
            {"t": 181_000, "o": 99.1, "h": 99.2, "l": 99.0, "c": 99.1},
        ]
        trade = simulate_trade(pos, candles, 0.01, 0.0025, 1.0)
        self.assertEqual(trade["exitReason"], "FOLLOWER_STOP")
        self.assertLess(trade["netReturn"], 0)


if __name__ == "__main__":
    unittest.main()
