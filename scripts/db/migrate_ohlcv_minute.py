"""
scripts/db/migrate_ohlcv_minute.py -- ohlcv_minute 테이블 생성 마이그레이션

tick_data를 1분 단위로 집계한 분봉 테이블을 생성한다.
월별 RANGE 파티셔닝(2026-04 ~ 2026-06 초기 3개월).
idempotent (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).

사용법:
  python scripts/db/migrate_ohlcv_minute.py            # 실행
  python scripts/db/migrate_ohlcv_minute.py --dry-run   # 미리보기
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

from src.utils.db_client import get_pool  # noqa: E402
from src.utils.logging import get_logger, setup_logging  # noqa: E402

setup_logging()
logger = get_logger(__name__)


# ── DDL ─────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv_minute (
    instrument_id  VARCHAR(20)    NOT NULL,
    bucket_at      TIMESTAMPTZ    NOT NULL,
    open           INTEGER        NOT NULL,
    high           INTEGER        NOT NULL,
    low            INTEGER        NOT NULL,
    close          INTEGER        NOT NULL,
    volume         BIGINT         NOT NULL DEFAULT 0,
    trade_count    INTEGER        NOT NULL DEFAULT 0,
    vwap           NUMERIC(15,2)  NOT NULL DEFAULT 0,
    PRIMARY KEY (instrument_id, bucket_at)
) PARTITION BY RANGE (bucket_at);
"""

PARTITION_SQLS = [
    """CREATE TABLE IF NOT EXISTS ohlcv_minute_2026_04 PARTITION OF ohlcv_minute
        FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');""",
    """CREATE TABLE IF NOT EXISTS ohlcv_minute_2026_05 PARTITION OF ohlcv_minute
        FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');""",
    """CREATE TABLE IF NOT EXISTS ohlcv_minute_2026_06 PARTITION OF ohlcv_minute
        FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');""",
]

INDEX_SQLS = [
    "CREATE INDEX IF NOT EXISTS idx_ohlcv_minute_bucket ON ohlcv_minute (bucket_at);",
    "CREATE INDEX IF NOT EXISTS idx_ohlcv_minute_instrument ON ohlcv_minute (instrument_id, bucket_at);",
]


# ── 마이그레이션 실행 ────────────────────────────────────────────


async def migrate(*, dry_run: bool = False) -> None:
    """ohlcv_minute 테이블 + 파티션 + 인덱스를 생성한다."""
    pool = await get_pool()

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        logger.info("  ohlcv_minute 테이블 CREATE TABLE IF NOT EXISTS 예정")
        logger.info("  파티션 3개월분 (2026-04 ~ 2026-06) 생성 예정")
        logger.info("  인덱스 2개 생성 예정")
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. 메인 테이블 생성
            await conn.execute(CREATE_TABLE_SQL)
            logger.info("ohlcv_minute 테이블 생성 완료 (IF NOT EXISTS)")

            # 2. 파티션 생성
            for sql in PARTITION_SQLS:
                await conn.execute(sql)
            logger.info("ohlcv_minute 파티션 3개월분 생성 완료")

            # 3. 인덱스 생성
            for sql in INDEX_SQLS:
                await conn.execute(sql)
            logger.info("ohlcv_minute 인덱스 2개 생성 완료")


# ── 검증 ────────────────────────────────────────────────────────


async def verify() -> None:
    """마이그레이션 결과를 확인한다."""
    pool = await get_pool()

    # 테이블 존재 여부
    exists = await pool.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'ohlcv_minute'
        )
        """
    )
    logger.info("[verify] ohlcv_minute 테이블 존재: %s", exists)

    # 파티션 수
    partitions = await pool.fetch(
        """
        SELECT inhrelid::regclass AS partition_name
        FROM pg_inherits
        WHERE inhparent = 'ohlcv_minute'::regclass
        ORDER BY inhrelid::regclass::text
        """
    )
    logger.info("[verify] 파티션 %d개:", len(partitions))
    for p in partitions:
        logger.info("    - %s", p["partition_name"])

    # 인덱스 수
    indexes = await pool.fetch(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'ohlcv_minute'
        ORDER BY indexname
        """
    )
    logger.info("[verify] 인덱스 %d개:", len(indexes))
    for idx in indexes:
        logger.info("    - %s", idx["indexname"])


# ── 메인 ────────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> None:
    await migrate(dry_run=args.dry_run)
    if not args.dry_run:
        await verify()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ohlcv_minute 테이블 생성 마이그레이션 (1분봉 집계)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s              # 실행
  %(prog)s --dry-run     # 미리보기
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 DB 변경 없이 미리보기만 출력",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
