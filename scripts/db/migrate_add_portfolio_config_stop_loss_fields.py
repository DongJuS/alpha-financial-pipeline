"""
scripts/db/migrate_add_portfolio_config_stop_loss_fields.py
    -- portfolio_config 에 Phase A 리스크 파라미터 3 컬럼 추가

Sell Strategy Phase A (Hard Stop-Loss) 의 mandate 파라미터를 코드 하드코딩에서
DB config 로 이관. `docs/plans/SELL_STRATEGY_PHASES.md` §3-3 스펙 그대로.

- individual_stop_loss_pct     INTEGER NOT NULL DEFAULT 7
    Layer 1 개별 종목 손절 임계 %.
    `_check_rule_based_exits` 의 기존 하드코딩 `stop_loss_pct=-3.0` 를 대체.
    Mandate 재해석 상 -3% → -7% 완화 (§3-1-1).

- take_profit_pct              INTEGER NOT NULL DEFAULT 5
    Take profit 임계 %.
    `_check_rule_based_exits` 의 기존 하드코딩 `take_profit_pct=5.0` 를 대체.
    Phase B 부분 매도도 재사용.

- portfolio_drawdown_limit_pct INTEGER NOT NULL DEFAULT 8
    Layer 2 포트폴리오 drawdown 임계 %.
    신규 method `_check_portfolio_drawdown` 이 소비.

기존 `daily_loss_limit_pct=3` 은 그대로 (Layer 3).

Idempotent (ADD COLUMN IF NOT EXISTS).

사용법:
  python scripts/db/migrate_add_portfolio_config_stop_loss_fields.py            # 실행
  python scripts/db/migrate_add_portfolio_config_stop_loss_fields.py --dry-run  # 미리보기
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

ADD_INDIVIDUAL_STOP_LOSS_SQL = """
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS individual_stop_loss_pct INTEGER NOT NULL DEFAULT 7
        CHECK (individual_stop_loss_pct BETWEEN 1 AND 100);
"""

ADD_TAKE_PROFIT_SQL = """
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS take_profit_pct INTEGER NOT NULL DEFAULT 5
        CHECK (take_profit_pct BETWEEN 1 AND 100);
"""

ADD_PORTFOLIO_DD_SQL = """
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS portfolio_drawdown_limit_pct INTEGER NOT NULL DEFAULT 8
        CHECK (portfolio_drawdown_limit_pct BETWEEN 1 AND 100);
"""

COMMENT_INDIVIDUAL_STOP_LOSS_SQL = """
COMMENT ON COLUMN portfolio_config.individual_stop_loss_pct IS
    'Phase A Layer 1 개별 종목 손절 임계 %%. _check_rule_based_exits 가 소비. Mandate default 7.';
"""

COMMENT_TAKE_PROFIT_SQL = """
COMMENT ON COLUMN portfolio_config.take_profit_pct IS
    'Take profit 임계 %%. _check_rule_based_exits (Phase A) + Phase B 부분 매도가 소비. Mandate default 5.';
"""

COMMENT_PORTFOLIO_DD_SQL = """
COMMENT ON COLUMN portfolio_config.portfolio_drawdown_limit_pct IS
    'Phase A Layer 2 포트폴리오 drawdown 임계 %%. _check_portfolio_drawdown 이 소비. Mandate default 8.';
"""

TARGET_COLUMNS: list[str] = [
    "individual_stop_loss_pct",
    "take_profit_pct",
    "portfolio_drawdown_limit_pct",
]


# ── 마이그레이션 실행 ────────────────────────────────────────────


async def migrate(*, dry_run: bool = False) -> None:
    """portfolio_config 에 Phase A 리스크 파라미터 3 컬럼을 추가한다."""
    pool = await get_pool()

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        logger.info("  ADD COLUMN individual_stop_loss_pct     INTEGER NOT NULL DEFAULT 7")
        logger.info("  ADD COLUMN take_profit_pct              INTEGER NOT NULL DEFAULT 5")
        logger.info("  ADD COLUMN portfolio_drawdown_limit_pct INTEGER NOT NULL DEFAULT 8")
        logger.info("  각 컬럼 CHECK BETWEEN 1 AND 100")
        logger.info("  COMMENT ON COLUMN × 3")
        existing = await pool.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'portfolio_config'
              AND column_name = ANY($1::text[])
            ORDER BY column_name
            """,
            TARGET_COLUMNS,
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
            await conn.execute(ADD_INDIVIDUAL_STOP_LOSS_SQL)
            logger.info("individual_stop_loss_pct INTEGER NOT NULL DEFAULT 7 컬럼 추가 완료")

            await conn.execute(ADD_TAKE_PROFIT_SQL)
            logger.info("take_profit_pct INTEGER NOT NULL DEFAULT 5 컬럼 추가 완료")

            await conn.execute(ADD_PORTFOLIO_DD_SQL)
            logger.info("portfolio_drawdown_limit_pct INTEGER NOT NULL DEFAULT 8 컬럼 추가 완료")

            await conn.execute(COMMENT_INDIVIDUAL_STOP_LOSS_SQL)
            await conn.execute(COMMENT_TAKE_PROFIT_SQL)
            await conn.execute(COMMENT_PORTFOLIO_DD_SQL)
            logger.info("COMMENT ON COLUMN × 3 반영 완료")


# ── 검증 ────────────────────────────────────────────────────────


async def verify() -> None:
    """portfolio_config 스키마에 3 컬럼이 존재하고 단일 행 default 값이 반영됐는지 확인."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'portfolio_config'
          AND column_name = ANY($1::text[])
        ORDER BY column_name
        """,
        TARGET_COLUMNS,
    )

    expected = set(TARGET_COLUMNS)
    found = {r["column_name"] for r in rows}

    if not expected.issubset(found):
        missing = expected - found
        logger.error("[verify] 누락 컬럼: %s", ", ".join(sorted(missing)))
        sys.exit(1)

    logger.info("\n=== portfolio_config 리스크 파라미터 컬럼 검증 ===")
    header = f"  {'column':<32} {'type':<10} {'nullable':<10} {'default':<10}"
    logger.info(header)
    logger.info("  " + "-" * len(header))
    for r in rows:
        logger.info(
            "  %-32s %-10s %-10s %-10s",
            r["column_name"],
            r["data_type"],
            r["is_nullable"],
            r["column_default"] or "",
        )

    row = await pool.fetchrow(
        """
        SELECT individual_stop_loss_pct, take_profit_pct, portfolio_drawdown_limit_pct,
               daily_loss_limit_pct
        FROM portfolio_config
        LIMIT 1
        """
    )
    if row is None:
        logger.warning("[verify] portfolio_config 에 행이 없습니다 (초기 seed 미실행).")
        return

    logger.info(
        "\n  현재 값 (단일 행): individual=%s%%, take_profit=%s%%, "
        "portfolio_dd=%s%%, daily_loss=%s%%",
        row["individual_stop_loss_pct"],
        row["take_profit_pct"],
        row["portfolio_drawdown_limit_pct"],
        row["daily_loss_limit_pct"],
    )


# ── 메인 ────────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> None:
    await migrate(dry_run=args.dry_run)
    if not args.dry_run:
        await verify()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="portfolio_config 에 Phase A 리스크 파라미터 3 컬럼 추가",
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
