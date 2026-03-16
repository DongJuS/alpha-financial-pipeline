"""
src/agents/strategy_b_runner.py — Strategy B StrategyRunner 어댑터

StrategyBConsensus를 래핑하여 StrategyRunner 프로토콜을 구현한다.
StrategyBConsensus.run()이 이미 list[PredictionSignal]을 반환하므로
name 속성만 추가하면 프로토콜이 완성된다.
"""
from __future__ import annotations

from src.agents.strategy_b_consensus import StrategyBConsensus
from src.db.models import PredictionSignal
from src.utils.logging import get_logger

logger = get_logger(__name__)


class StrategyBRunner:
    """
    Strategy B (Consensus/Debate) StrategyRunner 구현.

    StrategyBConsensus.run()을 직접 위임한다.
    """

    name: str = "B"

    def __init__(
        self,
        max_rounds: int | None = None,
        consensus_threshold: float | None = None,
    ) -> None:
        self._consensus = StrategyBConsensus(
            max_rounds=max_rounds,
            consensus_threshold=consensus_threshold,
        )

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        """주어진 티커에 대해 토론 기반 합의 신호를 생성합니다."""
        if not tickers:
            return []

        try:
            logger.info("StrategyBRunner: 토론 시작 (%d종목)", len(tickers))
            signals = await self._consensus.run(tickers)
            logger.info("StrategyBRunner: 토론 완료 (%d신호)", len(signals))
            return signals
        except Exception as e:
            logger.error("StrategyBRunner: 토론 실패: %s", e, exc_info=True)
            return []
