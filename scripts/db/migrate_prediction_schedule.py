"""
scripts/db/migrate_prediction_schedule.py -- prediction_schedule 테이블 생성 + 시드

prediction_schedule 테이블을 CREATE TABLE IF NOT EXISTS 로 생성한 뒤,
기본 전략(A, B, RL) 시드 데이터를 삽입한다.
idempotent (ON CONFLICT DO NOTHING).

사용법:
  python scripts/db/migrate_prediction_schedule.py            # 실행
  python scripts/db/migrate_prediction_schedule.py --dry-run   # 미리보기
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
CREATE TABLE IF NOT EXISTS prediction_schedule (
    strategy_code   VARCHAR(5)    PRIMARY KEY,
    interval_minutes INT          NOT NULL DEFAULT 30,
    is_enabled      BOOLEAN       NOT NULL DEFAULT true,
    last_run_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);
"""

SEED_SQL = """
INSERT INTO prediction_schedule (strategy_code, interval_minutes, is_enabled)
VALUES ('A', 30, true), ('B', 30, true), ('RL', 30, true)
ON CONFLICT (strategy_code) DO NOTHING;
"""


# ── 마이그레이션 실행 ────────────────────────────────────────────


async def migrate(*, dry_run: bool = False) -> int:
    """prediction_schedule 테이블 생성 + 시드 데이터를 삽입한다."""
    pool = await get_pool()

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        logger.info("  prediction_schedule 테이블 CREATE TABLE IF NOT EXISTS 예정")
        logger.info("  시드 데이터: A(30min), B(30min), RL(30min)")
        return 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. 테이블 생성
            await conn.execute(CREATE_TABLE_SQL)
            logger.info("prediction_schedule 테이블 생성 완료 (IF NOT EXISTS)")

            # 2. 시드 데이터 삽입
            result = await conn.execute(SEED_SQL)
            # result 형식: "INSERT 0 N"
            count = int(result.split()[-1]) if result else 0
            logger.info("prediction_schedule 시드 데이터 삽입 완료: %d건 INSERT", count)

    return count


# ── 검증 ────────────────────────────────────────────────────────


async def verify() -> None:
    """마이그레이션 결과를 확인한다."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT strategy_code, interval_minutes, is_enabled, last_run_at, updated_at
        FROM prediction_schedule
        ORDER BY strategy_code
        """
    )

    if not rows:
        logger.warning("[verify] prediction_schedule 테이블이 비어 있습니다.")
        return

    logger.info("\n=== prediction_schedule 검증: %d건 ===", len(rows))
    header = f"  {'strategy_code':<15} {'interval_min':>12} {'enabled':>8} {'last_run_at':<25}"
    logger.info(header)
    logger.info("  " + "-" * len(header))
    for r in rows:
        logger.info(
            "  %-15s %12d %8s %-25s",
            r["strategy_code"],
            r["interval_minutes"],
            str(r["is_enabled"]),
            str(r["last_run_at"] or ""),
        )


# ── 메인 ────────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> None:
    count = await migrate(dry_run=args.dry_run)
    if not args.dry_run:
        await verify()


def main():
    parser = argparse.ArgumentParser(
        description="prediction_schedule 테이블 생성 + 시드 데이터 마이그레이션",
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
