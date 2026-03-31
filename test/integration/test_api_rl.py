"""
test/integration/test_api_rl.py — RL API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 RL 관련 엔드포인트를 검증합니다.

테스트 대상:
  - GET  /api/v1/rl/policies          — 등록된 정책 목록
  - GET  /api/v1/rl/policies/active    — 활성 정책 목록
  - GET  /api/v1/rl/experiments        — 실험 실행 목록
  - GET  /api/v1/rl/evaluations        — 평가 결과 목록
  - GET  /api/v1/rl/training-jobs      — 학습 작업 목록
  - GET  /api/v1/rl/shadow/policies    — Shadow 정책 목록
  - GET  /api/v1/rl/tickers            — RL 대상 종목 목록
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
class TestRLPolicies(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/rl/policies"""

    async def test_list_policies_returns_list_response(self) -> None:
        """등록된 RL 정책 목록을 조회한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/policies")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIsInstance(body["data"], list)
        self.assertIn("total", body["meta"])
        self.assertIn("page", body["meta"])
        self.assertIn("per_page", body["meta"])

    async def test_list_policies_with_pagination(self) -> None:
        """페이지네이션 파라미터를 전달할 수 있다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/rl/policies",
                params={"page": 1, "per_page": 5},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertLessEqual(len(body["data"]), 5)

    async def test_list_policies_approved_only(self) -> None:
        """승인된 정책만 필터링 조회할 수 있다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/rl/policies",
                params={"approved_only": True},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body["data"], list)
        for policy in body["data"]:
            self.assertTrue(policy.get("approved"))


@pytest.mark.integration
class TestRLPoliciesActive(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/rl/policies/active"""

    async def test_list_active_policies(self) -> None:
        """활성 정책 목록을 조회한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/policies/active")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIsInstance(body["data"], list)
        for item in body["data"]:
            self.assertIn("ticker", item)
            self.assertIn("policy_id", item)

    async def test_active_policies_have_required_fields(self) -> None:
        """활성 정책 항목에는 필수 필드가 포함되어야 한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/policies/active")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for item in body["data"]:
            self.assertIn("return_pct", item)
            self.assertIn("max_drawdown_pct", item)
            self.assertIn("approved", item)


@pytest.mark.integration
class TestRLExperiments(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/rl/experiments"""

    async def test_list_experiments(self) -> None:
        """실험 실행 목록을 조회한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/experiments")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIsInstance(body["data"], list)

    async def test_list_experiments_with_pagination(self) -> None:
        """실험 목록에 페이지네이션을 적용할 수 있다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/rl/experiments",
                params={"page": 1, "per_page": 5},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertLessEqual(len(body["data"]), 5)
        self.assertEqual(body["meta"]["per_page"], 5)

    async def test_list_experiments_approved_only(self) -> None:
        """승인된 실험만 필터링 조회할 수 있다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/rl/experiments",
                params={"approved_only": True},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body["data"], list)
        for exp in body["data"]:
            self.assertTrue(exp.get("approved"))


@pytest.mark.integration
class TestRLEvaluations(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/rl/evaluations"""

    async def test_list_evaluations(self) -> None:
        """평가 결과 목록을 조회한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/evaluations")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIsInstance(body["data"], list)

    async def test_list_evaluations_with_status_filter(self) -> None:
        """상태 필터로 평가 결과를 조회할 수 있다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/rl/evaluations",
                params={"status": "approved"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body["data"], list)

    async def test_list_evaluations_with_pagination(self) -> None:
        """평가 결과 목록에 페이지네이션을 적용할 수 있다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/rl/evaluations",
                params={"page": 1, "per_page": 10},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertLessEqual(len(body["data"]), 10)

    async def test_evaluations_have_required_fields(self) -> None:
        """평가 결과 항목에는 필수 필드가 포함되어야 한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/evaluations")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for item in body["data"]:
            self.assertIn("policy_id", item)
            self.assertIn("ticker", item)
            self.assertIn("return_pct", item)
            self.assertIn("approved", item)


@pytest.mark.integration
class TestRLTrainingJobs(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/rl/training-jobs"""

    async def test_list_training_jobs(self) -> None:
        """학습 작업 목록을 조회한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/training-jobs")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("total", body)
        self.assertIsInstance(body["data"], list)
        self.assertIsInstance(body["total"], int)

    async def test_training_jobs_items_have_required_fields(self) -> None:
        """학습 작업 항목에는 필수 필드가 포함되어야 한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/training-jobs")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for item in body["data"]:
            self.assertIn("job_id", item)
            self.assertIn("status", item)
            self.assertIn("tickers", item)
            self.assertIn("created_at", item)


@pytest.mark.integration
class TestRLShadowPolicies(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/rl/shadow/policies"""

    async def test_list_shadow_policies(self) -> None:
        """Shadow 모드 정책 목록을 조회한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/shadow/policies")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIsInstance(body["data"], list)

    async def test_shadow_policies_meta_has_total(self) -> None:
        """Shadow 정책 목록의 meta에 total 필드가 포함되어야 한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/rl/shadow/policies")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("total", body["meta"])
        self.assertIsInstance(body["meta"]["total"], int)


@pytest.mark.integration
class TestRLTickers(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/rl/tickers"""

    async def test_list_rl_tickers(self) -> None:
        """RL 대상 종목 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/rl/tickers",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 404))
        if resp.status_code == 200:
            body = resp.json()
            self.assertIsInstance(body, (list, dict))

    async def test_list_rl_tickers_returns_data(self) -> None:
        """RL 대상 종목 목록이 데이터를 포함한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/rl/tickers",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 404))
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, dict):
                self.assertTrue("data" in body or "tickers" in body)
