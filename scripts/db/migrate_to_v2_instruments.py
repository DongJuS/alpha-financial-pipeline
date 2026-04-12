"""
scripts/db/migrate_to_v2_instruments.py — 라이브 DB를 v2 instruments 스키마로 마이그레이션

PR #147 에서 코드가 변경되었지만 라이브 DB 스키마는 아직 old 상태일 수 있다.
이 스크립트는 idempotent 하게 old → new 스키마를 변환한다.

변환 내용:
    1. stock_master → krx_stock_master 리네임 (인덱스 포함)
    2. instruments 테이블 경량화 (메타데이터 컬럼 제거, raw_code → ticker 리네임)
    3. trading_universe 테이블 신설

사용법:
    python scripts/db/migrate_to_v2_instruments.py              # 실행
    python scripts/db/migrate_to_v2_instruments.py --dry-run    # SQL만 출력 (실행 안 함)
    python scripts/db/migrate_to_v2_instruments.py --check      # 현재 스키마 상태 확인
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]

# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼: 스키마 조회
# ─────────────────────────────────────────────────────────────────────────────

_CHECK_TABLE_EXISTS = """
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = $1
)
"""

_CHECK_COLUMN_EXISTS = """
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2
)
"""

_CHECK_CONSTRAINT_EXISTS = """
SELECT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_schema = 'public' AND constraint_name = $1
)
"""

_CHECK_INDEX_EXISTS = """
SELECT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public' AND indexname = $1
)
"""


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: stock_master → krx_stock_master 리네임
# ─────────────────────────────────────────────────────────────────────────────

async def migrate_stock_master(conn: asyncpg.Connection, *, dry_run: bool) -> None:
    """stock_master 테이블을 krx_stock_master로 리네임한다."""
    old_exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "stock_master")
    new_exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "krx_stock_master")

    if new_exists and not old_exists:
        logger.info("[stock_master] 이미 krx_stock_master로 리네임됨 — skip")
        return

    if not old_exists and not new_exists:
        logger.warning("[stock_master] stock_master도 krx_stock_master도 존재하지 않음 — skip")
        return

    if old_exists and new_exists:
        logger.warning(
            "[stock_master] stock_master와 krx_stock_master 모두 존재. "
            "데이터 충돌 위험 — 수동 확인 필요. skip"
        )
        return

    # old_exists=True, new_exists=False → 리네임 진행
    sqls = [
        "ALTER TABLE stock_master RENAME TO krx_stock_master",
        # 인덱스 리네임 (존재하는 경우에만)
        "ALTER INDEX IF EXISTS idx_stock_master_market RENAME TO idx_krx_stock_master_market",
        "ALTER INDEX IF EXISTS idx_stock_master_sector RENAME TO idx_krx_stock_master_sector",
        "ALTER INDEX IF EXISTS idx_stock_master_tier RENAME TO idx_krx_stock_master_tier",
        "ALTER INDEX IF EXISTS idx_stock_master_etf RENAME TO idx_krx_stock_master_etf",
    ]

    for sql in sqls:
        if dry_run:
            logger.info("[DRY-RUN] %s;", sql)
        else:
            await conn.execute(sql)
            logger.info("[stock_master] 실행: %s", sql)

    if not dry_run:
        logger.info("[stock_master] krx_stock_master 리네임 완료")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: instruments 경량화
# ─────────────────────────────────────────────────────────────────────────────

# OLD에만 있고 NEW에 없는 컬럼들
_INSTRUMENTS_DROP_COLUMNS = [
    "name", "name_en", "sector", "industry", "asset_type",
    "isin", "listed_at", "delisted_at", "market_cap", "total_shares",
]

# OLD 인덱스 (NEW에서 제거된 것들)
_INSTRUMENTS_DROP_INDEXES = [
    "idx_instruments_market",
    "idx_instruments_sector",
    "idx_instruments_asset",
    "idx_instruments_raw_code",
]


async def migrate_instruments(conn: asyncpg.Connection, *, dry_run: bool) -> None:
    """instruments 테이블을 v2 경량 스키마로 변환한다."""
    exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "instruments")
    if not exists:
        logger.warning("[instruments] 테이블 없음 — skip")
        return

    # 2-a. raw_code → ticker 리네임 (raw_code가 존재하면)
    has_raw_code = await conn.fetchval(_CHECK_COLUMN_EXISTS, "instruments", "raw_code")
    has_ticker = await conn.fetchval(_CHECK_COLUMN_EXISTS, "instruments", "ticker")

    if has_raw_code and not has_ticker:
        sql = "ALTER TABLE instruments RENAME COLUMN raw_code TO ticker"
        if dry_run:
            logger.info("[DRY-RUN] %s;", sql)
        else:
            await conn.execute(sql)
            logger.info("[instruments] raw_code → ticker 리네임 완료")
    elif has_ticker:
        logger.info("[instruments] ticker 컬럼 이미 존재 — 리네임 skip")
    else:
        logger.warning("[instruments] raw_code도 ticker도 없음 — 리네임 skip")

    # 2-b. 메타데이터 컬럼 삭제
    for col in _INSTRUMENTS_DROP_COLUMNS:
        col_exists = await conn.fetchval(_CHECK_COLUMN_EXISTS, "instruments", col)
        if not col_exists:
            logger.info("[instruments] 컬럼 '%s' 이미 없음 — skip", col)
            continue
        sql = f"ALTER TABLE instruments DROP COLUMN {col}"
        if dry_run:
            logger.info("[DRY-RUN] %s;", sql)
        else:
            await conn.execute(sql)
            logger.info("[instruments] 컬럼 '%s' 삭제 완료", col)

    # 2-c. OLD unique constraint 삭제 + NEW unique constraint 추가
    old_constraint = await conn.fetchval(_CHECK_CONSTRAINT_EXISTS, "uq_instruments_market_code")
    if old_constraint:
        sql = "ALTER TABLE instruments DROP CONSTRAINT uq_instruments_market_code"
        if dry_run:
            logger.info("[DRY-RUN] %s;", sql)
        else:
            await conn.execute(sql)
            logger.info("[instruments] 구 constraint uq_instruments_market_code 삭제 완료")

    new_constraint = await conn.fetchval(_CHECK_CONSTRAINT_EXISTS, "uq_instruments_market_ticker")
    if not new_constraint:
        sql = (
            "ALTER TABLE instruments "
            "ADD CONSTRAINT uq_instruments_market_ticker UNIQUE (market_id, ticker)"
        )
        if dry_run:
            logger.info("[DRY-RUN] %s;", sql)
        else:
            await conn.execute(sql)
            logger.info("[instruments] 신규 constraint uq_instruments_market_ticker 추가 완료")
    else:
        logger.info("[instruments] uq_instruments_market_ticker 이미 존재 — skip")

    # 2-d. OLD 인덱스 삭제
    for idx_name in _INSTRUMENTS_DROP_INDEXES:
        idx_exists = await conn.fetchval(_CHECK_INDEX_EXISTS, idx_name)
        if not idx_exists:
            logger.info("[instruments] 인덱스 '%s' 이미 없음 — skip", idx_name)
            continue
        sql = f"DROP INDEX {idx_name}"
        if dry_run:
            logger.info("[DRY-RUN] %s;", sql)
        else:
            await conn.execute(sql)
            logger.info("[instruments] 인덱스 '%s' 삭제 완료", idx_name)

    # 2-e. NEW 인덱스 추가
    new_indexes = [
        ("idx_instruments_active", "CREATE INDEX idx_instruments_active ON instruments(is_active) WHERE is_active = true"),
        ("idx_instruments_ticker", "CREATE INDEX idx_instruments_ticker ON instruments(ticker)"),
    ]
    for idx_name, sql in new_indexes:
        idx_exists = await conn.fetchval(_CHECK_INDEX_EXISTS, idx_name)
        if idx_exists:
            logger.info("[instruments] 인덱스 '%s' 이미 존재 — skip", idx_name)
            continue
        if dry_run:
            logger.info("[DRY-RUN] %s;", sql)
        else:
            await conn.execute(sql)
            logger.info("[instruments] 인덱스 '%s' 생성 완료", idx_name)


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: trading_universe 테이블 생성
# ─────────────────────────────────────────────────────────────────────────────

_TRADING_UNIVERSE_DDL = """
CREATE TABLE IF NOT EXISTS trading_universe (
    account_scope   VARCHAR(10)  NOT NULL REFERENCES trading_accounts(account_scope),
    instrument_id   VARCHAR(20)  NOT NULL REFERENCES instruments(instrument_id),
    priority        INTEGER      NOT NULL DEFAULT 0,
    max_weight_pct  NUMERIC(5,2),
    added_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    memo            TEXT,
    PRIMARY KEY (account_scope, instrument_id)
)
"""


async def create_trading_universe(conn: asyncpg.Connection, *, dry_run: bool) -> None:
    """trading_universe 테이블을 생성한다 (IF NOT EXISTS)."""
    exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "trading_universe")
    if exists:
        logger.info("[trading_universe] 이미 존재 — skip")
        return

    # FK 의존성 확인
    accounts_exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "trading_accounts")
    instruments_exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "instruments")

    if not accounts_exists:
        logger.error("[trading_universe] trading_accounts 테이블 없음 — 생성 불가")
        return
    if not instruments_exists:
        logger.error("[trading_universe] instruments 테이블 없음 — 생성 불가")
        return

    if dry_run:
        logger.info("[DRY-RUN] %s;", _TRADING_UNIVERSE_DDL.strip())
    else:
        await conn.execute(_TRADING_UNIVERSE_DDL)
        logger.info("[trading_universe] 테이블 생성 완료")


# ─────────────────────────────────────────────────────────────────────────────
# --check: 현재 스키마 상태 리포트
# ─────────────────────────────────────────────────────────────────────────────

async def check_schema(conn: asyncpg.Connection) -> None:
    """현재 DB 스키마 상태를 진단하고 출력한다."""
    print("\n=== Schema Check Report ===\n")

    # 1. stock_master vs krx_stock_master
    sm_exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "stock_master")
    ksm_exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "krx_stock_master")
    if sm_exists and not ksm_exists:
        print("[stock_master]     OLD (stock_master 존재) -> 리네임 필요")
    elif ksm_exists and not sm_exists:
        print("[stock_master]     OK  (krx_stock_master 존재)")
    elif sm_exists and ksm_exists:
        print("[stock_master]     WARN: 둘 다 존재 — 수동 확인 필요")
    else:
        print("[stock_master]     MISSING: 어느 쪽도 없음")

    # 2. instruments 컬럼 상태
    inst_exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "instruments")
    if not inst_exists:
        print("[instruments]      MISSING: 테이블 없음")
    else:
        has_raw_code = await conn.fetchval(_CHECK_COLUMN_EXISTS, "instruments", "raw_code")
        has_ticker = await conn.fetchval(_CHECK_COLUMN_EXISTS, "instruments", "ticker")

        if has_raw_code:
            print("[instruments]      OLD: raw_code 컬럼 존재 -> ticker로 리네임 필요")
        elif has_ticker:
            print("[instruments]      OK:  ticker 컬럼 존재")
        else:
            print("[instruments]      WARN: raw_code도 ticker도 없음")

        metadata_cols = [c for c in _INSTRUMENTS_DROP_COLUMNS
                         if await conn.fetchval(_CHECK_COLUMN_EXISTS, "instruments", c)]
        if metadata_cols:
            print(f"[instruments]      OLD: 메타데이터 컬럼 잔존 -> 삭제 필요: {', '.join(metadata_cols)}")
        else:
            print("[instruments]      OK:  메타데이터 컬럼 모두 제거됨")

        # constraint 상태
        old_cst = await conn.fetchval(_CHECK_CONSTRAINT_EXISTS, "uq_instruments_market_code")
        new_cst = await conn.fetchval(_CHECK_CONSTRAINT_EXISTS, "uq_instruments_market_ticker")
        if old_cst:
            print("[instruments]      OLD: uq_instruments_market_code 존재 -> 교체 필요")
        if new_cst:
            print("[instruments]      OK:  uq_instruments_market_ticker 존재")
        elif not old_cst and not new_cst:
            print("[instruments]      WARN: unique constraint 없음")

        # 인덱스 상태
        for idx_name in _INSTRUMENTS_DROP_INDEXES:
            idx_exists = await conn.fetchval(_CHECK_INDEX_EXISTS, idx_name)
            if idx_exists:
                print(f"[instruments]      OLD: 인덱스 '{idx_name}' 존재 -> 삭제 필요")
        for idx_name in ["idx_instruments_active", "idx_instruments_ticker"]:
            idx_exists = await conn.fetchval(_CHECK_INDEX_EXISTS, idx_name)
            if idx_exists:
                print(f"[instruments]      OK:  인덱스 '{idx_name}' 존재")
            else:
                print(f"[instruments]      NEED: 인덱스 '{idx_name}' 없음 -> 생성 필요")

    # 3. trading_universe
    tu_exists = await conn.fetchval(_CHECK_TABLE_EXISTS, "trading_universe")
    if tu_exists:
        print("[trading_universe] OK:  테이블 존재")
    else:
        print("[trading_universe] NEED: 테이블 없음 -> 생성 필요")

    print("\n=== End ===\n")


# ─────────────────────────────────────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────────────────────────────────────

async def run_migration(*, dry_run: bool) -> None:
    """마이그레이션을 순서대로 실행한다."""
    logger.info("DB 연결 중: %s", DATABASE_URL.split("@")[-1])
    conn: asyncpg.Connection = await asyncpg.connect(DATABASE_URL)

    try:
        logger.info("=== v2 instruments 마이그레이션 시작 (dry_run=%s) ===", dry_run)

        # Step 1: stock_master → krx_stock_master
        await migrate_stock_master(conn, dry_run=dry_run)

        # Step 2: instruments 경량화
        await migrate_instruments(conn, dry_run=dry_run)

        # Step 3: trading_universe 생성
        await create_trading_universe(conn, dry_run=dry_run)

        logger.info("=== v2 instruments 마이그레이션 완료 ===")

    finally:
        await conn.close()


async def run_check() -> None:
    """현재 스키마 상태만 확인한다."""
    logger.info("DB 연결 중: %s", DATABASE_URL.split("@")[-1])
    conn: asyncpg.Connection = await asyncpg.connect(DATABASE_URL)

    try:
        await check_schema(conn)
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="v2 instruments 스키마 마이그레이션 (idempotent)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="SQL을 출력만 하고 실행하지 않는다.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="현재 스키마 상태만 확인하고 종료한다.",
    )
    args = parser.parse_args()

    if args.check:
        asyncio.run(run_check())
    else:
        asyncio.run(run_migration(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
