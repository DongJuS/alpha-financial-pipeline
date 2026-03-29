import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.utils.market_hours import is_market_open_now, market_session_status

KST = ZoneInfo("Asia/Seoul")


class MarketHoursTest(unittest.IsolatedAsyncioTestCase):
    async def test_open_during_regular_market_hours(self) -> None:
        now = datetime(2026, 3, 13, 10, 15, tzinfo=KST)

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "open")
            self.assertTrue(await is_market_open_now())

    async def test_returns_pre_market_before_session(self) -> None:
        now = datetime(2026, 3, 13, 8, 45, tzinfo=KST)

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "pre_market")

    async def test_returns_closed_after_close(self) -> None:
        now = datetime(2026, 3, 13, 15, 31, tzinfo=KST)

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "closed")

    async def test_returns_closed_on_weekend(self) -> None:
        # 2026-03-14 is a Saturday
        now = datetime(2026, 3, 14, 10, 0, tzinfo=KST)

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "closed")

    async def test_closed_on_weekend_not_market_open(self) -> None:
        # 2026-03-14 is a Saturday
        now = datetime(2026, 3, 14, 10, 0, tzinfo=KST)

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(await is_market_open_now())

    async def test_returns_closed_early_morning(self) -> None:
        now = datetime(2026, 3, 13, 7, 0, tzinfo=KST)

        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertEqual(await market_session_status(), "closed")
            self.assertFalse(await is_market_open_now())


if __name__ == "__main__":
    unittest.main()
