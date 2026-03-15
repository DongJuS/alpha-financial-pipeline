"""
src/agents/strategy_runner.py — StrategyRunner Protocol + StrategyRegistry

모든 전략(A/B/RL/S/L)을 동일한 인터페이스로 추상화하고,
Orchestrator가 활성화된 Runner들을 병렬 실행할 수 있도록 한다.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from src.db.models import PredictionSignal
from src.utils.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class StrategyRunner(Protocol):
    """모든 전략이 구현해야 하는 인터페이스."""

    name: str  # "A", "B", "RL", "S", "L"

    async def run(self, tickers: list[str]) -> list[PredictionSignal]: ...


class StrategyRegistry:
    """활성화된 StrategyRunner들을 등록/관리하고 병렬 실행한다."""

    def __init__(self) -> None:
        self._runners: dict[str, StrategyRunner] = {}

    def register(self, runner: StrategyRunner) -> None:
        """Runner를 등록한다. 같은 name이면 덮어쓴다."""
        self._runners[runner.name] = runner
        logger.info("StrategyRegistry: '%s' runner 등록됨", runner.name)

    def unregister(self, name: str) -> None:
        """Runner를 제거한다."""
        removed = self._runners.pop(name, None)
        if removed:
            logger.info("StrategyRegistry: '%s' runner 제거됨", name)

    @property
    def active_names(self) -> list[str]:
        """등록된 Runner 이름 목록 (정렬)."""
        return sorted(self._runners.keys())

    @property
    def runner_count(self) -> int:
        return len(self._runners)

    def get(self, name: str) -> StrategyRunner | None:
        return self._runners.get(name)

    async def run_all(self, tickers: list[str]) -> dict[str, list[PredictionSignal]]:
        """등록된 모든 Runner를 병렬 실행하고, {strategy_name: predictions} 딕셔너리를 반환한다."""
        if not self._runners:
            return {}

        names = list(self._runners.keys())
        runners = list(self._runners.values())

        async def _safe_run(runner: StrategyRunner) -> list[PredictionSignal]:
            try:
                return await runner.run(tickers)
            except Exception as exc:
                logger.error("Strategy '%s' 실행 실패: %s", runner.name, exc, exc_info=True)
                return []

        results = await asyncio.gather(*[_safe_run(r) for r in runners])
        return dict(zip(names, results))

    async def run_selected(
        self, tickers: list[str], strategy_names: list[str]
    ) -> dict[str, list[PredictionSignal]]:
        """지정된 전략만 병렬 실행한다."""
        selected: dict[str, StrategyRunner] = {}
        for name in strategy_names:
            runner = self._runners.get(name)
            if runner:
                selected[name] = runner
            else:
                logger.warning("StrategyRegistry: '%s' runner가 등록되어 있지 않아 건너뜁니다", name)

        if not selected:
            return {}

        names = list(selected.keys())
        runners = list(selected.values())

        async def _safe_run(runner: StrategyRunner) -> list[PredictionSignal]:
            try:
                return await runner.run(tickers)
            except Exception as exc:
                logger.error("Strategy '%s' 실행 실패: %s", runner.name, exc, exc_info=True)
                return []

        results = await asyncio.gather(*[_safe_run(r) for r in runners])
        return dict(zip(names, results))
