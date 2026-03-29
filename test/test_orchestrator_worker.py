import unittest
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from scripts.run_orchestrator_worker import _is_weekend_kst, _run_cycle_if_weekday

KST = ZoneInfo("Asia/Seoul")


class OrchestratorWorkerWeekendGuardTest(unittest.IsolatedAsyncioTestCase):
    def test_is_weekend_kst_true_on_sunday(self) -> None:
        now = datetime(2026, 3, 22, 14, 0, tzinfo=KST)

        self.assertTrue(_is_weekend_kst(now))

    def test_is_weekend_kst_false_on_monday(self) -> None:
        now = datetime(2026, 3, 23, 9, 0, tzinfo=KST)

        self.assertFalse(_is_weekend_kst(now))

    async def test_run_cycle_if_weekday_skips_on_weekend(self) -> None:
        agent = AsyncMock()
        now = datetime(2026, 3, 22, 14, 0, tzinfo=KST)

        result = await _run_cycle_if_weekday(agent, ["005930"], now_kst=now)

        self.assertIsNone(result)
        agent.run_cycle.assert_not_awaited()

    async def test_run_cycle_if_weekday_runs_on_weekday(self) -> None:
        agent = AsyncMock()
        agent.run_cycle.return_value = {"orders": 0}
        now = datetime(2026, 3, 23, 9, 0, tzinfo=KST)

        result = await _run_cycle_if_weekday(agent, ["005930"], now_kst=now)

        self.assertEqual(result, {"orders": 0})
        agent.run_cycle.assert_awaited_once_with(tickers=["005930"])


if __name__ == "__main__":
    unittest.main()
