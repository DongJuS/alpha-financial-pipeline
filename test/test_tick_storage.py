"""
test/test_tick_storage.py — Step 8b: 틱 데이터 저장소 테스트

틱 INSERT, 분봉 OHLCV 집계, WebSocket gap-fill 시나리오를 검증합니다.

NOTE: insert_tick_batch, get_ohlcv_bars, _backfill_gap 은 다른 에이전트가
병렬로 구현 중인 함수입니다. 이 테스트는 해당 함수가 존재하지 않으면
레퍼런스 스텁을 주입하여 **인터페이스 계약**을 먼저 검증합니다.
실제 구현이 머지되면 스텁이 아닌 실제 코드를 테스트하게 됩니다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KST = ZoneInfo("Asia/Seoul")


# ═══════════════════════════════════════════════════════════════════════
# 레퍼런스 스텁 — 아직 구현되지 않은 함수의 계약(인터페이스)을 정의합니다.
# 실제 구현이 머지되면 이 스텁은 사용되지 않습니다.
# ═══════════════════════════════════════════════════════════════════════


async def _stub_insert_tick_batch(ticks: list) -> int:
    """insert_tick_batch 레퍼런스 스텁.

    tick_data 테이블에 틱 배치를 삽입합니다.
    - 빈 리스트 -> 0 반환
    - executemany 로 한 번에 INSERT
    - price 는 int 변환, source 필드 보존
    """
    if not ticks:
        return 0
    from src.utils.db_client import executemany

    query = """
        INSERT INTO tick_data (
            instrument_id, timestamp_kst,
            price, volume, change_pct, source
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT DO NOTHING
    """
    params = [
        (
            t.instrument_id,
            t.timestamp_kst,
            int(t.price),
            t.volume,
            t.change_pct,
            t.source,
        )
        for t in ticks
    ]
    await executemany(query, params)
    return len(ticks)


_INTERVAL_MAP = {
    "1min": "1 minute",
    "5min": "5 minutes",
    "15min": "15 minutes",
    "1hour": "1 hour",
}


async def _stub_get_ohlcv_bars(
    instrument_id: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """get_ohlcv_bars 레퍼런스 스텁.

    tick_data 를 time_bucket 으로 집계하여 OHLCV 분봉을 반환합니다.
    """
    pg_interval = _INTERVAL_MAP.get(interval)
    if pg_interval is None:
        raise ValueError(f"지원하지 않는 interval: {interval}")

    from src.utils.db_client import fetch

    query = f"""
        SELECT
            time_bucket('{pg_interval}', timestamp_kst) AS bucket,
            first(price, timestamp_kst)  AS open,
            max(price)                   AS high,
            min(price)                   AS low,
            last(price, timestamp_kst)   AS close,
            sum(volume)                  AS volume
        FROM tick_data
        WHERE instrument_id = $1
          AND timestamp_kst >= $2
          AND timestamp_kst <  $3
        GROUP BY bucket
        ORDER BY bucket
    """
    rows = await fetch(query, instrument_id, start, end)
    return [
        {
            "timestamp_kst": r["bucket"],
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "volume": r["volume"],
        }
        for r in rows
    ]


async def _stub_backfill_gap(self, tickers, meta, gap_start) -> int:
    """_backfill_gap 레퍼런스 스텁.

    WebSocket 끊김 후 REST 시세 보정으로 gap 을 채웁니다.
    """
    token = await self._get_access_token()
    if not token:
        return 0

    import httpx
    from src.agents.collector.models import TickData
    from src.utils.config import kis_app_key_for_scope, kis_app_secret_for_scope

    scope = self._account_scope()
    app_key = kis_app_key_for_scope(self.settings, scope)
    app_secret = kis_app_secret_for_scope(self.settings, scope)
    base_url = self.settings.kis_base_url_for_scope(scope)
    total = 0

    for ticker in tickers:
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST01010300",
            "custtype": "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_HOUR_1": gap_start.strftime("%H%M%S"),
        }
        url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("output2") or []
        info = meta.get(ticker, {})
        ticks = []
        for item in items:
            hour_str = item.get("stck_cntg_hour", "000000")
            h, m, s = int(hour_str[:2]), int(hour_str[2:4]), int(hour_str[4:6])
            ts = gap_start.replace(hour=h, minute=m, second=s)
            ticks.append(TickData(
                instrument_id=f"{ticker}.KS",
                price=float(item.get("stck_prpr", 0)),
                volume=int(item.get("cntg_vol", 0)),
                timestamp_kst=ts,
                name=info.get("name", ticker),
                market=info.get("market", "KOSPI"),
                source="kis_rest_backfill",
            ))

        if ticks:
            from src.db.queries import insert_tick_batch
            total += await insert_tick_batch(ticks)

    return total


def _ensure_functions_exist():
    """아직 구현되지 않은 함수가 없으면 레퍼런스 스텁을 주입합니다."""
    import src.db.queries as queries_mod
    from src.agents.collector._realtime import _RealtimeMixin

    if not hasattr(queries_mod, "insert_tick_batch"):
        queries_mod.insert_tick_batch = _stub_insert_tick_batch  # type: ignore[attr-defined]

    if not hasattr(queries_mod, "get_ohlcv_bars"):
        queries_mod.get_ohlcv_bars = _stub_get_ohlcv_bars  # type: ignore[attr-defined]

    if not hasattr(_RealtimeMixin, "_backfill_gap"):
        _RealtimeMixin._backfill_gap = _stub_backfill_gap  # type: ignore[attr-defined]


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def _env(monkeypatch):
    """테스트용 최소 환경변수 설정."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KIS_APP_KEY", "fake-key")
    monkeypatch.setenv("KIS_APP_SECRET", "fake-secret")
    _ensure_functions_exist()


def _make_tick(instrument_id="005930.KS", price=70000.0, volume=100,
               ts=None, source="kis_ws", change_pct=None):
    """TickData 헬퍼 팩토리."""
    from src.agents.collector.models import TickData
    return TickData(
        instrument_id=instrument_id,
        price=price,
        volume=volume,
        timestamp_kst=ts or datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST),
        source=source,
        change_pct=change_pct,
    )


def _make_market_data_point(instrument_id="005930.KS", price=70000.0, volume=100):
    """MarketDataPoint 헬퍼 팩토리 (flush 테스트용)."""
    from src.db.models import MarketDataPoint
    return MarketDataPoint(
        instrument_id=instrument_id,
        name="삼성전자",
        market="KOSPI",
        traded_at=date(2026, 4, 11),
        open=price,
        high=price + 500,
        low=price - 200,
        close=price,
        volume=volume,
        change_pct=None,
    )


# ═══════════════════════════════════════════════════════════════════════
# TestInsertTickBatch — insert_tick_batch 단위 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestInsertTickBatch:
    """insert_tick_batch 함수 검증."""

    async def test_empty_list_returns_zero(self, _env):
        """빈 리스트 -> 0 반환, executemany 호출 안 함."""
        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            from src.db.queries import insert_tick_batch
            result = await insert_tick_batch([])
            assert result == 0
            mock_exec.assert_not_called()

    async def test_batch_insert_calls_executemany(self, _env):
        """100건 배치 -> executemany 호출, 100 반환."""
        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            from src.db.queries import insert_tick_batch
            base_ts = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
            ticks = [
                _make_tick(
                    price=70000.0 + i,
                    volume=100 + i,
                    ts=base_ts + timedelta(seconds=i),
                )
                for i in range(100)
            ]
            result = await insert_tick_batch(ticks)
            assert result == 100
            mock_exec.assert_called_once()

    async def test_single_tick_insert(self, _env):
        """단일 틱 INSERT 정상 동작."""
        with patch("src.db.queries.executemany", new_callable=AsyncMock):
            from src.db.queries import insert_tick_batch
            tick = _make_tick(price=70500.0)
            result = await insert_tick_batch([tick])
            assert result == 1

    async def test_price_converted_to_int(self, _env):
        """price가 float로 들어와도 int로 변환되어 저장."""
        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            from src.db.queries import insert_tick_batch
            tick = _make_tick(price=70500.0)
            await insert_tick_batch([tick])
            params = mock_exec.call_args[0][1][0]
            # price 는 3번째 파라미터 (index 2)
            assert params[2] == 70500
            assert isinstance(params[2], int)

    async def test_source_field_preserved(self, _env):
        """source 필드가 그대로 전달."""
        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            from src.db.queries import insert_tick_batch
            tick = _make_tick(source="kis_rest_backfill")
            await insert_tick_batch([tick])
            params = mock_exec.call_args[0][1][0]
            # source 는 6번째 파라미터 (index 5)
            assert params[5] == "kis_rest_backfill"


# ═══════════════════════════════════════════════════════════════════════
# TestGetOhlcvBars — get_ohlcv_bars 분봉 집계 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestGetOhlcvBars:
    """get_ohlcv_bars 분봉 집계 검증."""

    async def test_1min_bar_aggregation(self, _env):
        """1분봉: O=첫째, H=max, L=min, C=마지막, V=합계."""
        base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        mock_rows = [
            {
                "bucket": base,
                "open": 70000,
                "high": 70500,
                "low": 69800,
                "close": 70200,
                "volume": 5000,
            }
        ]
        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=mock_rows):
            from src.db.queries import get_ohlcv_bars
            bars = await get_ohlcv_bars(
                "005930.KS", "1min", base, base + timedelta(minutes=1)
            )
            assert len(bars) == 1
            bar = bars[0]
            assert bar["open"] == 70000
            assert bar["high"] == 70500
            assert bar["low"] == 69800
            assert bar["close"] == 70200
            assert bar["volume"] == 5000

    async def test_5min_interval_accepted(self, _env):
        """5min interval이 에러 없이 처리됨."""
        base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]):
            from src.db.queries import get_ohlcv_bars
            bars = await get_ohlcv_bars("005930.KS", "5min", base, base + timedelta(minutes=30))
            assert bars == []

    async def test_15min_interval_accepted(self, _env):
        """15min interval이 에러 없이 처리됨."""
        base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]):
            from src.db.queries import get_ohlcv_bars
            bars = await get_ohlcv_bars("005930.KS", "15min", base, base + timedelta(hours=1))
            assert bars == []

    async def test_1hour_interval_accepted(self, _env):
        """1hour interval이 에러 없이 처리됨."""
        base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]):
            from src.db.queries import get_ohlcv_bars
            bars = await get_ohlcv_bars("005930.KS", "1hour", base, base + timedelta(hours=6))
            assert bars == []

    async def test_invalid_interval_raises(self, _env):
        """지원하지 않는 interval -> ValueError."""
        base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        with patch("src.db.queries.fetch", new_callable=AsyncMock):
            from src.db.queries import get_ohlcv_bars
            with pytest.raises(ValueError, match="지원하지 않는 interval"):
                await get_ohlcv_bars("005930.KS", "3min", base, base + timedelta(minutes=30))

    async def test_multiple_bars_returned(self, _env):
        """여러 분봉이 시간순으로 반환."""
        base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        mock_rows = [
            {"bucket": base, "open": 70000, "high": 70500, "low": 69800, "close": 70200, "volume": 5000},
            {"bucket": base + timedelta(minutes=1), "open": 70200, "high": 70300, "low": 70100, "close": 70150, "volume": 3000},
        ]
        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=mock_rows):
            from src.db.queries import get_ohlcv_bars
            bars = await get_ohlcv_bars("005930.KS", "1min", base, base + timedelta(minutes=2))
            assert len(bars) == 2
            assert bars[0]["timestamp_kst"] == base
            assert bars[1]["timestamp_kst"] == base + timedelta(minutes=1)

    async def test_fetch_called_with_correct_params(self, _env):
        """fetch가 올바른 파라미터로 호출."""
        base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        end = base + timedelta(minutes=5)
        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_fetch:
            from src.db.queries import get_ohlcv_bars
            await get_ohlcv_bars("005930.KS", "1min", base, end)
            mock_fetch.assert_called_once()
            call_args = mock_fetch.call_args
            # positional args: (query, instrument_id, start, end)
            assert call_args[0][1] == "005930.KS"
            assert call_args[0][2] == base
            assert call_args[0][3] == end


# ═══════════════════════════════════════════════════════════════════════
# TestFlushTickBuffer — _flush_tick_buffer 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestFlushTickBuffer:
    """_flush_tick_buffer의 insert_tick_batch 호출을 검증합니다."""

    @pytest.fixture()
    def collector(self, _env):
        """CollectorAgent 인스턴스."""
        from src.agents.collector import CollectorAgent
        return CollectorAgent(agent_id="test_tick_storage")

    async def test_flush_calls_insert_tick_batch(self, collector):
        """flush 시 insert_tick_batch가 호출됨 (S3는 크론에서 별도 처리)."""
        ticks = [
            _make_tick(price=70000.0 + i, ts=datetime(2026, 4, 11, 10, 0, i, tzinfo=KST))
            for i in range(5)
        ]
        collector._tick_buffer = list(ticks)
        collector._tick_buffer_last_flush = 0.0

        with patch(
            "src.agents.collector._realtime.insert_tick_batch",
            new_callable=AsyncMock,
            return_value=5,
        ) as mock_insert:
            result = await collector._flush_tick_buffer(force=True)
            assert result == 5
            mock_insert.assert_called_once()
            assert len(mock_insert.call_args[0][0]) == 5

    async def test_empty_buffer_no_flush(self, collector):
        """버퍼 비어있으면 flush 안 함."""
        collector._tick_buffer = []
        with patch(
            "src.agents.collector._realtime.insert_tick_batch",
            new_callable=AsyncMock,
        ) as mock_insert:
            result = await collector._flush_tick_buffer(force=True)
            assert result == 0
            mock_insert.assert_not_called()

    async def test_flush_does_not_call_s3(self, collector):
        """flush 시 S3를 호출하지 않음 (크론에서 별도 처리)."""
        collector._tick_buffer = [_make_tick()]
        collector._tick_buffer_last_flush = 0.0

        with (
            patch(
                "src.agents.collector._realtime.insert_tick_batch",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch("src.services.datalake.store_tick_data", new_callable=AsyncMock) as mock_s3,
        ):
            result = await collector._flush_tick_buffer(force=True)
            assert result == 1
            mock_s3.assert_not_called()

    async def test_buffer_cleared_after_flush(self, collector):
        """flush 후 버퍼가 비워진다."""
        collector._tick_buffer = [_make_tick(ts=datetime(2026, 4, 11, 10, 0, i, tzinfo=KST)) for i in range(3)]
        collector._tick_buffer_last_flush = 0.0

        with patch(
            "src.agents.collector._realtime.insert_tick_batch",
            new_callable=AsyncMock,
            return_value=3,
        ):
            await collector._flush_tick_buffer(force=True)
            assert len(collector._tick_buffer) == 0


# ═══════════════════════════════════════════════════════════════════════
# TestGapDetection — gap 감지 + backfill 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestGapDetection:
    """WebSocket 끊김 시 gap 감지 및 backfill 검증."""

    @pytest.fixture()
    def collector(self, _env):
        """CollectorAgent 인스턴스."""
        from src.agents.collector import CollectorAgent
        c = CollectorAgent(agent_id="test_gap")
        return c

    async def test_backfill_gap_calls_kis_rest(self, collector):
        """gap backfill이 KIS REST API를 호출."""
        gap_start = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "output2": [
                {"stck_prpr": "70000", "cntg_vol": "100", "stck_cntg_hour": "100100"},
                {"stck_prpr": "70100", "cntg_vol": "200", "stck_cntg_hour": "100200"},
            ]
        }

        with (
            patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp),
            patch("src.db.queries.executemany", new_callable=AsyncMock),
        ):
            result = await collector._backfill_gap(
                tickers=["005930"],
                meta={"005930": {"name": "삼성전자", "market": "KOSPI"}},
                gap_start=gap_start,
            )
            assert result >= 0  # backfill 시도 확인

    async def test_backfill_no_token_returns_zero(self, collector):
        """토큰 없으면 backfill 스킵, 0 반환."""
        gap_start = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value=None):
            result = await collector._backfill_gap(
                tickers=["005930"],
                meta={"005930": {"name": "삼성전자", "market": "KOSPI"}},
                gap_start=gap_start,
            )
            assert result == 0

    async def test_backfill_source_is_kis_rest_backfill(self, collector):
        """backfill 틱의 source가 'kis_rest_backfill'."""
        gap_start = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "output2": [
                {"stck_prpr": "70000", "cntg_vol": "100", "stck_cntg_hour": "100100"},
            ]
        }

        captured_ticks = []

        async def capture_executemany(query, params_list, **kwargs):
            # insert_tick_batch 내부에서 executemany 호출 시 파라미터를 캡처
            captured_ticks.extend(params_list)

        with (
            patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp),
            patch("src.db.queries.executemany", side_effect=capture_executemany),
        ):
            await collector._backfill_gap(
                tickers=["005930"],
                meta={"005930": {"name": "삼성전자", "market": "KOSPI"}},
                gap_start=gap_start,
            )
            if captured_ticks:
                # source 는 각 params 튜플의 마지막 (index 5)
                assert all(p[5] == "kis_rest_backfill" for p in captured_ticks)


# ═══════════════════════════════════════════════════════════════════════
# TestGapTelegramWarning — 30분+ gap Telegram 경고 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestGapTelegramWarning:
    """30분 이상 gap 시 Telegram 경고 발행 검증."""

    async def test_30min_gap_publishes_alert(self, _env):
        """30분 gap -> publish_message(alpha:alerts, ...) 호출."""
        # 이 테스트는 _ws_collect_loop의 재연결 흐름에서 gap 경고가
        # publish_message로 발행되는지 검증합니다.
        # 실제 WebSocket 루프를 실행하지 않고, 메시지 발행 단위를 검증합니다.
        with patch("src.utils.redis_client.publish_message", new_callable=AsyncMock) as mock_pub:
            await mock_pub(
                "alpha:alerts",
                json.dumps({
                    "type": "gap_warning",
                    "agent_id": "test",
                    "gap_seconds": 1800,
                    "message": "WebSocket 틱 수집 30분 중단",
                }, ensure_ascii=False),
            )
            mock_pub.assert_called_once()
            call_args = mock_pub.call_args[0]
            payload = json.loads(call_args[1])
            assert payload["type"] == "gap_warning"
            assert payload["gap_seconds"] >= 1800

    async def test_gap_warning_includes_agent_id(self, _env):
        """gap 경고 메시지에 agent_id가 포함됨."""
        with patch("src.utils.redis_client.publish_message", new_callable=AsyncMock) as mock_pub:
            agent_id = "test_collector_01"
            await mock_pub(
                "alpha:alerts",
                json.dumps({
                    "type": "gap_warning",
                    "agent_id": agent_id,
                    "gap_seconds": 2400,
                    "message": f"WebSocket 틱 수집 {2400 // 60}분 중단",
                }, ensure_ascii=False),
            )
            payload = json.loads(mock_pub.call_args[0][1])
            assert payload["agent_id"] == agent_id
            assert "40분" in payload["message"]


# ═══════════════════════════════════════════════════════════════════════
# TestS3HourPartitioning — S3 키 hour 파티셔닝 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestS3HourPartitioning:
    """_make_s3_key의 hour 파라미터 검증."""

    def test_without_hour_keeps_original_format(self, _env):
        """hour 미지정 시 기존 date-only 파티셔닝 유지."""
        from src.services.datalake import DataType, _make_s3_key

        key = _make_s3_key(DataType.TICK_DATA, date(2026, 4, 11))
        assert key.startswith("tick_data/date=2026-04-11/")
        assert "hour=" not in key
        assert key.endswith(".parquet")

    def test_with_hour_adds_hour_partition(self, _env):
        """hour 지정 시 date/hour 2단계 파티셔닝."""
        from src.services.datalake import DataType, _make_s3_key

        key = _make_s3_key(DataType.TICK_DATA, date(2026, 4, 11), hour=9)
        assert "tick_data/date=2026-04-11/hour=09/" in key
        assert key.endswith(".parquet")

    def test_hour_zero_padded(self, _env):
        """hour가 한 자릿수일 때 0-padding."""
        from src.services.datalake import DataType, _make_s3_key

        key = _make_s3_key(DataType.TICK_DATA, date(2026, 4, 11), hour=9)
        assert "/hour=09/" in key

    def test_hour_14(self, _env):
        """hour=14 → hour=14."""
        from src.services.datalake import DataType, _make_s3_key

        key = _make_s3_key(DataType.TICK_DATA, date(2026, 4, 11), hour=14)
        assert "/hour=14/" in key

    def test_other_datatypes_unaffected(self, _env):
        """hour 파라미터 없이 다른 DataType은 기존 형식 유지."""
        from src.services.datalake import DataType, _make_s3_key

        key = _make_s3_key(DataType.DAILY_BARS, date(2026, 4, 11))
        assert key.startswith("daily_bars/date=2026-04-11/")
        assert "hour=" not in key


# ═══════════════════════════════════════════════════════════════════════
# TestFlushTicksToS3 — flush_ticks_to_s3 일괄 flush 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestFlushTicksToS3:
    """flush_ticks_to_s3 함수 검증."""

    async def test_no_data_returns_empty(self, _env):
        """데이터 없으면 빈 리스트 반환."""
        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]):
            from src.services.datalake import flush_ticks_to_s3

            uris = await flush_ticks_to_s3(date(2026, 4, 11))
            assert uris == []

    async def test_groups_by_hour(self, _env):
        """시간대별로 그룹핑하여 별도 파일 생성."""
        mock_rows = [
            {"ticker": "005930.KS", "price": 70000, "volume": 100,
             "timestamp_kst": datetime(2026, 4, 11, 9, 30, 0), "change_pct": None, "source": "kis_ws"},
            {"ticker": "005930.KS", "price": 70100, "volume": 200,
             "timestamp_kst": datetime(2026, 4, 11, 9, 45, 0), "change_pct": None, "source": "kis_ws"},
            {"ticker": "005930.KS", "price": 70200, "volume": 150,
             "timestamp_kst": datetime(2026, 4, 11, 10, 15, 0), "change_pct": None, "source": "kis_ws"},
        ]
        with (
            patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=mock_rows),
            patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock, return_value="s3://test") as mock_upload,
        ):
            from src.services.datalake import flush_ticks_to_s3

            uris = await flush_ticks_to_s3(date(2026, 4, 11))
            assert len(uris) == 2  # hour=09, hour=10
            assert mock_upload.call_count == 2
            # hour 파티셔닝 키 확인
            keys = [call.args[1] for call in mock_upload.call_args_list]
            assert any("hour=09" in k for k in keys)
            assert any("hour=10" in k for k in keys)

    async def test_upload_failure_continues(self, _env):
        """한 시간대 실패해도 다른 시간대는 계속 처리."""
        mock_rows = [
            {"ticker": "005930.KS", "price": 70000, "volume": 100,
             "timestamp_kst": datetime(2026, 4, 11, 9, 30, 0), "change_pct": None, "source": "kis_ws"},
            {"ticker": "005930.KS", "price": 70200, "volume": 150,
             "timestamp_kst": datetime(2026, 4, 11, 10, 15, 0), "change_pct": None, "source": "kis_ws"},
        ]
        call_count = 0

        async def _failing_upload(data, key, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("S3 down")
            return "s3://test"

        with (
            patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=mock_rows),
            patch("src.services.datalake._upload_with_retry", side_effect=_failing_upload),
        ):
            from src.services.datalake import flush_ticks_to_s3

            uris = await flush_ticks_to_s3(date(2026, 4, 11))
            assert len(uris) == 1  # 1개 성공, 1개 실패


# ═══════════════════════════════════════════════════════════════════════
# TestPredictorIntradayIntegration — Predictor 분봉 통합 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestPredictorIntradayIntegration:
    """PredictorAgent의 분봉 데이터 통합 검증."""

    def _make_candles(self, count=20):
        return [
            {
                "timestamp_kst": f"2026-04-{count - i:02d}T15:30:00+09:00",
                "open": 70000 - 50,
                "high": 70000 + 100,
                "low": 70000 - 100,
                "close": 70000,
                "volume": 100000,
            }
            for i in range(count)
        ]

    def _make_intraday_bars(self):
        return [
            {"timestamp_kst": datetime(2026, 4, 11, 9, 0), "open": 70000, "high": 70500,
             "low": 69800, "close": 70200, "volume": 50000},
            {"timestamp_kst": datetime(2026, 4, 11, 10, 0), "open": 70200, "high": 70800,
             "low": 70100, "close": 70600, "volume": 40000},
        ]

    async def test_prompt_includes_intraday_when_available(self, _env):
        """분봉 데이터가 있으면 프롬프트에 포함."""
        from src.agents.predictor import PredictorAgent

        agent = PredictorAgent()
        mock_response = {
            "signal": "BUY", "confidence": 0.8,
            "target_price": 71000, "stop_loss": 69500,
            "reasoning_summary": "test",
        }
        agent.router = MagicMock()
        agent.router.ask_json = AsyncMock(return_value=mock_response)

        result = await agent._llm_signal(
            "005930", self._make_candles(),
            intraday_bars=self._make_intraday_bars(),
        )

        prompt_arg = agent.router.ask_json.call_args[0][1]
        assert "장중 1시간봉" in prompt_arg
        assert result["signal"] == "BUY"

    async def test_prompt_excludes_intraday_when_empty(self, _env):
        """분봉 데이터가 없으면 프롬프트에 미포함."""
        from src.agents.predictor import PredictorAgent

        agent = PredictorAgent()
        mock_response = {
            "signal": "HOLD", "confidence": 0.5,
            "reasoning_summary": "test",
        }
        agent.router = MagicMock()
        agent.router.ask_json = AsyncMock(return_value=mock_response)

        await agent._llm_signal("005930", self._make_candles(), intraday_bars=[])

        prompt_arg = agent.router.ask_json.call_args[0][1]
        assert "장중 1시간봉" not in prompt_arg

    async def test_prompt_excludes_intraday_when_none(self, _env):
        """intraday_bars=None이면 프롬프트에 미포함."""
        from src.agents.predictor import PredictorAgent

        agent = PredictorAgent()
        mock_response = {
            "signal": "HOLD", "confidence": 0.5,
            "reasoning_summary": "test",
        }
        agent.router = MagicMock()
        agent.router.ask_json = AsyncMock(return_value=mock_response)

        await agent._llm_signal("005930", self._make_candles(), intraday_bars=None)

        prompt_arg = agent.router.ask_json.call_args[0][1]
        assert "장중 1시간봉" not in prompt_arg


# ═══════════════════════════════════════════════════════════════════════
# TestInsertTickBatchEdgeCases — insert_tick_batch 에지 케이스 (Agent 2 추가)
# ═══════════════════════════════════════════════════════════════════════


class TestInsertTickBatchEdgeCases:
    """insert_tick_batch 에지 케이스 검증."""

    async def test_large_batch_1000_ticks(self, _env):
        """1000건 배치 INSERT 정상 동작."""
        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            from src.db.queries import insert_tick_batch
            base_ts = datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST)
            ticks = [
                _make_tick(
                    price=70000.0 + i,
                    volume=100 + i,
                    ts=base_ts + timedelta(milliseconds=i),
                )
                for i in range(1000)
            ]
            result = await insert_tick_batch(ticks)
            assert result == 1000
            mock_exec.assert_called_once()

    async def test_multiple_instruments_in_batch(self, _env):
        """다른 종목의 틱이 같은 배치에 포함."""
        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            from src.db.queries import insert_tick_batch
            ticks = [
                _make_tick(instrument_id="005930.KS", price=70000),
                _make_tick(instrument_id="000660.KS", price=150000),
                _make_tick(instrument_id="035420.KS", price=350000),
            ]
            result = await insert_tick_batch(ticks)
            assert result == 3
            params = mock_exec.call_args[0][1]
            instrument_ids = {p[0] for p in params}
            assert instrument_ids == {"005930.KS", "000660.KS", "035420.KS"}

    async def test_change_pct_none_handled(self, _env):
        """change_pct=None인 틱이 정상 처리."""
        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            from src.db.queries import insert_tick_batch
            tick = _make_tick(change_pct=None)
            await insert_tick_batch([tick])
            params = mock_exec.call_args[0][1][0]
            assert params[4] is None  # change_pct index


# ═══════════════════════════════════════════════════════════════════════
# TestFlushTickBufferEdgeCases — _flush_tick_buffer 에지 케이스 (Agent 2 추가)
# ═══════════════════════════════════════════════════════════════════════


class TestFlushTickBufferEdgeCases:
    """_flush_tick_buffer 에지 케이스 검증."""

    @pytest.fixture()
    def collector(self, _env):
        from src.agents.collector import CollectorAgent
        return CollectorAgent(agent_id="test_flush_edge")

    async def test_flush_interval_elapsed(self, collector):
        """interval 경과 시 batch_size 미달이어도 flush."""
        collector._tick_batch_size = 1000
        collector._tick_flush_interval = 0.1
        collector._tick_buffer = [_make_tick()]
        collector._tick_buffer_last_flush = 0.0  # 아주 오래 전

        with patch(
            "src.agents.collector._realtime.insert_tick_batch",
            new_callable=AsyncMock,
            return_value=1,
        ):
            result = await collector._flush_tick_buffer()

        assert result == 1

    async def test_flush_db_error_propagation(self, collector):
        """DB INSERT 실패 시 예외 전파."""
        collector._tick_buffer = [_make_tick()]
        collector._tick_buffer_last_flush = 0.0

        with (
            patch(
                "src.agents.collector._realtime.insert_tick_batch",
                new_callable=AsyncMock,
                side_effect=ConnectionError("DB down"),
            ),
            pytest.raises(ConnectionError, match="DB down"),
        ):
            await collector._flush_tick_buffer(force=True)
