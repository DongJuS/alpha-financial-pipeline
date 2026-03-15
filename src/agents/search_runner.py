"""
src/agents/search_runner.py — SearchRunner (Strategy S)

SearchRunner는 ResearchPortfolioManager를 래핑하는 StrategyRunner 구현체이다.
검색/스크래핑 기반 신호 생성을 Orchestrator의 N-way 블렌딩에 참여시킨다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.db.models import PredictionSignal
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.agents.research_portfolio_manager import ResearchPortfolioManager

logger = get_logger(__name__)


class SearchRunner:
    """
    Strategy S (Search/Scraping) StrategyRunner 구현.

    ResearchPortfolioManager를 래핑하여 StrategyRunner 프로토콜을 구현한다.
    """

    name: str = "S"

    def __init__(self, research_portfolio_manager: ResearchPortfolioManager) -> None:
        """
        Args:
            research_portfolio_manager: ResearchPortfolioManager 인스턴스
        """
        self.research_portfolio_manager = research_portfolio_manager

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        """
        주어진 티커 리스트에 대해 검색 기반 예측 신호를 생성한다.

        Args:
            tickers: 종목코드 리스트

        Returns:
            PredictionSignal 리스트
        """
        if not tickers:
            return []

        try:
            logger.info("SearchRunner: 리서치 사이클 시작 (%d종목)", len(tickers))
            signals = await self.research_portfolio_manager.run_research_cycle(tickers)
            logger.info("SearchRunner: 리서치 사이클 완료 (%d신호)", len(signals))
            return signals
        except Exception as e:
            logger.error("SearchRunner: 리서치 실패: %s", e, exc_info=True)
            return []
