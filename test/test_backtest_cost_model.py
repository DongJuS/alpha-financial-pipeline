"""CostModel 단위 테스트."""

from pytest import approx

from src.backtest.cost_model import CostModel, TradeCost


def _default_model() -> CostModel:
    """기본 비용 모델 (수수료 0.015 %, 세금 0.18 %, 슬리피지 3 bps)."""
    return CostModel()


class TestCostModelBuy:
    """BUY 시 commission 만 부과, tax 는 0."""

    def test_buy_no_tax(self) -> None:
        cost = _default_model().calculate("BUY", 60_000, 100)
        assert cost.tax == 0.0

    def test_buy_commission(self) -> None:
        cost = _default_model().calculate("BUY", 60_000, 100)
        # 60,000 * 100 * 0.00015 = 900
        assert cost.commission == approx(900.0)


class TestCostModelSell:
    """SELL 시 commission + tax 모두 부과."""

    def test_sell_commission_and_tax(self) -> None:
        cost = _default_model().calculate("SELL", 60_000, 100)
        notional = 60_000 * 100  # 6,000,000
        expected_commission = notional * 0.00015  # 900
        expected_tax = notional * 0.0018  # 10,800
        assert cost.commission == expected_commission
        assert cost.tax == expected_tax


class TestSlippage:
    """슬리피지는 BUY/SELL 양방향 동일."""

    def test_slippage_amount(self) -> None:
        model = _default_model()
        notional = 60_000 * 100  # 6,000,000
        expected_slippage = notional * (3 / 10_000)  # 1,800

        buy_cost = model.calculate("BUY", 60_000, 100)
        sell_cost = model.calculate("SELL", 60_000, 100)

        assert buy_cost.slippage_cost == expected_slippage
        assert sell_cost.slippage_cost == expected_slippage


class TestTotalCost:
    """삼성전자 60,000 원 x 100 주 BUY 총 비용 검증."""

    def test_buy_total(self) -> None:
        cost = _default_model().calculate("BUY", 60_000, 100)
        # commission 900 + tax 0 + slippage 1,800 = 2,700
        assert cost.total == approx(2_700.0)

    def test_sell_total(self) -> None:
        cost = _default_model().calculate("SELL", 60_000, 100)
        # commission 900 + tax 10,800 + slippage 1,800 = 13,500
        assert cost.total == 13_500.0


class TestEdgeCases:
    """경계 조건."""

    def test_zero_quantity(self) -> None:
        cost = _default_model().calculate("BUY", 60_000, 0)
        assert cost == TradeCost(
            commission=0.0, tax=0.0, slippage_cost=0.0, total=0.0
        )

    def test_custom_rates(self) -> None:
        model = CostModel(
            commission_rate_pct=0.01,
            tax_rate_pct=0.25,
            slippage_bps=5,
        )
        cost = model.calculate("SELL", 10_000, 10)
        notional = 100_000
        assert cost.commission == notional * 0.0001  # 10
        assert cost.tax == notional * 0.0025  # 250
        assert cost.slippage_cost == notional * 0.0005  # 50
