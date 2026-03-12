"""
src/agents/strategy_a_tournament.py — Strategy A 토너먼트 실행기

- Predictor 5개 인스턴스를 병렬 실행
- 과거 예측 결과를 실제 시세로 백필/채점
- 최근 N일 롤링 정확도로 우승 인스턴스 선정
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.predictor import PredictorAgent
from src.db.queries import upsert_tournament_score
from src.utils.db_client import execute, fetch, fetchrow
from src.utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@dataclass
class PredictorProfile:
    agent_id: str
    model: str
    persona: str


PROFILES = [
    PredictorProfile("predictor_1", "claude-3-5-sonnet-latest", "가치 투자형"),
    PredictorProfile("predictor_2", "claude-3-5-sonnet-latest", "기술적 분석형"),
    PredictorProfile("predictor_3", "gpt-4o-mini", "모멘텀형"),
    PredictorProfile("predictor_4", "gpt-4o-mini", "역추세형"),
    PredictorProfile("predictor_5", "gemini-1.5-pro", "거시경제형"),
]


class StrategyATournament:
    async def run_predictors(self, tickers: list[str]) -> dict[str, int]:
        async def _run(profile: PredictorProfile) -> tuple[str, int]:
            agent = PredictorAgent(
                agent_id=profile.agent_id,
                strategy="A",
                llm_model=profile.model,
                persona=profile.persona,
            )
            predictions = await agent.run_once(tickers=tickers, limit=len(tickers))
            return profile.agent_id, len(predictions)

        results = await asyncio.gather(*[_run(p) for p in PROFILES])
        return {agent_id: count for agent_id, count in results}

    async def backfill_outcomes(self, target_date: date) -> int:
        """
        predictions.was_correct / actual_close를 market_data 일봉 기준으로 채웁니다.
        """
        rows = await fetch(
            """
            SELECT id, ticker, signal
            FROM predictions
            WHERE strategy = 'A'
              AND trading_date = $1
              AND was_correct IS NULL
            """,
            target_date,
        )
        updated = 0
        for row in rows:
            md = await fetchrow(
                """
                SELECT open, close
                FROM market_data
                WHERE ticker = $1
                  AND interval = 'daily'
                  AND (timestamp_kst AT TIME ZONE 'Asia/Seoul')::date = $2
                ORDER BY timestamp_kst DESC
                LIMIT 1
                """,
                row["ticker"],
                target_date,
            )
            if not md:
                continue

            open_price = int(md["open"])
            close_price = int(md["close"])
            if close_price > open_price:
                actual_signal = "BUY"
            elif close_price < open_price:
                actual_signal = "SELL"
            else:
                actual_signal = "HOLD"

            was_correct = row["signal"] == actual_signal
            await execute(
                """
                UPDATE predictions
                SET actual_close = $1,
                    was_correct = $2
                WHERE id = $3
                """,
                close_price,
                was_correct,
                row["id"],
            )
            updated += 1
        return updated

    async def compute_and_store_scores(self, score_date: date, rolling_days: int = 5) -> str:
        start_date_expr = f"{rolling_days} days"
        rows = await fetch(
            """
            SELECT
                agent_id,
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE was_correct = TRUE)::int AS correct
            FROM predictions
            WHERE strategy = 'A'
              AND trading_date >= CURRENT_DATE - ($1)::interval
              AND was_correct IS NOT NULL
            GROUP BY agent_id
            ORDER BY (COUNT(*) FILTER (WHERE was_correct = TRUE))::float / NULLIF(COUNT(*), 0) DESC NULLS LAST
            """,
            start_date_expr,
        )

        # 기본 우승자(초기 데이터 없음)
        winner = "predictor_1"
        if rows:
            ratios = {
                r["agent_id"]: (r["correct"] / r["total"]) if r["total"] > 0 else 0.0
                for r in rows
            }
            winner = max(ratios, key=ratios.get)

        for profile in PROFILES:
            score_row = next((r for r in rows if r["agent_id"] == profile.agent_id), None)
            correct = int(score_row["correct"]) if score_row else 0
            total = int(score_row["total"]) if score_row else 0
            await upsert_tournament_score(
                agent_id=profile.agent_id,
                llm_model=profile.model,
                persona=profile.persona,
                trading_date=score_date,
                correct=correct,
                total=total,
                is_winner=(profile.agent_id == winner),
            )

        logger.info("Strategy A 우승 인스턴스: %s", winner)
        return winner

    async def run_daily_tournament(self, tickers: list[str], scoring_date: date | None = None) -> dict:
        result_counts = await self.run_predictors(tickers=tickers)

        target_score_date = scoring_date or date.today()
        backfilled = await self.backfill_outcomes(target_score_date)
        winner = await self.compute_and_store_scores(score_date=target_score_date)

        return {
            "predictions_by_agent": result_counts,
            "outcomes_backfilled": backfilled,
            "winner_agent_id": winner,
        }


async def _main_async(args: argparse.Namespace) -> None:
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    tournament = StrategyATournament()
    result = await tournament.run_daily_tournament(tickers=tickers)
    print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy A Tournament Runner")
    parser.add_argument("--tickers", required=True, help="쉼표 구분 티커 목록")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
