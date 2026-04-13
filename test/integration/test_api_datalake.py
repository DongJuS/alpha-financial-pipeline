"""
test/integration/test_api_datalake.py — DataLake API 통합 테스트

FastAPI TestClient로 데이터 레이크 라우터를 격리 테스트한다.
S3/MinIO는 mock으로 대체.

테스트 대상:
  - GET  /api/v1/datalake/overview     — 데이터 레이크 개요
  - GET  /api/v1/datalake/objects      — 오브젝트 목록
  - GET  /api/v1/datalake/object-info  — 오브젝트 상세 정보
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers.datalake import router as datalake_router

API_PREFIX = "/api/v1/datalake"

_PATCH_PREFIX = "src.api.routers.datalake"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(datalake_router, prefix=API_PREFIX)
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


def _mock_settings():
    return SimpleNamespace(s3_bucket_name="test-bucket")


def _mock_s3_client_for_overview():
    """overview 용 S3 mock: paginate 지원."""
    mock_client = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": "rl/model_v1.pt", "Size": 1024},
                {"Key": "rl/model_v2.pt", "Size": 2048},
                {"Key": "daily/005930.parquet", "Size": 4096},
            ],
        },
    ]
    mock_client.get_paginator.return_value = mock_paginator
    return mock_client


def _mock_s3_client_for_list():
    """objects 용 S3 mock: list_objects_v2 지원."""
    mock_client = MagicMock()
    mock_client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "rl/model_v1.pt", "Size": 1024, "LastModified": None, "StorageClass": "STANDARD"},
        ],
        "CommonPrefixes": [{"Prefix": "daily/"}],
    }
    return mock_client


class TestDatalakeOverview:
    """GET /api/v1/datalake/overview"""

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_get_overview(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """데이터 레이크 개요를 조회한다."""
        mock_settings.return_value = _mock_settings()
        mock_s3.return_value = _mock_s3_client_for_overview()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert "bucket_name" in body
        assert "total_objects" in body
        assert "total_size_bytes" in body
        assert "total_size_display" in body
        assert "prefixes" in body

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_overview_has_valid_types(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """개요 응답의 필드 타입이 올바른지 확인한다."""
        mock_settings.return_value = _mock_settings()
        mock_s3.return_value = _mock_s3_client_for_overview()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["bucket_name"], str)
        assert isinstance(body["total_objects"], int)
        assert isinstance(body["total_size_bytes"], int)
        assert isinstance(body["total_size_display"], str)
        assert isinstance(body["prefixes"], list)

    def test_overview_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/overview")
        assert resp.status_code in (401, 403)


class TestDatalakeObjects:
    """GET /api/v1/datalake/objects"""

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_list_objects(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """오브젝트 목록을 조회한다."""
        mock_settings.return_value = _mock_settings()
        mock_s3.return_value = _mock_s3_client_for_list()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/objects")
        assert resp.status_code == 200
        body = resp.json()
        assert "prefix" in body
        assert "objects" in body
        assert "common_prefixes" in body
        assert "total" in body

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_list_objects_has_valid_types(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """오브젝트 목록 응답의 필드 타입이 올바른지 확인한다."""
        mock_settings.return_value = _mock_settings()
        mock_s3.return_value = _mock_s3_client_for_list()

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/objects")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["prefix"], str)
        assert isinstance(body["objects"], list)
        assert isinstance(body["common_prefixes"], list)
        assert isinstance(body["total"], int)

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_list_objects_with_prefix(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """특정 접두사로 오브젝트를 조회할 수 있다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {
            "Contents": [],
            "CommonPrefixes": [],
        }
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/objects", params={"prefix": "rl/"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["prefix"] == "rl/"


class TestDatalakeObjectInfo:
    """GET /api/v1/datalake/object-info"""

    def test_object_info_requires_key(self) -> None:
        """key 파라미터 없이 요청하면 422를 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/object-info")
        assert resp.status_code == 422

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_object_info_not_found(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """존재하지 않는 키로 조회하면 404를 반환한다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client.head_object.side_effect = Exception("NoSuchKey")
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(
            f"{API_PREFIX}/object-info",
            params={"key": "nonexistent/object/key.json"},
        )
        assert resp.status_code == 404

    def test_object_info_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(
            f"{API_PREFIX}/object-info",
            params={"key": "test/key"},
        )
        assert resp.status_code in (401, 403)
