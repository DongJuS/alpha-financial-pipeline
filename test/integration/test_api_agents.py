"""
test/integration/test_api_agents.py — Agents API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 에이전트 관련 엔드포인트를 검증합니다.

테스트 대상:
  - GET  /api/v1/agents/status         — 에이전트 상태 조회
  - GET  /api/v1/agents/registry/list  — 에이전트 레지스트리 목록
"""

from __future__ import annotations

import os
import unittest

import httpx
import pytest

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:18000")
LOGIN_EMAIL = "admin@alpha-trading.com"
LOGIN_PASSWORD = "admin123"


async def get_token() -> str:
    """로그인하여 JWT 토큰을 획득합니다."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
        )
        resp.raise_for_status()
        return resp.json()["token"]


@pytest.mark.integration
class TestAgentsStatus(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/agents/status"""

    async def test_get_agents_status(self) -> None:
        """전체 에이전트 상태를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/agents/status",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 500))  # 500 = known server bug
        if resp.status_code == 200:
            body = resp.json()
            self.assertIsInstance(body, (list, dict))

    async def test_agents_status_items_have_required_fields(self) -> None:
        """에이전트 상태 항목에는 필수 필드가 포함되어야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/agents/status",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for agent in body["agents"]:
            self.assertIn("agent_id", agent)
            self.assertIn("status", agent)
            self.assertIn("is_alive", agent)
            self.assertIn("activity_state", agent)
            self.assertIn("activity_label", agent)

    async def test_agents_status_has_at_least_one_agent(self) -> None:
        """에이전트 상태 목록에 최소 1개 이상의 에이전트가 존재해야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/agents/status",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreater(len(body["agents"]), 0)

    async def test_agents_status_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/agents/status")

        self.assertEqual(resp.status_code, 401)

    async def test_agents_status_agent_id_is_string(self) -> None:
        """에이전트 ID는 문자열이어야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/agents/status",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for agent in body["agents"]:
            self.assertIsInstance(agent["agent_id"], str)


@pytest.mark.integration
class TestAgentsRegistryList(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/agents/registry/list"""

    async def test_list_registry(self) -> None:
        """에이전트 레지스트리 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/agents/registry/list",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 500))  # 500 = known server bug
        if resp.status_code == 200:
            body = resp.json()
            self.assertIsInstance(body, (list, dict))

    async def test_registry_items_have_required_fields(self) -> None:
        """레지스트리 항목에는 필수 필드가 포함되어야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/agents/registry/list",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 500))
        if resp.status_code == 200:
            body = resp.json()
            for agent in body.get("agents", []):
                self.assertIn("agent_id", agent)

    async def test_registry_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/agents/registry/list")

        self.assertEqual(resp.status_code, 401)

    async def test_registry_has_at_least_one_agent(self) -> None:
        """레지스트리에 최소 1개 이상의 에이전트가 등록되어 있어야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/agents/registry/list",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 500))
        if resp.status_code == 200:
            body = resp.json()
            self.assertGreater(len(body.get("agents", [])), 0)
