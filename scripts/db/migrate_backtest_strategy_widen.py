"""
scripts/db/migrate_backtest_strategy_widen.py
    -- backtest_runs.strategy 컬럼을 VARCHAR(10) → VARCHAR(50) 로 확장

배경
- `backtest_runs.strategy` 는 지금까지 "RL" / "A" / "B" / "BLEND" 4 종만
  저장되어 VARCHAR(10) 로 충분했음.
- 이제 RL 백테스트 저장 시 profile 세부를 포함해 "RL (dreamer_v3)",
  "RL (tabular_q_v2_momentum)" 등 최대 ~25자 문자열을 저장한다.
- UI /rl-trading '그래프 조회' 탭 알고리즘 필터가 세부 알고리즘을 구분
  할 수 있게 된다. 사용자 요청 반영.

Idempotent
- ALTER COLUMN TYPE 은 이미 목표 폭 이상이면 no-op (PG 12+).
- information_schema 로 사전 조회 → dry-run 프리뷰 지원.

사용법
  python scripts/db/migrate_backtest_strategy_widen.py             # 실행
  python scripts/db/migrate_backtest_strategy_widen.py --dry-run   # 미리보기
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

ALTER_STRATEGY_SQL = """
ALTER TABLE backtest_runs ALTER COLUMN strategy TYPE VARCHAR(50);
"""

COMMENT_STRATEGY_SQL = """
COMMENT ON COLUMN backtest_runs.strategy IS
    '백테스트 전략. RL 은 "RL (profile_name)" 형식 (예: "RL (dreamer_v3)"). A/B/BLEND 는 그대로.';
"""


async def _current_length(pool) -> int | None:
    row = await pool.fetchrow(
        """
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_name = 'backtest_runs' AND column_name = 'strategy'
        """
    )
    if row is None:
        return None
    return row["character_maximum_length"]


async def migrate(*, dry_run: bool = False) -> None:
    """backtest_runs.strategy 를 VARCHAR(50) 로 확장한다."""
    pool = await get_pool()
    current = await _current_length(pool)

    if current is None:
        logger.error("backtest_runs.strategy 컬럼을 찾을 수 없습니다.")
        raise SystemExit(1)

    logger.info("현재 strategy 컬럼 폭: VARCHAR(%s)", current)

    if current >= 50:
        logger.info("이미 VARCHAR(%s) — 변경 없이 종료 (idempotent).", current)
        return

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        logger.info("  ALTER TABLE backtest_runs ALTER COLUMN strategy TYPE VARCHAR(50)")
        logger.info("  COMMENT ON COLUMN backtest_runs.strategy")
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(ALTER_STRATEGY_SQL)
            logger.info("strategy 컬럼 VARCHAR(%s) → VARCHAR(50) 확장 완료", current)

            await conn.execute(COMMENT_STRATEGY_SQL)
            logger.info("COMMENT ON COLUMN 반영 완료")

    # 결과 검증
    new_len = await _current_length(pool)
    logger.info("최종 strategy 컬럼 폭: VARCHAR(%s)", new_len)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 실행하지 않고 계획만 표시",
    )
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
