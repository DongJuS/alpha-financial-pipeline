import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from src.utils.market_hours import is_market_open_now, market_session_status

KST = ZoneInfo("Asia/Seoul")


class MarketHoursTest(unittest.IsolatedAsyncioTestCase):
    async def test_open_during_regular_market_hours(self) -> None:
        now = datetime(2026, 3, 13, 10, 15, tzinfo=KST)

        with patch("src.utils.market_hours.ensure_holidays_cached", new=AsyncMock(return_value=[])):
            self.assertEqual(await market_session_status(now), "open")
            self.assertTrue(await is_market_open_now(now))

    async def test_returns_pre_open_before_session(self) -> None:
        now = datetime(2026, 3, 13, 8, 59, tzinfo=KST)

        with patch("src.utils.market_hours.ensure_holidays_cached", new=AsyncMock(return_value=[])):
            self.assertEqual(await market_session_status(now), "pre_open")

    async def test_returns_after_hours_after_close(self) -> None:
        now = datetime(2026, 3, 13, 15, 31, tzinfo=KST)

        with patch("src.utils.market_hours.ensure_holidays_cached", new=AsyncMock(return_value=[])):
            self.assertEqual(await market_session_status(now), "after_hours")

    async def test_returns_weekend_without_holiday_lookup(self) -> None:
        now = datetime(2026, 3, 14, 10, 0, tzinfo=KST)

        with patch("src.utils.market_hours.ensure_holidays_cached", new=AsyncMock()) as holidays_mock:
            self.assertEqual(await market_session_status(now), "weekend")

        holidays_mock.assert_not_awaited()

    async def test_returns_holiday_on_cached_krx_holiday(self) -> None:
        now = datetime(2026, 3, 13, 10, 0, tzinfo=KST)

        with patch(
            "src.utils.market_hours.ensure_holidays_cached",
            new=AsyncMock(return_value=["2026-03-13"]),
        ):
            self.assertEqual(await market_session_status(now), "holiday")
            self.assertFalse(await is_market_open_now(now))

    async def test_returns_closed_when_holiday_lookup_fails(self) -> None:
        now = datetime(2026, 3, 13, 10, 0, tzinfo=KST)

        with patch(
            "src.utils.market_hours.ensure_holidays_cached",
            new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ):
            self.assertEqual(await market_session_status(now), "closed")
            self.assertFalse(await is_market_open_now(now))


if __name__ == "__main__":
    unittest.main()
