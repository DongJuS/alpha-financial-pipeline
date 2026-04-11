"""
test/test_index_collector.py — IndexCollector KOSPI/KOSDAQ 지수 ���집 테스트

수집 로직, Redis 캐시 TTL, 자격증명 미설정 시 동작, DB 저장 검증.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

KST = ZoneInfo("Asia/Seoul")
pytestmark = [pytest.mark.unit]


# =============================================================================
# Constants
# =============================================================================


class TestIndexCollectorConstants:
    """IndexCollector 상수 검증."""

    def test_kospi_code(self):
        from src.agents.index_collector import KOSPI_CODE
        assert KOSPI_CODE == "0001"

    def test_kosdaq_code(self):
        from src.agents.index_collector import KOSDAQ_CODE
        assert KOSDAQ_CODE == "1001"


# =============================================================================
# IndexCollector 초기화
# =============================================================================


class TestIndexCollectorInit:
    """IndexCollector 초기화 검증."""

    def test_init(self):
        with patch("src.agents.index_collector.KISPaperApiClient"):
            from src.agents.index_collector import IndexCollector
            collector = IndexCollector()
            assert collector._missing_credentials_logged is False

    def test_has_client(self):
        with patch("src.agents.index_collector.KISPaperApiClient"):
            from src.agents.index_collector import IndexCollector
            collector = IndexCollector()
            assert collector.client is not None


# =============================================================================
# collect_once
# =============================================================================


class TestCollectOnce:
    """collect_once 메서드 검증."""

    async def test_missing_credentials_skips(self):
        """KIS 자격증명 미설정 시 수집 건너뜀."""
        with patch("src.agents.index_collector.KISPaperApiClient") as MockClient:
            mock_client = MagicMock()
            mock_client.settings = MagicMock()
            mock_client.account_scope = "paper"
            MockClient.return_value = mock_client

            with patch("src.agents.index_collector.has_kis_credentials", return_value=False):
                from src.agents.index_collector import IndexCollector
                collector = IndexCollector()
                result = await collector.collect_once()

        assert result["success"] is True
        assert result["skipped"] is True
        assert result["reason"] == "missing_kis_credentials"

    async def test_missing_credentials_logged_once(self):
        """자격증명 미설정 경고가 한 번만 로깅."""
        with patch("src.agents.index_collector.KISPaperApiClient") as MockClient:
            mock_client = MagicMock()
            mock_client.settings = MagicMock()
            mock_client.account_scope = "paper"
            MockClient.return_value = mock_client

            with patch("src.agents.index_collector.has_kis_credentials", return_value=False):
                from src.agents.index_collector import IndexCollector
                collector = IndexCollector()
                await collector.collect_once()
                assert collector._missing_credentials_logged is True
                await collector.collect_once()
                # 두 번째 호출에서도 여전히 True

    async def test_successful_collection(self):
        """정상 수집 시 KOSPI/KOSDAQ 데이터 반환."""
        with patch("src.agents.index_collector.KISPaperApiClient") as MockClient:
            mock_client = MagicMock()
            mock_client.settings = MagicMock()
            mock_client.account_scope = "paper"
            mock_client.fetch_index_quote = AsyncMock(side_effect=[
                {"value": 2800.0, "change_pct": 0.5, "previous_close": 2786.0},
                {"value": 900.0, "change_pct": -0.3, "previous_close": 902.7},
            ])
            MockClient.return_value = mock_client

            redis_mock = AsyncMock()
            redis_mock.set = AsyncMock()

            with (
                patch("src.agents.index_collector.has_kis_credentials", return_value=True),
                patch("src.agents.index_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
                patch("src.agents.index_collector.upsert_macro_indicators", new_callable=AsyncMock, return_value=2),
            ):
                from src.agents.index_collector import IndexCollector
                collector = IndexCollector()
                result = await collector.collect_once()

        assert result["success"] is True
        assert "kospi" in result
        assert "kosdaq" in result
        assert result["kospi"]["value"] == 2800.0

    async def test_redis_cache_ttl(self):
        """Redis 캐시에 TTL이 설정되는지 확인."""
        with patch("src.agents.index_collector.KISPaperApiClient") as MockClient:
            mock_client = MagicMock()
            mock_client.settings = MagicMock()
            mock_client.account_scope = "paper"
            mock_client.fetch_index_quote = AsyncMock(return_value={
                "value": 2800.0, "change_pct": 0.5,
            })
            MockClient.return_value = mock_client

            redis_mock = AsyncMock()
            redis_mock.set = AsyncMock()

            with (
                patch("src.agents.index_collector.has_kis_credentials", return_value=True),
                patch("src.agents.index_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
                patch("src.agents.index_collector.upsert_macro_indicators", new_callable=AsyncMock),
            ):
                from src.agents.index_collector import IndexCollector, TTL_MARKET_INDEX
                collector = IndexCollector()
                await collector.collect_once()

            # Redis set이 TTL과 함께 호출됨
            redis_mock.set.assert_awaited_once()
            call_kwargs = redis_mock.set.call_args
            assert call_kwargs.kwargs.get("ex") == TTL_MARKET_INDEX or call_kwargs[1].get("ex") == TTL_MARKET_INDEX

    async def test_api_error_returns_failure(self):
        """KIS API 오류 시 success=False 반환."""
        with patch("src.agents.index_collector.KISPaperApiClient") as MockClient:
            mock_client = MagicMock()
            mock_client.settings = MagicMock()
            mock_client.account_scope = "paper"
            mock_client.fetch_index_quote = AsyncMock(side_effect=ConnectionError("API down"))
            MockClient.return_value = mock_client

            with patch("src.agents.index_collector.has_kis_credentials", return_value=True):
                from src.agents.index_collector import IndexCollector
                collector = IndexCollector()
                result = await collector.collect_once()

        assert result["success"] is False
        assert "error" in result
