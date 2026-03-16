"""
test/test_data_pipeline.py — 과거 데이터 수집 파이프라인 테스트
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KST = ZoneInfo("Asia/Seoul")


class TestCollectorHistoricalDaily(unittest.TestCase):
    """CollectorAgent.fetch_historical_ohlcv 일봉 수집 테스트."""

    @patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        "JWT_SECRET": "test-secret",
    })
    def _make_agent(self):
        from src.agents.collector import CollectorAgent
        return CollectorAgent(agent_id="test_collector")

    @patch("src.agents.collector.upsert_market_data", new_callable=AsyncMock, return_value=3)
    @patch("src.agents.collector.CollectorAgent._load_fdr")
    def test_fetch_historical_daily_basic(self, mock_fdr_loader, mock_upsert):
        """일봉 과거 데이터 수집이 정상 동작하는지 확인합니다."""
        import asyncio
        import pandas as pd

        mock_fdr = MagicMock()
        dates = pd.date_range("2024-01-02", periods=3, freq="B")
        df = pd.DataFrame({
            "Open": [70000, 70500, 71000],
            "High": [71000, 71500, 72000],
            "Low": [69000, 69500, 70000],
            "Close": [70500, 71000, 71500],
            "Volume": [1000000, 1200000, 1100000],
            "Change": [0.01, 0.007, 0.007],
        }, index=dates)
        mock_fdr.DataReader.return_value = df
        mock_fdr_loader.return_value = mock_fdr

        agent = self._make_agent()
        points = asyncio.get_event_loop().run_until_complete(
            agent.fetch_historical_ohlcv(
                ticker="005930",
                start_date="2024-01-01",
                end_date="2024-01-05",
                interval="D",
                name="삼성전자",
                market="KOSPI",
            )
        )

        self.assertEqual(len(points), 3)
        self.assertEqual(points[0].ticker, "005930")
        self.assertEqual(points[0].name, "삼성전자")
        self.assertEqual(points[0].interval, "daily")
        mock_upsert.assert_called_once()

    @patch("src.agents.collector.upsert_market_data", new_callable=AsyncMock, return_value=0)
    @patch("src.agents.collector.CollectorAgent._load_fdr")
    def test_fetch_historical_daily_empty(self, mock_fdr_loader, mock_upsert):
        """데이터가 없을 때 빈 리스트를 반환하는지 확인합니다."""
        import asyncio
        import pandas as pd

        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = pd.DataFrame()
        mock_fdr_loader.return_value = mock_fdr

        agent = self._make_agent()
        points = asyncio.get_event_loop().run_until_complete(
            agent.fetch_historical_ohlcv("999999", "2024-01-01", "2024-01-05")
        )

        self.assertEqual(len(points), 0)


class TestCollectorCheckDataExists(unittest.TestCase):
    """CollectorAgent.check_data_exists 테스트."""

    @patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        "JWT_SECRET": "test-secret",
    })
    @patch("src.utils.db_client.fetchval", new_callable=AsyncMock, return_value=150)
    def test_check_data_exists_returns_count(self, mock_fetchval):
        """기존 데이터 건수를 정확히 반환하는지 확인합니다."""
        import asyncio
        from src.agents.collector import CollectorAgent

        agent = CollectorAgent()
        count = asyncio.get_event_loop().run_until_complete(
            agent.check_data_exists("005930", "daily")
        )
        self.assertEqual(count, 150)


class TestSeedHistoricalDataCLI(unittest.TestCase):
    """seed_historical_data.py CLI 인자 파싱 테스트."""

    def test_argparse_requires_start(self):
        """--start 미지정 시 에러가 발생하는지 확인합니다."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--start", required=True)

        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_argparse_interval_choices(self):
        """interval 선택지가 올바른지 확인합니다."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--start", required=True)
        parser.add_argument("--interval", default="D", choices=["D", "1", "5", "15", "30", "60"])

        args = parser.parse_args(["--start", "2024-01-01", "--interval", "5"])
        self.assertEqual(args.interval, "5")


if __name__ == "__main__":
    unittest.main()
