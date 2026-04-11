"""
test/test_orchestrator_dynamic_weight.py — Dynamic weight, execute_blended_signals, run_cycle 분기 테스트

OrchestratorAgent의 _maybe_update_dynamic_weights, _normalize_active_weights 에지케이스,
_execute_blended_signals, run_cycle independent/blend 분기를 검증합니다.
"""
from __future__ import annotations

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.orchestrator import OrchestratorAgent, DEFAULT_BLEND_WEIGHTS
from src.db.models import PredictionSignal


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_signal(
    ticker: str = "005930",
    signal: str = "BUY",
    confidence: float = 0.8,
    strategy: str = "A",
) -> PredictionSignal:
    return PredictionSignal(
        agent_id=f"test_{strategy}",
        llm_model="test",
        strategy=strategy,
        ticker=ticker,
        signal=signal,
        confidence=confidence,
        target_price=70000,
        stop_loss=65000,
        reasoning_summary="test",
        trading_date=date(2026, 4, 11),
    )


# ── Dynamic Weight Optimization Tests ──────────────────────────────────────────


@pytest.mark.unit
class TestMaybeUpdateDynamicWeights:
    """_maybe_update_dynamic_weights 동적 가중치 최적화 테스트."""

    @patch("src.agents.orchestrator.get_settings")
    async def test_disabled_returns_early(self, mock_settings):
        """DYNAMIC_BLEND_WEIGHTS_ENABLED=false이면 즉시 반환."""
        settings = MagicMock()
        settings.dynamic_blend_weights_enabled = False
        mock_settings.return_value = settings

        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.5})
        original_weights = dict(orch.strategy_blend_weights)
        await orch._maybe_update_dynamic_weights(["A", "B"])
        assert orch.strategy_blend_weights == original_weights

    @patch("src.agents.orchestrator.get_settings")
    async def test_enabled_with_empty_active_strategies(self, mock_settings):
        """활성 전략이 없으면 base_for_active가 비어서 즉시 반환."""
        settings = MagicMock()
        settings.dynamic_blend_weights_enabled = True
        mock_settings.return_value = settings

        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.5})
        original_weights = dict(orch.strategy_blend_weights)
        await orch._maybe_update_dynamic_weights([])
        assert orch.strategy_blend_weights == original_weights

    @patch("src.agents.orchestrator.get_settings")
    async def test_enabled_with_unregistered_strategies(self, mock_settings):
        """활성 전략이 등록되지 않은 키이면 base_for_active가 비어서 즉시 반환."""
        settings = MagicMock()
        settings.dynamic_blend_weights_enabled = True
        mock_settings.return_value = settings

        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.5})
        original_weights = dict(orch.strategy_blend_weights)
        await orch._maybe_update_dynamic_weights(["X", "Y", "Z"])
        assert orch.strategy_blend_weights == original_weights

    @patch("src.utils.blend_weight_optimizer.BlendWeightOptimizer.optimize", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.get_settings")
    async def test_enabled_updates_weights(self, mock_settings, mock_optimize):
        """활성 전략이 있으면 optimizer 호출 후 가중치가 갱신된다."""
        settings = MagicMock()
        settings.dynamic_blend_weights_enabled = True
        settings.dynamic_blend_lookback_days = 30
        settings.dynamic_blend_min_weight = 0.05
        mock_settings.return_value = settings

        mock_optimize.return_value = {"A": 0.7, "B": 0.3}

        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.3, "RL": 0.2})
        await orch._maybe_update_dynamic_weights(["A", "B"])

        # A, B는 새 가중치, RL은 활성이 아니므로 0
        assert orch.strategy_blend_weights["A"] == 0.7
        assert orch.strategy_blend_weights["B"] == 0.3
        assert orch.strategy_blend_weights["RL"] == 0.0

    @patch("src.utils.blend_weight_optimizer.BlendWeightOptimizer.optimize", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.get_settings")
    async def test_partial_active_strategies(self, mock_settings, mock_optimize):
        """3개 중 1개만 활성이면 나머지 가중치는 0."""
        settings = MagicMock()
        settings.dynamic_blend_weights_enabled = True
        settings.dynamic_blend_lookback_days = 30
        settings.dynamic_blend_min_weight = 0.05
        mock_settings.return_value = settings

        mock_optimize.return_value = {"A": 1.0}

        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34})
        await orch._maybe_update_dynamic_weights(["A"])

        assert orch.strategy_blend_weights["A"] == 1.0
        assert orch.strategy_blend_weights["B"] == 0.0
        assert orch.strategy_blend_weights["RL"] == 0.0


# ── Execute Blended Signals Tests ──────────────────────────────────────────────


@pytest.mark.unit
class TestExecuteBlendedSignals:
    """_execute_blended_signals 테스트."""

    async def test_empty_signals_returns_empty(self):
        """빈 시그널 리스트 → 빈 주문 리스트."""
        orch = OrchestratorAgent()
        result = await orch._execute_blended_signals([])
        assert result == []

    @patch("src.agents.portfolio_manager.PortfolioManagerAgent.process_predictions", new_callable=AsyncMock)
    async def test_signals_forwarded_to_portfolio_manager(self, mock_process):
        """시그널이 PortfolioManagerAgent로 전달된다."""
        mock_process.return_value = [
            {"ticker": "005930", "side": "BUY", "quantity": 1, "price": 70000}
        ]
        orch = OrchestratorAgent()
        signals = [_make_signal("005930", "BUY", 0.9, "BLEND")]
        result = await orch._execute_blended_signals(signals)
        assert len(result) == 1
        assert result[0]["ticker"] == "005930"
        mock_process.assert_awaited_once()
        # signal_source_override 확인
        call_kwargs = mock_process.call_args
        assert call_kwargs.kwargs.get("signal_source_override") == "BLEND"

    @patch("src.agents.portfolio_manager.PortfolioManagerAgent.process_predictions", new_callable=AsyncMock)
    async def test_exception_returns_empty(self, mock_process):
        """PortfolioManagerAgent 예외 시 빈 리스트 반환."""
        mock_process.side_effect = RuntimeError("DB connection failed")
        orch = OrchestratorAgent()
        signals = [_make_signal("005930", "BUY", 0.9, "BLEND")]
        result = await orch._execute_blended_signals(signals)
        assert result == []

    @patch("src.agents.portfolio_manager.PortfolioManagerAgent.process_predictions", new_callable=AsyncMock)
    async def test_multiple_signals(self, mock_process):
        """다수 시그널이 한 번에 전달된다."""
        mock_process.return_value = [
            {"ticker": "005930", "side": "BUY"},
            {"ticker": "035720", "side": "SELL"},
        ]
        orch = OrchestratorAgent()
        signals = [
            _make_signal("005930", "BUY", 0.9),
            _make_signal("035720", "SELL", 0.8),
        ]
        result = await orch._execute_blended_signals(signals)
        assert len(result) == 2


# ── Normalize Active Weights Additional Edge Cases ─────────────────────────────


@pytest.mark.unit
class TestNormalizeActiveWeightsEdgeCases:
    """_normalize_active_weights 추가 에지케이스."""

    def test_single_active_with_zero_weight(self):
        """단일 활성 전략이 0 가중치이면 동일 분배(1.0)."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.0, "B": 0.5})
        result = orch._normalize_active_weights({"A"})
        # A가 0.0이므로 raw는 비어 total=0 → equal distribution
        assert abs(result["A"] - 1.0) < 1e-6

    def test_mixed_zero_and_positive_weights(self):
        """일부 0, 일부 양수 → 양수만으로 정규화."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.0, "B": 0.6, "RL": 0.4})
        result = orch._normalize_active_weights({"A", "B", "RL"})
        # A(0.0)는 제외, B(0.6), RL(0.4) → B=0.6, RL=0.4
        assert "A" not in result
        assert abs(result["B"] - 0.6) < 1e-6
        assert abs(result["RL"] - 0.4) < 1e-6

    def test_very_small_weights(self):
        """매우 작은 가중치도 정규화 가능."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.001, "B": 0.001})
        result = orch._normalize_active_weights({"A", "B"})
        assert abs(result["A"] - 0.5) < 1e-6
        assert abs(result["B"] - 0.5) < 1e-6

    def test_unequal_weights_normalization(self):
        """3:1 비율이 유지되는지 검증."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.75, "B": 0.25})
        result = orch._normalize_active_weights({"A", "B"})
        assert abs(result["A"] - 0.75) < 1e-6
        assert abs(result["B"] - 0.25) < 1e-6

    def test_four_strategies_active(self):
        """4개 전략이 활성인 경우."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.25, "B": 0.25, "RL": 0.25, "S": 0.25})
        result = orch._normalize_active_weights({"A", "B", "RL", "S"})
        assert abs(sum(result.values()) - 1.0) < 1e-6
        assert len(result) == 4


# ── Record Paper Trading Run Tests ─────────────────────────────────────────────


@pytest.mark.unit
class TestRecordPaperTradingRun:
    """_record_paper_trading_run 테스트."""

    @patch("src.agents.orchestrator.insert_paper_trading_run", new_callable=AsyncMock)
    @patch("src.utils.performance.compute_trade_performance")
    @patch("src.db.queries.fetch_trade_rows_for_date", new_callable=AsyncMock)
    async def test_no_rows_returns_early(self, mock_fetch, mock_compute, mock_insert):
        """당일 거래가 없으면 기록하지 않는다."""
        mock_fetch.return_value = []
        orch = OrchestratorAgent()
        await orch._record_paper_trading_run()
        mock_compute.assert_not_called()
        mock_insert.assert_not_called()

    @patch("src.agents.orchestrator.insert_paper_trading_run", new_callable=AsyncMock)
    @patch("src.utils.performance.compute_trade_performance")
    @patch("src.db.queries.fetch_trade_rows_for_date", new_callable=AsyncMock)
    async def test_with_rows_records_performance(self, mock_fetch, mock_compute, mock_insert):
        """거래가 있으면 성과를 계산하고 기록한다."""
        mock_fetch.return_value = [{"some": "trade_row"}]
        mock_compute.return_value = {
            "total_trades": 5,
            "return_pct": 1.5,
            "max_drawdown_pct": -0.5,
            "sharpe_ratio": 1.2,
        }
        orch = OrchestratorAgent()
        await orch._record_paper_trading_run()
        mock_insert.assert_awaited_once()
        call_kwargs = mock_insert.call_args.kwargs
        assert call_kwargs["trade_count"] == 5
        assert call_kwargs["return_pct"] == 1.5
        assert call_kwargs["passed"] is True  # return_pct >= 0

    @patch("src.agents.orchestrator.insert_paper_trading_run", new_callable=AsyncMock)
    @patch("src.utils.performance.compute_trade_performance")
    @patch("src.db.queries.fetch_trade_rows_for_date", new_callable=AsyncMock)
    async def test_negative_return_not_passed(self, mock_fetch, mock_compute, mock_insert):
        """수익률이 음수이면 passed=False."""
        mock_fetch.return_value = [{"some": "trade_row"}]
        mock_compute.return_value = {
            "total_trades": 3,
            "return_pct": -2.1,
            "max_drawdown_pct": -5.0,
            "sharpe_ratio": -0.3,
        }
        orch = OrchestratorAgent()
        await orch._record_paper_trading_run()
        call_kwargs = mock_insert.call_args.kwargs
        assert call_kwargs["passed"] is False


# ── Run Cycle Branch Tests ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestRunCycleModeBranching:
    """run_cycle의 independent/blend 모드 분기 검증."""

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False)
    async def test_market_closed_skips_cycle(self, mock_market):
        """장 외 시간에는 cycle 스킵."""
        orch = OrchestratorAgent()
        result = await orch.run_cycle(["005930"])
        assert result["skipped"] == "market_closed"

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    async def test_no_predictions_returns_no_predictions_mode(self, mock_market):
        """전략이 예측을 안 하면 mode='no_predictions'."""
        orch = OrchestratorAgent()
        with patch.object(orch, "run_strategies", new_callable=AsyncMock, return_value={}):
            result = await orch.run_cycle(["005930"])
        assert result["mode"] == "no_predictions"
        assert result["predicted"] == 0

    def test_independent_mode_flag(self):
        """independent_portfolio=True이면 독립 모드로 진입."""
        orch = OrchestratorAgent(independent_portfolio=True)
        assert orch.independent_portfolio is True

    def test_blend_mode_flag(self):
        """independent_portfolio=False이면 블렌딩 모드."""
        orch = OrchestratorAgent(independent_portfolio=False)
        assert orch.independent_portfolio is False


# ── Orchestrator Init Tests ────────────────────────────────────────────────────


@pytest.mark.unit
class TestOrchestratorInit:
    """OrchestratorAgent 생성자 다양한 조합."""

    def test_default_weights(self):
        orch = OrchestratorAgent()
        assert orch.strategy_blend_weights == DEFAULT_BLEND_WEIGHTS

    def test_custom_agent_id(self):
        orch = OrchestratorAgent(agent_id="custom_orch")
        assert orch.agent_id == "custom_orch"

    def test_empty_strategy_portfolios_on_init(self):
        orch = OrchestratorAgent()
        assert orch._strategy_portfolios == {}
        assert orch._strategy_virtual_brokers == {}

    def test_registry_starts_empty(self):
        orch = OrchestratorAgent()
        assert orch.registry.runner_count == 0
