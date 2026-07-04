"""
scripts/db/migrate_add_broker_orders_trigger_fields.py
    -- broker_orders 에 trigger_source · trigger_snapshot 컬럼 추가

Sell Strategy Phase A (Hard Stop-Loss) 의 감사 트레이싱을 위한 컬럼 2 개를
`broker_orders` 테이블에 추가한다. `docs/plans/SELL_STRATEGY_PHASES.md` §3-3
스펙 그대로.

- trigger_source   VARCHAR(20) NULL
    'llm_signal' | 'hard_stop_L1' | 'hard_stop_L2' | 'take_profit'
    | 'time_exit' | 'rebalance'
    Phase B, C 도 동일 컬럼 재사용 (신규 컬럼 남발 회피).
- trigger_snapshot JSONB       NULL
    layer / avg_fill_price / current_price / stop_line /
    portfolio_dd_pct / daily_realized_pnl_pct / triggered_at / dry_run 등을
    dict 로 저장. 감사 재현용.

`signal_source` (누가 냈나 — 전략) 와 `trigger_source` (왜 매도가 나갔나
세부 원인) 는 병기. Hard stop 발주 예: signal_source='EXIT',
trigger_source='hard_stop_L1'.

Idempotent (ADD COLUMN IF NOT EXISTS + COMMENT ON COLUMN 재실행 안전).

사용법:
  python scripts/db/migrate_add_broker_orders_trigger_fields.py            # 실행
  python scripts/db/migrate_add_broker_orders_trigger_fields.py --dry-run  # 미리보기
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

ADD_TRIGGER_SOURCE_SQL = """
ALTER TABLE broker_orders
    ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(20) NULL;
"""

ADD_TRIGGER_SNAPSHOT_SQL = """
ALTER TABLE broker_orders
    ADD COLUMN IF NOT EXISTS trigger_snapshot JSONB NULL;
"""

COMMENT_TRIGGER_SOURCE_SQL = """
COMMENT ON COLUMN broker_orders.trigger_source IS
    'Sell strategy phase A~D trigger origin: llm_signal|hard_stop_L1|hard_stop_L2|take_profit|time_exit|rebalance';
"""

COMMENT_TRIGGER_SNAPSHOT_SQL = """
COMMENT ON COLUMN broker_orders.trigger_snapshot IS
    'JSONB — layer/pricing/state at trigger time. Audit reproducibility.';
"""


# ── 마이그레이션 실행 ────────────────────────────────────────────


async def migrate(*, dry_run: bool = False) -> None:
    """broker_orders 에 trigger_source · trigger_snapshot 컬럼을 추가한다."""
    pool = await get_pool()

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        logger.info("  ALTER TABLE broker_orders ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(20) NULL")
        logger.info("  ALTER TABLE broker_orders ADD COLUMN IF NOT EXISTS trigger_snapshot JSONB NULL")
        logger.info("  COMMENT ON COLUMN broker_orders.trigger_source")
        logger.info("  COMMENT ON COLUMN broker_orders.trigger_snapshot")
        existing = await pool.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'broker_orders'
              AND column_name IN ('trigger_source', 'trigger_snapshot')
            ORDER BY column_name
            """
        )
        if existing:
            logger.info(
                "  기존 존재 컬럼: %s",
                ", ".join(r["column_name"] for r in existing),
            )
        else:
            logger.info("  기존 존재 컬럼: 없음 (fresh add)")
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(ADD_TRIGGER_SOURCE_SQL)
            logger.info("trigger_source VARCHAR(20) NULL 컬럼 추가 완료")

            await conn.execute(ADD_TRIGGER_SNAPSHOT_SQL)
            logger.info("trigger_snapshot JSONB NULL 컬럼 추가 완료")

            await conn.execute(COMMENT_TRIGGER_SOURCE_SQL)
            await conn.execute(COMMENT_TRIGGER_SNAPSHOT_SQL)
            logger.info("COMMENT ON COLUMN 반영 완료")


# ── 검증 ────────────────────────────────────────────────────────


async def verify() -> None:
    """broker_orders 스키마에 두 컬럼이 존재하는지 확인한다."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'broker_orders'
          AND column_name IN ('trigger_source', 'trigger_snapshot')
        ORDER BY column_name
        """
    )

    expected = {"trigger_source", "trigger_snapshot"}
    found = {r["column_name"] for r in rows}

    if not expected.issubset(found):
        missing = expected - found
        logger.error("[verify] 누락 컬럼: %s", ", ".join(sorted(missing)))
        sys.exit(1)

    logger.info("\n=== broker_orders 감사 컬럼 검증 ===")
    header = f"  {'column':<20} {'type':<20} {'nullable':<10}"
    logger.info(header)
    logger.info("  " + "-" * len(header))
    for r in rows:
        logger.info(
            "  %-20s %-20s %-10s",
            r["column_name"],
            r["data_type"],
            r["is_nullable"],
        )


# ── 메인 ────────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> None:
    await migrate(dry_run=args.dry_run)
    if not args.dry_run:
        await verify()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="broker_orders 에 trigger_source · trigger_snapshot 컬럼 추가",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s              # 실행
  %(prog)s --dry-run    # 미리보기
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
