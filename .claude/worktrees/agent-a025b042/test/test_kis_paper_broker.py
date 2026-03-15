import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.brokers import build_paper_broker, build_real_broker
from src.brokers.kis import KISOrderReceipt, KISPaperApiClient, KISPaperBroker, KISRealApiClient, KISRealBroker
from src.brokers.paper import PaperBroker
from src.db.models import PaperOrderRequest


class KISPaperClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_place_order_uses_paper_tr_id_and_market_payload(self) -> None:
        settings = types.SimpleNamespace(
            kis_app_key="app-key",
            kis_app_secret="app-secret",
            kis_account_number="50012345-01",
            kis_request_timeout_seconds=15,
            kis_base_url_for_scope=lambda scope: "https://paper.example",
        )
        client = KISPaperApiClient(settings=settings, token_provider=AsyncMock(return_value="token"))
        order = PaperOrderRequest(
            ticker="005930",
            name="삼성전자",
            signal="BUY",
            quantity=2,
            price=70000,
            signal_source="A",
            agent_id="portfolio_manager_agent",
            account_scope="paper",
        )

        with patch.object(
            client,
            "_request_json",
            new=AsyncMock(return_value={"output": {"ODNO": "12345678"}}),
        ) as request_mock:
            receipt = await client.place_order(order)

        self.assertEqual(receipt.order_no, "12345678")
        request_mock.assert_awaited_once()
        args, kwargs = request_mock.await_args
        self.assertEqual(args[2], "VTTC0802U")
        self.assertEqual(kwargs["json_body"]["CANO"], "50012345")
        self.assertEqual(kwargs["json_body"]["ACNT_PRDT_CD"], "01")
        self.assertEqual(kwargs["json_body"]["ORD_DVSN"], "01")
        self.assertEqual(kwargs["json_body"]["ORD_QTY"], "2")

    async def test_inquire_balance_uses_paper_balance_tr_id(self) -> None:
        settings = types.SimpleNamespace(
            kis_app_key="app-key",
            kis_app_secret="app-secret",
            kis_account_number="50012345-01",
            kis_request_timeout_seconds=15,
            kis_base_url_for_scope=lambda scope: "https://paper.example",
        )
        client = KISPaperApiClient(settings=settings, token_provider=AsyncMock(return_value="token"))

        with patch.object(
            client,
            "_request_json",
            new=AsyncMock(return_value={"output1": [], "output2": [{"dnca_tot_amt": "10000000"}]}),
        ) as request_mock:
            payload = await client.inquire_balance()

        self.assertEqual(payload["summary"]["dnca_tot_amt"], "10000000")
        args, kwargs = request_mock.await_args
        self.assertEqual(args[2], "VTTC8434R")
        self.assertEqual(kwargs["params"]["CANO"], "50012345")

    async def test_real_client_uses_real_tr_ids(self) -> None:
        settings = types.SimpleNamespace(
            kis_app_key="paper-app-key",
            kis_app_secret="paper-app-secret",
            kis_real_app_key="real-app-key",
            kis_real_app_secret="real-app-secret",
            kis_account_number="50012345-01",
            kis_request_timeout_seconds=15,
            kis_base_url_for_scope=lambda scope: "https://real.example" if scope == "real" else "https://paper.example",
        )
        client = KISRealApiClient(settings=settings, token_provider=AsyncMock(return_value="token"))
        order = PaperOrderRequest(
            ticker="005930",
            name="삼성전자",
            signal="SELL",
            quantity=1,
            price=70000,
            signal_source="A",
            agent_id="portfolio_manager_agent",
            account_scope="real",
        )

        with patch.object(
            client,
            "_request_json",
            new=AsyncMock(return_value={"output": {"ODNO": "99001122"}}),
        ) as request_mock:
            receipt = await client.place_order(order)

        self.assertEqual(receipt.order_no, "99001122")
        args, _ = request_mock.await_args
        self.assertEqual(args[2], "TTTC0801U")


class KISPaperBrokerTest(unittest.IsolatedAsyncioTestCase):
    async def test_kis_mode_records_pending_order_when_submission_succeeds(self) -> None:
        settings = types.SimpleNamespace(
            kis_app_key="app-key",
            kis_app_secret="app-secret",
            kis_account_number="50012345-01",
            paper_broker_backend="kis",
        )
        fake_client = Mock()
        fake_client.is_configured.return_value = True
        fake_client.place_order = AsyncMock(return_value=KISOrderReceipt(order_no="88001122", raw={}))
        broker = KISPaperBroker(settings=settings, execution_mode="kis", client=fake_client)
        order = PaperOrderRequest(
            ticker="005930",
            name="삼성전자",
            signal="BUY",
            quantity=1,
            price=70000,
            signal_source="A",
            agent_id="portfolio_manager_agent",
            account_scope="paper",
        )

        with (
            patch.object(broker, "_ensure_account", new=AsyncMock()),
            patch("src.brokers.kis.get_trading_account", new=AsyncMock(return_value={"cash_balance": 1_000_000, "total_equity": 1_000_000})),
            patch("src.brokers.kis.insert_broker_order", new=AsyncMock()) as insert_order_mock,
            patch("src.brokers.kis.update_broker_order_status", new=AsyncMock()) as update_order_mock,
        ):
            result = await broker.execute_order(order)

        self.assertEqual(result.status, "PENDING")
        insert_order_mock.assert_awaited_once()
        update_order_mock.assert_awaited_once()
        self.assertEqual(update_order_mock.await_args.kwargs["broker_order_id"], "88001122")

    async def test_kis_shadow_mode_executes_internal_broker_and_attaches_reference(self) -> None:
        settings = types.SimpleNamespace(
            kis_app_key="app-key",
            kis_app_secret="app-secret",
            kis_account_number="50012345-01",
            paper_broker_backend="kis_shadow",
        )
        fallback_broker = AsyncMock()
        fallback_broker.execute_order.return_value = types.SimpleNamespace(
            client_order_id="paper-local-1",
            account_scope="paper",
            status="FILLED",
            ticker="005930",
            side="BUY",
            quantity=1,
            price=70000,
            cash_balance=930000,
            total_equity=1000000,
            rejection_reason=None,
        )
        fake_client = Mock()
        fake_client.place_order = AsyncMock(return_value=KISOrderReceipt(order_no="77001122", raw={}))
        broker = KISPaperBroker(
            settings=settings,
            execution_mode="kis_shadow",
            client=fake_client,
            fallback_broker=fallback_broker,
        )
        order = PaperOrderRequest(
            ticker="005930",
            name="삼성전자",
            signal="BUY",
            quantity=1,
            price=70000,
            signal_source="A",
            agent_id="portfolio_manager_agent",
            account_scope="paper",
        )

        with patch("src.brokers.kis.attach_broker_order_reference", new=AsyncMock()) as attach_mock:
            result = await broker.execute_order(order)

        self.assertEqual(result.status, "FILLED")
        fallback_broker.execute_order.assert_awaited_once()
        attach_mock.assert_awaited_once_with(
            "paper-local-1",
            broker_name="internal-paper+kis-shadow",
            broker_order_id="77001122",
        )


class PaperBrokerFactoryTest(unittest.TestCase):
    def test_build_paper_broker_defaults_to_internal(self) -> None:
        settings = types.SimpleNamespace(paper_broker_backend="internal")
        broker = build_paper_broker(settings)
        self.assertIsInstance(broker, PaperBroker)

    def test_build_paper_broker_supports_kis_mode(self) -> None:
        settings = types.SimpleNamespace(
            paper_broker_backend="kis",
            kis_app_key="app-key",
            kis_app_secret="app-secret",
            kis_account_number="50012345-01",
            kis_request_timeout_seconds=15,
            kis_base_url_for_scope=lambda scope: "https://paper.example",
        )
        broker = build_paper_broker(settings)
        self.assertIsInstance(broker, KISPaperBroker)

    def test_build_real_broker_defaults_to_kis_live(self) -> None:
        settings = types.SimpleNamespace(
            real_broker_backend="kis",
            kis_app_key="app-key",
            kis_app_secret="app-secret",
            kis_real_app_key="real-app-key",
            kis_real_app_secret="real-app-secret",
            kis_account_number="50012345-01",
            kis_request_timeout_seconds=15,
            kis_base_url_for_scope=lambda scope: "https://real.example" if scope == "real" else "https://paper.example",
        )
        broker = build_real_broker(settings)
        self.assertIsInstance(broker, KISRealBroker)


if __name__ == "__main__":
    unittest.main()
