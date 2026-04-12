"""
test/test_datalake_s3_error_handling.py — Datalake S3 에러 처리 검증

S3/MinIO 연결 실패 시 4개 엔드포인트 모두 502 JSON 응답을 반환하고,
응답 body에 S3 내부 정보(bucket name, endpoint URL)가 노출되지 않는지 확인한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_admin_user, get_current_settings, get_current_user
from src.api.routers.datalake import router as datalake_router

API_PREFIX = "/api/v1/datalake"
_PATCH_PREFIX = "src.api.routers.datalake"

# S3 내부 정보가 에러 응답에 노출되면 안 되는 키워드 목록
_FORBIDDEN_LEAK_KEYWORDS = [
    "test-bucket",
    "alpha-bucket",
    "minio",
    "s3.amazonaws.com",
    "endpoint",
    "Could not connect",
    "service unavailable",
    "botocore",
    "ClientError",
]


def _build_client() -> TestClient:
    """인증 우회된 FastAPI TestClient를 생성한다 (admin 권한 포함)."""
    app = FastAPI()
    app.include_router(datalake_router, prefix=API_PREFIX)

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
        jwt_secret="test-secret"
    )
    return TestClient(app, raise_server_exceptions=False)


def _mock_settings():
    return SimpleNamespace(s3_bucket_name="test-bucket")


# ======================================================================
# 개별 엔드포인트 502 반환 테스트
# ======================================================================


class TestDatalakeS3ErrorHandling:
    """S3 연결 실패 시 모든 엔드포인트가 502 JSON을 반환하는지 검증한다."""

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_overview_s3_connection_error_returns_502(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """GET /overview -- S3 paginator 예외 시 502 JSON 반환."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = ConnectionError(
            "Could not connect to the endpoint URL: https://minio.local:9000"
        )
        mock_client.get_paginator.return_value = mock_paginator
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/overview")

        assert resp.status_code == 502
        body = resp.json()
        assert "detail" in body
        assert body["detail"] == "S3 스토리지 연결에 실패했습니다."

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_objects_s3_connection_error_returns_502(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """GET /objects -- S3 list_objects_v2 예외 시 502 JSON 반환."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client.list_objects_v2.side_effect = ConnectionError(
            "S3 service unavailable"
        )
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/objects")

        assert resp.status_code == 502
        body = resp.json()
        assert "detail" in body
        assert body["detail"] == "S3 스토리지 연결에 실패했습니다."

    @patch(f"{_PATCH_PREFIX}.asyncio")
    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_object_info_s3_connection_error_returns_502(
        self, mock_settings: MagicMock, mock_s3: MagicMock, mock_asyncio: MagicMock
    ) -> None:
        """GET /object-info -- asyncio.to_thread 레벨 에러 시 502 JSON 반환.

        /object-info의 내부 _head() 함수는 자체 try/except로 S3 에러를 잡아
        None을 반환한다. 외부 try/except는 asyncio.to_thread 자체가 실패하는
        경우(스레드 풀 고갈 등)를 방어한다.
        """
        mock_settings.return_value = _mock_settings()
        mock_s3.return_value = MagicMock()

        # asyncio.to_thread가 RuntimeError를 던지는 상황 시뮬레이션
        import asyncio as real_asyncio

        async def _failing_to_thread(*args, **kwargs):
            raise RuntimeError("Thread pool exhausted")

        mock_asyncio.to_thread = _failing_to_thread

        client = _build_client()
        resp = client.get(
            f"{API_PREFIX}/object-info",
            params={"key": "some/key.json"},
        )

        assert resp.status_code == 502
        body = resp.json()
        assert "detail" in body
        assert body["detail"] == "S3 스토리지 연결에 실패했습니다."

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_delete_object_s3_connection_error_returns_502(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """DELETE /objects -- S3 delete_object 예외 시 502 JSON 반환."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = ConnectionError(
            "Could not connect to the endpoint URL: https://minio.local:9000"
        )
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.delete(
            f"{API_PREFIX}/objects",
            params={"key": "some/key.json"},
        )

        assert resp.status_code == 502
        body = resp.json()
        assert "detail" in body
        assert body["detail"] == "S3 스토리지 연결에 실패했습니다."


# ======================================================================
# 정보 누출 방지 테스트
# ======================================================================


class TestS3ErrorNoInfoLeak:
    """에러 응답에 S3 내부 정보가 포함되지 않는지 검증한다."""

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_s3_error_does_not_leak_bucket_info(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """S3 에러 응답의 detail에 bucket name, URL 등 내부 정보가 없어야 한다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        # 원본 에러 메시지에 민감 정보를 의도적으로 포함
        mock_paginator.paginate.side_effect = Exception(
            "An error occurred (AccessDenied) when calling ListObjectsV2 "
            "on bucket test-bucket at https://s3.amazonaws.com: Access Denied"
        )
        mock_client.get_paginator.return_value = mock_paginator
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/overview")

        assert resp.status_code == 502
        body = resp.json()
        detail = body["detail"]

        for keyword in _FORBIDDEN_LEAK_KEYWORDS:
            assert keyword.lower() not in detail.lower(), (
                f"에러 응답에 민감 정보 '{keyword}'가 노출됨: {detail}"
            )

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_s3_error_does_not_leak_in_objects_endpoint(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """GET /objects 에러 응답에도 내부 정보가 노출되지 않아야 한다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client.list_objects_v2.side_effect = Exception(
            "botocore.exceptions.ClientError: bucket=test-bucket "
            "endpoint=https://minio.local:9000"
        )
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/objects")

        assert resp.status_code == 502
        body = resp.json()
        detail = body["detail"]

        for keyword in _FORBIDDEN_LEAK_KEYWORDS:
            assert keyword.lower() not in detail.lower(), (
                f"에러 응답에 민감 정보 '{keyword}'가 노출됨: {detail}"
            )

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_s3_error_does_not_leak_in_delete_endpoint(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """DELETE /objects 에러 응답에도 내부 정보가 노출되지 않아야 한다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = Exception(
            "botocore.exceptions.EndpointConnectionError: "
            "Could not connect to https://minio.local:9000/test-bucket"
        )
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.delete(
            f"{API_PREFIX}/objects",
            params={"key": "some/key.json"},
        )

        assert resp.status_code == 502
        body = resp.json()
        detail = body["detail"]

        for keyword in _FORBIDDEN_LEAK_KEYWORDS:
            assert keyword.lower() not in detail.lower(), (
                f"에러 응답에 민감 정보 '{keyword}'가 노출됨: {detail}"
            )
