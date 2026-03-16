"""
src/agents/index_collector.py — KOSPI/KOSDAQ 지수 수집 에이전트

KIS API를 통해 KOSPI(0001) 및 KOSDAQ(1001) 지수를 정기적으로 수집하여
Redis 캐시에 저장합니다.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from src.brokers.kis import KISPaperApiClient
from src.utils.logging import get_logger
from src.utils.redis_client import KEY_MARKET_INDEX, TTL_MARKET_INDEX, get_redis

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

# 지수 코드
KOSPI_CODE = "0001"
KOSDAQ_CODE = "1001"


class IndexCollector:
    """KOSPI/KOSDAQ 지수 수집 및 캐시 관리자"""

    def __init__(self) -> None:
        self.client = KISPaperApiClient()

    async def collect_once(self) -> dict:
        """KOSPI/KOSDAQ 지수를 한 번 수집하고 Redis에 저장합니다.

        Returns:
            성공 여부 및 수집 데이터를 포함한 딕셔너리
        """
        try:
            # KOSPI, KOSDAQ 동시 수집
            kospi_data = await self.client.fetch_index_quote(KOSPI_CODE)
            kosdaq_data = await self.client.fetch_index_quote(KOSDAQ_CODE)

            # Redis 캐시에 저장
            payload = {
                "kospi": kospi_data,
                "kosdaq": kosdaq_data,
            }
            redis = await get_redis()
            await redis.set(
                KEY_MARKET_INDEX,
                json.dumps(payload),
                ex=TTL_MARKET_INDEX,
            )

            logger.info(
                "📊 지수 수집 완료: KOSPI=%.2f(%.2f%%), KOSDAQ=%.2f(%.2f%%)",
                kospi_data["value"],
                kospi_data["change_pct"],
                kosdaq_data["value"],
                kosdaq_data["change_pct"],
            )

            return {
                "success": True,
                "kospi": kospi_data,
                "kosdaq": kosdaq_data,
                "timestamp_kst": datetime.now(KST).isoformat(),
            }

        except Exception as exc:
            logger.error("❌ 지수 수집 실패: %s", exc, exc_info=True)
            return {
                "success": False,
                "error": str(exc),
                "timestamp_kst": datetime.now(KST).isoformat(),
            }
