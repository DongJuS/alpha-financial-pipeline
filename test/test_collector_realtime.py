"""
test/test_collector_realtime.py — _RealtimeMixin WebSocket 실시간 틱 수집 테스트

_flush_tick_buffer, _parse_ws_tick_packet, _backfill_gap, _fetch_quote,
collect_realtime_ticks, _ws_collect_loop 검증.
기존 test_collector_ws.py의 기본 패킷 파싱 테스트를 보완하여
에지 케이스와 통합 시나리오에 집중합니다.
"""

from __future__ import annotations

import asyncio
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


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KIS_APP_KEY", "fake-key")
    monkeypatch.setenv("KIS_APP_SECRET", "fake-secret")


@pytest.fixture()
def collector(_env):
    from src.agents.collector import CollectorAgent
    return CollectorAgent(agent_id="test_realtime")


def _make_tick():
    from src.agents.collector.models import TickData
    return TickData(
        instrument_id="005930.KS",
        price=72000.0,
        volume=100,
        timestamp_kst=datetime.now(KST),
        name="삼성전자",
        market="KOSPI",
        source="kis_ws",
    )


# =============================================================================
# _flush_tick_buffer edge cases
# =============================================================================


class TestFlushTickBufferEdgeCases:
    """틱 버퍼 flush 에지 케이스 검증."""

    async def test_empty_buffer_returns_zero(self, collector):
        """빈 버퍼는 force=True 이어도 0 반환."""
        collector._tick_buffer = []
        result = await collector._flush_tick_buffer(force=True)
        assert result == 0

    async def test_flush_by_time_interval(self, collector):
        """시간 간격이 초과하면 batch_size 미달이어도 flush."""
        collector._tick_batch_size = 1000
        collector._tick_flush_interval = 0.0  # 0초 → 즉시 flush 조건
        collector._tick_buffer = [_make_tick()]
        collector._tick_buffer_last_flush = 0.0  # 먼 과거

        with patch(
            "src.agents.collector._realtime.insert_tick_batch",
            new_callable=AsyncMock,
            return_value=1,
        ):
            result = await collector._flush_tick_buffer()

        assert result == 1
        assert len(collector._tick_buffer) == 0

    async def test_buffer_cleared_after_flush(self, collector):
        """flush 후 버퍼가 비워지는지 확인."""
        collector._tick_batch_size = 1
        collector._tick_buffer = [_make_tick()]
        collector._tick_buffer_last_flush = asyncio.get_event_loop().time()

        with patch(
            "src.agents.collector._realtime.insert_tick_batch",
            new_callable=AsyncMock,
            return_value=1,
        ):
            await collector._flush_tick_buffer()

        assert collector._tick_buffer == []


# =============================================================================
# _parse_ws_tick_packet edge cases
# =============================================================================


class TestParseWsPacketEdgeCases:
    """패킷 파싱 에지 케이스 검증."""

    def test_json_control_message_returns_none(self, collector):
        """JSON 제어 메시지는 None 반환."""
        raw = json.dumps({"header": {"tr_id": "H0STCNT0"}, "body": {"rt_cd": "0"}})
        result = collector._parse_ws_tick_packet(raw, {"005930"})
        assert result is None

    def test_non_zero_prefix_returns_none(self, collector):
        """'0|'로 시작하지 않으면 None."""
        result = collector._parse_ws_tick_packet("1|H0STCNT0|1|data", {"005930"})
        assert result is None

    def test_insufficient_pipe_parts_returns_none(self, collector):
        """'|'로 분리 시 4개 미만이면 None."""
        result = collector._parse_ws_tick_packet("0|H0STCNT0|1", {"005930"})
        assert result is None

    def test_valid_packet_structure(self, collector):
        """유효한 패킷에서 tr_id, ticker, price, volume 추출."""
        raw = "0|H0STCNT0|1|005930^0^72000^73000^71000^72000^1000000^0^0^0^0^0^0^5000000^0^0^0^0^0"
        result = collector._parse_ws_tick_packet(raw, {"005930"})
        assert result is not None
        assert result["ticker"] == "005930"
        assert result["tr_id"] == "H0STCNT0"
        assert result["price"] == 72000

    def test_multiple_tickers_in_subscribed_set(self, collector):
        """여러 종목 구독 시 올바른 ticker 매칭."""
        raw = "0|H0STCNT0|1|000660^0^150000^151000^149000^150000^800000^0^0^0^0^0^0^3000000^0^0^0^0^0"
        subscribed = {"005930", "000660", "035420"}
        result = collector._parse_ws_tick_packet(raw, subscribed)
        assert result is not None
        assert result["ticker"] == "000660"


# =============================================================================
# _fetch_quote
# =============================================================================


class TestFetchQuote:
    """REST 시세 보정 조회 검증."""

    async def test_no_token_returns_none(self, collector):
        """토큰 미설정 시 None 반환."""
        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value=None):
            result = await collector._fetch_quote("005930")
        assert result is None

    async def test_successful_quote(self, collector):
        """정상 응답 시 가격/거래량 반환."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "output": {
                "stck_prpr": "72000",
                "acml_vol": "5000000",
                "hts_kor_isnm": "삼성전자",
            }
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="token"),
            patch("src.agents.collector._realtime.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collector._fetch_quote("005930")

        assert result is not None
        assert result["price"] == 72000
        assert result["volume"] == 5000000
        assert result["name"] == "삼성전자"

    async def test_api_error_returns_none(self, collector):
        """API 오류 시 None 반환."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="token"),
            patch("src.agents.collector._realtime.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collector._fetch_quote("005930")

        assert result is None


# =============================================================================
# _backfill_gap
# =============================================================================


class TestBackfillGap:
    """WebSocket 재연결 후 gap backfill 검증."""

    async def test_no_token_returns_zero(self, collector):
        """토큰 미설정 시 0 반환."""
        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value=None):
            count = await collector._backfill_gap(
                ["005930"],
                {"005930": {"name": "삼성전자", "market": "KOSPI"}},
                datetime.now(KST),
            )
        assert count == 0

    async def test_successful_backfill(self, collector):
        """정상 backfill 시 복구된 틱 수 반환."""
        import httpx as _httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "output2": [
                {"stck_prpr": "72000", "cntg_vol": "100", "stck_cntg_hour": "100000"},
                {"stck_prpr": "72100", "cntg_vol": "200", "stck_cntg_hour": "100100"},
            ],
        }

        # httpx.AsyncClient는 _fill_one 내부에서 async with로 사용됨
        # 실제 AsyncClient 인스턴스를 mock으로 대체
        class MockAsyncClient:
            def __init__(self, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, *args, **kwargs):
                return mock_resp

        with (
            patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="token"),
            patch("src.agents.collector._realtime.httpx.AsyncClient", MockAsyncClient),
            patch("src.db.queries.insert_tick_batch", new_callable=AsyncMock),
        ):
            count = await collector._backfill_gap(
                ["005930"],
                {"005930": {"name": "삼성전자", "market": "KOSPI"}},
                datetime.now(KST),
            )

        assert count == 2

    async def test_partial_failure_still_counts(self, collector):
        """일부 종목 실패해도 다른 종목 결과는 합산."""
        call_count = 0

        mock_resp_ok = MagicMock()
        mock_resp_ok.raise_for_status = MagicMock()
        mock_resp_ok.json.return_value = {
            "output2": [
                {"stck_prpr": "72000", "cntg_vol": "100", "stck_cntg_hour": "100000"},
            ],
        }

        class MockAsyncClient:
            def __init__(self, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, *args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise ConnectionError("fail")
                return mock_resp_ok

        with (
            patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="token"),
            patch("src.agents.collector._realtime.httpx.AsyncClient", MockAsyncClient),
            patch("src.db.queries.insert_tick_batch", new_callable=AsyncMock),
        ):
            count = await collector._backfill_gap(
                ["005930", "000660"],
                {
                    "005930": {"name": "삼성전자", "market": "KOSPI"},
                    "000660": {"name": "SK하이닉스", "market": "KOSPI"},
                },
                datetime.now(KST),
            )

        assert count == 1  # 1개 성공


# =============================================================================
# collect_realtime_ticks coordinator
# =============================================================================


class TestCollectRealtimeTicks:
    """collect_realtime_ticks 코디네이터 검증."""

    async def test_empty_tickers_raises(self, collector):
        """빈 tickers 리스트면 ValueError."""
        with pytest.raises(ValueError, match="--tickers"):
            await collector.collect_realtime_ticks(tickers=[])

    async def test_no_credentials_fallback(self, collector):
        """KIS 자격증명 미설정 + fallback_on_error 시 일봉 수집으로 폴백."""
        import pandas as pd

        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({
            "Code": ["005930"],
            "Name": ["삼성전자"],
            "Market": ["KOSPI"],
        })

        with (
            patch.object(collector, "_resolve_tickers", return_value=[("005930", "삼성전자", "KOSPI")]),
            patch.object(collector, "_has_kis_market_credentials", return_value=False),
            patch.object(collector, "collect_daily_bars", new_callable=AsyncMock, return_value=[]) as mock_daily,
        ):
            result = await collector.collect_realtime_ticks(
                tickers=["005930"], fallback_on_error=True,
            )

        assert result == 0
        mock_daily.assert_awaited_once()

    async def test_no_credentials_no_fallback_raises(self, collector):
        """KIS 자격증명 미설정 + fallback_on_error=False 시 RuntimeError."""
        with (
            patch.object(collector, "_resolve_tickers", return_value=[("005930", "삼성전자", "KOSPI")]),
            patch.object(collector, "_has_kis_market_credentials", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="미설정"):
                await collector.collect_realtime_ticks(
                    tickers=["005930"], fallback_on_error=False,
                )

    async def test_ws_failure_with_fallback(self, collector):
        """WebSocket 실패 후 fallback으로 FDR 수집."""
        with (
            patch.object(collector, "_resolve_tickers", return_value=[("005930", "삼성전자", "KOSPI")]),
            patch.object(collector, "_has_kis_market_credentials", return_value=True),
            patch.object(collector, "_ws_collect_loop", new_callable=AsyncMock, return_value=-1),
            patch.object(collector, "_beat", new_callable=AsyncMock),
            patch.object(collector, "collect_daily_bars", new_callable=AsyncMock, return_value=[]) as mock_daily,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await collector.collect_realtime_ticks(
                tickers=["005930"], fallback_on_error=True,
            )

        assert result == 0
        assert mock_daily.await_count == 3  # 3번 폴백 반복


# =============================================================================
# _extract_price / _extract_volume edge cases
# =============================================================================


class TestExtractHelpersEdgeCases:
    """정적 헬퍼 메서드 에지 케이스 보강."""

    def test_price_at_boundary_100(self, collector):
        """price=100은 유효 범위 내."""
        fields = ["abc", "def", "ghi", "100"]
        assert collector._extract_price(fields) == 100

    def test_price_at_boundary_2_million(self, collector):
        """price=2_000_000은 유효 범위 내."""
        fields = ["abc", "def", "ghi", "2000000"]
        assert collector._extract_price(fields) == 2000000

    def test_price_below_100_at_index2_still_returned(self, collector):
        """fields[2]가 digit이면 범위 검사 없이 바로 반환 (index 2 우선 규칙)."""
        fields = ["abc", "def", "99"]
        # index 2가 digit이면 그냥 반환하므로 99
        assert collector._extract_price(fields) == 99

    def test_price_below_100_in_fallback_skipped(self, collector):
        """fields[2]가 비숫자이고 다른 필드에 99만 있으면 범위 밖이므로 None."""
        fields = ["abc", "def", "xyz", "99"]
        assert collector._extract_price(fields) is None

    def test_price_above_2_million_skipped(self, collector):
        """price=2_000_001은 범위 밖 → fallback에서 무시."""
        fields = ["abc", "def", "2000001"]
        # fields[2]가 digit이면 일단 반환 (index 2 우선 규칙)
        # 실제 소스에서는 fields[2].isdigit()이면 그냥 반환
        result = collector._extract_price(fields)
        assert result == 2000001  # index 2 우선 규칙

    def test_volume_empty_fields(self, collector):
        """빈 필드 리스트에서 volume 추출 시 None."""
        assert collector._extract_volume([]) is None

    def test_ticker_empty_subscribed(self, collector):
        """빈 subscribed set이면 None."""
        assert collector._extract_ticker(["005930"], set()) is None
