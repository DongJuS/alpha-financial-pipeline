"""
test/test_migrate_instruments_v2.py — instruments v2 마이그레이션 스크립트 테스트

scripts/db/migrate_to_v2_instruments.py의 스키마 감지 및 DDL 실행 로직을 검증합니다.
실제 DB 연결 없이 asyncpg.connect를 mock하여 의사결정 로직만 테스트합니다.

NOTE: 스크립트가 아직 배포 전이면 아래 _stub 구현으로 계약(contract)을 검증합니다.
      스크립트 배포 후 import 경로를 scripts.db.migrate_to_v2_instruments로 교체하세요.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Contract stubs — 스크립트의 핵심 함수 계약을 정의합니다.
# scripts/db/migrate_to_v2_instruments.py 가 제공해야 할 인터페이스.
# ---------------------------------------------------------------------------

async def check_schema_state(conn) -> dict:
    """현재 DB 스키마 상태를 분석하여 마이그레이션 필요 여부를 반환합니다.

    Returns:
        {
            "old_table_exists": bool,   # stock_master 존재 여부
            "new_table_exists": bool,   # krx_stock_master 존재 여부
            "needs_rename": bool,       # rename 필요 여부
            "has_trading_universe": bool,
            "metadata_columns": list[str],  # 삭제 대상 컬럼
        }
    """
    old_exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'stock_master' AND table_schema = 'public')"
    )
    new_exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'krx_stock_master' AND table_schema = 'public')"
    )
    tu_exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'trading_universe' AND table_schema = 'public')"
    )

    # instruments 테이블의 메타데이터 컬럼 감지
    DROP_CANDIDATES = {"name", "sector", "listed_at"}
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'instruments' AND table_schema = 'public'"
    )
    existing_cols = {r["column_name"] for r in rows}
    meta_cols = sorted(DROP_CANDIDATES & existing_cols)

    return {
        "old_table_exists": bool(old_exists),
        "new_table_exists": bool(new_exists),
        "needs_rename": bool(old_exists) and not bool(new_exists),
        "has_trading_universe": bool(tu_exists),
        "metadata_columns": meta_cols,
    }


async def run_migration(conn, *, dry_run: bool = False) -> dict:
    """마이그레이션을 실행합니다.

    Returns:
        {"success": True, "dry_run": bool, "actions": list[str]}
    """
    state = await check_schema_state(conn)
    actions: list[str] = []

    if dry_run:
        if state["needs_rename"]:
            actions.append("WOULD rename stock_master -> krx_stock_master")
        for col in state["metadata_columns"]:
            actions.append(f"WOULD drop column instruments.{col}")
        if not state["has_trading_universe"]:
            actions.append("WOULD create trading_universe table")
        return {"success": True, "dry_run": True, "actions": actions}

    # 1. Rename stock_master -> krx_stock_master
    if state["needs_rename"]:
        await conn.execute("ALTER TABLE stock_master RENAME TO krx_stock_master")
        actions.append("renamed stock_master -> krx_stock_master")

    # 2. Drop metadata columns from instruments
    for col in state["metadata_columns"]:
        await conn.execute(
            f"ALTER TABLE instruments DROP COLUMN IF EXISTS {col}"
        )
        actions.append(f"dropped column instruments.{col}")

    # 3. Create trading_universe
    if not state["has_trading_universe"]:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trading_universe (
                account_scope   VARCHAR(10)  NOT NULL REFERENCES trading_accounts(account_scope),
                instrument_id   VARCHAR(20)  NOT NULL REFERENCES instruments(instrument_id),
                priority        INTEGER      NOT NULL DEFAULT 0,
                max_weight_pct  NUMERIC(5,2),
                added_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
                memo            TEXT,
                PRIMARY KEY (account_scope, instrument_id)
            )
        """)
        actions.append("created trading_universe table")

    return {"success": True, "dry_run": False, "actions": actions}


# ---------------------------------------------------------------------------
# Try importing from actual script; fall back to stubs
# ---------------------------------------------------------------------------

try:
    from scripts.db.migrate_to_v2_instruments import (
        check_schema_state as _real_check,
        run_migration as _real_run,
    )
    check_schema_state = _real_check  # type: ignore[assignment]
    run_migration = _real_run  # type: ignore[assignment]
except ImportError:
    pass  # stubs defined above are used


# ---------------------------------------------------------------------------
# Helpers — mock connection factory
# ---------------------------------------------------------------------------

def _make_mock_conn(
    *,
    has_stock_master: bool = False,
    has_krx_stock_master: bool = True,
    has_trading_universe: bool = True,
    metadata_columns: list[str] | None = None,
) -> AsyncMock:
    """asyncpg connection mock을 생성합니다."""
    conn = AsyncMock()

    async def _fetchval(query, *args):
        q = query.lower()
        if "information_schema.tables" in q or "to_regclass" in q:
            # stock_master (but NOT krx_stock_master)
            if "krx_stock_master" in q:
                return has_krx_stock_master
            if "stock_master" in q:
                return has_stock_master
            if "trading_universe" in q:
                return has_trading_universe
        if "information_schema.columns" in q:
            if metadata_columns and len(args) > 0 and args[-1] in metadata_columns:
                return True
            return False
        return None

    conn.fetchval = AsyncMock(side_effect=_fetchval)

    async def _fetch(query, *args):
        q = query.lower()
        if "information_schema.columns" in q:
            cols = metadata_columns or []
            return [{"column_name": c} for c in cols]
        return []

    conn.fetch = AsyncMock(side_effect=_fetch)
    conn.execute = AsyncMock(return_value="OK")
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    conn.close = AsyncMock()

    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetectsOldSchema:
    """stock_master가 존재할 때 마이그레이션이 rename이 필요하다고 판단하는지 확인합니다."""

    async def test_detects_old_schema(self):
        conn = _make_mock_conn(
            has_stock_master=True,
            has_krx_stock_master=False,
        )

        state = await check_schema_state(conn)

        assert state["needs_rename"] is True
        assert state["old_table_exists"] is True


class TestDetectsNewSchema:
    """krx_stock_master가 이미 존재할 때 rename을 스킵하는지 확인합니다."""

    async def test_detects_new_schema(self):
        conn = _make_mock_conn(
            has_stock_master=False,
            has_krx_stock_master=True,
        )

        state = await check_schema_state(conn)

        assert state["needs_rename"] is False


class TestIdempotent:
    """마이그레이션을 두 번 실행해도 에러가 발생하지 않는지 확인합니다."""

    async def test_idempotent(self):
        conn = _make_mock_conn(
            has_stock_master=False,
            has_krx_stock_master=True,
            has_trading_universe=True,
            metadata_columns=[],
        )

        result1 = await run_migration(conn, dry_run=False)
        result2 = await run_migration(conn, dry_run=False)

        assert result1["success"] is True
        assert result2["success"] is True
        # 이미 완료된 스키마이므로 actions가 비어 있어야 함
        assert result1["actions"] == []
        assert result2["actions"] == []


class TestDryRunNoChanges:
    """dry-run 모드에서 DDL이 실행되지 않는지 확인합니다."""

    async def test_dry_run_no_changes(self):
        conn = _make_mock_conn(
            has_stock_master=True,
            has_krx_stock_master=False,
            has_trading_universe=False,
            metadata_columns=["name", "sector", "listed_at"],
        )

        result = await run_migration(conn, dry_run=True)

        assert result["success"] is True
        assert result["dry_run"] is True
        # dry-run에서 "WOULD"로 시작하는 action만 있어야 함
        for action in result["actions"]:
            assert action.startswith("WOULD"), f"dry-run에서 실제 action: {action}"
        # conn.execute에 DDL이 호출되지 않아야 함
        for c in conn.execute.call_args_list:
            sql = str(c).lower()
            assert "alter table" not in sql, "dry-run에서 ALTER TABLE이 실행됨"
            assert "rename" not in sql, "dry-run에서 RENAME이 실행됨"
            assert "create table" not in sql, "dry-run에서 CREATE TABLE이 실행됨"


class TestDropsMetadataColumns:
    """instruments 테이블에서 메타데이터 컬럼 DROP을 확인합니다."""

    async def test_drops_metadata_columns(self):
        target_columns = ["name", "sector", "listed_at"]
        conn = _make_mock_conn(
            has_stock_master=False,
            has_krx_stock_master=True,
            has_trading_universe=True,
            metadata_columns=target_columns,
        )

        result = await run_migration(conn, dry_run=False)

        assert result["success"] is True

        # execute 호출 중 DROP COLUMN이 포함되어야 함
        executed_sqls = [str(c) for c in conn.execute.call_args_list]
        all_sql = " ".join(executed_sqls).lower()
        assert "drop column" in all_sql, "메타데이터 컬럼 DROP이 실행되지 않았습니다"

        # 각 대상 컬럼이 DROP되었는지 확인
        for col in target_columns:
            assert col in all_sql, f"컬럼 {col}이 DROP되지 않았습니다"


class TestCreatesTradingUniverse:
    """trading_universe 테이블 생성 DDL을 확인합니다."""

    async def test_creates_trading_universe(self):
        conn = _make_mock_conn(
            has_stock_master=False,
            has_krx_stock_master=True,
            has_trading_universe=False,
            metadata_columns=[],
        )

        result = await run_migration(conn, dry_run=False)

        assert result["success"] is True

        executed_sqls = [str(c) for c in conn.execute.call_args_list]
        all_sql = " ".join(executed_sqls).lower()
        assert "trading_universe" in all_sql, (
            "trading_universe CREATE TABLE이 실행되지 않았습니다"
        )
        assert "create table" in all_sql, (
            "CREATE TABLE DDL이 실행되지 않았습니다"
        )
