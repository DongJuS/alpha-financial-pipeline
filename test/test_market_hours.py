import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.utils.market_hours import is_market_open_now, market_session_status

KST = ZoneInfo("Asia/Seoul")


class MarketHoursTest(unittest.IsolatedAsyncioTestCase):
    async def test_open_during_regular_market_hours(self) -> None:
        now = datetime(2026, 3, 13, 10, 15, tzinfo=KST)  # Friday

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "open")
            self.assertTrue(await is_market_open_now())

    async def test_returns_pre_market_before_session(self) -> None:
        now = datetime(2026, 3, 13, 8, 45, tzinfo=KST)  # Friday 08:45

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "pre_market")

    async def test_returns_closed_after_close(self) -> None:
        now = datetime(2026, 3, 13, 15, 31, tzinfo=KST)  # Friday 15:31

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "closed")

    async def test_returns_closed_on_weekend(self) -> None:
        now = datetime(2026, 3, 14, 10, 0, tzinfo=KST)  # Saturday

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "closed")

    async def test_is_market_open_returns_false_on_weekend(self) -> None:
        now = datetime(2026, 3, 14, 10, 0, tzinfo=KST)  # Saturday

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(await is_market_open_now())

    async def test_is_market_open_returns_false_before_open(self) -> None:
        now = datetime(2026, 3, 13, 8, 0, tzinfo=KST)  # Friday 08:00

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(await is_market_open_now())


if __name__ == "__main__":
    unittest.main()
