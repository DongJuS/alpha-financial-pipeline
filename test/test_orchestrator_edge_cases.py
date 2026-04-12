"""
test/test_orchestrator_edge_cases.py — Orchestrator 에지케이스 테스트

Independent Portfolio 모드, Dynamic Weight 최적화의 경계 조건을 검증합니다.
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
        trading_date=date(2026, 4, 12),
    )


# ── Independent Portfolio Mode Tests ──────────────────────────────────────────


@pytest.mark.unit
class TestIndependentModeEdgeCases:
    """독립 포트폴리오 모드 에지케이스 테스트."""

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    async def test_independent_mode_empty_predictions_dict(self, mock_market):
        """all_predictions = {} (빈 dict)일 때 orders가 빈 리스트.

        run_strategies가 빈 dict를 반환하면 run_cycle은
        mode='no_predictions'으로 조기 반환하고 orders=0이어야 한다.
        """
        orch = OrchestratorAgent(independent_portfolio=True)
        with patch.object(orch, "run_strategies", new_callable=AsyncMock, return_value={}):
            result = await orch.run_cycle(["005930"])
        assert result["mode"] == "no_predictions"
        assert result["orders"] == 0
        assert result["predicted"] == 0

    @patch("src.agents.orchestrator.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_operational_audit", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_blend_results", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_orders", new_callable=AsyncMock)
    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    async def test_independent_mode_all_strategies_empty_predictions(
        self, mock_market, mock_store_orders, mock_store_blend,
        mock_audit, mock_set_hb, mock_insert_hb,
    ):
        """모든 전략이 빈 predictions 리스트를 반환할 때 orders가 빈 리스트.

        all_predictions가 비어있지 않지만(키가 존재), 각 전략의 리스트가 []이면
        독립 모드에서 각 전략을 순회하되 빈 predictions는 continue로 건너뛴다.
        최종 orders는 0이어야 한다.
        """
        orch = OrchestratorAgent(independent_portfolio=True)
        empty_predictions = {"A": [], "B": [], "RL": []}

        with (
            patch.object(orch, "run_strategies", new_callable=AsyncMock, return_value=empty_predictions),
            patch("src.utils.aggregate_risk.AggregateRiskMonitor.get_risk_summary", new_callable=AsyncMock) as mock_risk,
            patch("src.utils.aggregate_risk.AggregateRiskMonitor.record_risk_snapshot", new_callable=AsyncMock),
            patch("src.utils.strategy_promotion.StrategyPromoter.evaluate_promotion_readiness", new_callable=AsyncMock, return_value=None),
            patch.object(orch, "_create_notifier") as mock_notifier_factory,
            patch.object(orch, "_check_agent_health", new_callable=AsyncMock, return_value=[]),
            patch.object(orch, "_record_daily_rankings", new_callable=AsyncMock),
            patch.object(orch, "_record_paper_trading_run", new_callable=AsyncMock),
        ):
            risk_summary = MagicMock()
            risk_summary.warnings = []
            mock_risk.return_value = risk_summary
            mock_notifier_factory.return_value = MagicMock()

            result = await orch.run_cycle(["005930"])

        assert result["orders"] == 0

    @patch("src.agents.orchestrator.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_operational_audit", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_blend_results", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_orders", new_callable=AsyncMock)
    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    async def test_independent_mode_strategy_weights_stored_as_raw(
        self, mock_market, mock_store_orders, mock_store_blend,
        mock_audit, mock_set_hb, mock_insert_hb,
    ):
        """independent 모드에서 S3에 저장되는 strategy_weights가 raw blend weights (normalized 아님).

        orchestrator.py line 404-405에서 independent 모드일 때
        self.strategy_blend_weights를 그대로 저장한다.
        blend 모드에서는 effective_weights(normalized)를 저장하지만
        independent에서는 raw weights를 사용하는 것이 의도된 동작이다.
        """
        custom_weights = {"A": 0.33, "B": 0.33, "RL": 0.34}
        orch = OrchestratorAgent(
            independent_portfolio=True,
            strategy_blend_weights=custom_weights,
        )
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.9, "A")],
        }

        with (
            patch.object(orch, "run_strategies", new_callable=AsyncMock, return_value=predictions),
            patch("src.utils.aggregate_risk.AggregateRiskMonitor.get_risk_summary", new_callable=AsyncMock) as mock_risk,
            patch("src.utils.aggregate_risk.AggregateRiskMonitor.record_risk_snapshot", new_callable=AsyncMock),
            patch("src.utils.strategy_promotion.StrategyPromoter.evaluate_promotion_readiness", new_callable=AsyncMock, return_value=None),
            patch.object(orch, "_create_notifier") as mock_notifier_factory,
            patch.object(orch, "_get_portfolio_for_strategy") as mock_get_pm,
            patch.object(orch, "_check_agent_health", new_callable=AsyncMock, return_value=[]),
            patch.object(orch, "_record_daily_rankings", new_callable=AsyncMock),
            patch.object(orch, "_record_paper_trading_run", new_callable=AsyncMock),
        ):
            risk_summary = MagicMock()
            risk_summary.warnings = []
            mock_risk.return_value = risk_summary
            mock_notifier_factory.return_value = MagicMock()

            mock_pm = MagicMock()
            mock_pm.process_predictions = AsyncMock(return_value=[])
            mock_get_pm.return_value = mock_pm

            result = await orch.run_cycle(["005930"])

        # independent 모드에서는 blend_meta가 None
        assert result.get("blend_meta") is None
        # strategy_blend_weights가 변경되지 않았는지 확인 (raw로 유지)
        assert orch.strategy_blend_weights == custom_weights


# ── Dynamic Weight Optimization Tests ─────────────────────────────────────────


@pytest.mark.unit
class TestDynamicWeightEdgeCases:
    """Dynamic Weight 최적화 에지케이스 테스트."""

    @patch("src.agents.orchestrator.get_settings")
    async def test_dynamic_weight_disabled_ignores_active_strategies(self, mock_settings):
        """DYNAMIC_BLEND_WEIGHTS_ENABLED=false일 때 가중치 불변.

        활성 전략 리스트가 전달되어도 settings가 false이면
        가중치를 전혀 건드리지 않고 즉시 반환해야 한다.
        """
        settings = MagicMock()
        settings.dynamic_blend_weights_enabled = False
        mock_settings.return_value = settings

        original_weights = {"A": 0.5, "B": 0.3, "RL": 0.2}
        orch = OrchestratorAgent(strategy_blend_weights=dict(original_weights))
        await orch._maybe_update_dynamic_weights(["A", "B", "RL"])
        assert orch.strategy_blend_weights == original_weights

    @patch("src.utils.blend_weight_optimizer.BlendWeightOptimizer.optimize", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.get_settings")
    async def test_dynamic_weight_optimizer_db_error_fallback(self, mock_settings, mock_optimize):
        """BlendWeightOptimizer.optimize()에서 DB 에러 시 base_weights로 fallback.

        BlendWeightOptimizer.optimize()는 내부에서 DB 에러를 잡아
        base_weights를 정규화하여 반환한다 (blend_weight_optimizer.py line 196-197).
        _maybe_update_dynamic_weights는 이 반환값을 그대로 사용한다.
        """
        settings = MagicMock()
        settings.dynamic_blend_weights_enabled = True
        settings.dynamic_blend_lookback_days = 30
        settings.dynamic_blend_min_weight = 0.05
        mock_settings.return_value = settings

        # optimize가 DB 에러 후 base_weights 정규화 결과를 반환하는 시나리오
        mock_optimize.return_value = {"A": 0.5, "B": 0.5}

        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.5, "RL": 0.0})
        await orch._maybe_update_dynamic_weights(["A", "B"])

        # optimize가 반환한 값이 활성 전략에 적용된다
        assert orch.strategy_blend_weights["A"] == 0.5
        assert orch.strategy_blend_weights["B"] == 0.5
        # 비활성 전략은 0.0
        assert orch.strategy_blend_weights["RL"] == 0.0

    def test_dynamic_weight_all_zero_weights_equal_distribution(self):
        """모든 가중치 0.0일 때 균등 분배 (_normalize_active_weights).

        strategy_blend_weights의 모든 값이 0.0이면
        _normalize_active_weights는 활성 전략 수로 균등 분배한다.
        """
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.0, "B": 0.0, "RL": 0.0}
        )
        result = orch._normalize_active_weights({"A", "B", "RL"})
        # 모든 가중치가 0이므로 동일 분배
        expected = 1.0 / 3
        for key in ("A", "B", "RL"):
            assert key in result
            assert abs(result[key] - expected) < 1e-6
        assert abs(sum(result.values()) - 1.0) < 1e-6
