"""
src/agents/strategy_a_runner.py — Strategy A StrategyRunner 어댑터

StrategyATournament을 래핑하여 StrategyRunner 프로토콜을 구현한다.
토너먼트 결과에서 PredictionSignal 리스트를 추출하여 반환한다.
"""
from __future__ import annotations

from datetime import date

from src.agents.strategy_a_tournament import StrategyATournament
from src.db.models import PredictionSignal
from src.utils.logging import get_logger

logger = get_logger(__name__)


class StrategyARunner:
    """
    Strategy A (Tournament) StrategyRunner 구현.

    StrategyATournament.run_daily_tournament()를 호출하고,
    DB에 기록된 예측 결과를 PredictionSignal로 반환한다.
    """

    name: str = "A"

    def __init__(
        self,
        rolling_days: int | None = None,
        min_samples: int | None = None,
    ) -> None:
        self._tournament = StrategyATournament(
            rolling_days=rolling_days,
            min_samples=min_samples,
        )

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        """토너먼트를 실행하고, 해당 사이클에서 생성된 예측 신호를 반환합니다.

        run_daily_tournament은 내부적으로 PredictorAgent.run_once()를 호출하여
        DB에 predictions를 insert한다. 여기서는 해당 사이클의 티커별 신호를
        DB에서 조회하여 반환한다.
        """
        if not tickers:
            return []

        try:
            logger.info("StrategyARunner: 토너먼트 시작 (%d종목)", len(tickers))
            result = await self._tournament.run_daily_tournament(
                tickers=tickers,
                scoring_date=date.today(),
            )

            winner_agent_id = result.get("winner_agent_id", "predictor_1")
            predictions_count = result.get("predictions_by_agent", {})
            total = sum(predictions_count.values())

            logger.info(
                "StrategyARunner: 토너먼트 완료 (winner=%s, predictions=%d, backfilled=%d)",
                winner_agent_id,
                total,
                result.get("outcomes_backfilled", 0),
            )

            # DB에서 오늘 Strategy A의 우승 에이전트 예측을 조회
            signals = await self._fetch_winner_predictions(
                winner_agent_id=winner_agent_id,
                trading_date=date.today(),
                tickers=tickers,
            )
            return signals

        except Exception as e:
            logger.error("StrategyARunner: 토너먼트 실패: %s", e, exc_info=True)
            return []

    @staticmethod
    async def _fetch_winner_predictions(
        winner_agent_id: str,
        trading_date: date,
        tickers: list[str],
    ) -> list[PredictionSignal]:
        """우승 에이전트의 오늘 예측을 DB에서 조회합니다."""
        from src.utils.db_client import fetch

        if not tickers:
            return []

        rows = await fetch(
            """
            SELECT
                agent_id, llm_model, strategy, ticker, signal,
                confidence, target_price, stop_loss,
                reasoning_summary, debate_transcript_id, trading_date
            FROM predictions
            WHERE strategy = 'A'
              AND agent_id = $1
              AND trading_date = $2
              AND ticker = ANY($3::text[])
            ORDER BY id DESC
            """,
            winner_agent_id,
            trading_date,
            tickers,
        )

        signals: list[PredictionSignal] = []
        for row in rows:
            signals.append(
                PredictionSignal(
                    agent_id=str(row["agent_id"]),
                    llm_model=str(row["llm_model"]),
                    strategy="A",
                    ticker=str(row["ticker"]),
                    signal=str(row["signal"]),
                    confidence=float(row["confidence"]),
                    target_price=row.get("target_price"),
                    stop_loss=row.get("stop_loss"),
                    reasoning_summary=str(row.get("reasoning_summary", "")),
                    debate_transcript_id=row.get("debate_transcript_id"),
                    trading_date=row["trading_date"],
                )
            )
        return signals
