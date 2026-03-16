import types
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from src.services.paper_reconciliation import reconcile_kis_paper_account


class PaperReconciliationServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_kis_paper_account_syncs_positions_orders_and_trades(self) -> None:
        fake_client = types.SimpleNamespace(
            is_configured=lambda: True,
            inquire_balance=AsyncMock(
                return_value={
                    "positions": [
                        {
                            "pdno": "005930",
                            "prdt_name": "삼성전자",
                            "hldg_qty": "3",
                            "pchs_avg_pric": "70000",
                            "prpr": "71000",
                        }
                    ],
                    "summary": {
                        "dnca_tot_amt": "9700000",
                        "scts_evlu_amt": "213000",
                        "tot_evlu_amt": "9913000",
                        "evlu_pfls_smtl_amt": "13000",
                    },
                }
            ),
            inquire_daily_ccld=AsyncMock(
                return_value={
                    "orders": [
                        {
                            "odno": "88001122",
                            "ord_qty": "3",
                            "tot_ccld_qty": "3",
                            "ord_unpr": "70000",
                            "avg_prvs": "71000",
                            "ord_dt": "20260313",
                            "ord_tmd": "091501",
                            "sll_buy_dvsn_cd": "02",
                            "sll_buy_dvsn_cd_name": "매수",
                            "pdno": "005930",
                            "prdt_name": "삼성전자",
                            "rmn_qty": "0",
                            "rjct_qty": "0",
                            "cncl_yn": "N",
                        }
                    ],
                    "summary": {},
                }
            ),
        )
        fake_settings = types.SimpleNamespace(paper_broker_backend="kis")

        with (
            patch("src.services.paper_reconciliation.get_settings", return_value=fake_settings),
            patch("src.services.paper_reconciliation.get_trading_account", new=AsyncMock(return_value={"seed_capital": 10_000_000})),
            patch("src.services.paper_reconciliation.list_positions", new=AsyncMock(return_value=[{"ticker": "000660", "name": "SK하이닉스", "current_price": 200000}])),
            patch("src.services.paper_reconciliation.save_position", new=AsyncMock()) as save_position_mock,
            patch("src.services.paper_reconciliation.upsert_trading_account", new=AsyncMock()) as upsert_account_mock,
            patch("src.services.paper_reconciliation.record_account_snapshot", new=AsyncMock()) as snapshot_mock,
            patch("src.services.paper_reconciliation.upsert_kis_broker_order", new=AsyncMock()) as upsert_order_mock,
            patch("src.services.paper_reconciliation.upsert_trade_fill", new=AsyncMock(return_value=True)) as upsert_trade_mock,
            patch("src.services.paper_reconciliation.insert_operational_audit", new=AsyncMock()) as audit_mock,
        ):
            result = await reconcile_kis_paper_account(
                report_date=date(2026, 3, 13),
                client=fake_client,
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["orders_synced"], 1)
        self.assertEqual(result["new_trades"], 1)
        self.assertEqual(save_position_mock.await_count, 2)
        upsert_account_mock.assert_awaited_once()
        snapshot_mock.assert_awaited_once()
        upsert_order_mock.assert_awaited_once()
        upsert_trade_mock.assert_awaited_once()
        audit_mock.assert_awaited_once()

    async def test_reconcile_kis_paper_account_falls_back_when_kis_not_configured(self) -> None:
        fake_client = types.SimpleNamespace(is_configured=lambda: False)
        fake_settings = types.SimpleNamespace(paper_broker_backend="internal")

        with patch("src.services.paper_reconciliation.get_settings", return_value=fake_settings), patch(
            "src.services.paper_reconciliation.insert_operational_audit",
            new=AsyncMock(),
        ) as audit_mock:
            result = await reconcile_kis_paper_account(
                report_date=date(2026, 3, 13),
                client=fake_client,
            )

        self.assertTrue(result["passed"])
        self.assertTrue(result["fallback_used"])
        self.assertIn("internal read model", result["summary"])
        audit_mock.assert_awaited_once()

    async def test_reconcile_kis_paper_account_skips_kis_client_for_internal_backend(self) -> None:
        fake_settings = types.SimpleNamespace(paper_broker_backend="internal")

        with (
            patch("src.services.paper_reconciliation.get_settings", return_value=fake_settings),
            patch("src.services.paper_reconciliation.KISPaperApiClient") as client_cls,
            patch("src.services.paper_reconciliation.insert_operational_audit", new=AsyncMock()) as audit_mock,
        ):
            result = await reconcile_kis_paper_account(report_date=date(2026, 3, 13))

        self.assertTrue(result["passed"])
        self.assertTrue(result["fallback_used"])
        self.assertIn("PAPER_BROKER_BACKEND=internal", result["summary"])
        client_cls.assert_not_called()
        audit_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
