from datetime import date
import unittest
from unittest.mock import AsyncMock, patch

from src.agents.notifier import NotifierAgent


class NotifierDailyReportTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_paper_daily_report_formats_summary(self) -> None:
        agent = NotifierAgent()
        sample_today = [
            {"ticker": "AAA", "side": "BUY", "quantity": 1, "price": 100, "amount": 100},
            {"ticker": "AAA", "side": "SELL", "quantity": 1, "price": 110, "amount": 110},
        ]
        sample_30d = sample_today * 2

        with (
            patch(
                "src.agents.notifier.fetch_trade_rows_for_date",
                new=AsyncMock(return_value=sample_today),
            ),
            patch(
                "src.agents.notifier.fetch_trade_rows",
                new=AsyncMock(return_value=sample_30d),
            ),
            patch.object(agent, "send", new=AsyncMock(return_value=True)) as send_mock,
        ):
            ok = await agent.send_paper_daily_report(report_date=date(2026, 3, 12))

        self.assertTrue(ok)
        send_mock.assert_awaited_once()
        _, kwargs = send_mock.await_args
        self.assertEqual(kwargs["event_type"], "paper_daily_report")
        self.assertIn("Alpha 페이퍼 일일 리포트 (2026-03-12)", kwargs["message"])
        self.assertIn("오늘 거래:", kwargs["message"])
        self.assertIn("30일 수익률:", kwargs["message"])

    async def test_send_paper_daily_report_includes_reconciliation_summary(self) -> None:
        agent = NotifierAgent()

        with (
            patch("src.agents.notifier.fetch_trade_rows_for_date", new=AsyncMock(return_value=[])),
            patch("src.agents.notifier.fetch_trade_rows", new=AsyncMock(return_value=[])),
            patch.object(agent, "send", new=AsyncMock(return_value=True)) as send_mock,
        ):
            ok = await agent.send_paper_daily_report(
                report_date=date(2026, 3, 13),
                reconciliation={
                    "summary": "KIS paper reconciliation 완료",
                    "new_trades": 2,
                },
            )

        self.assertTrue(ok)
        _, kwargs = send_mock.await_args
        self.assertIn("동기화 결과: KIS paper reconciliation 완료", kwargs["message"])
        self.assertIn("신규 KIS 체결 반영: 2건", kwargs["message"])


if __name__ == "__main__":
    unittest.main()
