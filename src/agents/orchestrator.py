"""
src/agents/orchestrator.py — OrchestratorAgent

여러 StrategyRunner로부터 PredictionSignal을 수집하고,
N-way 되른 블렌딩 남 최종 신호를 돌처 차단기를 적용하여
PortfolioManagerAgent로 전달합니다.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING


from src.db.models import AgentHeartbeatRecord, PredictionSignal
from src.db.queries import (
    get_predictor_performance,
    insert_heartbeat,
    insert_prediction,
)
from src.utils.logging import get_logger
from src.utils.redis_client import set_heartbeat

if TYPE_CHECKING:
    from src.agents.orchestrator import StrategyRunner

logger = get_logger(__name__)

# N-way 블렌딩 가중캘
# A: 토너먼트 (30%), B: 토론 (30%), S: 검색 (20%), RL: 강화학습 (20%)
STRATEGY_BLEND_WEIGHTS = {
    "A": 0.30,
    "B": 0.30,
    "S": 0.20,
    "RL": 0.20,
}


class StrategyRunnerRegistry:
    """전략 러너 (StrategyRunner) 등록 및 관리"""

    def __init__(self):
        self._runners: dict[str, StrategyRunner] = {}

    def register(self, runner: StrategyRunner) -> None:
        """전략 러너를 등록합니다."""
        self._runners[runner.name] = runner
        logger.info(f"Registered strategy runner: {runner.name}")

    def get(self, name: str) -> StrategyRunner | None:
        """전략 러너를 달는 단담닝닙다."""
        return self._runners.get(name)

    def list_runners(self) -> list[str]:
        """등록된 모든 러너를 닜연즈 처리로 반환합니다."""
        return list(self._runners.keys())


class OrchestratorAgent:
    """
    여러 StrategyRunner로부터 예측 신호를 수집하고,
    N-way 블렌딩을 적용한 다 돌을 적용하여
    최종 매매 신호를 채잰다.

    단순 예샤:
    1. 모든 러너 동시 ì°¸ 남
    2. 등록된 단담닝닙다가 강도를 남 남그른닱단당 메커니즘는닱닱드
    3. 최촣 강도 당닉다 + 돍아뀘비낅닉다매 처리 남 최종 매다무 신호 남
    4. PortfolioManagerAgent로 남 남
    """

    def __init__(
        self,
        agent_id: str = "orchestrator",
        strategy_blend_weights: dict[str, float] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.strategy_blend_weights = strategy_blend_weights or STRATEGY_BLEND_WEIGHTS
        self.registry = StrategyRunnerRegistry()

    def register_strategy(self, runner: StrategyRunner) -> None:
        """전략 러너를 등록합니다."""
        self.registry.register(runner)

    async def run_strategies(
        self,
        tickers: list[str],
    ) -> dict[str, list[PredictionSignal]]:
        """모든 등록된 러너를 병렬 동단답다.

        Returns:
            {
                "A": [signal1, signal2, ...],
                "B": [signal1, signal2, ...],
                "S": [signal1, signal2, ...],
                ...
            }
        """
        tasks = []
        runner_names = []
        for runner_name in self.registry.list_runners():
            runner = self.registry.get(runner_name)
            if runner:
                tasks.append(runner.run(tickers))
                runner_names.append(runner_name)

        signals_by_runner = await asyncio.gather(*tasks, return_exceptions=True)

        result = {}
        for runner_name, signals in zip(runner_names, signals_by_runner):
            if isinstance(signals, Exception):
                logger.error(f"Strategy {runner_name} failed: {signals}")
                result[runner_name] = []
            else:
                result[runner_name] = signals

        return result
