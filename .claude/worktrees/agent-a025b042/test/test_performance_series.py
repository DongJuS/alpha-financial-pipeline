from datetime import datetime, timezone
import unittest

from src.utils.performance import compute_benchmark_series, compute_trade_performance_series


class PerformanceSeriesTest(unittest.TestCase):
    def test_compute_trade_performance_series_returns_points(self) -> None:
        rows = [
            {
                "ticker": "005930",
                "side": "BUY",
                "price": 100,
                "quantity": 1,
                "executed_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            },
            {
                "ticker": "005930",
                "side": "SELL",
                "price": 110,
                "quantity": 1,
                "executed_at": datetime(2026, 1, 3, tzinfo=timezone.utc),
            },
        ]

        series = compute_trade_performance_series(rows)

        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["date"], "2026-01-02")
        self.assertEqual(series[1]["date"], "2026-01-03")
        self.assertEqual(series[1]["realized_pnl_cum"], 10)
        self.assertEqual(series[1]["portfolio_return_pct"], 10.0)

    def test_compute_benchmark_series(self) -> None:
        rows = [
            {"trade_date": "2026-01-02", "avg_close": 1000.0},
            {"trade_date": "2026-01-03", "avg_close": 1050.0},
        ]
        series = compute_benchmark_series(rows)

        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["benchmark_return_pct"], 0.0)
        self.assertEqual(series[1]["benchmark_return_pct"], 5.0)


if __name__ == "__main__":
    unittest.main()
