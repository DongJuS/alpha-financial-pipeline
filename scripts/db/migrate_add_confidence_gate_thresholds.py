"""
scripts/db/migrate_add_confidence_gate_thresholds.py
    -- portfolio_config 에 RL/LLM signal 실행 gate 파라미터 3 컬럼 추가

배경 (사용자 요청 2026-07-08)
- 사용자 mandate: "최대한 hold, 낙폭 클 때만 판매, 상승폭 5%+ 예상 시만 매수".
- 낙폭 gate 는 Phase A Hard Stop-Loss 로 이미 구현 (individual_stop_loss_pct).
- 매수/일반 매도 gate 미구현 → RL 이 BUY 신호 내면 confidence 무관 실행.

접근 (senior)
- "상승폭 5% 이상 예측" 은 RL/LLM 원 역할. 별도 upside predictor 만들면 순환.
- 대안: PolicyDecision.confidence 를 대리 지표로. Dreamer/SB3/tabular Q 모두
  confidence 값 반환 (0~1). 정확한 upside % 회귀 head 는 별도 리서치 스코프.
- 임계값 이상만 실행 → 사용자 원 원칙 "hold-bias" 자연 반영.

3 신규 컬럼
- buy_confidence_threshold  NUMERIC(4,3) NOT NULL DEFAULT 0.600
    BUY 실행 최소 confidence. RL/LLM signal 이 이 이상일 때만 broker 로 전달.
- sell_confidence_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.600
    SELL 실행 최소 confidence. Phase A rule-based exit (trigger_source 있음)
    은 예외 — 손절은 confidence 무관 실행.
- hold_bias_enabled         BOOLEAN NOT NULL DEFAULT TRUE
    gate on/off 스위치. FALSE 면 기존(gate 없음) 동작.

기존 hardstop 은 그대로. 신호 종류별 처리:
  - trigger_source is None (RL/LLM 직접) → confidence gate 적용
  - trigger_source is set (Phase A rule-based exit) → gate 무시, 그대로 실행

Idempotent: ADD COLUMN IF NOT EXISTS.

사용법
  python scripts/db/migrate_add_confidence_gate_thresholds.py             # 실행
  python scripts/db/migrate_add_confidence_gate_thresholds.py --dry-run   # 미리보기
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

ADD_BUY_CONFIDENCE_SQL = """
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS buy_confidence_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.600
        CHECK (buy_confidence_threshold BETWEEN 0 AND 1);
"""

ADD_SELL_CONFIDENCE_SQL = """
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS sell_confidence_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.600
        CHECK (sell_confidence_threshold BETWEEN 0 AND 1);
"""

ADD_HOLD_BIAS_SQL = """
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS hold_bias_enabled BOOLEAN NOT NULL DEFAULT TRUE;
"""

COMMENT_BUY_SQL = """
COMMENT ON COLUMN portfolio_config.buy_confidence_threshold IS
    'BUY 실행 최소 confidence (0~1). RL/LLM PolicyDecision.confidence 가 이 이상일 때만 broker 로 전달. Mandate default 0.600.';
"""

COMMENT_SELL_SQL = """
COMMENT ON COLUMN portfolio_config.sell_confidence_threshold IS
    'SELL 실행 최소 confidence (0~1). Phase A rule-based exit (trigger_source 있음) 은 예외. Mandate default 0.600.';
"""

COMMENT_HOLD_BIAS_SQL = """
COMMENT ON COLUMN portfolio_config.hold_bias_enabled IS
    'Confidence gate on/off 스위치. FALSE 면 기존(gate 없음) 동작. 사용자 mandate "최대한 hold" 반영. Default TRUE.';
"""

TARGET_COLUMNS: list[str] = [
    "buy_confidence_threshold",
    "sell_confidence_threshold",
    "hold_bias_enabled",
]


# ── 마이그레이션 실행 ────────────────────────────────────────────


async def migrate(*, dry_run: bool = False) -> None:
    """portfolio_config 에 signal confidence gate 3 컬럼을 추가한다."""
    pool = await get_pool()

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        logger.info("  ADD COLUMN buy_confidence_threshold  NUMERIC(4,3) NOT NULL DEFAULT 0.600")
        logger.info("  ADD COLUMN sell_confidence_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.600")
        logger.info("  ADD COLUMN hold_bias_enabled         BOOLEAN NOT NULL DEFAULT TRUE")
        logger.info("  각 numeric 컬럼 CHECK BETWEEN 0 AND 1")
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
            await conn.execute(ADD_BUY_CONFIDENCE_SQL)
            logger.info("buy_confidence_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.600 컬럼 추가 완료")

            await conn.execute(ADD_SELL_CONFIDENCE_SQL)
            logger.info("sell_confidence_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.600 컬럼 추가 완료")

            await conn.execute(ADD_HOLD_BIAS_SQL)
            logger.info("hold_bias_enabled BOOLEAN NOT NULL DEFAULT TRUE 컬럼 추가 완료")

            await conn.execute(COMMENT_BUY_SQL)
            await conn.execute(COMMENT_SELL_SQL)
            await conn.execute(COMMENT_HOLD_BIAS_SQL)
            logger.info("COMMENT ON COLUMN × 3 반영 완료")


# ── 검증 ────────────────────────────────────────────────────────


async def verify() -> None:
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
    logger.info("=== 검증: portfolio_config 신규 컬럼 ===")
    for r in rows:
        logger.info(
            "  %-30s %s (nullable=%s, default=%s)",
            r["column_name"],
            r["data_type"],
            r["is_nullable"],
            r["column_default"],
        )


async def _run(dry_run: bool) -> None:
    # migrate + verify 를 하나의 event loop 에서 실행. 별도 asyncio.run 으로
    # 분리하면 get_pool() 이 첫 loop 에서 만든 pool 을 두 번째 loop 에서 재
    # 사용해 ConnectionDoesNotExistError 발생.
    await migrate(dry_run=dry_run)
    if not dry_run:
        await verify()


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
