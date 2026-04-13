"""
test/integration/test_api_rl.py — RL API 통합 테스트

FastAPI TestClient로 RL 라우터를 격리 테스트한다.
파일시스템 기반 레지스트리는 mock으로 대체.

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

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers.rl import router as rl_router

API_PREFIX = "/api/v1/rl"

_PATCH_PREFIX = "src.api.routers.rl"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(rl_router, prefix=API_PREFIX)
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


def _mock_empty_store():
    """빈 DB를 시뮬레이션하는 store mock."""
    mock_store = MagicMock()
    mock_store.list_all_tickers = AsyncMock(return_value=[])
    mock_store.list_active_policies = AsyncMock(return_value={})
    mock_store.list_policies = AsyncMock(return_value=[])
    mock_store.load_policy = AsyncMock(return_value=None)
    return mock_store


def _mock_empty_exp_mgr():
    """빈 실험 관리자를 반환하는 mock."""
    mock_mgr = MagicMock()
    mock_mgr.list_runs.return_value = []
    return mock_mgr


class TestRLPolicies:
    """GET /api/v1/rl/policies"""

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_policies_returns_list_response(self, mock_get_store: MagicMock) -> None:
        """등록된 RL 정책 목록을 조회한다."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/policies")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert isinstance(body["data"], list)
        assert "total" in body["meta"]
        assert "page" in body["meta"]
        assert "per_page" in body["meta"]

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_policies_with_pagination(self, mock_get_store: MagicMock) -> None:
        """페이지네이션 파라미터를 전달할 수 있다."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/policies", params={"page": 1, "per_page": 5})
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["data"]) <= 5

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_policies_approved_only(self, mock_get_store: MagicMock) -> None:
        """승인된 정책만 필터링 조회할 수 있다."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/policies", params={"approved_only": True})
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body["data"], list)


class TestRLPoliciesActive:
    """GET /api/v1/rl/policies/active"""

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_active_policies(self, mock_get_store: MagicMock) -> None:
        """활성 정책 목록을 조회한다."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/policies/active")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert isinstance(body["data"], list)

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_active_policies_have_required_fields(self, mock_get_store: MagicMock) -> None:
        """활성 정책 항목에 필수 필드가 포함되어야 한다 (빈 목록에서도 구조 확인)."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/policies/active")
        assert resp.status_code == 200

        body = resp.json()
        # 데이터가 비었으면 구조만 확인
        assert "data" in body
        assert "meta" in body


class TestRLExperiments:
    """GET /api/v1/rl/experiments"""

    @patch(f"{_PATCH_PREFIX}._get_exp_mgr")
    def test_list_experiments(self, mock_get_mgr: MagicMock) -> None:
        """실험 실행 목록을 조회한다."""
        mock_get_mgr.return_value = _mock_empty_exp_mgr()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/experiments")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert isinstance(body["data"], list)

    @patch(f"{_PATCH_PREFIX}._get_exp_mgr")
    def test_list_experiments_with_pagination(self, mock_get_mgr: MagicMock) -> None:
        """실험 목록에 페이지네이션을 적용할 수 있다."""
        mock_get_mgr.return_value = _mock_empty_exp_mgr()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/experiments", params={"page": 1, "per_page": 5})
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["data"]) <= 5
        assert body["meta"]["per_page"] == 5

    @patch(f"{_PATCH_PREFIX}._get_exp_mgr")
    def test_list_experiments_approved_only(self, mock_get_mgr: MagicMock) -> None:
        """승인된 실험만 필터링 조회할 수 있다."""
        mock_get_mgr.return_value = _mock_empty_exp_mgr()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/experiments", params={"approved_only": True})
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body["data"], list)


class TestRLEvaluations:
    """GET /api/v1/rl/evaluations"""

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_evaluations(self, mock_get_store: MagicMock) -> None:
        """평가 결과 목록을 조회한다."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/evaluations")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert isinstance(body["data"], list)

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_evaluations_with_status_filter(self, mock_get_store: MagicMock) -> None:
        """상태 필터로 평가 결과를 조회할 수 있다."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/evaluations", params={"status": "approved"})
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body["data"], list)

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_evaluations_with_pagination(self, mock_get_store: MagicMock) -> None:
        """평가 결과 목록에 페이지네이션을 적용할 수 있다."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/evaluations", params={"page": 1, "per_page": 10})
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["data"]) <= 10

    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_evaluations_have_required_fields(self, mock_get_store: MagicMock) -> None:
        """평가 결과의 구조를 확인 (빈 목록)."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/evaluations")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "meta" in body


class TestRLTrainingJobs:
    """GET /api/v1/rl/training-jobs"""

    @patch("src.db.queries.list_training_jobs", new_callable=AsyncMock)
    def test_list_training_jobs(self, mock_list: AsyncMock) -> None:
        """학습 작업 목록을 조회한다."""
        mock_list.return_value = []
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/training-jobs")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "total" in body
        assert isinstance(body["data"], list)
        assert isinstance(body["total"], int)

    @patch("src.db.queries.list_training_jobs", new_callable=AsyncMock)
    def test_training_jobs_items_have_required_fields(self, mock_list: AsyncMock) -> None:
        """학습 작업 항목의 구조를 확인 (빈 목록에서도 구조 검증)."""
        mock_list.return_value = []
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/training-jobs")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "total" in body


class TestRLShadowPolicies:
    """GET /api/v1/rl/shadow/policies"""

    @patch(f"{_PATCH_PREFIX}._get_shadow_engine")
    def test_list_shadow_policies(self, mock_engine: MagicMock) -> None:
        """Shadow 모드 정책 목록을 조회한다."""
        engine_mock = MagicMock()
        engine_mock.list_shadow_policies.return_value = []
        mock_engine.return_value = engine_mock

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/shadow/policies")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert isinstance(body["data"], list)

    @patch(f"{_PATCH_PREFIX}._get_shadow_engine")
    def test_shadow_policies_meta_has_total(self, mock_engine: MagicMock) -> None:
        """Shadow 정책 목록의 meta에 total 필드가 포함되어야 한다."""
        engine_mock = MagicMock()
        engine_mock.list_shadow_policies.return_value = []
        mock_engine.return_value = engine_mock

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/shadow/policies")
        assert resp.status_code == 200

        body = resp.json()
        assert "total" in body["meta"]
        assert isinstance(body["meta"]["total"], int)


class TestRLTickers:
    """RL 종목 관리 API: GET/PUT/DELETE /api/v1/rl/tickers"""

    @patch("src.db.queries.list_rl_targets", new_callable=AsyncMock, return_value=[])
    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_rl_tickers(self, mock_get_store: MagicMock, mock_list_targets: AsyncMock) -> None:
        """RL 대상 종목 목록을 조회한다."""
        mock_get_store.return_value = _mock_empty_store()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/tickers")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, dict)
        assert "tickers" in body
        assert "total" in body

    @patch("src.db.queries.list_rl_targets", new_callable=AsyncMock, return_value=[
        {"instrument_id": "005930.KS", "data_scope": "daily"},
    ])
    @patch(f"{_PATCH_PREFIX}._get_store")
    def test_list_rl_tickers_returns_data(self, mock_get_store: MagicMock, mock_list_targets: AsyncMock) -> None:
        """RL 대상 종목 목록이 데이터를 포함한다."""
        mock_store = _mock_empty_store()
        mock_store.list_active_policies = AsyncMock(return_value={"005930.KS": "policy_1"})
        mock_get_store.return_value = mock_store

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/tickers")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, dict)
        assert "tickers" in body
        assert len(body["tickers"]) == 1
        assert body["tickers"][0]["ticker"] == "005930.KS"
        assert body["tickers"][0]["data_scope"] == "daily"
        assert body["tickers"][0]["active_policy_id"] == "policy_1"
        assert body["tickers"][0]["has_policy"] is True
        assert body["total"] == 1

    @patch("src.db.queries.insert_training_job", new_callable=AsyncMock, return_value="rl-job-test")
    @patch("src.db.queries.find_queued_training_job", new_callable=AsyncMock, return_value=None)
    @patch(f"{_PATCH_PREFIX}._get_store")
    @patch("src.db.queries.list_rl_target_tickers", new_callable=AsyncMock, return_value=["005930.KS", "000660.KS"])
    @patch("src.db.queries.upsert_rl_targets", new_callable=AsyncMock, return_value=["000660.KS"])
    def test_put_rl_tickers(
        self,
        mock_upsert: AsyncMock,
        mock_list: AsyncMock,
        mock_store: MagicMock,
        mock_find: AsyncMock,
        mock_insert: AsyncMock,
    ) -> None:
        """PUT /tickers -- RL 대상 종목을 추가하고 학습 작업을 자동 생성한다."""
        mock_store.return_value = _mock_empty_store()
        client = _build_client()
        resp = client.put(
            f"{API_PREFIX}/tickers",
            json={"tickers": ["005930.KS", "000660.KS"], "data_scope": "daily"},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert "tickers" in body
        assert "added" in body
        assert "auto_training_jobs" in body
        assert "total" in body
        assert body["total"] == 2
        mock_upsert.assert_awaited_once_with(["005930.KS", "000660.KS"], data_scope="daily")

    @patch("src.db.queries.list_rl_target_tickers", new_callable=AsyncMock, return_value=["005930.KS"])
    @patch("src.db.queries.remove_rl_target", new_callable=AsyncMock, return_value=True)
    def test_delete_rl_ticker(self, mock_remove: AsyncMock, mock_list: AsyncMock) -> None:
        """DELETE /tickers/{ticker} -- RL 대상 종목을 제거한다."""
        client = _build_client()
        resp = client.delete(f"{API_PREFIX}/tickers/000660.KS")
        assert resp.status_code == 200

        body = resp.json()
        assert body["removed"] == "000660.KS"
        assert "remaining" in body
        assert "total" in body
        mock_remove.assert_awaited_once_with("000660.KS")

    @patch("src.db.queries.remove_rl_target", new_callable=AsyncMock, return_value=False)
    def test_delete_rl_ticker_not_found(self, mock_remove: AsyncMock) -> None:
        """DELETE /tickers/{ticker} -- 존재하지 않는 종목 제거 시 404."""
        client = _build_client()
        resp = client.delete(f"{API_PREFIX}/tickers/999999.KS")
        assert resp.status_code == 404
