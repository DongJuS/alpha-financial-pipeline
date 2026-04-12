"""
test/integration/test_api_strategy_debate_detail.py — Strategy B Debate Detail API 통합 테스트

FastAPI TestClient로 토론 단건 조회 및 목록 필터를 격리 테스트한다.
DB는 mock으로 대체.

테스트 대상:
  - GET /api/v1/strategy/b/debate/{debate_id}
  - GET /api/v1/strategy/b/debates?ticker=...
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers.strategy import router as strategy_router

API_PREFIX = "/api/v1/strategy"

_PATCH_PREFIX = "src.api.routers.strategy"


class _FakeRecord(dict):
    """asyncpg.Record를 흉내내는 dict 서브클래스.

    엔드포인트에서 ``dict(row)`` 로 변환하므로 dict 인터페이스를 제공한다.
    """

    def __getattr__(self, key: str):  # noqa: ANN001
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


_SAMPLE_DEBATE_ROW = _FakeRecord(
    id=42,
    date="2026-04-10",
    ticker="005930",
    rounds=3,
    consensus_reached=True,
    final_signal="BUY",
    confidence=0.85,
    proposer_content="삼성전자 매수 제안 근거 ...",
    challenger1_content="반대 의견 1 ...",
    challenger2_content="반대 의견 2 ...",
    synthesizer_content="종합 판단 ...",
    no_consensus_reason=None,
    created_at="2026-04-10T14:30:00+09:00",
)


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(strategy_router, prefix=API_PREFIX)
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
        jwt_secret="test-secret",
        strategy_blend_ratio=0.5,
    )
    return TestClient(app, raise_server_exceptions=False)


class TestGetDebateTranscriptSuccess:
    """GET /api/v1/strategy/b/debate/{debate_id} — 정상 조회"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_get_debate_transcript_success(self, mock_fetchrow: AsyncMock) -> None:
        """debate_id로 조회 시 정상 응답(200) + DebateResponse 구조 검증."""
        mock_fetchrow.return_value = _SAMPLE_DEBATE_ROW

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/b/debate/42")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 42
        assert body["ticker"] == "005930"
        assert body["consensus_reached"] is True
        assert body["final_signal"] == "BUY"
        assert body["rounds"] == 3
        mock_fetchrow.assert_awaited_once()


class TestGetDebateTranscriptNotFound:
    """GET /api/v1/strategy/b/debate/{debate_id} — 존재하지 않는 ID"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    def test_get_debate_transcript_not_found(self, mock_fetchrow: AsyncMock) -> None:
        """존재하지 않는 debate_id → 404 반환 검증."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/b/debate/99999")

        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        mock_fetchrow.assert_awaited_once()


class TestDebateResponseHasRequiredFields:
    """GET /api/v1/strategy/b/debate/{debate_id} — 필드 존재 검증"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_debate_response_has_required_fields(self, mock_fetchrow: AsyncMock) -> None:
        """응답에 DebateResponse 필수 필드가 모두 포함되는지 검증."""
        mock_fetchrow.return_value = _SAMPLE_DEBATE_ROW

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/b/debate/42")

        assert resp.status_code == 200
        body = resp.json()

        required_fields = [
            "id",
            "date",
            "ticker",
            "rounds",
            "consensus_reached",
            "proposer_content",
            "challenger1_content",
            "challenger2_content",
            "synthesizer_content",
        ]
        for field in required_fields:
            assert field in body, f"Missing required field: {field}"


class TestDebateWithoutTokenReturns401:
    """GET /api/v1/strategy/b/debate/{debate_id} — 미인증 요청"""

    def test_debate_without_token_returns_401(self) -> None:
        """미인증 요청 → 401 또는 403 반환 검증."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/b/debate/42")

        assert resp.status_code in (401, 403)


class TestListDebatesWithTickerFilter:
    """GET /api/v1/strategy/b/debates?ticker=005930 — 필터 파라미터 동작"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_list_debates_with_ticker_filter(self, mock_fetch: AsyncMock) -> None:
        """ticker 필터 파라미터가 DB 쿼리에 전달되는지 검증."""
        list_row = _FakeRecord(
            id=42,
            date="2026-04-10",
            ticker="005930",
            rounds=3,
            consensus_reached=True,
            final_signal="BUY",
            confidence=0.85,
            no_consensus_reason=None,
            created_at="2026-04-10T14:30:00+09:00",
        )
        mock_fetch.return_value = [list_row]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/b/debates", params={"ticker": "005930"})

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert len(body["items"]) == 1
        assert body["items"][0]["ticker"] == "005930"

        # ticker 파라미터가 fetch 호출에 전달되었는지 확인
        call_args = mock_fetch.call_args
        assert "005930" in call_args.args, "ticker 필터가 DB 쿼리에 전달되지 않았습니다"
