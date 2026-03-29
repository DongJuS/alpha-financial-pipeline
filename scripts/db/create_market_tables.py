"""
scripts/db/create_market_tables.py — 시장 데이터 신규 테이블 생성

markets + instruments + ohlcv_daily (파티셔닝) 생성.
기존 market_data / ticker_master는 건드리지 않음 (나중에 마이그레이션).

사용법:
  python scripts/db/create_market_tables.py
  python scripts/db/create_market_tables.py --drop  # 기존 테이블 삭제 후 재생성
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.utils.db_client import execute, get_pool
from src.utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


DDL_MARKETS = """
CREATE TABLE IF NOT EXISTS markets (
    market_id      VARCHAR(10) PRIMARY KEY,
    name           TEXT        NOT NULL,
    country        VARCHAR(3)  NOT NULL,
    timezone       VARCHAR(30) NOT NULL,
    currency       VARCHAR(5)  NOT NULL,
    open_time      TIME,
    close_time     TIME,
    data_source    VARCHAR(20) NOT NULL,
    is_active      BOOLEAN DEFAULT true,
    created_at     TIMESTAMPTZ DEFAULT now()
);
"""

SEED_MARKETS = """
INSERT INTO markets (market_id, name, country, timezone, currency, open_time, close_time, data_source)
VALUES
    ('KOSPI',  '코스피',           'KR', 'Asia/Seoul',       'KRW', '09:00', '15:30', 'fdr'),
    ('KOSDAQ', '코스닥',           'KR', 'Asia/Seoul',       'KRW', '09:00', '15:30', 'fdr'),
    ('NYSE',   '뉴욕증권거래소',    'US', 'America/New_York', 'USD', '09:30', '16:00', 'fdr'),
    ('NASDAQ', '나스닥',           'US', 'America/New_York', 'USD', '09:30', '16:00', 'fdr')
ON CONFLICT (market_id) DO NOTHING;
"""

DDL_INSTRUMENTS = """
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id  VARCHAR(20)  PRIMARY KEY,
    raw_code       VARCHAR(15)  NOT NULL,
    name           TEXT         NOT NULL,
    name_en        TEXT,
    market_id      VARCHAR(10)  NOT NULL REFERENCES markets(market_id),
    sector         TEXT,
    industry       TEXT,
    asset_type     VARCHAR(10)  NOT NULL DEFAULT 'stock',
    isin           VARCHAR(15),
    listed_at      DATE,
    delisted_at    DATE,
    market_cap     BIGINT,
    total_shares   BIGINT,
    is_active      BOOLEAN      NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ  DEFAULT now(),
    updated_at     TIMESTAMPTZ  DEFAULT now(),

    CONSTRAINT uq_instruments_market_code UNIQUE (market_id, raw_code)
);

CREATE INDEX IF NOT EXISTS idx_instruments_market    ON instruments(market_id, is_active);
CREATE INDEX IF NOT EXISTS idx_instruments_sector    ON instruments(market_id, sector) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_instruments_asset     ON instruments(asset_type, is_active);
CREATE INDEX IF NOT EXISTS idx_instruments_raw_code  ON instruments(raw_code);
"""

DDL_OHLCV_DAILY = """
CREATE TABLE IF NOT EXISTS ohlcv_daily (
    instrument_id  VARCHAR(20)   NOT NULL,
    traded_at      DATE          NOT NULL,
    open           NUMERIC(15,4) NOT NULL,
    high           NUMERIC(15,4) NOT NULL,
    low            NUMERIC(15,4) NOT NULL,
    close          NUMERIC(15,4) NOT NULL,
    volume         BIGINT        NOT NULL,
    amount         BIGINT,
    change_pct     NUMERIC(8,4),
    market_cap     BIGINT,
    turnover_ratio NUMERIC(8,4),
    foreign_ratio  NUMERIC(5,2),
    adj_close      NUMERIC(15,4),

    PRIMARY KEY (instrument_id, traded_at)
) PARTITION BY RANGE (traded_at);

CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_instrument
    ON ohlcv_daily (instrument_id, traded_at DESC);
"""


def _partition_ddl(year: int) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS ohlcv_daily_{year} "
        f"PARTITION OF ohlcv_daily "
        f"FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01');"
    )


async def create_tables(drop: bool = False) -> None:
    pool = await get_pool()

    if drop:
        logger.warning("기존 테이블 삭제 중...")
        async with pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS ohlcv_daily CASCADE")
            await conn.execute("DROP TABLE IF EXISTS instruments CASCADE")
            await conn.execute("DROP TABLE IF EXISTS markets CASCADE")
        logger.info("기존 테이블 삭제 완료")

    async with pool.acquire() as conn:
        # 1. markets
        await conn.execute(DDL_MARKETS)
        await conn.execute(SEED_MARKETS)
        logger.info("markets 테이블 생성 + 시드 완료")

        # 2. instruments
        await conn.execute(DDL_INSTRUMENTS)
        logger.info("instruments 테이블 생성 완료")

        # 3. ohlcv_daily (파티션 테이블)
        await conn.execute(DDL_OHLCV_DAILY)

        # 연도별 파티션: 2010~2027
        for year in range(2010, 2028):
            await conn.execute(_partition_ddl(year))

        # default 파티션
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS ohlcv_daily_default "
            "PARTITION OF ohlcv_daily DEFAULT;"
        )
        logger.info("ohlcv_daily 파티셔닝 테이블 생성 완료 (2010~2027 + default)")

    # 확인
    async with pool.acquire() as conn:
        for tbl in ["markets", "instruments", "ohlcv_daily"]:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                tbl,
            )
            count = await conn.fetchval(f"SELECT count(*) FROM {tbl}") if exists else 0
            logger.info("  %s: %s (%d rows)", tbl, "✓" if exists else "✗", count)


def main():
    parser = argparse.ArgumentParser(description="시장 데이터 테이블 생성")
    parser.add_argument("--drop", action="store_true", help="기존 테이블 삭제 후 재생성")
    args = parser.parse_args()
    asyncio.run(create_tables(drop=args.drop))


if __name__ == "__main__":
    main()
