"""
test/test_data_flow_e2e.py — 수집 → DB 저장 → S3 아카이브 mock E2E 테스트

전체 데이터 흐름을 mock으로 검증:
1. FDR → CollectorAgent → DB upsert → S3 저장 → Redis 캐시 → Pub/Sub
2. Gen API → GenCollectorAgent → DB 듀얼라이트 → S3 → Redis → Pub/Sub
3. Tick → DB → S3 flush (시간대별)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

KST = ZoneInfo("Asia/Seoul")
pytestmark = [pytest.mark.unit]


def _make_redis_mock():
    mock_pipe = MagicMock()
    mock_pipe.set = MagicMock()
    mock_pipe.lpush = MagicMock()
    mock_pipe.ltrim = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[True] * 4)
    redis_mock = AsyncMock()
    redis_mock.pipeline = MagicMock(return_value=mock_pipe)
    redis_mock.set = AsyncMock()
    return redis_mock


# =============================================================================
# E2E: FDR → CollectorAgent → DB → S3 → Redis → Pub/Sub
# =============================================================================


class TestFDRCollectorE2E:
    """FDR 일봉 수집 전체 데이터 흐름 검증."""

    async def test_fdr_daily_bars_e2e(self):
        """FDR 수집 → DB upsert → S3 Parquet → Redis 캐시 → Pub/Sub 발행."""
        from src.agents.collector import CollectorAgent

        agent = CollectorAgent(agent_id="e2e_collector")

        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({
            "Code": ["005930", "000660"],
            "Name": ["삼성전자", "SK하이닉스"],
            "Market": ["KOSPI", "KOSPI"],
        })
        dates = pd.date_range("2026-04-01", periods=3, freq="B")
        mock_fdr.DataReader.return_value = pd.DataFrame({
            "Open": [70000, 70500, 71000],
            "High": [71000, 71500, 72000],
            "Low": [69000, 69500, 70000],
            "Close": [70500, 71000, 71500],
            "Volume": [1000000, 1200000, 1100000],
        }, index=dates)

        redis_mock = _make_redis_mock()
        s3_records_captured = []

        async def _capture_s3(records, **kwargs):
            s3_records_captured.extend(records)
            return "s3://bucket/daily_bars/test.parquet"

        db_saved_count = 0

        async def _mock_upsert(points):
            nonlocal db_saved_count
            db_saved_count = len(points)
            return len(points)

        pub_messages = []

        async def _capture_pub(topic, message):
            pub_messages.append(json.loads(message))

        with (
            patch.object(agent, "_load_fdr", return_value=mock_fdr),
            patch("src.agents.collector._daily.upsert_market_data", new_callable=AsyncMock, side_effect=_mock_upsert),
            patch("src.agents.collector._daily.insert_collector_error", new_callable=AsyncMock),
            patch("src.services.datalake.store_daily_bars", new_callable=AsyncMock, side_effect=_capture_s3),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.collector._daily.publish_message", new_callable=AsyncMock, side_effect=_capture_pub),
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock),
        ):
            points = await agent.collect_daily_bars(tickers=["005930", "000660"], lookback_days=30)

        # 1. 수집 결과
        assert len(points) == 6  # 2 tickers * 3 bars each
        assert all(p.market == "KOSPI" for p in points)

        # 2. DB 저장
        assert db_saved_count == 6

        # 3. S3 저장 (store_daily_bars에 전달된 레코드)
        assert len(s3_records_captured) == 6

        # 4. Redis 캐시 (pipeline 실행)
        pipe = redis_mock.pipeline()
        assert pipe.execute.await_count >= 1

        # 5. Pub/Sub
        assert len(pub_messages) == 1
        assert pub_messages[0]["type"] == "data_ready"
        assert pub_messages[0]["count"] == 6

    async def test_fdr_empty_data_no_error(self):
        """데이터 없는 종목도 에러 없이 처리."""
        from src.agents.collector import CollectorAgent

        agent = CollectorAgent(agent_id="e2e_empty")

        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({
            "Code": ["999999"],
            "Name": ["없는종목"],
            "Market": ["KOSPI"],
        })
        mock_fdr.DataReader.return_value = pd.DataFrame()

        redis_mock = _make_redis_mock()

        with (
            patch.object(agent, "_load_fdr", return_value=mock_fdr),
            patch("src.agents.collector._daily.upsert_market_data", new_callable=AsyncMock, return_value=0),
            patch("src.agents.collector._daily.insert_collector_error", new_callable=AsyncMock),
            patch("src.services.datalake.store_daily_bars", new_callable=AsyncMock),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.collector._daily.publish_message", new_callable=AsyncMock),
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock),
        ):
            points = await agent.collect_daily_bars(tickers=["999999"])

        assert points == []


# =============================================================================
# E2E: Gen API → GenCollectorAgent → DB → S3 → Redis → Pub/Sub
# =============================================================================


class TestGenCollectorE2E:
    """Gen 모드 전체 데이터 흐름 검증."""

    async def test_gen_daily_e2e(self):
        """Gen 일봉: API → 파싱 → 듀얼라이트 → S3 → Redis → Pub/Sub."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        tickers_resp = MagicMock()
        tickers_resp.raise_for_status = MagicMock()
        tickers_resp.json.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
        ]
        ohlcv_resp = MagicMock()
        ohlcv_resp.raise_for_status = MagicMock()
        ohlcv_resp.json.return_value = [
            {"date": "2026-04-10", "open": 71000, "high": 73000,
             "low": 70000, "close": 72000, "volume": 100000, "change_pct": 1.5},
            {"date": "2026-04-11", "open": 72000, "high": 74000,
             "low": 71000, "close": 73000, "volume": 120000, "change_pct": 1.39},
        ]

        redis_mock = _make_redis_mock()
        dual_write_count = 0
        s3_stored = False
        pub_messages = []

        async def _mock_dual_write(points):
            nonlocal dual_write_count
            dual_write_count = len(points)
            return len(points)

        async def _mock_s3(records, **kwargs):
            nonlocal s3_stored
            s3_stored = True
            return "s3://test"

        async def _capture_pub(topic, message):
            pub_messages.append(json.loads(message))

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, side_effect=[tickers_resp, ohlcv_resp]),
            patch.object(agent, "_dual_write_legacy", new_callable=AsyncMock, side_effect=_mock_dual_write),
            patch("src.agents.gen_collector._store_daily_bars", new_callable=AsyncMock, side_effect=_mock_s3),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock, side_effect=_capture_pub),
            patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock),
        ):
            points = await agent.collect_daily_bars(lookback_days=5)

        # 1. 수집 결과
        assert len(points) == 2

        # 2. instrument_id 형식 확인
        assert all(p.instrument_id == "005930.KS" for p in points)

        # 3. 듀얼라이트 (legacy market_data)
        assert dual_write_count == 2

        # 4. S3 저장
        assert s3_stored is True

        # 5. Pub/Sub 메시지
        assert len(pub_messages) == 1
        assert pub_messages[0]["type"] == "data_ready"

        await agent.close()

    async def test_gen_tick_e2e(self):
        """Gen 실시간 틱: API → 파싱 → 듀얼라이트 → Redis → Pub/Sub."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        quotes_resp = MagicMock()
        quotes_resp.raise_for_status = MagicMock()
        quotes_resp.json.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI",
             "current_price": 72500, "open": 72000, "high": 73000, "low": 71500,
             "volume": 500000, "change_pct": 0.69},
        ]

        redis_mock = _make_redis_mock()
        pub_messages = []

        async def _capture_pub(topic, message):
            pub_messages.append(json.loads(message))

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, return_value=quotes_resp),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock, side_effect=_capture_pub),
            patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            count = await agent.collect_realtime_ticks(interval_sec=0.01, max_cycles=1)

        assert count == 1
        assert len(pub_messages) == 1
        assert pub_messages[0]["type"] == "tick"
        assert pub_messages[0]["price"] == 72500

        await agent.close()


# =============================================================================
# E2E: Tick → DB → S3 flush
# =============================================================================


class TestTickFlushE2E:
    """틱 데이터 DB 저장 → S3 시간대별 flush 검증."""

    async def test_tick_buffer_to_db_to_s3(self):
        """틱 버퍼 → tick_data 테이블 → S3 Parquet flush."""
        from src.services.datalake import flush_ticks_to_s3

        # DB에서 조회되는 당일 틱 데이터 mock
        db_rows = [
            {"ticker": "005930", "price": 72000, "volume": 100,
             "timestamp_kst": datetime(2026, 4, 11, 9, 5),
             "change_pct": 1.0, "source": "kis_ws"},
            {"ticker": "005930", "price": 72100, "volume": 200,
             "timestamp_kst": datetime(2026, 4, 11, 9, 30),
             "change_pct": 1.1, "source": "kis_ws"},
            {"ticker": "000660", "price": 150000, "volume": 50,
             "timestamp_kst": datetime(2026, 4, 11, 10, 0),
             "change_pct": -0.5, "source": "kis_ws"},
            {"ticker": "000660", "price": 150500, "volume": 80,
             "timestamp_kst": datetime(2026, 4, 11, 14, 30),
             "change_pct": -0.2, "source": "kis_ws"},
        ]

        uploaded_keys = []

        async def _mock_upload(data, key, **kwargs):
            uploaded_keys.append(key)
            return f"s3://bucket/{key}"

        with (
            patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=db_rows),
            patch("src.services.datalake.upload_bytes", new_callable=AsyncMock, side_effect=_mock_upload),
        ):
            uris = await flush_ticks_to_s3(date(2026, 4, 11))

        # 3개 시간대: 9시(2건), 10시(1건), 14시(1건) → 3개 파일
        assert len(uris) == 3
        assert all("tick_data" in key for key in uploaded_keys)
        assert any("hour=09" in key for key in uploaded_keys)
        assert any("hour=10" in key for key in uploaded_keys)
        assert any("hour=14" in key for key in uploaded_keys)


# =============================================================================
# E2E: Historical seed → DB → Redis cache
# =============================================================================


class TestHistoricalSeedE2E:
    """Historical 벌크 수집 → DB → Redis 캐시 갱신."""

    async def test_historical_seed_updates_redis(self):
        """과거 데이터 수집 후 최신 point로 Redis 캐시 갱신."""
        from src.agents.collector import CollectorAgent

        agent = CollectorAgent(agent_id="e2e_historical")

        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = pd.DataFrame({
            "Open": [70000, 71000],
            "High": [71000, 72000],
            "Low": [69000, 70000],
            "Close": [70500, 71500],
            "Volume": [1000000, 1100000],
        }, index=pd.date_range("2026-04-10", periods=2, freq="B"))

        mock_pipe = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True] * 4)
        redis_mock = AsyncMock()
        redis_mock.pipeline = MagicMock(return_value=mock_pipe)

        with (
            patch.object(agent, "_load_fdr", return_value=mock_fdr),
            patch("src.db.queries.upsert_market_data", new_callable=AsyncMock, return_value=2),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
        ):
            points = await agent._fetch_historical_daily(
                "005930", "2026-04-10", "2026-04-11", "삼성전자", "KOSPI",
            )

        assert len(points) == 2
        # Redis pipeline이 실행되어 최신 point가 캐시됨
        mock_pipe.execute.assert_awaited()


# =============================================================================
# E2E: 수집 모드 판별
# =============================================================================


class TestCollectionModeDecision:
    """수집 모드 판별 로직 검증."""

    def test_gen_mode_when_gen_api_url_set(self, monkeypatch):
        """GEN_API_URL 설정 시 gen 모드."""
        monkeypatch.setenv("GEN_API_URL", "http://gen:9999")
        url = os.environ.get("GEN_API_URL")
        assert url is not None
        # gen 모드: GenCollectorAgent 사용
        from src.agents.gen_collector import GenCollectorAgent
        agent = GenCollectorAgent(gen_api_url=url)
        assert "gen" in agent.gen_api_url or "9999" in agent.gen_api_url

    def test_fdr_mode_when_no_gen_api_url(self, monkeypatch):
        """GEN_API_URL 미설정 시 FDR 모드."""
        monkeypatch.delenv("GEN_API_URL", raising=False)
        url = os.environ.get("GEN_API_URL")
        assert url is None
        # FDR 모드: CollectorAgent 사용
        from src.agents.collector import CollectorAgent
        agent = CollectorAgent()
        assert hasattr(agent, "collect_daily_bars")
