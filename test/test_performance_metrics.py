"""
test/test_performance_metrics.py — compute_trade_performance() 성과 지표 테스트

avg_profit_loss_ratio 및 기존 지표의 정상 반환을 검증합니다.
"""

from __future__ import annotations

import pytest

from src.utils.performance import compute_trade_performance

pytestmark = [pytest.mark.unit]


class TestAvgProfitLossRatio:
    """avg_profit_loss_ratio 계산 검증."""

    def test_ratio_with_wins_and_losses(self):
        """이익 3건(+1000), 손실 2건(-500) → ratio = 1000/500 = 2.0"""
        rows = [
            # 이익 매매 3건: 매수 100 → 매도 200 → 실현이익 100*10=1000
            {"ticker": "A", "side": "BUY", "quantity": 10, "price": 100, "amount": 1000},
            {"ticker": "A", "side": "SELL", "quantity": 10, "price": 200, "amount": 2000},
            {"ticker": "B", "side": "BUY", "quantity": 10, "price": 100, "amount": 1000},
            {"ticker": "B", "side": "SELL", "quantity": 10, "price": 200, "amount": 2000},
            {"ticker": "C", "side": "BUY", "quantity": 10, "price": 100, "amount": 1000},
            {"ticker": "C", "side": "SELL", "quantity": 10, "price": 200, "amount": 2000},
            # 손실 매매 2건: 매수 100 → 매도 50 → 실현손실 50*10=500
            {"ticker": "D", "side": "BUY", "quantity": 10, "price": 100, "amount": 1000},
            {"ticker": "D", "side": "SELL", "quantity": 10, "price": 50, "amount": 500},
            {"ticker": "E", "side": "BUY", "quantity": 10, "price": 100, "amount": 1000},
            {"ticker": "E", "side": "SELL", "quantity": 10, "price": 50, "amount": 500},
        ]

        result = compute_trade_performance(rows)

        assert "avg_profit_loss_ratio" in result, (
            "avg_profit_loss_ratio가 반환 dict에 포함되어야 합니다"
        )
        assert result["avg_profit_loss_ratio"] == 2.0

    def test_ratio_no_losses(self):
        """모두 이익 매매 → 분모(avg_loss)가 0이므로 None."""
        rows = [
            {"ticker": "A", "side": "BUY", "quantity": 10, "price": 100, "amount": 1000},
            {"ticker": "A", "side": "SELL", "quantity": 10, "price": 200, "amount": 2000},
            {"ticker": "B", "side": "BUY", "quantity": 5, "price": 100, "amount": 500},
            {"ticker": "B", "side": "SELL", "quantity": 5, "price": 150, "amount": 750},
        ]

        result = compute_trade_performance(rows)

        assert "avg_profit_loss_ratio" in result
        assert result["avg_profit_loss_ratio"] is None

    def test_ratio_no_wins(self):
        """모두 손실 매매 → 분자(avg_win)가 0이므로 None."""
        rows = [
            {"ticker": "A", "side": "BUY", "quantity": 10, "price": 200, "amount": 2000},
            {"ticker": "A", "side": "SELL", "quantity": 10, "price": 100, "amount": 1000},
            {"ticker": "B", "side": "BUY", "quantity": 5, "price": 300, "amount": 1500},
            {"ticker": "B", "side": "SELL", "quantity": 5, "price": 100, "amount": 500},
        ]

        result = compute_trade_performance(rows)

        assert "avg_profit_loss_ratio" in result
        assert result["avg_profit_loss_ratio"] is None

    def test_ratio_empty_rows(self):
        """빈 매매 이력 → None."""
        result = compute_trade_performance([])

        assert "avg_profit_loss_ratio" in result
        assert result["avg_profit_loss_ratio"] is None


class TestExistingMetricsCompat:
    """기존 지표(return_pct, max_drawdown_pct, sharpe_ratio, win_rate)가 정상 반환되는지 확인."""

    def test_existing_metrics_returned(self):
        """기존 테스트와 동일한 데이터로 기존 지표 호환성 검증."""
        rows = [
            {"ticker": "AAA", "side": "BUY", "quantity": 1, "price": 100, "amount": 100},
            {"ticker": "AAA", "side": "SELL", "quantity": 1, "price": 110, "amount": 110},
            {"ticker": "BBB", "side": "BUY", "quantity": 1, "price": 200, "amount": 200},
            {"ticker": "BBB", "side": "SELL", "quantity": 1, "price": 180, "amount": 180},
        ]

        result = compute_trade_performance(rows)

        # 기존 지표 키가 모두 존재해야 한다
        expected_keys = {
            "return_pct",
            "max_drawdown_pct",
            "sharpe_ratio",
            "win_rate",
            "total_trades",
            "realized_pnl",
            "invested_capital",
            "sell_count",
        }
        assert expected_keys.issubset(result.keys()), (
            f"누락된 키: {expected_keys - result.keys()}"
        )

        # 기존 테스트의 기대값과 동일한지 확인
        assert result["total_trades"] == 4
        assert result["return_pct"] == -3.33
        assert result["win_rate"] == 0.5
        assert result["max_drawdown_pct"] == -10.0
        assert result["sharpe_ratio"] == 0.0

    def test_buy_only_metrics(self):
        """매도 없는 경우에도 기존 지표가 기본값으로 반환된다."""
        rows = [
            {"ticker": "AAA", "side": "BUY", "quantity": 2, "price": 100, "amount": 200},
        ]

        result = compute_trade_performance(rows)

        assert result["total_trades"] == 1
        assert result["return_pct"] == 0.0
        assert result["win_rate"] == 0.0
        assert result["max_drawdown_pct"] == 0.0
        assert result["sharpe_ratio"] is None
