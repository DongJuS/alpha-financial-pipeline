"""
scripts/db/migrate_add_log_tables.py
    -- event_logs · error_logs 로그 테이블 생성

`src/utils/db_logger.py` 는 애플리케이션 이벤트/에러를 DB 에 적재하지만,
정작 대상 테이블(`event_logs`, `error_logs`)의 DDL 이 어디에도 없어서 k3s
마이그레이션 이후 두 테이블이 생성되지 않은 채 flush 가 조용히 실패해 왔다
(`db_logger._flush()` 의 except 가 debug 레벨로만 로깅). 그 결과 장애가
아무 곳에도 기록되지 않는 "조용한 고장" 상태가 됐다.

컬럼은 `db_logger.py` 의 INSERT 문 기준 그대로 정의한다.
- event_logs (ts, source, event_type, data, pod_name)
    data 는 `json.dumps(...)` 결과 → JSONB.
- error_logs (ts, source, level, logger, message, traceback, pod_name)

Idempotent (CREATE TABLE / INDEX IF NOT EXISTS — 재실행 안전).

사용법:
  python scripts/db/migrate_add_log_tables.py            # 실행
  python scripts/db/migrate_add_log_tables.py --dry-run  # 미리보기
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

CREATE_EVENT_LOGS_SQL = """
CREATE TABLE IF NOT EXISTS event_logs (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source     TEXT,
    event_type TEXT,
    data       JSONB,
    pod_name   TEXT
);
"""

CREATE_ERROR_LOGS_SQL = """
CREATE TABLE IF NOT EXISTS error_logs (
    id        BIGSERIAL PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    source    TEXT,
    level     TEXT,
    logger    TEXT,
    message   TEXT,
    traceback TEXT,
    pod_name  TEXT
);
"""

INDEX_SQLS = [
    "CREATE INDEX IF NOT EXISTS idx_event_logs_ts ON event_logs (ts DESC);",
    "CREATE INDEX IF NOT EXISTS idx_event_logs_source_ts ON event_logs (source, ts DESC);",
    "CREATE INDEX IF NOT EXISTS idx_error_logs_ts ON error_logs (ts DESC);",
    "CREATE INDEX IF NOT EXISTS idx_error_logs_source_ts ON error_logs (source, ts DESC);",
    "CREATE INDEX IF NOT EXISTS idx_error_logs_level ON error_logs (level);",
]

TABLES = ("event_logs", "error_logs")


# ── 마이그레이션 실행 ────────────────────────────────────────────


async def migrate(*, dry_run: bool = False) -> None:
    """event_logs · error_logs 테이블과 인덱스를 생성한다."""
    pool = await get_pool()

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        logger.info("  CREATE TABLE IF NOT EXISTS event_logs (...)")
        logger.info("  CREATE TABLE IF NOT EXISTS error_logs (...)")
        for sql in INDEX_SQLS:
            logger.info("  %s", sql.strip())
        existing = await pool.fetch(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename IN ('event_logs', 'error_logs')
            ORDER BY tablename
            """
        )
        found = {r["tablename"] for r in existing}
        logger.info("  기존 존재 테이블: %s", ", ".join(sorted(found)) or "없음 (fresh create)")
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(CREATE_EVENT_LOGS_SQL)
            logger.info("event_logs 테이블 생성 완료")

            await conn.execute(CREATE_ERROR_LOGS_SQL)
            logger.info("error_logs 테이블 생성 완료")

            for sql in INDEX_SQLS:
                await conn.execute(sql)
            logger.info("인덱스 %d개 반영 완료", len(INDEX_SQLS))


# ── 검증 ────────────────────────────────────────────────────────


async def verify() -> None:
    """두 로그 테이블이 존재하는지 확인한다."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename IN ('event_logs', 'error_logs')
        """
    )
    found = {r["tablename"] for r in rows}
    missing = set(TABLES) - found
    if missing:
        logger.error("[verify] 누락 테이블: %s", ", ".join(sorted(missing)))
        sys.exit(1)
    logger.info("[verify] event_logs · error_logs 확인 완료")


async def main_async(args: argparse.Namespace) -> None:
    await migrate(dry_run=args.dry_run)
    if not args.dry_run:
        await verify()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="event_logs · error_logs 로그 테이블 생성",
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
