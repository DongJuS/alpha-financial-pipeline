"""
test/integration/test_api_backtest.py — Backtest 읽기 전용 API 통합 테스트

FastAPI TestClient로 backtest 라우터를 격리 테스트한다.
DB는 mock으로 대체. (test/test_api_backtest.py와 보완적 — 여기서는 통합 시나리오 중점)

테스트 대상:
  - GET /api/v1/backtest/runs              — 실행 목록 (페이지네이션 + strategy 필터)
  - GET /api/v1/backtest/runs/{run_id}     — 실행 상세
  - GET /api/v1/backtest/runs/{run_id}/daily — 일별 스냅샷
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers.backtest import router as backtest_router

API_PREFIX = "/api/v1/backtest"
_PATCH_PREFIX = "src.api.routers.backtest"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(backtest_router, prefix=API_PREFIX)
    if authenticated:
        async def mock_user():
            return {
                "sub": str(uuid4()),
                "email": "test@test.com",
                "name": "Tester",
                "is_admin": True,
            }
        app.dependency_overrides[get_current_user] = mock_user
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="test-secret"
    )
    return TestClient(app, raise_server_exceptions=False)


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


# ── GET /runs ───────────────────────────────────────────────────────────


class TestListBacktestRuns:
    """GET /api/v1/backtest/runs"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetchval", new_callable=AsyncMock)
    def test_list_runs_returns_paginated_response(
        self, mock_fetchval: AsyncMock, mock_fetch: AsyncMock
    ) -> None:
        """목록 조회가 페이지네이션 메타데이터를 포함한다."""
        mock_fetchval.return_value = 1
        mock_fetch.return_value = [SAMPLE_RUN]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/runs")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert body["meta"]["page"] == 1
        assert body["meta"]["per_page"] == 20

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetchval", new_callable=AsyncMock)
    def test_list_runs_strategy_filter_pattern_validation(
        self, mock_fetchval: AsyncMock, mock_fetch: AsyncMock
    ) -> None:
        """strategy 파라미터가 ^(RL|A|B|BLEND)$ 패턴만 허용한다."""
        client = _build_client()

        # 유효한 필터
        mock_fetchval.return_value = 0
        mock_fetch.return_value = []

        for valid_strategy in ["RL", "A", "B", "BLEND"]:
            resp = client.get(f"{API_PREFIX}/runs?strategy={valid_strategy}")
            assert resp.status_code == 200, f"strategy={valid_strategy} should be valid"

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetchval", new_callable=AsyncMock)
    def test_list_runs_invalid_strategy_returns_422(
        self, mock_fetchval: AsyncMock, mock_fetch: AsyncMock
    ) -> None:
        """유효하지 않은 strategy 값은 422를 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/runs?strategy=INVALID")
        assert resp.status_code == 422

    def test_list_runs_requires_authentication(self) -> None:
        """인증 없이 호출하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/runs")
        assert resp.status_code in (401, 403)


# ── GET /runs/{run_id} ─────────────────────────────────────────────────


class TestGetBacktestRun:
    """GET /api/v1/backtest/runs/{run_id}"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_get_run_detail_has_all_fields(self, mock_fetchrow: AsyncMock) -> None:
        """상세 응답에 모든 BacktestRunDetail 필드가 포함된다."""
        mock_fetchrow.return_value = SAMPLE_RUN

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/runs/1")
        assert resp.status_code == 200

        body = resp.json()
        required_fields = [
            "id", "ticker", "strategy", "train_start", "train_end",
            "test_start", "test_end", "initial_capital",
            "commission_rate_pct", "tax_rate_pct", "slippage_bps",
            "total_return_pct", "annual_return_pct", "sharpe_ratio",
            "max_drawdown_pct", "win_rate", "total_trades",
            "avg_holding_days", "baseline_return_pct", "excess_return_pct",
        ]
        for field in required_fields:
            assert field in body, f"Missing field: {field}"

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_get_run_not_found_returns_404(self, mock_fetchrow: AsyncMock) -> None:
        """존재하지 않는 run_id에 대해 404를 반환한다."""
        mock_fetchrow.return_value = None

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/runs/99999")
        assert resp.status_code == 404


# ── GET /runs/{run_id}/daily ────────────────────────────────────────────


class TestGetBacktestDaily:
    """GET /api/v1/backtest/runs/{run_id}/daily"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_daily_returns_sorted_list(
        self, mock_fetchrow: AsyncMock, mock_fetch: AsyncMock
    ) -> None:
        """일별 스냅샷이 리스트로 반환된다."""
        mock_fetchrow.return_value = {"id": 1}
        mock_fetch.return_value = [
            {
                "date": date(2025, 1, 2),
                "close_price": Decimal("65000.0"),
                "cash": Decimal("10000000.00"),
                "position_qty": 0,
                "position_value": Decimal("0.00"),
                "portfolio_value": Decimal("10000000.00"),
                "daily_return_pct": Decimal("0.0"),
            },
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/runs/1/daily")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["date"] == "2025-01-02"
        assert body[0]["portfolio_value"] == 10_000_000.0

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_daily_run_not_found_returns_404(self, mock_fetchrow: AsyncMock) -> None:
        """존재하지 않는 run_id의 daily → 404."""
        mock_fetchrow.return_value = None

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/runs/99999/daily")
        assert resp.status_code == 404
