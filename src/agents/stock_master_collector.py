"""
src/agents/stock_master_collector.py — 종목 마스터 수집기

KRX 전종목(KOSPI/KOSDAQ ~2,650) + ETF/ETN(~700) 마스터 데이터를 수집하여
stock_master 테이블에 upsert하고 Redis 캐시를 갱신합니다.

사용법:
    python -m src.agents.stock_master_collector
    python -m src.agents.stock_master_collector --include-etf
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, StockMasterRecord
from src.db.marketplace_queries import (
    get_sectors,
    list_stock_master,
    update_stock_sectors,
    upsert_stock_master,
)
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import (
    KEY_ETF_LIST,
    KEY_SECTOR_MAP,
    KEY_STOCK_MASTER,
    TTL_ETF_LIST,
    TTL_SECTOR_MAP,
    TTL_STOCK_MASTER,
    get_redis,
    set_heartbeat,
)
from src.db.queries import insert_heartbeat

setup_logging()
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")


class StockMasterCollector:
    """KRX 전종목 + ETF 마스터 데이터 수집기."""

    def __init__(self, agent_id: str = "stock_master_collector") -> None:
        self.agent_id = agent_id

    @staticmethod
    def _load_fdr():
        import FinanceDataReader as fdr
        return fdr

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

    def _fetch_krx_listing(self) -> list[StockMasterRecord]:
        """FinanceDataReader로 KRX 전종목 목록을 조회합니다."""
        fdr = self._load_fdr()
        listing = fdr.StockListing("KRX")

        records: list[StockMasterRecord] = []
        for _, row in listing.iterrows():
            ticker = str(row.get("Code", "")).strip()
            if not ticker:
                continue

            name = str(row.get("Name", ticker)).strip()
            market_raw = str(row.get("Market", "")).strip().upper()
            if market_raw not in {"KOSPI", "KOSDAQ", "KONEX"}:
                continue

            # 섹터/산업군 추출 (FDR StockListing에 Sector/Industry 컬럼이 있을 경우)
            sector = None
            industry = None
            for col in ["Sector", "섹터", "IndustryCode"]:
                if col in row.index and row[col]:
                    sector = str(row[col]).strip() or None
                    break
            for col in ["Industry", "산업", "IndustryName"]:
                if col in row.index and row[col]:
                    industry = str(row[col]).strip() or None
                    break

            # 시가총액
            market_cap = None
            for col in ["Marcap", "MarketCap", "시가총액"]:
                if col in row.index:
                    try:
                        market_cap = int(float(row[col]))
                    except (ValueError, TypeError):
                        pass
                    break

            records.append(
                StockMasterRecord(
                    ticker=ticker,
                    name=name,
                    market=market_raw,  # type: ignore[arg-type]
                    sector=sector,
                    industry=industry,
                    market_cap=market_cap,
                    is_etf=False,
                    is_etn=False,
                    is_active=True,
                )
            )

        logger.info("KRX 종목 조회 완료: %d건", len(records))
        return records

    def _fetch_etf_listing(self) -> list[StockMasterRecord]:
        """FinanceDataReader로 ETF/ETN 목록을 조회합니다."""
        fdr = self._load_fdr()
        records: list[StockMasterRecord] = []

        for listing_type, is_etf, is_etn in [("ETF/KR", True, False)]:
            try:
                df = fdr.StockListing(listing_type)
                if df is None or df.empty:
                    logger.warning("%s 목록이 비어 있습니다.", listing_type)
                    continue

                for _, row in df.iterrows():
                    ticker = str(row.get("Code", row.get("Symbol", ""))).strip()
                    if not ticker:
                        continue
                    name = str(row.get("Name", ticker)).strip()

                    records.append(
                        StockMasterRecord(
                            ticker=ticker,
                            name=name,
                            market="KOSPI",  # ETF는 대부분 KOSPI 상장
                            sector="ETF",
                            is_etf=is_etf,
                            is_etn=is_etn,
                            is_active=True,
                        )
                    )
            except Exception as e:
                logger.warning("%s 목록 조회 실패: %s", listing_type, e)

        logger.info("ETF/ETN 조회 완료: %d건", len(records))
        return records

    def _fetch_market_sector_map(self) -> dict[str, tuple[Optional[str], Optional[str]]]:
        """KOSPI/KOSDAQ 개별 리스팅에서 섹터/업종 매핑을 수집합니다.

        FDR의 시장별 리스팅(KOSPI/KOSDAQ)은 KRX 통합 리스팅보다
        업종명(sector) 데이터를 더 신뢰성 있게 제공합니다.
        Returns: {ticker: (sector, industry)} dict
        """
        fdr = self._load_fdr()
        sector_map: dict[str, tuple[Optional[str], Optional[str]]] = {}

        # 섹터 컬럼 후보 (FDR 버전/마켓별로 컬럼명이 다를 수 있음)
        sector_cols = ["Sector", "업종명", "업종", "IndustryName", "IndustryCode", "섹터"]
        industry_cols = ["Industry", "업종상세", "IndustryDetail", "산업"]

        for market_code in ("KOSPI", "KOSDAQ"):
            try:
                df = fdr.StockListing(market_code)
                if df is None or df.empty:
                    continue

                col_index = set(df.columns.tolist())
                s_col = next((c for c in sector_cols if c in col_index), None)
                i_col = next((c for c in industry_cols if c in col_index), None)

                if not s_col and not i_col:
                    logger.debug("%s 리스팅에 섹터 컬럼 없음 (columns=%s)", market_code, list(df.columns))
                    continue

                for _, row in df.iterrows():
                    ticker = str(row.get("Code", row.get("Symbol", ""))).strip()
                    if not ticker:
                        continue
                    sector = str(row[s_col]).strip() if s_col and row.get(s_col) else None
                    industry = str(row[i_col]).strip() if i_col and row.get(i_col) else None
                    sector = sector or None
                    industry = industry or None
                    if sector or industry:
                        sector_map[ticker] = (sector, industry)

                logger.info("%s 섹터 맵 수집: %d건", market_code, sum(
                    1 for t in sector_map if t in sector_map
                ))
            except Exception as e:
                logger.warning("%s 섹터 맵 조회 실패: %s", market_code, e)

        return sector_map

    async def seed_sector_data(self) -> int:
        """NULL 섹터 종목에 KOSPI/KOSDAQ 리스팅 기반 섹터 데이터를 충전합니다."""
        sector_map = await asyncio.to_thread(self._fetch_market_sector_map)
        if not sector_map:
            logger.warning("섹터 맵 수집 결과 없음 — 섹터 시딩 건너뜀")
            return 0

        updated = await update_stock_sectors(sector_map)
        logger.info("섹터 데이터 시딩 완료: %d건 대상 처리", updated)
        return updated

    async def collect_stock_master(self, include_etf: bool = True) -> int:
        """전체 종목 마스터 수집 + DB upsert."""
        # KRX 전종목
        records = await asyncio.to_thread(self._fetch_krx_listing)

        # ETF/ETN 추가
        if include_etf:
            etf_records = await asyncio.to_thread(self._fetch_etf_listing)
            records.extend(etf_records)

        # DB upsert
        saved = await upsert_stock_master(records)

        # 섹터 데이터 보강 — KOSPI/KOSDAQ 리스팅에서 NULL 섹터 충전
        try:
            await self.seed_sector_data()
        except Exception as e:
            logger.warning("섹터 시딩 실패 (비필수): %s", e)

        # Redis 캐시 갱신
        await self.refresh_stock_master_cache()
        await self.refresh_sector_cache()
        if include_etf:
            await self.refresh_etf_cache()

        await self._beat(
            status="healthy",
            last_action=f"종목 마스터 수집 완료 ({saved}건)",
            metrics={"total_stocks": saved, "include_etf": include_etf},
        )
        logger.info("종목 마스터 수집 완료: %d건 upsert", saved)
        return saved

    async def refresh_stock_master_cache(self) -> None:
        """전체 종목 마스터를 Redis에 캐싱합니다."""
        stocks = await list_stock_master(limit=5000)
        redis = await get_redis()
        await redis.set(
            KEY_STOCK_MASTER,
            json.dumps(stocks, ensure_ascii=False, default=str),
            ex=TTL_STOCK_MASTER,
        )
        logger.info("Redis 종목 마스터 캐시 갱신: %d건", len(stocks))

    async def refresh_sector_cache(self) -> None:
        """섹터 → 종목 매핑을 Redis에 캐싱합니다."""
        sectors = await get_sectors()
        redis = await get_redis()
        await redis.set(
            KEY_SECTOR_MAP,
            json.dumps(sectors, ensure_ascii=False, default=str),
            ex=TTL_SECTOR_MAP,
        )
        logger.info("Redis 섹터 매핑 캐시 갱신: %d개 섹터", len(sectors))

    async def refresh_etf_cache(self) -> None:
        """ETF/ETN 목록을 Redis에 캐싱합니다."""
        etfs = await list_stock_master(is_etf=True, limit=2000)
        redis = await get_redis()
        await redis.set(
            KEY_ETF_LIST,
            json.dumps(etfs, ensure_ascii=False, default=str),
            ex=TTL_ETF_LIST,
        )
        logger.info("Redis ETF 목록 캐시 갱신: %d건", len(etfs))


async def _main_async(args: argparse.Namespace) -> None:
    collector = StockMasterCollector()
    await collector.collect_stock_master(include_etf=args.include_etf)


def main() -> None:
    parser = argparse.ArgumentParser(description="종목 마스터 수집기")
    parser.add_argument("--include-etf", action="store_true", default=True, help="ETF/ETN 포함 여부")
    parser.add_argument("--no-etf", dest="include_etf", action="store_false", help="ETF/ETN 제외")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
