"""
scripts/db/migrate_backtest_widen_win_rate.py
    -- backtest_runs.win_rate NUMERIC(6,4) → NUMERIC(7,4) 로 확장

배경
- 승률(win_rate) 은 % 단위 저장. 매매 1건이 이익이면 win_rate=100.0.
- 현재 NUMERIC(6,4) 는 최대 99.9999 만 저장 가능. 100.0 → overflow.
- 실제 관측: 2026-07-07 소급 실행 시 000660.KS (SK하이닉스), 079550.KS
  (LIG넥스원, 재실행 케이스) 저장 실패:
    asyncpg.exceptions.NumericValueOutOfRangeError: numeric field overflow
    DETAIL: A field with precision 6, scale 4 must round to an absolute
        value less than 10^2.
  → 저장 자체가 실패해 UI 그래프 조회 탭에 표시 안 됨.

확장 방침
- NUMERIC(6,4) → NUMERIC(7,4): 최대 999.9999. 100.0 여유 있게 담음.
- 다른 NUMERIC(6,4) 컬럼 (commission_rate_pct, tax_rate_pct) 은 실 값이
  0~1 범위 (0.015, 0.18 등) 라 100 을 넘을 일 없음. 이번 확장 대상 아님
  (사용자 원칙: 필요한 만큼만 확장).

Idempotent
- ALTER COLUMN TYPE 은 이미 목표 폭 이상이면 no-op (PG 12+).
- information_schema 로 사전 조회 → dry-run 프리뷰 지원.

사용법
  python scripts/db/migrate_backtest_widen_win_rate.py             # 실행
  python scripts/db/migrate_backtest_widen_win_rate.py --dry-run   # 미리보기
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

ALTER_WIN_RATE_SQL = """
ALTER TABLE backtest_runs ALTER COLUMN win_rate TYPE NUMERIC(7,4);
"""

COMMENT_WIN_RATE_SQL = """
COMMENT ON COLUMN backtest_runs.win_rate IS
    '백테스트 승률 %% (0~100). 매매 1건이 이익이면 100.0 저장 가능하도록 NUMERIC(7,4). 2026-07-07 000660.KS overflow 이슈로 6→7 확장.';
"""


async def _current_precision(pool) -> tuple[int | None, int | None]:
    row = await pool.fetchrow(
        """
        SELECT numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_name = 'backtest_runs' AND column_name = 'win_rate'
        """
    )
    if row is None:
        return None, None
    return row["numeric_precision"], row["numeric_scale"]


async def _run(dry_run: bool) -> None:
    """backtest_runs.win_rate 를 NUMERIC(7,4) 로 확장한다."""
    pool = await get_pool()
    precision, scale = await _current_precision(pool)

    if precision is None:
        logger.error("backtest_runs.win_rate 컬럼을 찾을 수 없습니다.")
        raise SystemExit(1)

    logger.info("현재 win_rate 컬럼 폭: NUMERIC(%s,%s)", precision, scale)

    if precision >= 7:
        logger.info("이미 NUMERIC(%s,%s) — 변경 없이 종료 (idempotent).", precision, scale)
        return

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        logger.info("  ALTER TABLE backtest_runs ALTER COLUMN win_rate TYPE NUMERIC(7,4)")
        logger.info("  COMMENT ON COLUMN backtest_runs.win_rate")
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(ALTER_WIN_RATE_SQL)
            logger.info(
                "win_rate 컬럼 NUMERIC(%s,%s) → NUMERIC(7,4) 확장 완료",
                precision, scale,
            )

            await conn.execute(COMMENT_WIN_RATE_SQL)
            logger.info("COMMENT ON COLUMN 반영 완료")

    new_p, new_s = await _current_precision(pool)
    logger.info("최종 win_rate 컬럼 폭: NUMERIC(%s,%s)", new_p, new_s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 실행하지 않고 계획만 표시",
    )
    args = parser.parse_args()
    asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
