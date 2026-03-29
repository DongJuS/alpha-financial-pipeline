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
from src.services.model_config import get_strategy_a_profiles
from src.utils.config import get_settings
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
    PredictorProfile("predictor_1", "claude-opus-4-6", "가치 투자형"),
    PredictorProfile("predictor_2", "claude-opus-4-6", "기술적 분석형"),
    PredictorProfile("predictor_3", "gemini-3.1-pro-preview", "모멘텀형"),
    PredictorProfile("predictor_4", "gemini-3.1-pro-preview", "역추세형"),
    PredictorProfile("predictor_5", "claude-haiku-4-5-20251001", "거시경제형"),
]


class StrategyATournament:
    def __init__(
        self,
        rolling_days: int | None = None,
        min_samples: int | None = None,
    ) -> None:
        settings = get_settings()
        default_rolling_days = settings.strategy_a_rolling_days
        default_min_samples = settings.strategy_a_min_samples
        self.rolling_days = max(
            1,
            int(rolling_days if rolling_days is not None else default_rolling_days),
        )
        self.min_samples = max(
            1,
            int(min_samples if min_samples is not None else default_min_samples),
        )

    async def _profiles(self) -> list[PredictorProfile]:
        rows = await get_strategy_a_profiles()
        profiles = [
            PredictorProfile(
                agent_id=str(row["agent_id"]),
                model=str(row["llm_model"]),
                persona=str(row["persona"]),
            )
            for row in rows
        ]
        return profiles or PROFILES

    async def run_predictors(self, tickers: list[str]) -> dict[str, int]:
        profiles = await self._profiles()

        async def _run(profile: PredictorProfile) -> tuple[str, int]:
            agent = PredictorAgent(
                agent_id=profile.agent_id,
                strategy="A",
                llm_model=profile.model,
                persona=profile.persona,
            )
            predictions = await agent.run_once(tickers=tickers, limit=len(tickers))
            return profile.agent_id, len(predictions)

        results = await asyncio.gather(*[_run(p) for p in profiles])
        return {agent_id: count for agent_id, count in results}

    async def backfill_outcomes(self, target_date: date) -> int:
        """
        predictions.was_correct / actual_close를 ohlcv_daily 일봉 기준으로 채웁니다.
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
        from src.utils.market_data import to_instrument_id
        updated = 0
        for row in rows:
            candidates = [
                to_instrument_id(row["ticker"], "KOSPI"),
                to_instrument_id(row["ticker"], "KOSDAQ"),
            ]
            md = await fetchrow(
                """
                SELECT od.open, od.close
                FROM ohlcv_daily od
                WHERE od.instrument_id = ANY($1)
                  AND od.traded_at = $2
                ORDER BY od.traded_at DESC
                LIMIT 1
                """,
                candidates,
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

    @staticmethod
    def _select_winner(rows: list[dict], min_samples: int) -> str:
        scored: list[tuple[float, int, str]] = []
        for row in rows:
            agent_id = str(row["agent_id"])
            total = int(row["total"] or 0)
            correct = int(row["correct"] or 0)
            if total < min_samples or total <= 0:
                continue
            ratio = correct / total
            scored.append((ratio, total, agent_id))

        if not scored:
            return "predictor_1"

        # ratio 우선, 동률이면 샘플 수(total) 우선, 그래도 동률이면 agent_id 오름차순
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return scored[0][2]

    async def compute_and_store_scores(
        self,
        score_date: date,
        rolling_days: int | None = None,
        min_samples: int | None = None,
    ) -> str:
        days = max(1, int(rolling_days if rolling_days is not None else self.rolling_days))
        required_samples = max(1, int(min_samples if min_samples is not None else self.min_samples))
        lookback_days = max(days - 1, 0)
        rows = await fetch(
            """
            SELECT
                agent_id,
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE was_correct = TRUE)::int AS correct
            FROM predictions
            WHERE strategy = 'A'
              AND trading_date BETWEEN ($1::date - ($2::int * INTERVAL '1 day'))::date AND $1::date
              AND was_correct IS NOT NULL
            GROUP BY agent_id
            ORDER BY agent_id
            """,
            score_date,
            lookback_days,
        )

        winner = self._select_winner(rows, min_samples=required_samples)
        profiles = await self._profiles()

        for profile in profiles:
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

        logger.info(
            "Strategy A 우승 인스턴스: %s (score_date=%s, rolling_days=%s, min_samples=%s)",
            winner,
            score_date.isoformat(),
            days,
            required_samples,
        )
        return winner

    async def run_daily_tournament(
        self,
        tickers: list[str],
        scoring_date: date | None = None,
        rolling_days: int | None = None,
        min_samples: int | None = None,
    ) -> dict:
        result_counts = await self.run_predictors(tickers=tickers)

        target_score_date = scoring_date or date.today()
        backfilled = await self.backfill_outcomes(target_score_date)
        winner = await self.compute_and_store_scores(
            score_date=target_score_date,
            rolling_days=rolling_days,
            min_samples=min_samples,
        )

        return {
            "predictions_by_agent": result_counts,
            "outcomes_backfilled": backfilled,
            "winner_agent_id": winner,
        }


async def _main_async(args: argparse.Namespace) -> None:
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    tournament = StrategyATournament(
        rolling_days=args.rolling_days,
        min_samples=args.min_samples,
    )
    result = await tournament.run_daily_tournament(
        tickers=tickers,
        rolling_days=args.rolling_days,
        min_samples=args.min_samples,
    )
    print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy A Tournament Runner")
    parser.add_argument("--tickers", required=True, help="쌍표 구분 티커 목록")
    parser.add_argument("--rolling-days", type=int, default=None, help="점수 롤링 의도우 일수")
    parser.add_argument("--min-samples", type=int, default=None, help="우승자 선정을 위한 최소 채점 샘플 수")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
