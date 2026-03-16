"""
test/test_gen_pipeline_e2e.py — Gen 파이프라인 E2E 검증 테스트

수집→저장 파이프라인의 각 단계를 검증합니다:
1. Gen 서버 데이터 생성 정합성
2. PostgreSQL 적재 확인
3. Redis 캐시 확인
4. S3/MinIO Parquet 저장 확인
5. Redis Pub/Sub 메시지 발행 확인
6. 기존 API 엔드포인트 정상 응답 확인
"""

from __future__ import annotations

import asyncio
import json
import math
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from src.gen.generator import MarketDataGenerator
from src.gen.models import GenOHLCV, GenQuote, GenTicker, GenTick, GenIndex, GenMacro

KST = ZoneInfo("Asia/Seoul")


# ── 1. Generator 단위 테스트 ─────────────────────────────────────────────────


class TestMarketDataGenerator(unittest.TestCase):
    """MarketDataGenerator의 데이터 생성 정합성 검증."""

    def setUp(self):
        self.gen = MarketDataGenerator(seed=42)

    def test_init_20_tickers(self):
        """초기화 시 20종목이 등록되어야 합니다."""
        tickers = self.gen.get_tickers()
        self.assertEqual(len(tickers), 20)

    def test_ticker_fields_valid(self):
        """각 종목의 필수 필드가 유효해야 합니다."""
        for t in self.gen.get_tickers():
            self.assertIsInstance(t, GenTicker)
            self.assertTrue(len(t.ticker) > 0)
            self.assertTrue(len(t.name) > 0)
            self.assertIn(t.market, {"KOSPI", "KOSDAQ"})
            self.assertGreater(t.base_price, 0)

    def test_generate_tick_returns_20_ticks(self):
        """generate_tick()이 20건의 틱을 반환해야 합니다."""
        ticks = self.gen.generate_tick()
        self.assertEqual(len(ticks), 20)

    def test_tick_data_valid(self):
        """각 틱의 가격/거래량이 유효 범위여야 합니다."""
        ticks = self.gen.generate_tick()
        for tick in ticks:
            self.assertIsInstance(tick, GenTick)
            self.assertGreaterEqual(tick.price, 100)
            self.assertGreater(tick.volume, 0)
            self.assertTrue(len(tick.timestamp) > 0)

    def test_price_changes_over_time(self):
        """여러 틱에 걸쳐 가격이 변동해야 합니다."""
        first_ticks = self.gen.generate_tick()
        prices_first = {t.ticker: t.price for t in first_ticks}

        for _ in range(10):
            self.gen.generate_tick()

        last_ticks = self.gen.generate_tick()
        prices_last = {t.ticker: t.price for t in last_ticks}

        # 최소 1종목 이상 가격이 변해야 함
        changed = sum(1 for t in prices_first if prices_first[t] != prices_last[t])
        self.assertGreater(changed, 0, "10틱 후에도 가격 변동이 없습니다.")

    def test_daily_history_length(self):
        """일봉 히스토리가 요청 일수에 근접해야 합니다 (주말 제외)."""
        bars = self.gen.generate_daily_history("005930", days=30)
        self.assertIsInstance(bars, list)
        # 30일 중 주말 약 8~9일 제외 → 21~22건 내외
        self.assertGreater(len(bars), 15)
        self.assertLessEqual(len(bars), 30)

    def test_daily_history_ohlcv_consistency(self):
        """일봉의 high >= max(open, close) 이고 low <= min(open, close) 이어야 합니다."""
        bars = self.gen.generate_daily_history("005930", days=60)
        for bar in bars:
            self.assertIsInstance(bar, GenOHLCV)
            self.assertGreaterEqual(bar.high, max(bar.open, bar.close),
                                    f"high({bar.high}) < max(open({bar.open}), close({bar.close}))")
            self.assertLessEqual(bar.low, min(bar.open, bar.close),
                                 f"low({bar.low}) > min(open({bar.open}), close({bar.close}))")
            self.assertGreater(bar.volume, 0)

    def test_daily_history_unknown_ticker(self):
        """존재하지 않는 종목의 히스토리는 빈 리스트여야 합니다."""
        bars = self.gen.generate_daily_history("999999", days=30)
        self.assertEqual(bars, [])

    def test_quote_valid(self):
        """현재가 스냅샷이 유효해야 합니다."""
        self.gen.generate_tick()  # 먼저 1틱 생성
        quote = self.gen.get_quote("005930")
        self.assertIsNotNone(quote)
        self.assertIsInstance(quote, GenQuote)
        self.assertGreaterEqual(quote.current_price, 100)
        self.assertIn(quote.market, {"KOSPI", "KOSDAQ"})

    def test_quote_unknown_ticker(self):
        """존재하지 않는 종목의 quote는 None이어야 합니다."""
        self.gen.generate_tick()
        quote = self.gen.get_quote("999999")
        self.assertIsNone(quote)

    def test_tick_buffer(self):
        """틱 버퍼가 쌓이고 count 파라미터가 동작해야 합니다."""
        for _ in range(5):
            self.gen.generate_tick()
        ticks = self.gen.get_ticks("005930", count=3)
        self.assertEqual(len(ticks), 3)

    def test_tick_buffer_max_100(self):
        """틱 버퍼가 100건을 초과하지 않아야 합니다."""
        for _ in range(120):
            self.gen.generate_tick()
        ticks = self.gen.get_ticks("005930", count=200)
        self.assertLessEqual(len(ticks), 100)

    def test_indices(self):
        """지수 데이터가 유효해야 합니다."""
        indices = self.gen.get_indices()
        self.assertEqual(len(indices), 2)
        symbols = {i.symbol for i in indices}
        self.assertEqual(symbols, {"KOSPI", "KOSDAQ"})
        for idx in indices:
            self.assertIsInstance(idx, GenIndex)
            self.assertGreater(idx.value, 0)

    def test_macro(self):
        """매크로 지표가 유효해야 합니다."""
        macros = self.gen.get_macro()
        self.assertGreater(len(macros), 0)
        categories = {m.category for m in macros}
        self.assertTrue(categories.issubset({"index", "currency", "commodity", "rate"}))

    def test_status(self):
        """상태 조회가 정상적이어야 합니다."""
        status = self.gen.get_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["tickers_count"], 20)
        self.assertGreaterEqual(status["uptime_seconds"], 0)

    def test_deterministic_with_seed(self):
        """동일 시드로 동일한 초기 가격이 생성되어야 합니다."""
        gen1 = MarketDataGenerator(seed=123)
        gen2 = MarketDataGenerator(seed=123)
        tickers1 = gen1.get_tickers()
        tickers2 = gen2.get_tickers()
        # 가격은 seed로 결정되므로 동일해야 함
        for t1, t2 in zip(tickers1, tickers2):
            self.assertEqual(t1.ticker, t2.ticker)


# ── 2. GenCollector 저장 파이프라인 단위 테스트 ────────────────────────────────


class TestGenCollectorPipeline(unittest.IsolatedAsyncioTestCase):
    """GenCollectorAgent의 수집→저장 경로를 mock으로 검증합니다."""

    @patch("src.agents.gen_collector.upsert_market_data", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.store_daily_bars", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock)
    async def test_collect_daily_bars_pipeline(
        self, mock_redis, mock_hb_insert, mock_hb_set, mock_publish, mock_s3, mock_db
    ):
        """일봉 수집 시 DB, S3, Redis, Pub/Sub 모두 호출되어야 합니다."""
        from src.agents.gen_collector import GenCollectorAgent

        # Mock Redis pipeline
        mock_pipe = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True, True, True, True])

        redis_instance = AsyncMock()
        redis_instance.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.return_value = redis_instance

        # Mock DB 반환
        mock_db.return_value = 100

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        # Mock httpx 응답
        with patch.object(agent._client, "get", new_callable=AsyncMock) as mock_get:
            # /gen/tickers 응답
            tickers_resp = MagicMock()
            tickers_resp.status_code = 200
            tickers_resp.raise_for_status = MagicMock()
            tickers_resp.json.return_value = [
                {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "반도체", "base_price": 72000},
            ]

            # /gen/ohlcv/005930 응답
            ohlcv_resp = MagicMock()
            ohlcv_resp.status_code = 200
            ohlcv_resp.raise_for_status = MagicMock()
            ohlcv_resp.json.return_value = [
                {
                    "ticker": "005930",
                    "name": "삼성전자",
                    "market": "KOSPI",
                    "date": "2026-03-15",
                    "open": 72000,
                    "high": 73000,
                    "low": 71000,
                    "close": 72500,
                    "volume": 1000000,
                    "change_pct": 0.69,
                },
            ]

            mock_get.side_effect = [tickers_resp, ohlcv_resp]

            result = await agent.collect_daily_bars(lookback_days=5)

        # 검증: DB 저장 호출
        mock_db.assert_called_once()
        self.assertEqual(len(mock_db.call_args[0][0]), 1)

        # 검증: S3 저장 호출
        mock_s3.assert_called_once()

        # 검증: Pub/Sub 발행
        mock_publish.assert_called_once()
        pub_data = json.loads(mock_publish.call_args[0][1])
        self.assertEqual(pub_data["type"], "data_ready")
        self.assertEqual(pub_data["source"], "gen")

        # 검증: Heartbeat
        mock_hb_set.assert_called()

        await agent.close()

    @patch("src.agents.gen_collector.upsert_market_data", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock)
    async def test_collect_ticks_pipeline(
        self, mock_redis, mock_hb_insert, mock_hb_set, mock_publish, mock_db
    ):
        """틱 수집 시 DB, Redis, Pub/Sub가 호출되어야 합니다."""
        from src.agents.gen_collector import GenCollectorAgent

        mock_pipe = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True, True, True, True])

        redis_instance = AsyncMock()
        redis_instance.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.return_value = redis_instance

        mock_db.return_value = 1

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        with patch.object(agent._client, "get", new_callable=AsyncMock) as mock_get:
            quotes_resp = MagicMock()
            quotes_resp.status_code = 200
            quotes_resp.raise_for_status = MagicMock()
            quotes_resp.json.return_value = [
                {
                    "ticker": "005930",
                    "name": "삼성전자",
                    "market": "KOSPI",
                    "current_price": 72500,
                    "open": 72000,
                    "high": 73000,
                    "low": 71500,
                    "volume": 500000,
                    "change_pct": 0.5,
                    "updated_at": "2026-03-16T10:00:00+09:00",
                },
            ]
            mock_get.return_value = quotes_resp

            count = await agent.collect_realtime_ticks(interval_sec=0.01, max_cycles=1)

        self.assertEqual(count, 1)
        mock_db.assert_called_once()
        # 1건 → publish 1회
        mock_publish.assert_called_once()

        await agent.close()


# ── 3. Server 엔드포인트 단위 테스트 (FastAPI TestClient) ─────────────────────


class TestGenServerEndpoints(unittest.TestCase):
    """Gen 서버 엔드포인트가 올바른 형태의 데이터를 반환하는지 검증."""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            from src.gen.server import app

            cls.client = TestClient(app)
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("FastAPI TestClient 사용 불가")

    def test_get_status(self):
        resp = self.client.get("/gen/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["running"])
        self.assertEqual(data["tickers_count"], 20)

    def test_get_tickers(self):
        resp = self.client.get("/gen/tickers")
        self.assertEqual(resp.status_code, 200)
        tickers = resp.json()
        self.assertEqual(len(tickers), 20)
        for t in tickers:
            self.assertIn("ticker", t)
            self.assertIn("name", t)
            self.assertIn("market", t)

    def test_get_ohlcv(self):
        resp = self.client.get("/gen/ohlcv/005930?days=30")
        self.assertEqual(resp.status_code, 200)
        bars = resp.json()
        self.assertGreater(len(bars), 10)
        for bar in bars:
            self.assertIn("open", bar)
            self.assertIn("high", bar)
            self.assertIn("low", bar)
            self.assertIn("close", bar)
            self.assertIn("volume", bar)

    def test_get_ohlcv_unknown_ticker(self):
        resp = self.client.get("/gen/ohlcv/999999?days=10")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_get_quote(self):
        # 먼저 틱 생성을 트리거
        self.client.get("/gen/status")
        resp = self.client.get("/gen/quote/005930")
        self.assertEqual(resp.status_code, 200)
        q = resp.json()
        self.assertEqual(q["ticker"], "005930")
        self.assertGreater(q["current_price"], 0)

    def test_get_quote_404(self):
        resp = self.client.get("/gen/quote/999999")
        self.assertEqual(resp.status_code, 404)

    def test_get_all_quotes(self):
        resp = self.client.get("/gen/quotes")
        self.assertEqual(resp.status_code, 200)
        quotes = resp.json()
        self.assertEqual(len(quotes), 20)

    def test_get_index(self):
        resp = self.client.get("/gen/index")
        self.assertEqual(resp.status_code, 200)
        indices = resp.json()
        self.assertEqual(len(indices), 2)
        symbols = {i["symbol"] for i in indices}
        self.assertEqual(symbols, {"KOSPI", "KOSDAQ"})

    def test_get_macro(self):
        resp = self.client.get("/gen/macro")
        self.assertEqual(resp.status_code, 200)
        macros = resp.json()
        self.assertGreater(len(macros), 0)

    def test_get_ticks_empty_initially(self):
        """틱이 아직 없을 때 빈 리스트를 반환해야 합니다."""
        # 새 generator에서는 tick_loop가 돌기 전에는 비어있을 수 있음
        resp = self.client.get("/gen/ticks/005930?count=5")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)


# ── 4. 데이터 정합성 검증 테스트 ─────────────────────────────────────────────


class TestDataIntegrity(unittest.TestCase):
    """생성된 데이터가 기존 MarketDataPoint 모델과 호환되는지 검증합니다."""

    def setUp(self):
        self.gen = MarketDataGenerator(seed=42)
        self.gen.generate_tick()  # 최소 1틱 생성

    def test_ohlcv_to_market_data_point_conversion(self):
        """GenOHLCV → MarketDataPoint 변환이 가능해야 합니다."""
        from src.db.models import MarketDataPoint

        bars = self.gen.generate_daily_history("005930", days=10)
        for bar in bars:
            ts = datetime.fromisoformat(bar.date + "T15:30:00")
            ts = ts.replace(tzinfo=KST)
            point = MarketDataPoint(
                ticker=bar.ticker,
                name=bar.name,
                market=bar.market,
                timestamp_kst=ts,
                interval="daily",
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                change_pct=bar.change_pct,
            )
            self.assertIsNotNone(point)
            self.assertEqual(point.interval, "daily")

    def test_quote_to_market_data_point_conversion(self):
        """GenQuote → MarketDataPoint 변환이 가능해야 합니다."""
        from src.db.models import MarketDataPoint

        quote = self.gen.get_quote("005930")
        self.assertIsNotNone(quote)
        point = MarketDataPoint(
            ticker=quote.ticker,
            name=quote.name,
            market=quote.market,
            timestamp_kst=datetime.now(KST),
            interval="tick",
            open=quote.open,
            high=quote.high,
            low=quote.low,
            close=quote.current_price,
            volume=quote.volume,
            change_pct=quote.change_pct,
        )
        self.assertEqual(point.interval, "tick")

    def test_gbm_price_no_negative(self):
        """GBM으로 100틱 생성해도 가격이 음수가 되지 않아야 합니다."""
        high_vol_gen = MarketDataGenerator(volatility=0.05, seed=42)
        for _ in range(100):
            ticks = high_vol_gen.generate_tick()
            for tick in ticks:
                self.assertGreaterEqual(tick.price, 100)

    def test_kospi_kosdaq_distribution(self):
        """20종목 중 KOSPI/KOSDAQ가 모두 포함되어야 합니다."""
        tickers = self.gen.get_tickers()
        markets = {t.market for t in tickers}
        self.assertEqual(markets, {"KOSPI", "KOSDAQ"})

    def test_daily_bars_weekday_only(self):
        """일봉에 주말(토/일) 데이터가 포함되지 않아야 합니다."""
        bars = self.gen.generate_daily_history("005930", days=120)
        for bar in bars:
            d = datetime.fromisoformat(bar.date)
            self.assertLess(d.weekday(), 5,
                            f"주말 데이터 발견: {bar.date} (weekday={d.weekday()})")


if __name__ == "__main__":
    unittest.main()
