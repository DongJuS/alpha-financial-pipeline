"""
test/integration/test_api_portfolio.py — Portfolio API 통합 테스트

FastAPI TestClient로 포트폴리오 라우터를 격리 테스트한다.
DB는 mock으로 대체.

테스트 대상:
  - GET  /api/v1/portfolio/positions
  - GET  /api/v1/portfolio/history
  - GET  /api/v1/portfolio/performance
  - GET  /api/v1/portfolio/performance-series
  - GET  /api/v1/portfolio/paper-overview
  - GET  /api/v1/portfolio/account-overview
  - GET  /api/v1/portfolio/orders
  - GET  /api/v1/portfolio/account-snapshots
  - GET  /api/v1/portfolio/config
  - POST /api/v1/portfolio/config
  - POST /api/v1/portfolio/trading-mode
  - GET  /api/v1/portfolio/readiness
  - GET  /api/v1/portfolio/readiness/audits
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_admin_user, get_current_settings, get_current_user
from src.api.routers import portfolio as portfolio_module
from src.api.routers.portfolio import router as portfolio_router

API_PREFIX = "/api/v1/portfolio"

_PATCH_PREFIX = "src.api.routers.portfolio"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(portfolio_router, prefix=API_PREFIX)
    if authenticated:
        async def mock_user():
            return {
                "sub": str(uuid4()),
                "email": "test@test.com",
                "name": "Tester",
                "is_admin": True,
            }
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_admin_user] = mock_user
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="test-secret",
        real_trading_confirmation_code="CONFIRM-REAL",
    )
    return TestClient(app, raise_server_exceptions=False)


class TestPortfolioPositions:
    """GET /api/v1/portfolio/positions"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_get_positions(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """현재 포트폴리오 포지션 목록을 조회한다."""
        mock_fetch.return_value = [
            {
                "ticker": "005930", "name": "삼성전자",
                "quantity": 10, "avg_price": 70000, "current_price": 72500,
                "is_paper": True, "account_scope": "paper",
            },
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/positions")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "positions" in body
        assert body["is_paper"] is True


class TestPortfolioHistory:
    """GET /api/v1/portfolio/history"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_history(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """포트폴리오 거래 내역을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/history")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "data" in body


class TestPortfolioPerformance:
    """GET /api/v1/portfolio/performance"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_performance(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """포트폴리오 성과 요약을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/performance")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "return_pct" in body
        assert "max_drawdown_pct" in body


class TestPortfolioPerformanceSeries:
    """GET /api/v1/portfolio/performance-series"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_performance_series(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock
    ) -> None:
        """포트폴리오 성과 시계열 데이터를 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/performance-series")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "points" in body


class TestPortfolioPaperOverview:
    """GET /api/v1/portfolio/paper-overview"""

    @patch(f"{_PATCH_PREFIX}.fetch_latest_paper_trading_run", new_callable=AsyncMock, return_value=None)
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_get_paper_overview(
        self, mock_fetchrow: AsyncMock, mock_latest_run: AsyncMock
    ) -> None:
        """페이퍼 트레이딩 개요를 조회한다."""
        mock_fetchrow.side_effect = [
            None,  # _resolve_mode config
            {"broker_name": "한국투자증권 KIS", "account_label": "KIS 모의투자"},
            {"active_days": 10, "trade_count": 50, "traded_tickers": 5, "last_executed_at": None},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/paper-overview")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "broker" in body


class TestPortfolioAccountOverview:
    """GET /api/v1/portfolio/account-overview"""

    @patch(f"{_PATCH_PREFIX}.build_account_overview", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    def test_get_account_overview(
        self, mock_fetchrow: AsyncMock, mock_overview: AsyncMock
    ) -> None:
        """실계좌 개요를 조회한다."""
        mock_overview.return_value = {
            "account_scope": "paper",
            "broker_name": "KIS",
            "account_label": "모의투자",
            "base_currency": "KRW",
            "seed_capital": 10_000_000,
            "cash_balance": 8_000_000,
            "buying_power": 8_000_000,
            "position_market_value": 2_000_000,
            "total_equity": 10_000_000,
            "realized_pnl": 0,
            "unrealized_pnl": 0,
            "total_pnl": 0,
            "total_pnl_pct": 0.0,
            "position_count": 1,
            "last_snapshot_at": None,
        }

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/account-overview")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)


class TestPortfolioOrders:
    """GET /api/v1/portfolio/orders"""

    @patch(f"{_PATCH_PREFIX}.build_broker_order_activity", new_callable=AsyncMock, return_value=[])
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    def test_get_orders(
        self, mock_fetchrow: AsyncMock, mock_orders: AsyncMock
    ) -> None:
        """주문 내역을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/orders")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "data" in body


class TestPortfolioAccountSnapshots:
    """GET /api/v1/portfolio/account-snapshots"""

    @patch(f"{_PATCH_PREFIX}.build_account_snapshot_series", new_callable=AsyncMock, return_value=[])
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    def test_get_account_snapshots(
        self, mock_fetchrow: AsyncMock, mock_snapshots: AsyncMock
    ) -> None:
        """계좌 스냅샷 이력을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/account-snapshots")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "points" in body


class TestPortfolioConfigGet:
    """GET /api/v1/portfolio/config"""

    @patch(f"{_PATCH_PREFIX}.market_session_status", new_callable=AsyncMock, return_value="closed")
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    def test_get_config(
        self, mock_fetchrow: AsyncMock, mock_market_status: AsyncMock
    ) -> None:
        """포트폴리오 설정을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/config")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "strategy_blend_ratio" in body


class TestPortfolioConfigPost:
    """POST /api/v1/portfolio/config"""

    @patch(f"{_PATCH_PREFIX}.execute", new_callable=AsyncMock)
    def test_post_config_empty_body(self, mock_execute: AsyncMock) -> None:
        """빈 바디로 설정을 업데이트하면 422를 반환한다 (필수 필드 누락)."""
        client = _build_client()
        resp = client.post(f"{API_PREFIX}/config", json={})
        assert resp.status_code == 422


class TestPortfolioTradingMode:
    """POST /api/v1/portfolio/trading-mode"""

    def test_post_trading_mode(self) -> None:
        """트레이딩 모드 변경 요청 (빈 바디)은 422를 반환한다."""
        client = _build_client()
        resp = client.post(f"{API_PREFIX}/trading-mode", json={})
        assert resp.status_code == 422


class TestPortfolioReadiness:
    """GET /api/v1/portfolio/readiness"""

    @patch(f"{_PATCH_PREFIX}.evaluate_real_trading_readiness", new_callable=AsyncMock)
    def test_get_readiness(self, mock_readiness: AsyncMock) -> None:
        """포트폴리오 준비 상태를 조회한다."""
        mock_readiness.return_value = {
            "ready": False,
            "critical_ok": True,
            "high_ok": False,
            "checks": [
                {"key": "db_connection", "ok": True, "message": "DB OK", "severity": "critical"},
            ],
        }

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/readiness")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "ready" in body


class TestPortfolioReadinessAudits:
    """GET /api/v1/portfolio/readiness/audits"""

    @patch(f"{_PATCH_PREFIX}.fetch_real_trading_audits", new_callable=AsyncMock, return_value=[])
    @patch(f"{_PATCH_PREFIX}.fetch_operational_audits", new_callable=AsyncMock, return_value=[])
    def test_get_readiness_audits(
        self, mock_op_audits: AsyncMock, mock_rt_audits: AsyncMock
    ) -> None:
        """포트폴리오 준비 상태 감사 이력을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/readiness/audits")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "operational_audits" in body
        assert "mode_switch_audits" in body
