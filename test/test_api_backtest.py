"""
test/test_api_backtest.py — Backtest API 단위 테스트

DB를 mock하여 Backtest REST API 엔드포인트를 검증한다.
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from src.api.deps import get_current_user
from src.api.routers.backtest import router

# ── 테스트용 미니 앱 (lifespan 없이 라우터만) ────────────────────────────

_app = FastAPI()
_app.include_router(router, prefix="/api/v1/backtest")


async def _mock_user():
    return {"sub": "test-user", "email": "t@t.com", "name": "Tester", "is_admin": True}


_app.dependency_overrides[get_current_user] = _mock_user

client = TestClient(_app, raise_server_exceptions=False)


# ── 공통 fixture 데이터 ──────────────────────────────────────────────────

SAMPLE_RUN = {
    "id": 1,
    "ticker": "005930",
    "strategy": "RL",
    "train_start": date(2024, 1, 1),
    "train_end": date(2024, 12, 31),
    "test_start": date(2025, 1, 1),
    "test_end": date(2025, 6, 30),
    "initial_capital": 10_000_000,
    "commission_rate_pct": Decimal("0.0150"),
    "tax_rate_pct": Decimal("0.1800"),
    "slippage_bps": 3,
    "total_return_pct": Decimal("12.3400"),
    "annual_return_pct": Decimal("24.6800"),
    "sharpe_ratio": Decimal("1.2300"),
    "max_drawdown_pct": Decimal("-5.6700"),
    "win_rate": Decimal("0.5833"),
    "total_trades": 12,
    "avg_holding_days": Decimal("8.50"),
    "baseline_return_pct": Decimal("5.1200"),
    "excess_return_pct": Decimal("7.2200"),
    "created_at": datetime(2025, 7, 1, 12, 0, 0),
}

SAMPLE_RUN_A = {
    **SAMPLE_RUN,
    "id": 2,
    "strategy": "A",
    "total_return_pct": Decimal("8.5000"),
}

SAMPLE_DAILY = [
    {
        "date": date(2025, 1, 2),
        "close_price": Decimal("65000.0000"),
        "cash": Decimal("10000000.00"),
        "position_qty": 0,
        "position_value": Decimal("0.00"),
        "portfolio_value": Decimal("10000000.00"),
        "daily_return_pct": Decimal("0.000000"),
    },
    {
        "date": date(2025, 1, 3),
        "close_price": Decimal("66000.0000"),
        "cash": Decimal("4010000.00"),
        "position_qty": 90,
        "position_value": Decimal("5940000.00"),
        "portfolio_value": Decimal("9950000.00"),
        "daily_return_pct": Decimal("-0.500000"),
    },
]

_PATCH_PREFIX = "src.api.routers.backtest"


# ── GET /runs ────────────────────────────────────────────────────────────


@patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.fetchval", new_callable=AsyncMock)
def test_list_runs_empty(mock_fetchval, mock_fetch):
    """빈 테이블 → data 빈 배열, total 0."""
    mock_fetchval.return_value = 0
    mock_fetch.return_value = []

    resp = client.get("/api/v1/backtest/runs")
    assert resp.status_code == 200

    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0
    assert body["meta"]["page"] == 1
    assert body["meta"]["per_page"] == 20


@patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.fetchval", new_callable=AsyncMock)
def test_list_runs_strategy_filter(mock_fetchval, mock_fetch):
    """strategy=RL 필터 → WHERE strategy=$1 쿼리 실행."""
    mock_fetchval.return_value = 1
    mock_fetch.return_value = [SAMPLE_RUN]

    resp = client.get("/api/v1/backtest/runs?strategy=RL")
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["strategy"] == "RL"
    assert body["meta"]["total"] == 1

    # fetchval에 strategy 파라미터 전달 확인
    sql_arg = mock_fetchval.call_args[0][0]
    assert "strategy = $1" in sql_arg


@patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.fetchval", new_callable=AsyncMock)
def test_list_runs_pagination(mock_fetchval, mock_fetch):
    """page=2, per_page=5 → OFFSET 5, LIMIT 5."""
    mock_fetchval.return_value = 15
    mock_fetch.return_value = [SAMPLE_RUN]

    resp = client.get("/api/v1/backtest/runs?page=2&per_page=5")
    assert resp.status_code == 200

    body = resp.json()
    assert body["meta"]["page"] == 2
    assert body["meta"]["per_page"] == 5
    assert body["meta"]["total"] == 15

    # LIMIT $1=5, OFFSET $2=5
    fetch_args = mock_fetch.call_args[0]
    assert fetch_args[1] == 5   # per_page (LIMIT)
    assert fetch_args[2] == 5   # offset = (2-1)*5


# ── GET /runs/{run_id} ──────────────────────────────────────────────────


@patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
def test_get_run_exists(mock_fetchrow):
    """존재하는 run → 200 + BacktestRunDetail 전체 필드."""
    mock_fetchrow.return_value = SAMPLE_RUN

    resp = client.get("/api/v1/backtest/runs/1")
    assert resp.status_code == 200

    body = resp.json()
    assert body["id"] == 1
    assert body["ticker"] == "005930"
    assert body["strategy"] == "RL"
    assert body["initial_capital"] == 10_000_000
    assert body["train_start"] == "2024-01-01"
    assert body["test_end"] == "2025-06-30"
    assert pytest.approx(body["total_return_pct"], abs=0.01) == 12.34
    assert pytest.approx(body["sharpe_ratio"], abs=0.01) == 1.23
    assert body["total_trades"] == 12
    assert "avg_holding_days" in body
    assert "baseline_return_pct" in body
    assert "excess_return_pct" in body


@patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
def test_get_run_not_found(mock_fetchrow):
    """존재하지 않는 run → 404."""
    mock_fetchrow.return_value = None

    resp = client.get("/api/v1/backtest/runs/999")
    assert resp.status_code == 404


# ── GET /runs/{run_id}/daily ─────────────────────────────────────────────


@patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
def test_get_daily_exists(mock_fetchrow, mock_fetch):
    """일별 스냅샷 정상 반환."""
    mock_fetchrow.return_value = {"id": 1}  # run 존재 확인
    mock_fetch.return_value = SAMPLE_DAILY

    resp = client.get("/api/v1/backtest/runs/1/daily")
    assert resp.status_code == 200

    body = resp.json()
    assert len(body) == 2
    assert body[0]["date"] == "2025-01-02"
    assert body[0]["portfolio_value"] == 10_000_000.0
    assert body[0]["position_qty"] == 0
    assert body[1]["position_qty"] == 90
    assert pytest.approx(body[1]["daily_return_pct"], abs=0.01) == -0.5


@patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
def test_get_daily_run_not_found(mock_fetchrow):
    """존재하지 않는 run의 daily → 404."""
    mock_fetchrow.return_value = None

    resp = client.get("/api/v1/backtest/runs/999/daily")
    assert resp.status_code == 404


# ── 인증 ─────────────────────────────────────────────────────────────────


def test_no_auth_returns_401():
    """인증 없이 호출 → 401."""
    no_auth_app = FastAPI()
    no_auth_app.include_router(router, prefix="/api/v1/backtest")
    no_auth_client = TestClient(no_auth_app, raise_server_exceptions=False)

    resp = no_auth_client.get("/api/v1/backtest/runs")
    assert resp.status_code in (401, 403)
