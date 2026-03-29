"""
test/test_gen_pipeline_e2e.py — Gen 파이프라인 E2E 검증 테스트

수집→저장 파이프라인의 각 단계를 검증합니다:
1. Gen 서버 데이터 생성 정합성
2. PostgreSQL 적재 확인
3. Redis 캐시 확인
4. S3/MinIO Parquet 저장 확인
5. Redis Pub/Sub 메시지 발행 확인
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from src.gen.generator import MarketDataGenerator
from src.gen.models import GenOHLCV, GenQuote, GenTicker, GenTick, GenIndex, GenMacro

KST = ZoneInfo("Asia/Seoul")


class TestMarketDataGenerator(unittest.TestCase):
    """MarketDataGenerator의 데이터 생성 정합성 검증."""

    def setUp(self):
        self.gen = MarketDataGenerator(seed=42)

    def test_init_20_tickers(self):
        tickers = self.gen.get_tickers()
        self.assertEqual(len(tickers), 20)

    def test_ticker_fields_valid(self):
        for t in self.gen.get_tickers():
            self.assertIsInstance(t, GenTicker)
            self.assertTrue(len(t.ticker) > 0)
            self.assertIn(t.market, {"KOSPI", "KOSDAQ"})
            self.assertGreater(t.base_price, 0)

    def test_generate_tick_returns_20_ticks(self):
        ticks = self.gen.generate_tick()
        self.assertEqual(len(ticks), 20)

    def test_tick_data_valid(self):
        ticks = self.gen.generate_tick()
        for tick in ticks:
            self.assertIsInstance(tick, GenTick)
            self.assertGreaterEqual(tick.price, 100)
            self.assertGreater(tick.volume, 0)

    def test_price_changes_over_time(self):
        first_ticks = self.gen.generate_tick()
        prices_first = {t.ticker: t.price for t in first_ticks}
        for _ in range(10):
            self.gen.generate_tick()
        last_ticks = self.gen.generate_tick()
        prices_last = {t.ticker: t.price for t in last_ticks}
        changed = sum(1 for t in prices_first if prices_first[t] != prices_last[t])
        self.assertGreater(changed, 0)

    def test_daily_history_length(self):
        bars = self.gen.generate_daily_history("005930", days=30)
        self.assertGreater(len(bars), 15)
        self.assertLessEqual(len(bars), 30)

    def test_daily_history_ohlcv_consistency(self):
        bars = self.gen.generate_daily_history("005930", days=60)
        for bar in bars:
            self.assertGreaterEqual(bar.high, max(bar.open, bar.close))
            self.assertLessEqual(bar.low, min(bar.open, bar.close))
            self.assertGreater(bar.volume, 0)

    def test_daily_history_unknown_ticker(self):
        bars = self.gen.generate_daily_history("999999", days=30)
        self.assertEqual(bars, [])

    def test_quote_valid(self):
        self.gen.generate_tick()
        quote = self.gen.get_quote("005930")
        self.assertIsNotNone(quote)
        self.assertIsInstance(quote, GenQuote)
        self.assertGreaterEqual(quote.current_price, 100)

    def test_quote_unknown_ticker(self):
        self.gen.generate_tick()
        quote = self.gen.get_quote("999999")
        self.assertIsNone(quote)

    def test_tick_buffer(self):
        for _ in range(5):
            self.gen.generate_tick()
        ticks = self.gen.get_ticks("005930", count=3)
        self.assertEqual(len(ticks), 3)

    def test_tick_buffer_max_100(self):
        for _ in range(120):
            self.gen.generate_tick()
        ticks = self.gen.get_ticks("005930", count=200)
        self.assertLessEqual(len(ticks), 100)

    def test_indices(self):
        indices = self.gen.get_indices()
        self.assertEqual(len(indices), 2)
        symbols = {i.symbol for i in indices}
        self.assertEqual(symbols, {"KOSPI", "KOSDAQ"})

    def test_macro(self):
        macros = self.gen.get_macro()
        self.assertGreater(len(macros), 0)

    def test_status(self):
        status = self.gen.get_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["tickers_count"], 20)

    def test_deterministic_with_seed(self):
        gen1 = MarketDataGenerator(seed=123)
        gen2 = MarketDataGenerator(seed=123)
        for t1, t2 in zip(gen1.get_tickers(), gen2.get_tickers()):
            self.assertEqual(t1.ticker, t2.ticker)

    def test_gbm_price_no_negative(self):
        high_vol_gen = MarketDataGenerator(volatility=0.05, seed=42)
        for _ in range(100):
            ticks = high_vol_gen.generate_tick()
            for tick in ticks:
                self.assertGreaterEqual(tick.price, 100)

    def test_kospi_kosdaq_distribution(self):
        tickers = self.gen.get_tickers()
        markets = {t.market for t in tickers}
        self.assertEqual(markets, {"KOSPI", "KOSDAQ"})

    def test_daily_bars_weekday_only(self):
        bars = self.gen.generate_daily_history("005930", days=120)
        for bar in bars:
            d = datetime.fromisoformat(bar.date)
            self.assertLess(d.weekday(), 5)


class TestGenCollectorPipeline(unittest.IsolatedAsyncioTestCase):
    """GenCollectorAgent의 수집→저장 경로를 mock으로 검증합니다."""

    @patch("src.agents.gen_collector.upsert_market_data", new_callable=AsyncMock)
    @patch("src.agents.gen_collector._store_daily_bars", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock)
    async def test_collect_daily_bars_pipeline(
        self, mock_redis, mock_hb_insert, mock_hb_set, mock_publish, mock_s3, mock_db
    ):
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
        mock_db.return_value = 100

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        with patch.object(agent._client, "get", new_callable=AsyncMock) as mock_get:
            tickers_resp = MagicMock()
            tickers_resp.raise_for_status = MagicMock()
            tickers_resp.json.return_value = [
                {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "반도체", "base_price": 72000},
            ]
            ohlcv_resp = MagicMock()
            ohlcv_resp.raise_for_status = MagicMock()
            ohlcv_resp.json.return_value = [
                {"ticker": "005930", "name": "삼성전자", "market": "KOSPI",
                 "date": "2026-03-15", "open": 72000, "high": 73000, "low": 71000,
                 "close": 72500, "volume": 1000000, "change_pct": 0.69},
            ]
            mock_get.side_effect = [tickers_resp, ohlcv_resp]
            await agent.collect_daily_bars(lookback_days=5)

        mock_db.assert_called_once()
        mock_s3.assert_called_once()
        mock_publish.assert_called_once()
        pub_data = json.loads(mock_publish.call_args[0][1])
        self.assertEqual(pub_data["type"], "data_ready")
        await agent.close()

    @patch("src.agents.gen_collector.upsert_market_data", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock)
    async def test_collect_ticks_pipeline(
        self, mock_redis, mock_hb_insert, mock_hb_set, mock_publish, mock_db
    ):
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
            quotes_resp.raise_for_status = MagicMock()
            quotes_resp.json.return_value = [
                {"ticker": "005930", "name": "삼성전자", "market": "KOSPI",
                 "current_price": 72500, "open": 72000, "high": 73000, "low": 71500,
                 "volume": 500000, "change_pct": 0.5, "updated_at": "2026-03-16T10:00:00+09:00"},
            ]
            mock_get.return_value = quotes_resp
            count = await agent.collect_realtime_ticks(interval_sec=0.01, max_cycles=1)

        self.assertEqual(count, 1)
        mock_db.assert_called_once()
        mock_publish.assert_called_once()
        await agent.close()


class TestGenServerEndpoints(unittest.TestCase):
    """Gen 서버 엔드포인트 검증."""

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
        self.assertTrue(resp.json()["running"])

    def test_get_tickers(self):
        resp = self.client.get("/gen/tickers")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 20)

    def test_get_ohlcv(self):
        resp = self.client.get("/gen/ohlcv/005930?days=30")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.json()), 10)

    def test_get_quote(self):
        resp = self.client.get("/gen/quote/005930")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(resp.json()["current_price"], 0)

    def test_get_quote_404(self):
        resp = self.client.get("/gen/quote/999999")
        self.assertEqual(resp.status_code, 404)

    def test_get_all_quotes(self):
        resp = self.client.get("/gen/quotes")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 20)

    def test_get_index(self):
        resp = self.client.get("/gen/index")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_get_macro(self):
        resp = self.client.get("/gen/macro")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.json()), 0)


class TestDataIntegrity(unittest.TestCase):
    """기존 MarketDataPoint 모델과의 호환성 검증."""

    def setUp(self):
        self.gen = MarketDataGenerator(seed=42)
        self.gen.generate_tick()

    def test_ohlcv_to_market_data_point(self):
        from src.db.models import MarketDataPoint
        bars = self.gen.generate_daily_history("005930", days=10)
        for bar in bars:
            ts = datetime.fromisoformat(bar.date + "T15:30:00").replace(tzinfo=KST)
            point = MarketDataPoint(
                ticker=bar.ticker, name=bar.name, market=bar.market,
                timestamp_kst=ts, interval="daily",
                open=bar.open, high=bar.high, low=bar.low,
                close=bar.close, volume=bar.volume, change_pct=bar.change_pct,
            )
            self.assertEqual(point.interval, "daily")

    def test_quote_to_market_data_point(self):
        from src.db.models import MarketDataPoint
        quote = self.gen.get_quote("005930")
        point = MarketDataPoint(
            ticker=quote.ticker, name=quote.name, market=quote.market,
            timestamp_kst=datetime.now(KST), interval="tick",
            open=quote.open, high=quote.high, low=quote.low,
            close=quote.current_price, volume=quote.volume, change_pct=quote.change_pct,
        )
        self.assertEqual(point.interval, "tick")


if __name__ == "__main__":
    unittest.main()
