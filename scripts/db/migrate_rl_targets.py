"""
scripts/db/migrate_rl_targets.py -- rl_targets 테이블 생성 + 기존 rl_policies backfill

rl_targets 테이블을 CREATE TABLE IF NOT EXISTS 로 생성한 뒤,
기존 rl_policies 에 등록된 instrument_id 를 rl_targets 에 backfill 한다.
idempotent (ON CONFLICT DO NOTHING).

사용법:
  python scripts/db/migrate_rl_targets.py            # 실행
  python scripts/db/migrate_rl_targets.py --dry-run   # 미리보기
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
CREATE TABLE IF NOT EXISTS rl_targets (
    instrument_id   VARCHAR(20)   NOT NULL REFERENCES instruments(instrument_id),
    data_scope      VARCHAR(10)   NOT NULL DEFAULT 'daily'
                    CHECK (data_scope IN ('daily', 'tick', 'combined')),
    is_active       BOOLEAN       NOT NULL DEFAULT true,
    memo            TEXT,
    added_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_rl_targets_active
    ON rl_targets(is_active) WHERE is_active = true;
"""

BACKFILL_SQL = """
INSERT INTO rl_targets (instrument_id)
SELECT DISTINCT instrument_id FROM rl_policies
ON CONFLICT DO NOTHING;
"""


# ── 마이그레이션 실행 ────────────────────────────────────────────


async def migrate(*, dry_run: bool = False) -> int:
    """rl_targets 테이블 생성 + rl_policies backfill 을 실행한다."""
    pool = await get_pool()

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        # rl_policies 에서 backfill 대상 미리보기
        rows = await pool.fetch(
            "SELECT DISTINCT instrument_id FROM rl_policies ORDER BY instrument_id"
        )
        logger.info("  rl_targets 테이블 CREATE TABLE IF NOT EXISTS 예정")
        logger.info("  idx_rl_targets_active 인덱스 생성 예정")
        logger.info("  backfill 대상: %d개 instrument_id", len(rows))
        for r in rows:
            logger.info("    - %s", r["instrument_id"])
        return 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. 테이블 생성
            await conn.execute(CREATE_TABLE_SQL)
            logger.info("rl_targets 테이블 생성 완료 (IF NOT EXISTS)")

            # 2. 인덱스 생성
            await conn.execute(CREATE_INDEX_SQL)
            logger.info("idx_rl_targets_active 인덱스 생성 완료")

            # 3. rl_policies backfill
            result = await conn.execute(BACKFILL_SQL)
            # result 형식: "INSERT 0 N"
            count = int(result.split()[-1]) if result else 0
            logger.info("rl_policies -> rl_targets backfill 완료: %d건 INSERT", count)

    return count


# ── 검증 ────────────────────────────────────────────────────────


async def verify() -> None:
    """마이그레이션 결과를 확인한다."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT instrument_id, data_scope, is_active, memo, added_at
        FROM rl_targets
        ORDER BY instrument_id
        """
    )

    if not rows:
        logger.warning("[verify] rl_targets 테이블이 비어 있습니다.")
        return

    logger.info("\n=== rl_targets 검증: %d건 ===", len(rows))
    header = f"  {'instrument_id':<20} {'data_scope':<12} {'active':>6} {'memo':<20}"
    logger.info(header)
    logger.info("  " + "-" * len(header))
    for r in rows:
        logger.info(
            "  %-20s %-12s %6s %-20s",
            r["instrument_id"],
            r["data_scope"],
            str(r["is_active"]),
            r["memo"] or "",
        )


# ── 메인 ────────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> None:
    await migrate(dry_run=args.dry_run)
    if not args.dry_run:
        await verify()


def main():
    parser = argparse.ArgumentParser(
        description="rl_targets 테이블 생성 + rl_policies backfill 마이그레이션",
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
