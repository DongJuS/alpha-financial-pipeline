"""
src/agents/macro_collector.py — 매크로 지표 수집기

해외지수, 환율, 원자재 등 매크로 지표를 FinanceDataReader로 수집하여
macro_indicators 테이블에 저장하고 Redis 캐시를 갱신합니다.

사용법:
    python -m src.agents.macro_collector
    python -m src.agents.macro_collector --category index
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, MacroIndicator
from src.db.marketplace_queries import upsert_macro_indicators
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import (
    KEY_MACRO,
    TTL_MACRO,
    TOPIC_ALERTS,
    get_redis,
    publish_message,
    set_heartbeat,
)
from src.db.queries import insert_heartbeat

setup_logging()
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")


# ── 매크로 지표 정의 ────────────────────────────────────────────────────────

FOREIGN_INDICES = {
    "US500": {"name": "S&P 500", "fdr_symbol": "US500"},
    "IXIC": {"name": "NASDAQ", "fdr_symbol": "IXIC"},
    "DJI": {"name": "Dow Jones", "fdr_symbol": "DJI"},
    "N225": {"name": "Nikkei 225", "fdr_symbol": "N225"},
    "HSI": {"name": "Hang Seng", "fdr_symbol": "HSI"},
    "SSEC": {"name": "Shanghai Composite", "fdr_symbol": "SSEC"},
}

CURRENCIES = {
    "USD/KRW": {"name": "달러/원", "fdr_symbol": "USD/KRW"},
    "EUR/KRW": {"name": "유로/원", "fdr_symbol": "EUR/KRW"},
    "JPY/KRW": {"name": "엔/원 (100엔)", "fdr_symbol": "JPY/KRW"},
    "CNY/KRW": {"name": "위안/원", "fdr_symbol": "CNY/KRW"},
}

COMMODITIES = {
    "GC=F": {"name": "금(Gold)", "fdr_symbol": "GC=F"},
    "CL=F": {"name": "WTI 원유", "fdr_symbol": "CL=F"},
    "HG=F": {"name": "구리(Copper)", "fdr_symbol": "HG=F"},
}


class MacroCollector:
    """해외지수/환율/원자재 매크로 지표 수집기."""

    def __init__(self, agent_id: str = "macro_collector") -> None:
        self.agent_id = agent_id

    @staticmethod
    def _load_fdr():
        import FinanceDataReader as fdr
        return fdr

    async def _beat(self, status: str, last_action: str, metrics: dict) -> None:
        await set_heartbeat(self.agent_id)
        await insert_heartbeat(
            AgentHeartbeatRecord(
                agent_id=self.agent_id,
                status=status,
                last_action=last_action,
                metrics=metrics,
            )
        )

    def _fetch_indicator(
        self,
        fdr_symbol: str,
        lookback_days: int = 5,
    ) -> Optional[tuple[float, Optional[float], Optional[float]]]:
        """
        FDR로 최신 종가, 전일대비%, 전일종가를 조회합니다.
        빈 응답이면 lookback을 점진적으로 늘려 재시도합니다.
        Returns: (value, change_pct, previous_close) or None
        """
        fdr = self._load_fdr()
        # 빈 DataFrame 응답 시 더 긴 lookback으로 최대 3회 재시도
        retry_days = [lookback_days, 14, 30]
        df = None
        for days in retry_days:
            start = (datetime.now(KST).date() - timedelta(days=days)).isoformat()
            try:
                result = fdr.DataReader(fdr_symbol, start)
                if result is not None and not result.empty:
                    df = result
                    break
                logger.debug("FDR 빈 응답 [%s] lookback=%d일 — 재시도", fdr_symbol, days)
            except Exception as e:
                logger.warning("FDR 조회 실패 [%s] lookback=%d일: %s", fdr_symbol, days, e)

        if df is None or df.empty:
            logger.warning("FDR 조회 최종 실패 [%s]: 데이터 없음", fdr_symbol)
            return None

        # 최신 행
        latest = df.iloc[-1]
        value = float(latest.get("Close", 0))
        if value == 0:
            return None

        # 전일 종가 및 변동률 계산
        previous_close = None
        change_pct = None
        if len(df) >= 2:
            prev = df.iloc[-2]
            previous_close = float(prev.get("Close", 0))
            if previous_close > 0:
                change_pct = round((value - previous_close) / previous_close * 100, 4)

        return (value, change_pct, previous_close)

    async def collect_foreign_indices(self) -> list[MacroIndicator]:
        """해외 주요 지수를 수집합니다."""
        today = datetime.now(KST).date()
        indicators: list[MacroIndicator] = []

        for symbol, info in FOREIGN_INDICES.items():
            result = await asyncio.to_thread(self._fetch_indicator, info["fdr_symbol"])
            if result is None:
                continue
            value, change_pct, prev_close = result
            indicators.append(
                MacroIndicator(
                    category="index",
                    symbol=symbol,
                    name=info["name"],
                    value=value,
                    change_pct=change_pct,
                    previous_close=prev_close,
                    snapshot_date=today,
                    source="fdr",
                )
            )

        logger.info("해외지수 수집 완료: %d/%d", len(indicators), len(FOREIGN_INDICES))
        return indicators

    async def collect_currencies(self) -> list[MacroIndicator]:
        """주요 환율을 수집합니다."""
        today = datetime.now(KST).date()
        indicators: list[MacroIndicator] = []

        for symbol, info in CURRENCIES.items():
            result = await asyncio.to_thread(self._fetch_indicator, info["fdr_symbol"])
            if result is None:
                continue
            value, change_pct, prev_close = result
            indicators.append(
                MacroIndicator(
                    category="currency",
                    symbol=symbol,
                    name=info["name"],
                    value=value,
                    change_pct=change_pct,
                    previous_close=prev_close,
                    snapshot_date=today,
                    source="fdr",
                )
            )

        logger.info("환율 수집 완료: %d/%d", len(indicators), len(CURRENCIES))
        return indicators

    async def collect_commodities(self) -> list[MacroIndicator]:
        """원자재 가격을 수집합니다."""
        today = datetime.now(KST).date()
        indicators: list[MacroIndicator] = []

        for symbol, info in COMMODITIES.items():
            result = await asyncio.to_thread(self._fetch_indicator, info["fdr_symbol"])
            if result is None:
                continue
            value, change_pct, prev_close = result
            indicators.append(
                MacroIndicator(
                    category="commodity",
                    symbol=symbol,
                    name=info["name"],
                    value=value,
                    change_pct=change_pct,
                    previous_close=prev_close,
                    snapshot_date=today,
                    source="fdr",
                )
            )

        logger.info("원자재 수집 완료: %d/%d", len(indicators), len(COMMODITIES))
        return indicators

    async def collect_all(self) -> int:
        """전체 매크로 지표를 수집합니다."""
        all_indicators: list[MacroIndicator] = []

        indices = await self.collect_foreign_indices()
        all_indicators.extend(indices)

        currencies = await self.collect_currencies()
        all_indicators.extend(currencies)

        commodities = await self.collect_commodities()
        all_indicators.extend(commodities)

        if not all_indicators:
            logger.warning("수집된 매크로 지표가 없습니다.")
            return 0

        saved = await upsert_macro_indicators(all_indicators)

        # Redis 캐시 갱신 (카테고리별)
        await self._refresh_macro_cache(all_indicators)

        # Redis Pub/Sub으로 매크로 변동 이벤트 발행
        await self._publish_macro_alert(all_indicators)

        await self._beat(
            status="healthy",
            last_action=f"매크로 지표 수집 완료 ({saved}건)",
            metrics={
                "total": saved,
                "indices": len(indices),
                "currencies": len(currencies),
                "commodities": len(commodities),
            },
        )
        logger.info("매크로 지표 전체 수집 완료: %d건", saved)
        return saved

    async def _refresh_macro_cache(self, indicators: list[MacroIndicator]) -> None:
        """카테고리별 매크로 지표 Redis 캐시를 갱신합니다."""
        redis = await get_redis()
        by_category: dict[str, list[dict]] = {}
        for ind in indicators:
            cat = ind.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(ind.model_dump(mode="json"))

        for category, items in by_category.items():
            key = KEY_MACRO.format(category=category)
            await redis.set(
                key,
                json.dumps(items, ensure_ascii=False, default=str),
                ex=TTL_MACRO,
            )
        logger.info("Redis 매크로 캐시 갱신: %s", list(by_category.keys()))

    async def _publish_macro_alert(self, indicators: list[MacroIndicator]) -> None:
        """매크로 지표 수집 완료 이벤트를 redis:topic:alerts 채널에 발행합니다."""
        try:
            event = {
                "type": "macro_indicators_updated",
                "timestamp": datetime.now(KST).isoformat(),
                "count": len(indicators),
                "categories": list(set(ind.category for ind in indicators)),
                "indicators": [ind.model_dump(mode="json") for ind in indicators],
            }
            await publish_message(TOPIC_ALERTS, json.dumps(event, ensure_ascii=False, default=str))
            logger.info("매크로 지표 변동 이벤트 발행: %d건", len(indicators))
        except Exception as exc:
            logger.warning("매크로 지표 이벤트 발행 실패: %s", exc)


async def _main_async(args: argparse.Namespace) -> None:
    collector = MacroCollector()
    if args.category:
        if args.category == "index":
            indicators = await collector.collect_foreign_indices()
        elif args.category == "currency":
            indicators = await collector.collect_currencies()
        elif args.category == "commodity":
            indicators = await collector.collect_commodities()
        else:
            logger.error("알 수 없는 카테고리: %s", args.category)
            return
        await upsert_macro_indicators(indicators)
    else:
        await collector.collect_all()


def main() -> None:
    parser = argparse.ArgumentParser(description="매크로 지표 수집기")
    parser.add_argument(
        "--category",
        choices=["index", "currency", "commodity"],
        default=None,
        help="특정 카테고리만 수집",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
