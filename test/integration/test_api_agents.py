"""
test/integration/test_api_agents.py — Agents API 통합 테스트

FastAPI TestClient로 에이전트 라우터를 격리 테스트한다.
DB/Redis는 mock으로 대체.

테스트 대상:
  - GET  /api/v1/agents/status         — 에이전트 상태 조회
  - GET  /api/v1/agents/registry/list  — 에이전트 레지스트리 목록
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers import agents as agents_module
from src.api.routers.agents import router as agents_router

API_PREFIX = "/api/v1/agents"

_PATCH_PREFIX = "src.api.routers.agents"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(agents_router, prefix=API_PREFIX)
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


_FALLBACK_REGISTRY = [
    {"agent_id": "collector_agent", "display_name": "collector_agent",
     "agent_type": "collector", "description": None,
     "is_on_demand": False, "default_config": {}},
    {"agent_id": "predictor_1", "display_name": "predictor_1",
     "agent_type": "predictor", "description": None,
     "is_on_demand": False, "default_config": {}},
]


class TestAgentsStatus:
    """GET /api/v1/agents/status"""

    @patch(f"{_PATCH_PREFIX}.check_heartbeat", new_callable=AsyncMock, return_value=False)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_get_agents_status(
        self, mock_fetch: AsyncMock, mock_hb: AsyncMock
    ) -> None:
        """전체 에이전트 상태를 조회한다."""
        # _load_agent_registry -> fetch raises to trigger fallback
        mock_fetch.side_effect = [
            Exception("no table"),  # _load_agent_registry
            [],  # heartbeat fetch in status endpoint
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "agents" in body
        assert isinstance(body["agents"], list)

    @patch(f"{_PATCH_PREFIX}.check_heartbeat", new_callable=AsyncMock, return_value=False)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_agents_status_items_have_required_fields(
        self, mock_fetch: AsyncMock, mock_hb: AsyncMock
    ) -> None:
        """에이전트 상태 항목에는 필수 필드가 포함되어야 한다."""
        mock_fetch.side_effect = [
            Exception("no table"),  # _load_agent_registry fallback
            [],  # heartbeat DB query
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200
        body = resp.json()
        for agent in body["agents"]:
            assert "agent_id" in agent
            assert "status" in agent
            assert "is_alive" in agent
            assert "activity_state" in agent
            assert "activity_label" in agent

    @patch(f"{_PATCH_PREFIX}.check_heartbeat", new_callable=AsyncMock, return_value=False)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_agents_status_has_at_least_one_agent(
        self, mock_fetch: AsyncMock, mock_hb: AsyncMock
    ) -> None:
        """에이전트 상태 목록에 최소 1개 이상의 에이전트가 존재해야 한다."""
        mock_fetch.side_effect = [
            Exception("no table"),
            [],
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["agents"]) > 0

    def test_agents_status_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code in (401, 403)

    @patch(f"{_PATCH_PREFIX}.check_heartbeat", new_callable=AsyncMock, return_value=False)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_agents_status_agent_id_is_string(
        self, mock_fetch: AsyncMock, mock_hb: AsyncMock
    ) -> None:
        """에이전트 ID는 문자열이어야 한다."""
        mock_fetch.side_effect = [
            Exception("no table"),
            [],
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200
        body = resp.json()
        for agent in body["agents"]:
            assert isinstance(agent["agent_id"], str)


class TestAgentsRegistryList:
    """GET /api/v1/agents/registry/list"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_list_registry(self, mock_fetch: AsyncMock) -> None:
        """에이전트 레지스트리 목록을 조회한다."""
        mock_fetch.return_value = _FALLBACK_REGISTRY

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/registry/list")
        assert resp.status_code == 200
        body = resp.json()
        assert "agents" in body
        assert isinstance(body["agents"], list)

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_registry_items_have_required_fields(
        self, mock_fetch: AsyncMock
    ) -> None:
        """레지스트리 항목에는 필수 필드가 포함되어야 한다."""
        mock_fetch.return_value = _FALLBACK_REGISTRY

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/registry/list")
        assert resp.status_code == 200
        body = resp.json()
        for agent in body["agents"]:
            assert "agent_id" in agent

    def test_registry_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/registry/list")
        assert resp.status_code in (401, 403)

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_registry_has_at_least_one_agent(
        self, mock_fetch: AsyncMock
    ) -> None:
        """레지스트리에 최소 1개 이상의 에이전트가 등록되어 있어야 한다."""
        mock_fetch.return_value = _FALLBACK_REGISTRY

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/registry/list")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["agents"]) > 0
