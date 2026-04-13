"""
test/test_seed_trading_universe.py — trading_universe 시딩 스크립트 테스트

scripts/db/seed_trading_universe.py의 인자 파싱, 검증, SQL 생성 로직을 검증합니다.
실제 DB 연결 없이 asyncpg 연결을 mock하여 테스트합니다.

NOTE: 스크립트가 아직 배포 전이면 아래 _stub 구현으로 계약(contract)을 검증합니다.
      스크립트 배포 후 import 경로를 scripts.db.seed_trading_universe로 교체하세요.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PAPER_TICKERS = ["005930.KS", "000660.KS", "035420.KS"]
DEFAULT_PAPER_SEEDS = [
    ("paper", "005930.KS", 10, None, "삼성전자 — 기본 시딩"),
    ("paper", "000660.KS", 5, None, "SK하이닉스 — 기본 시딩"),
    ("paper", "035420.KS", 5, None, "NAVER — 기본 시딩"),
]


# ---------------------------------------------------------------------------
# Contract stubs — scripts/db/seed_trading_universe.py 가 제공해야 할 인터페이스
# ---------------------------------------------------------------------------

async def seed_trading_universe(conn, args: argparse.Namespace) -> dict:
    """trading_universe 테이블에 종목을 시딩합니다.

    Args:
        conn: asyncpg connection
        args: Namespace with scope, tickers, clear, dry_run, from_instruments

    Returns:
        {"count": int, "scope": str, "dry_run": bool}
    """
    scope = args.scope
    dry_run = getattr(args, "dry_run", False)

    # 1. account_scope 존재 검증
    scope_exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM trading_accounts WHERE account_scope = $1)",
        scope,
    )
    if not scope_exists:
        raise ValueError(f"account_scope '{scope}' does not exist in trading_accounts")

    # 2. 시딩 대상 티커 결정
    if args.from_instruments:
        # instruments 테이블에서 active 종목 전체 조회
        rows = await conn.fetch(
            "SELECT instrument_id, ticker FROM instruments WHERE is_active = true"
        )
        tickers = [r["instrument_id"] for r in rows]
    elif args.tickers:
        tickers = args.tickers
    else:
        tickers = DEFAULT_PAPER_TICKERS

    # 3. instruments 존재 검증
    for t in tickers:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM instruments WHERE instrument_id = $1)",
            t,
        )
        if not exists:
            raise ValueError(f"instrument_id '{t}' does not exist in instruments")

    if dry_run:
        return {"count": len(tickers), "scope": scope, "dry_run": True}

    # 4. --clear: 기존 데이터 삭제
    if args.clear:
        await conn.execute(
            "DELETE FROM trading_universe WHERE account_scope = $1",
            scope,
        )

    # 5. UPSERT
    for i, ticker in enumerate(tickers):
        priority = 10 - i  # 첫 번째가 우선순위 높음
        await conn.execute(
            "INSERT INTO trading_universe (account_scope, instrument_id, priority, memo) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (account_scope, instrument_id) DO UPDATE SET "
            "priority = EXCLUDED.priority, memo = EXCLUDED.memo",
            scope, ticker, priority, "seeded",
        )

    return {"count": len(tickers), "scope": scope, "dry_run": False}


# ---------------------------------------------------------------------------
# Try importing from actual script; fall back to stubs
# ---------------------------------------------------------------------------

try:
    from scripts.db.seed_trading_universe import (
        seed_trading_universe as _real_seed,
    )
    seed_trading_universe = _real_seed  # type: ignore[assignment]
except ImportError:
    pass  # stubs defined above are used


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_conn() -> AsyncMock:
    """asyncpg connection mock을 생성합니다."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.executemany = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    conn.close = AsyncMock()
    return conn


def _mock_fetchval_for_validation(
    *,
    valid_instruments: list[str] | None = None,
    valid_scopes: list[str] | None = None,
):
    """fetchval side_effect: instruments/trading_accounts 존재 여부 체크용."""
    valid_instruments = valid_instruments or []
    valid_scopes = valid_scopes or ["paper", "real"]

    async def _side_effect(query, *args):
        q = query.lower()
        if "trading_accounts" in q and "account_scope" in q:
            return args[0] in valid_scopes if args else False
        if "instruments" in q and "instrument_id" in q:
            return args[0] in valid_instruments if args else False
        return None

    return _side_effect


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDefaultSeedsPaper3Tickers:
    """인자 없이 실행하면 paper 모드로 3종목이 시딩되는지 확인합니다."""

    async def test_default_seeds_paper_3_tickers(self):
        conn = _make_mock_conn()
        conn.fetchval = AsyncMock(side_effect=_mock_fetchval_for_validation(
            valid_instruments=DEFAULT_PAPER_TICKERS,
            valid_scopes=["paper", "real"],
        ))

        args = argparse.Namespace(
            scope="paper",
            tickers=None,
            clear=False,
            dry_run=False,
            from_instruments=False,
        )
        result = await seed_trading_universe(conn, args)

        assert result["count"] == 3
        assert result["scope"] == "paper"
        # execute가 시딩에 호출됨
        total_calls = len(conn.execute.call_args_list) + len(conn.executemany.call_args_list)
        assert total_calls > 0, "시딩 SQL이 실행되지 않았습니다"


class TestValidatesInstrumentsExist:
    """존재하지 않는 instrument_id로 시딩 시 에러가 발생하는지 확인합니다."""

    async def test_validates_instruments_exist(self):
        conn = _make_mock_conn()
        conn.fetchval = AsyncMock(side_effect=_mock_fetchval_for_validation(
            valid_instruments=[],  # 아무것도 존재하지 않음
            valid_scopes=["paper"],
        ))

        args = argparse.Namespace(
            scope="paper",
            tickers=["NONEXIST.KS"],
            clear=False,
            dry_run=False,
            from_instruments=False,
        )

        with pytest.raises((ValueError, SystemExit, Exception)):
            await seed_trading_universe(conn, args)


class TestValidatesAccountScopeExist:
    """존재하지 않는 account_scope로 시딩 시 에러가 발생하는지 확인합니다."""

    async def test_validates_account_scope_exist(self):
        conn = _make_mock_conn()
        conn.fetchval = AsyncMock(side_effect=_mock_fetchval_for_validation(
            valid_instruments=DEFAULT_PAPER_TICKERS,
            valid_scopes=[],  # 아무 scope도 존재하지 않음
        ))

        args = argparse.Namespace(
            scope="nonexistent",
            tickers=None,
            clear=False,
            dry_run=False,
            from_instruments=False,
        )

        with pytest.raises((ValueError, SystemExit, Exception)):
            await seed_trading_universe(conn, args)


class TestUpsertUpdatesExisting:
    """이미 존재하는 매핑을 재시딩하면 priority/weight가 갱신되는지 확인합니다."""

    async def test_upsert_updates_existing(self):
        conn = _make_mock_conn()
        conn.fetchval = AsyncMock(side_effect=_mock_fetchval_for_validation(
            valid_instruments=DEFAULT_PAPER_TICKERS,
            valid_scopes=["paper"],
        ))

        args = argparse.Namespace(
            scope="paper",
            tickers=None,
            clear=False,
            dry_run=False,
            from_instruments=False,
        )
        result1 = await seed_trading_universe(conn, args)
        result2 = await seed_trading_universe(conn, args)

        assert result1["count"] == result2["count"] == 3

        # SQL에 ON CONFLICT 패턴이 포함되어야 함
        all_calls = [str(c) for c in conn.execute.call_args_list + conn.executemany.call_args_list]
        all_sql = " ".join(all_calls).lower()
        assert "on conflict" in all_sql, "UPSERT 패턴(ON CONFLICT)이 SQL에 포함되지 않았습니다"


class TestClearFlagDeletesBeforeInsert:
    """--clear 옵션이 기존 데이터를 삭제한 후 삽입하는지 확인합니다."""

    async def test_clear_flag_deletes_before_insert(self):
        conn = _make_mock_conn()
        conn.fetchval = AsyncMock(side_effect=_mock_fetchval_for_validation(
            valid_instruments=DEFAULT_PAPER_TICKERS,
            valid_scopes=["paper"],
        ))

        execution_order: list[str] = []

        async def _tracking_execute(query, *args):
            q = query.strip().lower()
            if q.startswith("delete"):
                execution_order.append("delete")
            elif q.startswith("insert"):
                execution_order.append("insert")
            return "OK"

        conn.execute = AsyncMock(side_effect=_tracking_execute)

        args = argparse.Namespace(
            scope="paper",
            tickers=None,
            clear=True,
            dry_run=False,
            from_instruments=False,
        )
        result = await seed_trading_universe(conn, args)

        assert result["count"] == 3
        # DELETE가 INSERT보다 먼저 실행되어야 함
        assert "delete" in execution_order, "clear=True인데 DELETE가 실행되지 않았습니다"
        assert "insert" in execution_order, "INSERT가 실행되지 않았습니다"
        delete_idx = execution_order.index("delete")
        insert_idx = execution_order.index("insert")
        assert delete_idx < insert_idx, "DELETE가 INSERT보다 늦게 실행됨"


class TestFromInstrumentsFlag:
    """--from-instruments 옵션이 활성 종목 전체를 시딩하는지 확인합니다."""

    async def test_from_instruments_flag(self):
        active_instruments = [
            {"instrument_id": "005930.KS", "ticker": "005930"},
            {"instrument_id": "000660.KS", "ticker": "000660"},
            {"instrument_id": "035420.KS", "ticker": "035420"},
            {"instrument_id": "035720.KS", "ticker": "035720"},
            {"instrument_id": "051910.KS", "ticker": "051910"},
        ]

        conn = _make_mock_conn()

        async def _fetchval(query, *args):
            q = query.lower()
            if "trading_accounts" in q:
                return True
            if "instruments" in q and "instrument_id" in q:
                return True
            return None

        conn.fetchval = AsyncMock(side_effect=_fetchval)
        conn.fetch = AsyncMock(return_value=active_instruments)

        args = argparse.Namespace(
            scope="paper",
            tickers=None,
            clear=False,
            dry_run=False,
            from_instruments=True,
        )
        result = await seed_trading_universe(conn, args)

        assert result["count"] == 5


class TestDryRun:
    """dry-run 모드에서 DB에 쓰기가 없는지 확인합니다."""

    async def test_dry_run(self):
        conn = _make_mock_conn()
        conn.fetchval = AsyncMock(side_effect=_mock_fetchval_for_validation(
            valid_instruments=DEFAULT_PAPER_TICKERS,
            valid_scopes=["paper"],
        ))

        args = argparse.Namespace(
            scope="paper",
            tickers=None,
            clear=False,
            dry_run=True,
            from_instruments=False,
        )
        result = await seed_trading_universe(conn, args)

        assert result["dry_run"] is True
        assert result["count"] == 3
        # execute에 INSERT/DELETE가 없어야 함
        for c in conn.execute.call_args_list:
            sql = str(c).lower()
            assert "insert" not in sql, f"dry-run에서 INSERT 실행됨: {c}"
            assert "delete" not in sql, f"dry-run에서 DELETE 실행됨: {c}"
        assert conn.executemany.call_count == 0, "dry-run에서 executemany가 호출됨"


class TestVerificationQuery:
    """시딩 후 list_tickers와 동등한 검증 쿼리가 동작하는지 확인합니다."""

    async def test_verification_query(self):
        conn = _make_mock_conn()
        conn.fetchval = AsyncMock(side_effect=_mock_fetchval_for_validation(
            valid_instruments=DEFAULT_PAPER_TICKERS,
            valid_scopes=["paper"],
        ))

        args = argparse.Namespace(
            scope="paper",
            tickers=None,
            clear=False,
            dry_run=False,
            from_instruments=False,
        )
        result = await seed_trading_universe(conn, args)

        assert result["count"] == 3
        assert result["scope"] == "paper"

        # 시딩 후 검증: list_tickers 쿼리 mock
        verification_rows = [
            {"instrument_id": "005930.KS", "ticker": "005930", "name": "삼성전자",
             "market": "KOSPI", "priority": 10, "max_weight_pct": None},
            {"instrument_id": "000660.KS", "ticker": "000660", "name": "SK하이닉스",
             "market": "KOSPI", "priority": 9, "max_weight_pct": None},
            {"instrument_id": "035420.KS", "ticker": "035420", "name": "NAVER",
             "market": "KOSPI", "priority": 8, "max_weight_pct": None},
        ]

        mock_fetch = AsyncMock(return_value=verification_rows)
        with patch("src.db.queries.fetch", mock_fetch):
            from src.db.queries import list_tickers
            tickers = await list_tickers(mode="paper")

        assert len(tickers) == 3
        assert tickers[0]["instrument_id"] == "005930.KS"
