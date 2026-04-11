"""
test/test_orchestrator_state_machine.py — Orchestrator 상태 머신 전이 테스트

OrchestratorAgent의 전략 등록/실행/에러 핸들링/사이클 흐름을 검증합니다.
"""
from __future__ import annotations

import pytest
from datetime import date, timezone, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.orchestrator import OrchestratorAgent, DEFAULT_BLEND_WEIGHTS
from src.agents.strategy_runner import StrategyRunner, StrategyRegistry
from src.db.models import PredictionSignal


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_signal(
    ticker: str = "005930",
    signal: str = "BUY",
    confidence: float = 0.8,
    strategy: str = "A",
) -> PredictionSignal:
    return PredictionSignal(
        agent_id="test_agent",
        llm_model="test",
        strategy=strategy,
        ticker=ticker,
        signal=signal,
        confidence=confidence,
        target_price=70000,
        stop_loss=65000,
        reasoning_summary="test signal",
        trading_date=date(2026, 4, 11),
    )


class FakeRunner:
    """StrategyRunner 프로토콜을 구현하는 테스트용 러너."""

    def __init__(
        self,
        name: str,
        signals: list[PredictionSignal] | None = None,
        raise_error: bool = False,
    ):
        self.name = name
        self._signals = signals or []
        self._raise_error = raise_error
        self.run_called = False

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        self.run_called = True
        if self._raise_error:
            raise RuntimeError(f"Runner {self.name} failed")
        return self._signals


# ── Strategy Registration Tests ──────────────────────────────────────────────


@pytest.mark.unit
class TestStrategyRegistration:
    """전략 러너 등록 관련 테스트."""

    def test_register_single_strategy(self):
        orch = OrchestratorAgent()
        runner = FakeRunner("A")
        orch.register_strategy(runner)
        assert orch.registry.runner_count == 1
        assert "A" in orch.registry.active_names

    def test_register_multiple_strategies(self):
        orch = OrchestratorAgent()
        runners = [FakeRunner("A"), FakeRunner("B"), FakeRunner("RL")]
        orch.register_strategies(*runners)
        assert orch.registry.runner_count == 3
        assert orch.registry.active_names == ["A", "B", "RL"]

    def test_register_overwrites_same_name(self):
        orch = OrchestratorAgent()
        runner1 = FakeRunner("A", signals=[_make_signal()])
        runner2 = FakeRunner("A", signals=[])
        orch.register_strategy(runner1)
        orch.register_strategy(runner2)
        assert orch.registry.runner_count == 1
        # runner2가 등록되어야 함
        registered = orch.registry.get("A")
        assert registered is runner2

    def test_empty_registry(self):
        orch = OrchestratorAgent()
        assert orch.registry.runner_count == 0
        assert orch.registry.active_names == []


# ── run_strategies Tests ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestRunStrategies:
    """run_strategies() 병렬 실행 검증."""

    async def test_run_strategies_empty_registry(self):
        orch = OrchestratorAgent()
        result = await orch.run_strategies(["005930"])
        assert result == {}

    async def test_run_strategies_returns_predictions(self):
        orch = OrchestratorAgent()
        signals = [_make_signal("005930"), _make_signal("035720")]
        runner = FakeRunner("A", signals=signals)
        orch.register_strategy(runner)

        result = await orch.run_strategies(["005930", "035720"])
        assert "A" in result
        assert len(result["A"]) == 2
        assert runner.run_called

    async def test_run_strategies_handles_runner_error(self):
        """러너 실행 중 에러가 발생해도 다른 러너는 정상 실행."""
        orch = OrchestratorAgent()
        good_runner = FakeRunner("A", signals=[_make_signal()])
        bad_runner = FakeRunner("B", raise_error=True)
        orch.register_strategies(good_runner, bad_runner)

        result = await orch.run_strategies(["005930"])
        assert len(result["A"]) == 1
        assert result["B"] == []  # 에러 발생 시 빈 리스트

    async def test_run_strategies_multiple_runners_parallel(self):
        """여러 러너가 병렬로 실행되는지 검증."""
        orch = OrchestratorAgent()
        runner_a = FakeRunner("A", signals=[_make_signal(strategy="A")])
        runner_b = FakeRunner("B", signals=[_make_signal(strategy="B")])
        runner_rl = FakeRunner("RL", signals=[_make_signal(strategy="RL")])
        orch.register_strategies(runner_a, runner_b, runner_rl)

        result = await orch.run_strategies(["005930"])
        assert set(result.keys()) == {"A", "B", "RL"}
        assert all(runner.run_called for runner in [runner_a, runner_b, runner_rl])


# ── run_cycle Tests ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRunCycle:
    """run_cycle() 통합 사이클 테스트."""

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False)
    async def test_run_cycle_skips_when_market_closed(self, mock_market):
        orch = OrchestratorAgent()
        result = await orch.run_cycle(["005930"])
        assert result["skipped"] == "market_closed"
        assert result["collected"] == 0

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    @patch("src.agents.orchestrator.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_operational_audit", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_blend_results", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_orders", new_callable=AsyncMock)
    async def test_run_cycle_no_predictions_returns_empty_dict(self, *mocks):
        """registry가 비어 run_strategies가 {}를 반환하면 no_predictions 모드."""
        orch = OrchestratorAgent()
        # 러너가 없으면 run_strategies가 {}를 반환 → no_predictions
        result = await orch.run_cycle(["005930"])
        assert result["mode"] == "no_predictions"
        assert result["predicted"] == 0

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    @patch("src.agents.orchestrator.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_operational_audit", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_blend_results", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_orders", new_callable=AsyncMock)
    async def test_run_cycle_empty_signals_still_blend_mode(self, *mocks):
        """전략이 등록되어 있지만 빈 시그널 반환 시 blend_mode로 진행."""
        orch = OrchestratorAgent()
        runner = FakeRunner("A", signals=[])
        orch.register_strategy(runner)

        result = await orch.run_cycle(["005930"])
        # {"A": []}은 not {} → 빈 시그널이어도 블렌딩 경로 진행
        assert result["mode"] == "blend_mode"
        assert result["predicted"] == 0

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    @patch("src.agents.orchestrator.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_operational_audit", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_blend_results", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_orders", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_daily_rankings_batch", new_callable=AsyncMock)
    async def test_run_cycle_blend_mode_produces_orders(self, *mocks):
        """블렌딩 모드에서 시그널이 주문으로 변환되는지 검증."""
        orch = OrchestratorAgent()
        signals_a = [_make_signal("005930", "BUY", 0.9, "A")]
        signals_b = [_make_signal("005930", "BUY", 0.7, "B")]
        orch.register_strategies(
            FakeRunner("A", signals=signals_a),
            FakeRunner("B", signals=signals_b),
        )

        # _execute_blended_signals를 mock하여 주문 반환
        mock_orders = [{"ticker": "005930", "signal": "BUY", "quantity": 10}]
        with patch.object(orch, "_execute_blended_signals", new_callable=AsyncMock, return_value=mock_orders):
            with patch.object(orch, "_check_agent_health", new_callable=AsyncMock, return_value=[]):
                with patch.object(orch, "_record_daily_rankings", new_callable=AsyncMock):
                    with patch.object(orch, "_record_paper_trading_run", new_callable=AsyncMock):
                        with patch("src.agents.orchestrator.AggregateRiskMonitor"):
                            result = await orch.run_cycle(["005930"])

        assert result["mode"] == "blend_mode"
        assert result["orders"] == 1
        assert "A" in result["active_strategies"]
        assert "B" in result["active_strategies"]

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    @patch("src.agents.orchestrator.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_operational_audit", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_blend_results", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.store_orders", new_callable=AsyncMock)
    async def test_run_cycle_no_registered_strategies(self, *mocks):
        """전략이 없으면 빈 결과 반환."""
        orch = OrchestratorAgent()
        result = await orch.run_cycle(["005930"])
        # 전략이 없으면 {} 반환 → no predictions 경로
        assert result["predicted"] == 0

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    async def test_run_cycle_exception_records_error_heartbeat(self, mock_market):
        """사이클 중 예외 발생 시 에러 heartbeat 기록."""
        orch = OrchestratorAgent()
        runner = FakeRunner("A", raise_error=True)
        orch.register_strategy(runner)

        with patch("src.agents.orchestrator.insert_heartbeat", new_callable=AsyncMock) as mock_hb:
            with pytest.raises(Exception):
                with patch.object(orch, "run_strategies", new_callable=AsyncMock, side_effect=Exception("boom")):
                    await orch.run_cycle(["005930"])

            # insert_heartbeat가 에러 상태로 호출됨
            mock_hb.assert_called()
            call_args = mock_hb.call_args[0][0]
            assert call_args.status == "error"


# ── Per-strategy Portfolio Tests ─────────────────────────────────────────────


@pytest.mark.unit
class TestPerStrategyPortfolio:
    """독립 포트폴리오 모드 테스트."""

    def test_independent_portfolio_flag(self):
        orch = OrchestratorAgent(independent_portfolio=True)
        assert orch.independent_portfolio is True

    def test_default_blend_mode(self):
        orch = OrchestratorAgent()
        assert orch.independent_portfolio is False

    def test_get_portfolio_for_strategy_creates_instance(self):
        """전략별 PM 인스턴스가 지연 생성되는지 검증."""
        orch = OrchestratorAgent(independent_portfolio=True)

        with patch("src.agents.portfolio_manager.PortfolioManagerAgent") as mock_pm_cls:
            mock_pm_cls.return_value = MagicMock(agent_id="portfolio_manager_A")
            pm = orch._get_portfolio_for_strategy("A")
            assert pm is not None
            # 같은 전략으로 재호출하면 동일 인스턴스
            pm2 = orch._get_portfolio_for_strategy("A")
            assert pm is pm2

    def test_custom_blend_weights(self):
        custom_weights = {"A": 0.5, "B": 0.3, "RL": 0.2}
        orch = OrchestratorAgent(strategy_blend_weights=custom_weights)
        assert orch.strategy_blend_weights == custom_weights

    def test_default_blend_weights(self):
        orch = OrchestratorAgent()
        assert orch.strategy_blend_weights == DEFAULT_BLEND_WEIGHTS


# ── Agent Health Check Tests ─────────────────────────────────────────────────


@pytest.mark.unit
class TestAgentHealthCheck:
    """에이전트 상태 점검 테스트."""

    @patch("src.agents.orchestrator.get_heartbeat_detail", new_callable=AsyncMock, return_value=None)
    async def test_check_agent_health_offline(self, mock_hb):
        orch = OrchestratorAgent()
        issues = await orch._check_agent_health()
        # 모든 에이전트가 offline
        assert len(issues) == 3
        assert all(i["status"] == "offline" for i in issues)

    @patch("src.agents.orchestrator.get_heartbeat_detail", new_callable=AsyncMock)
    async def test_check_agent_health_degraded(self, mock_hb):
        mock_hb.return_value = {"status": "degraded", "mode": "paper", "error_count": "2"}
        orch = OrchestratorAgent()
        issues = await orch._check_agent_health()
        assert len(issues) == 3
        assert all(i["status"] == "degraded" for i in issues)
        assert all(i["error_count"] == 2 for i in issues)

    @patch("src.agents.orchestrator.get_heartbeat_detail", new_callable=AsyncMock)
    async def test_check_agent_health_all_healthy(self, mock_hb):
        mock_hb.return_value = {"status": "healthy", "mode": "paper"}
        orch = OrchestratorAgent()
        issues = await orch._check_agent_health()
        assert issues == []

    @patch("src.agents.orchestrator.get_heartbeat_detail", new_callable=AsyncMock)
    async def test_check_agent_health_error(self, mock_hb):
        mock_hb.return_value = {"status": "error", "mode": "paper", "error_count": "5"}
        orch = OrchestratorAgent()
        issues = await orch._check_agent_health()
        assert len(issues) == 3
        assert all(i["status"] == "error" for i in issues)


# ── Edge Cases ───────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestOrchestratorEdgeCases:
    """에지 케이스 테스트."""

    def test_agent_id_default(self):
        orch = OrchestratorAgent()
        assert orch.agent_id == "orchestrator_agent"

    def test_agent_id_custom(self):
        orch = OrchestratorAgent(agent_id="custom_orch")
        assert orch.agent_id == "custom_orch"

    async def test_run_strategies_with_empty_tickers(self):
        orch = OrchestratorAgent()
        runner = FakeRunner("A", signals=[])
        orch.register_strategy(runner)
        result = await orch.run_strategies([])
        assert "A" in result

    @patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=True)
    @patch("src.agents.screener.screen_tickers", new_callable=AsyncMock, return_value=[])
    @patch("src.agents.orchestrator.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.orchestrator.insert_heartbeat", new_callable=AsyncMock)
    async def test_run_cycle_screener_no_match(self, *mocks):
        """스크리너가 종목을 통과시키지 않으면 스킵."""
        orch = OrchestratorAgent()
        orch.register_strategy(FakeRunner("A"))
        result = await orch.run_cycle(["005930"], screener_kwargs={"min_volume": 100})
        assert result["skipped"] == "screener_no_match"
