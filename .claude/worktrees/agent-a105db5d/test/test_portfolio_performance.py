import unittest

from src.utils.performance import compute_trade_performance


class PortfolioPerformanceMetricsTest(unittest.TestCase):
    def test_compute_trade_performance_realized_pnl_metrics(self) -> None:
        rows = [
            {"ticker": "AAA", "side": "BUY", "quantity": 1, "price": 100, "amount": 100},
            {"ticker": "AAA", "side": "SELL", "quantity": 1, "price": 110, "amount": 110},
            {"ticker": "BBB", "side": "BUY", "quantity": 1, "price": 200, "amount": 200},
            {"ticker": "BBB", "side": "SELL", "quantity": 1, "price": 180, "amount": 180},
        ]
        result = compute_trade_performance(rows)

        self.assertEqual(result["total_trades"], 4)
        self.assertEqual(result["return_pct"], -3.33)
        self.assertEqual(result["win_rate"], 0.5)
        self.assertEqual(result["max_drawdown_pct"], -10.0)
        self.assertEqual(result["sharpe_ratio"], 0.0)

    def test_compute_trade_performance_without_sells(self) -> None:
        rows = [
            {"ticker": "AAA", "side": "BUY", "quantity": 2, "price": 100, "amount": 200},
        ]
        result = compute_trade_performance(rows)

        self.assertEqual(result["total_trades"], 1)
        self.assertEqual(result["return_pct"], 0.0)
        self.assertEqual(result["win_rate"], 0.0)
        self.assertEqual(result["max_drawdown_pct"], 0.0)
        self.assertIsNone(result["sharpe_ratio"])


if __name__ == "__main__":
    unittest.main()
