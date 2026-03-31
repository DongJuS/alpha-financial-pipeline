"""
test/integration/test_api_datalake.py — DataLake API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 데이터 레이크 엔드포인트를 검증합니다.

테스트 대상:
  - GET  /api/v1/datalake/overview     — 데이터 레이크 개요
  - GET  /api/v1/datalake/objects      — 오브젝트 목록
  - GET  /api/v1/datalake/object-info  — 오브젝트 상세 정보
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
class TestDatalakeOverview(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/datalake/overview"""

    async def test_get_overview(self) -> None:
        """데이터 레이크 개요를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            resp = await client.get(
                "/api/v1/datalake/overview",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("bucket_name", body)
        self.assertIn("total_objects", body)
        self.assertIn("total_size_bytes", body)
        self.assertIn("total_size_display", body)
        self.assertIn("prefixes", body)

    async def test_overview_has_valid_types(self) -> None:
        """개요 응답의 필드 타입이 올바른지 확인한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            resp = await client.get(
                "/api/v1/datalake/overview",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body["bucket_name"], str)
        self.assertIsInstance(body["total_objects"], int)
        self.assertIsInstance(body["total_size_bytes"], int)
        self.assertIsInstance(body["total_size_display"], str)
        self.assertIsInstance(body["prefixes"], list)

    async def test_overview_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/datalake/overview")

        self.assertEqual(resp.status_code, 401)


@pytest.mark.integration
class TestDatalakeObjects(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/datalake/objects"""

    async def test_list_objects(self) -> None:
        """오브젝트 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            resp = await client.get(
                "/api/v1/datalake/objects",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("prefix", body)
        self.assertIn("objects", body)
        self.assertIn("common_prefixes", body)
        self.assertIn("total", body)

    async def test_list_objects_has_valid_types(self) -> None:
        """오브젝트 목록 응답의 필드 타입이 올바른지 확인한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            resp = await client.get(
                "/api/v1/datalake/objects",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body["prefix"], str)
        self.assertIsInstance(body["objects"], list)
        self.assertIsInstance(body["common_prefixes"], list)
        self.assertIsInstance(body["total"], int)

    async def test_list_objects_with_prefix(self) -> None:
        """특정 접두사로 오브젝트를 조회할 수 있다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            resp = await client.get(
                "/api/v1/datalake/objects",
                params={"prefix": "rl/"},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["prefix"], "rl/")


@pytest.mark.integration
class TestDatalakeObjectInfo(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/datalake/object-info"""

    async def test_object_info_requires_key(self) -> None:
        """key 파라미터 없이 요청하면 422를 반환한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/datalake/object-info",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 422)

    async def test_object_info_not_found(self) -> None:
        """존재하지 않는 키로 조회하면 404를 반환한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/datalake/object-info",
                params={"key": "nonexistent/object/key.json"},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 404)

    async def test_object_info_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/datalake/object-info",
                params={"key": "test/key"},
            )

        self.assertEqual(resp.status_code, 401)
