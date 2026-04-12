"""
test/test_qa_datalake_predictor.py — QA Round 2 커버리지 보강

Datalake S3 연결 실패 / 빈 버킷 시나리오와
Predictor 에러 처리 / fallback 검증을 추가한다.

테스트 대상:
  - Datalake: S3 연결 예외 시 graceful 에러 응답, 빈 버킷 정상 처리
  - Predictor: 전원 실패 RuntimeError, fallback primary 실패 기록, 성공 시 구조 검증
"""

from __future__ import annotations

import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers.datalake import router as datalake_router
from src.agents.predictor import PredictorAgent

# ──────────────────────────────────────────────
# Datalake 공통 헬퍼
# ──────────────────────────────────────────────

API_PREFIX = "/api/v1/datalake"
_PATCH_PREFIX = "src.api.routers.datalake"


def _build_client() -> TestClient:
    """인증 우회된 FastAPI TestClient를 생성한다."""
    app = FastAPI()
    app.include_router(datalake_router, prefix=API_PREFIX)

    async def mock_user():
        return {
            "sub": str(uuid4()),
            "email": "qa@test.com",
            "name": "QATester",
            "is_admin": True,
        }

    app.dependency_overrides[get_current_user] = mock_user
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="test-secret"
    )
    return TestClient(app, raise_server_exceptions=False)


def _mock_settings():
    return SimpleNamespace(s3_bucket_name="test-bucket")


# ──────────────────────────────────────────────
# Predictor 공통 헬퍼
# ──────────────────────────────────────────────


def _build_candles(count: int = 20) -> list[dict]:
    candles: list[dict] = []
    for idx in range(count):
        price = 100_000 + (count - idx) * 100
        candles.append(
            {
                "timestamp_kst": f"2026-03-{count - idx:02d}T15:30:00+09:00",
                "open": price - 50,
                "high": price + 100,
                "low": price - 100,
                "close": price,
                "volume": 100_000 + idx,
            }
        )
    return candles


# ======================================================================
# Datalake S3 연결 실패 테스트
# ======================================================================


class TestDatalakeS3ConnectionError:
    """S3/MinIO 연결 실패 시 엔드포인트의 graceful 에러 처리를 검증한다."""

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_datalake_overview_s3_connection_error(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """S3 클라이언트의 paginator가 예외를 던질 때 overview가 502 에러를 반환한다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = Exception(
            "Could not connect to the endpoint URL"
        )
        mock_client.get_paginator.return_value = mock_paginator
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/overview")

        # S3 연결 실패 시 502 Bad Gateway가 발생해야 한다
        assert resp.status_code == 502
        body = resp.json()
        assert "detail" in body
        assert "S3" in body["detail"]

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_datalake_objects_s3_unavailable(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """S3 list_objects_v2가 실패할 때 objects 엔드포인트가 502 에러를 반환한다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client.list_objects_v2.side_effect = Exception(
            "S3 service unavailable"
        )
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/objects")

        # S3 연결 실패 시 502 Bad Gateway가 발생해야 한다
        assert resp.status_code == 502
        body = resp.json()
        assert "detail" in body
        assert "S3" in body["detail"]

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_datalake_overview_empty_bucket(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """S3가 정상이나 버킷이 비어있을 때 overview가 0값을 정상 반환한다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        # 빈 버킷: Contents 키가 없는 페이지 반환
        mock_paginator.paginate.return_value = [{}]
        mock_client.get_paginator.return_value = mock_paginator
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/overview")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_objects"] == 0
        assert body["total_size_bytes"] == 0
        assert body["prefixes"] == []
        assert body["bucket_name"] == "test-bucket"

    @patch(f"{_PATCH_PREFIX}._get_s3_client")
    @patch(f"{_PATCH_PREFIX}.get_settings")
    def test_datalake_delete_s3_connection_error(
        self, mock_settings: MagicMock, mock_s3: MagicMock
    ) -> None:
        """S3 delete_object가 실패할 때 delete 엔드포인트가 502 에러를 반환한다."""
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = Exception(
            "Could not connect to the endpoint URL"
        )
        mock_s3.return_value = mock_client

        client = _build_client()
        resp = client.delete(f"{API_PREFIX}/objects", params={"key": "test/file.txt"})

        assert resp.status_code == 502
        body = resp.json()
        assert "detail" in body
        assert "S3" in body["detail"]


# ======================================================================
# Predictor 에러 처리 테스트
# ======================================================================


class TestPredictorErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Predictor의 에러 처리 및 fallback 동작을 검증한다."""

    async def test_predictor_all_providers_fail_raises_runtime_error(self) -> None:
        """모든 LLM 프로바이더가 configured=False일 때 RuntimeError가 발생한다."""
        agent = PredictorAgent(llm_model="gpt-4o-mini")
        agent.router._clients = {
            "gpt": types.SimpleNamespace(is_configured=False, ask_json=AsyncMock()),
            "claude": types.SimpleNamespace(is_configured=False, ask_json=AsyncMock()),
            "gemini": types.SimpleNamespace(is_configured=False, ask_json=AsyncMock()),
        }

        with self.assertRaises(RuntimeError) as ctx:
            await agent._llm_signal("005930", _build_candles())

        # 에러 메시지에 모든 프로바이더 실패 관련 내용이 포함되어야 한다
        error_msg = str(ctx.exception)
        assert "failed" in error_msg.lower() or "LLM" in error_msg

    async def test_predictor_fallback_records_primary_failure(self) -> None:
        """primary 실패 -> secondary 성공 시, primary의 ask_json이 호출되고 실패했음을 검증한다."""
        agent = PredictorAgent(llm_model="gpt-4o-mini")

        mock_gpt = types.SimpleNamespace(
            is_configured=True,
            ask_json=AsyncMock(side_effect=RuntimeError("quota exceeded")),
        )
        mock_claude = types.SimpleNamespace(
            is_configured=True,
            ask_json=AsyncMock(
                return_value={
                    "signal": "BUY",
                    "confidence": 0.85,
                    "target_price": 70000,
                    "stop_loss": 65000,
                    "reasoning_summary": "fallback success",
                }
            ),
        )
        mock_gemini = types.SimpleNamespace(
            is_configured=True,
            ask_json=AsyncMock(return_value={"signal": "HOLD", "confidence": 0.5}),
        )
        agent.router._clients = {
            "gpt": mock_gpt,
            "claude": mock_claude,
            "gemini": mock_gemini,
        }

        result = await agent._llm_signal("005930", _build_candles())

        # primary(gpt)가 호출되었고 실패했어야 한다
        mock_gpt.ask_json.assert_awaited_once()
        # secondary(claude)가 호출되어 성공했어야 한다
        mock_claude.ask_json.assert_awaited_once()
        # tertiary(gemini)는 호출되지 않았어야 한다
        mock_gemini.ask_json.assert_not_awaited()
        # 결과는 secondary의 응답이어야 한다
        self.assertEqual(result["signal"], "BUY")

    async def test_predictor_signal_structure_on_success(self) -> None:
        """성공 시 반환값에 signal, confidence 키가 포함되는지 구조를 검증한다."""
        agent = PredictorAgent(llm_model="claude-3-5-sonnet-latest")

        mock_claude = types.SimpleNamespace(
            is_configured=True,
            ask_json=AsyncMock(
                return_value={
                    "signal": "SELL",
                    "confidence": 0.72,
                    "target_price": None,
                    "stop_loss": 95000,
                    "reasoning_summary": "하락 추세 감지",
                }
            ),
        )
        agent.router._clients = {
            "claude": mock_claude,
            "gpt": types.SimpleNamespace(is_configured=False, ask_json=AsyncMock()),
            "gemini": types.SimpleNamespace(is_configured=False, ask_json=AsyncMock()),
        }

        result = await agent._llm_signal("005930", _build_candles())

        # 필수 키 존재 검증
        assert "signal" in result
        assert "confidence" in result
        # signal 값이 유효한 enum 값인지 검증
        assert result["signal"] in {"BUY", "SELL", "HOLD"}
        # confidence가 0~1 범위인지 검증
        assert 0.0 <= result["confidence"] <= 1.0
        # 추가 필드 존재 검증
        assert "target_price" in result
        assert "stop_loss" in result
        assert "reasoning_summary" in result
