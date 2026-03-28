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
from src.db.models import MacroIndicator
from src.db.marketplace_queries import upsert_macro_indicators
from src.utils.config import has_kis_credentials
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
        self._missing_credentials_logged = False

    async def collect_once(self) -> dict:
        """KOSPI/KOSDAQ 지수를 한 번 수집하고 Redis/PostgreSQL에 저장합니다.

        Returns:
            성공 여부 및 수집 데이터를 포함한 딕셔너리
        """
        if not has_kis_credentials(self.client.settings, self.client.account_scope):
            if not self._missing_credentials_logged:
                logger.warning("KIS 자격증명이 없어 지수 수집을 건너뜁니다.")
                self._missing_credentials_logged = True
            return {
                "success": True,
                "skipped": True,
                "reason": "missing_kis_credentials",
                "timestamp_kst": datetime.now(KST).isoformat(),
            }

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

            # PostgreSQL macro_indicators 테이블에 저장 (시계열 기록)
            today = datetime.now(KST).date()
            macro_records = [
                MacroIndicator(
                    category="index",
                    symbol="KOSPI",
                    name="KOSPI",
                    value=kospi_data["value"],
                    change_pct=kospi_data["change_pct"],
                    previous_close=kospi_data.get("previous_close"),
                    snapshot_date=today,
                    source="kis",
                ),
                MacroIndicator(
                    category="index",
                    symbol="KOSDAQ",
                    name="KOSDAQ",
                    value=kosdaq_data["value"],
                    change_pct=kosdaq_data["change_pct"],
                    previous_close=kosdaq_data.get("previous_close"),
                    snapshot_date=today,
                    source="kis",
                ),
            ]
            await upsert_macro_indicators(macro_records)

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
