"""
src/agents/ranking_calculator.py — 일별 랭킹 계산기

매일 장 마감 후 ohlcv_daily + instruments + stock_master를 기반으로
시가총액, 거래량, 거래대금, 상승률, 하락률 랭킹을 계산합니다.

사용법:
    python -m src.agents.ranking_calculator
    python -m src.agents.ranking_calculator --ranking-type market_cap
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, DailyRanking
from src.db.marketplace_queries import upsert_daily_rankings
from src.utils.db_client import fetch
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import (
    KEY_RANKINGS,
    TTL_RANKINGS,
    get_redis,
    set_heartbeat,
)
from src.db.queries import insert_heartbeat

setup_logging()
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")


class RankingCalculator:
    """일별 사전 계산 랭킹 계산기."""

    def __init__(self, agent_id: str = "ranking_calculator") -> None:
        self.agent_id = agent_id

    async def _beat(self, status: str, last_action: str, metrics: dict) -> None:
        """에이전트 heartbeat 기록."""
        await set_heartbeat(self.agent_id)
        await insert_heartbeat(
            AgentHeartbeatRecord(
                agent_id=self.agent_id,
                status=status,
                last_action=last_action,
                metrics=metrics,
            )
        )

    async def calculate_market_cap_ranking(
        self,
        ranking_date: Optional[date] = None,
        limit: int = 50,
    ) -> list[DailyRanking]:
        """시가총액 랭킹을 계산합니다."""
        if ranking_date is None:
            ranking_date = datetime.now(KST).date()

        rows = await fetch(
            """
            SELECT sm.ticker, sm.name, sm.market_cap,
                   COALESCE(od.change_pct, 0) AS change_pct
            FROM stock_master sm
            LEFT JOIN LATERAL (
                SELECT od.change_pct
                FROM ohlcv_daily od
                JOIN instruments i ON od.instrument_id = i.instrument_id
                WHERE i.raw_code = sm.ticker
                ORDER BY od.traded_at DESC
                LIMIT 1
            ) od ON TRUE
            WHERE sm.is_active = TRUE
              AND sm.is_etf = FALSE AND sm.is_etn = FALSE
              AND sm.market_cap IS NOT NULL AND sm.market_cap > 0
            ORDER BY sm.market_cap DESC
            LIMIT $1
            """,
            limit,
        )

        rankings: list[DailyRanking] = []
        for rank, row in enumerate(rows, start=1):
            rankings.append(
                DailyRanking(
                    ranking_date=ranking_date,
                    ranking_type="market_cap",
                    rank=rank,
                    ticker=row["ticker"],
                    name=row["name"],
                    value=float(row["market_cap"]) if row["market_cap"] else None,
                    change_pct=float(row["change_pct"]) if row["change_pct"] else None,
                )
            )

        logger.info("시가총액 랭킹 계산 완료: %d건", len(rankings))
        return rankings

    async def calculate_volume_ranking(
        self,
        ranking_date: Optional[date] = None,
        limit: int = 50,
    ) -> list[DailyRanking]:
        """거래량 랭킹을 계산합니다."""
        if ranking_date is None:
            ranking_date = datetime.now(KST).date()

        rows = await fetch(
            """
            SELECT i.raw_code AS ticker, sm.name,
                   SUM(od.volume) AS total_volume,
                   COALESCE(od.change_pct, 0) AS change_pct
            FROM ohlcv_daily od
            JOIN instruments i ON od.instrument_id = i.instrument_id
            LEFT JOIN stock_master sm ON i.raw_code = sm.ticker
            WHERE od.traded_at = $1
              AND sm.is_active = TRUE
              AND sm.is_etf = FALSE AND sm.is_etn = FALSE
            GROUP BY i.raw_code, sm.name, od.change_pct
            ORDER BY total_volume DESC
            LIMIT $2
            """,
            ranking_date,
            limit,
        )

        rankings: list[DailyRanking] = []
        for rank, row in enumerate(rows, start=1):
            rankings.append(
                DailyRanking(
                    ranking_date=ranking_date,
                    ranking_type="volume",
                    rank=rank,
                    ticker=row["ticker"],
                    name=row["name"],
                    value=float(row["total_volume"]) if row["total_volume"] else None,
                    change_pct=float(row["change_pct"]) if row["change_pct"] else None,
                )
            )

        logger.info("거래량 랭킹 계산 완료: %d건", len(rankings))
        return rankings

    async def calculate_turnover_ranking(
        self,
        ranking_date: Optional[date] = None,
        limit: int = 50,
    ) -> list[DailyRanking]:
        """거래대금 랭킹을 계산합니다."""
        if ranking_date is None:
            ranking_date = datetime.now(KST).date()

        rows = await fetch(
            """
            SELECT i.raw_code AS ticker, sm.name,
                   SUM(od.close * od.volume) AS total_turnover,
                   COALESCE(od.change_pct, 0) AS change_pct
            FROM ohlcv_daily od
            JOIN instruments i ON od.instrument_id = i.instrument_id
            LEFT JOIN stock_master sm ON i.raw_code = sm.ticker
            WHERE od.traded_at = $1
              AND sm.is_active = TRUE
              AND sm.is_etf = FALSE AND sm.is_etn = FALSE
            GROUP BY i.raw_code, sm.name, od.change_pct
            ORDER BY total_turnover DESC
            LIMIT $2
            """,
            ranking_date,
            limit,
        )

        rankings: list[DailyRanking] = []
        for rank, row in enumerate(rows, start=1):
            rankings.append(
                DailyRanking(
                    ranking_date=ranking_date,
                    ranking_type="turnover",
                    rank=rank,
                    ticker=row["ticker"],
                    name=row["name"],
                    value=float(row["total_turnover"]) if row["total_turnover"] else None,
                    change_pct=float(row["change_pct"]) if row["change_pct"] else None,
                )
            )

        logger.info("거래대금 랭킹 계산 완료: %d건", len(rankings))
        return rankings

    async def calculate_gainer_ranking(
        self,
        ranking_date: Optional[date] = None,
        limit: int = 50,
    ) -> list[DailyRanking]:
        """상승률 랭킹을 계산합니다."""
        if ranking_date is None:
            ranking_date = datetime.now(KST).date()

        rows = await fetch(
            """
            SELECT i.raw_code AS ticker, sm.name, od.change_pct
            FROM ohlcv_daily od
            JOIN instruments i ON od.instrument_id = i.instrument_id
            LEFT JOIN stock_master sm ON i.raw_code = sm.ticker
            WHERE od.traded_at = $1
              AND od.change_pct > 0
              AND sm.is_active = TRUE
              AND sm.is_etf = FALSE AND sm.is_etn = FALSE
            ORDER BY od.change_pct DESC
            LIMIT $2
            """,
            ranking_date,
            limit,
        )

        rankings: list[DailyRanking] = []
        for rank, row in enumerate(rows, start=1):
            rankings.append(
                DailyRanking(
                    ranking_date=ranking_date,
                    ranking_type="gainer",
                    rank=rank,
                    ticker=row["ticker"],
                    name=row["name"],
                    change_pct=float(row["change_pct"]),
                )
            )

        logger.info("상승률 랭킹 계산 완료: %d건", len(rankings))
        return rankings

    async def calculate_loser_ranking(
        self,
        ranking_date: Optional[date] = None,
        limit: int = 50,
    ) -> list[DailyRanking]:
        """하락률 랭킹을 계산합니다."""
        if ranking_date is None:
            ranking_date = datetime.now(KST).date()

        rows = await fetch(
            """
            SELECT i.raw_code AS ticker, sm.name, od.change_pct
            FROM ohlcv_daily od
            JOIN instruments i ON od.instrument_id = i.instrument_id
            LEFT JOIN stock_master sm ON i.raw_code = sm.ticker
            WHERE od.traded_at = $1
              AND od.change_pct < 0
              AND sm.is_active = TRUE
              AND sm.is_etf = FALSE AND sm.is_etn = FALSE
            ORDER BY od.change_pct ASC
            LIMIT $2
            """,
            ranking_date,
            limit,
        )

        rankings: list[DailyRanking] = []
        for rank, row in enumerate(rows, start=1):
            rankings.append(
                DailyRanking(
                    ranking_date=ranking_date,
                    ranking_type="loser",
                    rank=rank,
                    ticker=row["ticker"],
                    name=row["name"],
                    change_pct=float(row["change_pct"]),
                )
            )

        logger.info("하락률 랭킹 계산 완료: %d건", len(rankings))
        return rankings

    async def calculate_all_rankings(self, ranking_date: Optional[date] = None) -> int:
        """모든 랭킹을 계산하고 저장합니다."""
        if ranking_date is None:
            ranking_date = datetime.now(KST).date()

        all_rankings: list[DailyRanking] = []

        market_cap = await self.calculate_market_cap_ranking(ranking_date)
        all_rankings.extend(market_cap)

        volume = await self.calculate_volume_ranking(ranking_date)
        all_rankings.extend(volume)

        turnover = await self.calculate_turnover_ranking(ranking_date)
        all_rankings.extend(turnover)

        gainer = await self.calculate_gainer_ranking(ranking_date)
        all_rankings.extend(gainer)

        loser = await self.calculate_loser_ranking(ranking_date)
        all_rankings.extend(loser)

        if not all_rankings:
            logger.warning("계산된 랭킹이 없습니다.")
            return 0

        saved = await upsert_daily_rankings(all_rankings)

        # Redis 캐시 갱신 (각 랭킹 타입별)
        await self._refresh_rankings_cache(all_rankings)

        await self._beat(
            status="healthy",
            last_action=f"랭킹 계산 완료 ({saved}건)",
            metrics={
                "total": saved,
                "market_cap": len(market_cap),
                "volume": len(volume),
                "turnover": len(turnover),
                "gainer": len(gainer),
                "loser": len(loser),
            },
        )

        logger.info("전체 랭킹 계산 완료: %d건", saved)
        return saved

    async def calculate_sector_heatmap(
        self, ranking_date: Optional[date] = None
    ) -> dict:
        """섹터별 평균 등락률 히트맵을 계산합니다."""
        if ranking_date is None:
            ranking_date = datetime.now(KST).date()

        rows = await fetch(
            """
            SELECT sm.sector,
                   COUNT(*) AS stock_count,
                   COALESCE(AVG(od.change_pct), 0) AS avg_change_pct,
                   COALESCE(SUM(sm.market_cap), 0) AS total_market_cap,
                   COALESCE(SUM(od.volume), 0) AS total_volume
            FROM stock_master sm
            LEFT JOIN LATERAL (
                SELECT od.change_pct, od.volume
                FROM ohlcv_daily od
                JOIN instruments i ON od.instrument_id = i.instrument_id
                WHERE i.raw_code = sm.ticker
                ORDER BY od.traded_at DESC
                LIMIT 1
            ) od ON TRUE
            WHERE sm.is_active = TRUE
              AND sm.is_etf = FALSE AND sm.is_etn = FALSE
              AND sm.sector IS NOT NULL AND sm.sector != ''
            GROUP BY sm.sector
            ORDER BY total_market_cap DESC
            """
        )

        heatmap = []
        for row in rows:
            heatmap.append({
                "sector": row["sector"],
                "stock_count": int(row["stock_count"]),
                "avg_change_pct": round(float(row["avg_change_pct"]), 2),
                "total_market_cap": int(row["total_market_cap"]),
                "total_volume": int(row["total_volume"]),
            })

        # Redis 캐시 저장
        redis = await get_redis()
        await redis.set(
            "redis:cache:sector_heatmap",
            json.dumps(heatmap, ensure_ascii=False),
            ex=300,
        )

        logger.info("섹터 히트맵 계산 완료: %d개 섹터", len(heatmap))
        return {"data": heatmap}

    async def _refresh_rankings_cache(self, rankings: list[DailyRanking]) -> None:
        """랭킹 Redis 캐시를 갱신합니다."""
        redis = await get_redis()
        by_type: dict[str, list[dict]] = {}

        for ranking in rankings:
            ranking_type = ranking.ranking_type
            if ranking_type not in by_type:
                by_type[ranking_type] = []
            by_type[ranking_type].append(ranking.model_dump(mode="json"))

        for ranking_type, items in by_type.items():
            key = KEY_RANKINGS.format(ranking_type=ranking_type)
            await redis.set(
                key,
                json.dumps(items, ensure_ascii=False, default=str),
                ex=TTL_RANKINGS,
            )

        logger.info("Redis 랭킹 캐시 갱신: %s", list(by_type.keys()))


async def _main_async(args: argparse.Namespace) -> None:
    calculator = RankingCalculator()

    if args.ranking_type:
        ranking_date = (
            date.fromisoformat(args.ranking_date) if args.ranking_date else None
        )
        if args.ranking_type == "market_cap":
            rankings = await calculator.calculate_market_cap_ranking(ranking_date)
        elif args.ranking_type == "volume":
            rankings = await calculator.calculate_volume_ranking(ranking_date)
        elif args.ranking_type == "turnover":
            rankings = await calculator.calculate_turnover_ranking(ranking_date)
        elif args.ranking_type == "gainer":
            rankings = await calculator.calculate_gainer_ranking(ranking_date)
        elif args.ranking_type == "loser":
            rankings = await calculator.calculate_loser_ranking(ranking_date)
        else:
            logger.error("알 수 없는 ranking_type: %s", args.ranking_type)
            return
        await upsert_daily_rankings(rankings)
    elif args.sector_heatmap:
        ranking_date = (
            date.fromisoformat(args.ranking_date) if args.ranking_date else None
        )
        await calculator.calculate_sector_heatmap(ranking_date)
    else:
        await calculator.calculate_all_rankings()


def main() -> None:
    parser = argparse.ArgumentParser(description="일별 랭킹 계산기")
    parser.add_argument(
        "--ranking-type",
        choices=["market_cap", "volume", "turnover", "gainer", "loser"],
        default=None,
        help="특정 랭킹 타입만 계산",
    )
    parser.add_argument(
        "--sector-heatmap",
        action="store_true",
        help="섹터 히트맵만 계산",
    )
    parser.add_argument(
        "--ranking-date",
        type=str,
        default=None,
        help="특정 날짜 (YYYY-MM-DD)",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
