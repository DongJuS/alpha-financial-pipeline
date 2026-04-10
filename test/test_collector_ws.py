"""
test/test_collector_ws.py — CollectorAgent WebSocket 관련 단위 테스트

KIS WebSocket 틱 패킷 파싱, 버퍼 flush, 재연결 로직을 검증합니다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def _env(monkeypatch):
    """테스트용 최소 환경변수 설정."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KIS_APP_KEY", "fake-key")
    monkeypatch.setenv("KIS_APP_SECRET", "fake-secret")


@pytest.fixture()
def collector(_env):
    """CollectorAgent 인스턴스 생성.

    패키지 구조(src.agents.collector)를 우선 시도하고,
    실패 시 단일 모듈(src.agents.collector)에서 import 합니다.
    """
    try:
        from src.agents.collector import CollectorAgent
    except ImportError:
        from src.agents.collector import CollectorAgent
    return CollectorAgent(agent_id="test_ws_collector")


@pytest.fixture()
def packets() -> dict:
    """test/fixtures/kis_ws_packets.json 로드."""
    with open(FIXTURES_DIR / "kis_ws_packets.json") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════
# TestParseWsTickPacket — _parse_ws_tick_packet 직접 테스트 (5개)
# ═══════════════════════════════════════════════════════════════════════


class TestParseWsTickPacket:
    """_parse_ws_tick_packet 파싱 결과를 검증합니다."""

    def test_normal_tick_returns_dict(self, collector, packets):
        """정상 틱 패킷 → ticker, price, volume 포함 dict 반환."""
        subscribed = {"005930"}
        result = collector._parse_ws_tick_packet(packets["tick_normal"], subscribed)

        assert result is not None
        assert result["ticker"] == "005930"
        assert result["tr_id"] == "H0STCNT0"
        assert "price" in result
        assert "volume" in result
        assert "raw" in result

    def test_subscribe_ack_returns_none(self, collector, packets):
        """구독 ACK(JSON 제어 메시지) → None 반환."""
        subscribed = {"005930"}
        result = collector._parse_ws_tick_packet(packets["subscribe_ack"], subscribed)

        assert result is None

    def test_invalid_format_returns_none(self, collector, packets):
        """잘못된 포맷 → None 반환."""
        subscribed = {"005930"}
        result = collector._parse_ws_tick_packet(packets["invalid_format"], subscribed)

        assert result is None

    def test_empty_string_returns_none(self, collector, packets):
        """빈 문자열 → None 반환."""
        subscribed = {"005930"}
        result = collector._parse_ws_tick_packet(packets["empty"], subscribed)

        assert result is None

    def test_ticker_not_in_subscribed_returns_none(self, collector, packets):
        """패킷의 ticker가 구독 set에 없으면 → None 반환."""
        subscribed = {"999999"}  # 005930이 아닌 다른 ticker
        result = collector._parse_ws_tick_packet(packets["tick_normal"], subscribed)

        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# TestExtractHelpers — 정적 헬퍼 메서드 테스트 (3개)
# ═══════════════════════════════════════════════════════════════════════


class TestExtractHelpers:
    """_extract_price, _extract_volume, _extract_ticker 헬퍼 검증."""

    def test_extract_price_from_index2(self, collector):
        """fields[2]에 가격이 있으면 해당 값을 반환."""
        # fields[2] = "53400" → 53400
        fields = ["005930", "0", "53400", "53500", "53200"]
        result = collector._extract_price(fields)
        assert result == 53400

    def test_extract_volume_from_candidate_indices(self, collector):
        """candidate_idx (13, 12, 11, 18) 순서로 volume을 추출."""
        # index 13에 거래량이 위치하는 필드 리스트
        fields = ["005930"] + ["0"] * 12 + ["16630538"] + ["0"] * 5
        result = collector._extract_volume(fields)
        assert result == 16630538

    def test_extract_ticker_in_subscribed_set(self, collector):
        """fields[0]이 subscribed set에 있으면 해당 ticker 반환."""
        fields = ["005930", "53400", "1", "53500"]
        subscribed = {"005930", "000660"}
        result = collector._extract_ticker(fields, subscribed)
        assert result == "005930"

    def test_extract_ticker_not_at_index0(self, collector):
        """fields[0]이 subscribed에 없지만 다른 인덱스에 있으면 해당 값 반환."""
        fields = ["UNKNOWN", "53400", "005930", "53500"]
        subscribed = {"005930"}
        result = collector._extract_ticker(fields, subscribed)
        assert result == "005930"

    def test_extract_ticker_returns_none_when_missing(self, collector):
        """subscribed에 해당하는 ticker가 fields에 없으면 None."""
        fields = ["UNKNOWN", "53400", "1", "53500"]
        subscribed = {"005930"}
        result = collector._extract_ticker(fields, subscribed)
        assert result is None

    def test_extract_price_fallback_range(self, collector):
        """fields[2]가 비숫자이면 100~2_000_000 범위의 첫 숫자를 반환."""
        fields = ["abc", "def", "xyz", "53400"]
        result = collector._extract_price(fields)
        assert result == 53400

    def test_extract_price_returns_none_for_no_valid_price(self, collector):
        """유효한 숫자가 없으면 None 반환."""
        fields = ["abc", "def", "ghi"]
        result = collector._extract_price(fields)
        assert result is None

    def test_extract_volume_returns_none_when_no_candidates(self, collector):
        """candidate_idx에 해당하는 필드가 모두 비숫자이면 None."""
        fields = ["x"] * 5  # index 11, 12, 13, 18 모두 범위 밖이거나 비숫자
        result = collector._extract_volume(fields)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# TestFlushTickBuffer — 버퍼 flush 조건 테스트 (3개)
# ═══════════════════════════════════════════════════════════════════════


class TestFlushTickBuffer:
    """_flush_tick_buffer의 flush 조건을 검증합니다."""

    @staticmethod
    def _make_point() -> "MarketDataPoint":
        from src.db.models import MarketDataPoint

        return MarketDataPoint(
            instrument_id="005930.KS",
            name="삼성전자",
            market="KOSPI",
            traded_at=date.today(),
            open=53400.0,
            high=53500.0,
            low=53200.0,
            close=53400.0,
            volume=100,
            change_pct=None,
        )

    @pytest.mark.asyncio
    async def test_no_flush_when_below_batch_and_interval(self, collector):
        """버퍼가 batch_size 미만이고 interval 미경과 → flush하지 않음 (0 반환)."""
        collector._tick_batch_size = 100
        collector._tick_flush_interval = 10.0
        collector._tick_buffer = [self._make_point()]
        collector._tick_buffer_last_flush = asyncio.get_event_loop().time()

        result = await collector._flush_tick_buffer()
        assert result == 0
        assert len(collector._tick_buffer) == 1  # 버퍼 유지

    @pytest.mark.asyncio
    async def test_flush_when_batch_size_reached(self, collector):
        """버퍼가 batch_size에 도달하면 flush가 발생한다."""
        collector._tick_batch_size = 3
        collector._tick_flush_interval = 999.0  # interval은 먼 미래
        collector._tick_buffer = [self._make_point() for _ in range(3)]
        collector._tick_buffer_last_flush = asyncio.get_event_loop().time()

        mock_store = AsyncMock()
        with (
            patch(
                "src.agents.collector._realtime.upsert_market_data",
                new_callable=AsyncMock,
                return_value=3,
            ) as mock_upsert,
            # store_tick_data는 _flush_tick_buffer 내에서 lazy import 되므로
            # src.services.datalake 모듈 자체를 패치
            patch.dict("sys.modules", {
                "src.services.datalake": MagicMock(store_tick_data=mock_store),
            }),
        ):
            result = await collector._flush_tick_buffer()

        assert result == 3
        mock_upsert.assert_awaited_once()
        assert len(collector._tick_buffer) == 0  # 버퍼 비워짐

    @pytest.mark.asyncio
    async def test_flush_when_force_true(self, collector):
        """force=True이면 batch_size/interval 무관하게 flush."""
        collector._tick_batch_size = 1000
        collector._tick_flush_interval = 999.0
        collector._tick_buffer = [self._make_point()]
        collector._tick_buffer_last_flush = asyncio.get_event_loop().time()

        mock_store = AsyncMock()
        with (
            patch(
                "src.agents.collector._realtime.upsert_market_data",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_upsert,
            patch.dict("sys.modules", {
                "src.services.datalake": MagicMock(store_tick_data=mock_store),
            }),
        ):
            result = await collector._flush_tick_buffer(force=True)

        assert result == 1
        mock_upsert.assert_awaited_once()
        assert len(collector._tick_buffer) == 0


# ═══════════════════════════════════════════════════════════════════════
# TestReconnectionLogic — 재연결 로직 테스트 (2개)
# ═══════════════════════════════════════════════════════════════════════


class TestReconnectionLogic:
    """_ws_collect_loop의 재연결/백오프 로직을 검증합니다."""

    @pytest.mark.asyncio
    async def test_reconnect_backoff_has_jitter(self, collector):
        """재연결 시 sleep이 jitter를 포함하는지 확인.

        websockets.connect가 매번 실패하면 reconnects가 증가하고,
        asyncio.sleep이 호출됨. sleep 인자에 랜덤 jitter가 포함되어야 한다.
        """
        connect_count = 0

        class _FailingWS:
            """async context manager가 __aenter__에서 예외를 발생시키는 mock."""

            def __init__(self, *args, **kwargs):
                nonlocal connect_count
                connect_count += 1

            async def __aenter__(self):
                raise ConnectionError("test connection failure")

            async def __aexit__(self, *args):
                return False

        sleep_args: list[float] = []

        async def capture_sleep(seconds, *args, **kwargs):
            sleep_args.append(seconds)
            return

        with (
            patch("src.agents.collector._realtime.websockets.connect", _FailingWS),
            patch.object(collector, "_ensure_ws_approval_key", new_callable=AsyncMock, return_value="fake-key"),
            patch.object(collector, "_beat", new_callable=AsyncMock),
            patch("src.agents.collector._realtime.insert_collector_error", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=capture_sleep),
        ):
            result = await collector._ws_collect_loop(
                subscribed=["005930"],
                meta={"005930": {"name": "삼성전자", "market": "KOSPI"}},
                reconnect_max=2,
            )

        assert result == -1  # 재연결 한도 초과
        # reconnect_max=2 → 3번 연결 시도 (reconnects 1, 2, 3 → 3 > 2 에서 break)
        assert connect_count == 3
        # sleep은 reconnects가 1, 2일 때 호출 (3번째 시도 후에는 break)
        assert len(sleep_args) == 2
        # 첫 번째 sleep: min(1*2, 30) + random.uniform(0,1) → 2.0 ~ 3.0 범위
        assert 2.0 <= sleep_args[0] < 3.0 + 0.01
        # 두 번째 sleep: min(2*2, 30) + random.uniform(0,1) → 4.0 ~ 5.0 범위
        assert 4.0 <= sleep_args[1] < 5.0 + 0.01

    @pytest.mark.asyncio
    async def test_reconnect_max_exceeded_returns_negative(self, collector):
        """재연결 한도를 초과하면 -1을 반환한다."""

        class _FailingWS:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                raise ConnectionError("test failure")

            async def __aexit__(self, *args):
                return False

        with (
            patch("src.agents.collector._realtime.websockets.connect", _FailingWS),
            patch.object(collector, "_ensure_ws_approval_key", new_callable=AsyncMock, return_value="fake-key"),
            patch.object(collector, "_beat", new_callable=AsyncMock),
            patch("src.agents.collector._realtime.insert_collector_error", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await collector._ws_collect_loop(
                subscribed=["005930"],
                meta={"005930": {"name": "삼성전자", "market": "KOSPI"}},
                reconnect_max=1,
            )

        assert result == -1
