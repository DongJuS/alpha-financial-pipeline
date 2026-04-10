"""Orchestrator heartbeat 모니터링 + Telegram 알림 테스트."""

import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from src.agents.notifier import NotifierAgent
from src.agents.orchestrator import OrchestratorAgent
from src.db.models import PredictionSignal


class CheckAgentHealthTest(unittest.IsolatedAsyncioTestCase):
    """OrchestratorAgent._check_agent_health() 단위 테스트."""

    async def test_all_ok_returns_empty(self) -> None:
        """모든 에이전트가 ok → 빈 리스트."""
        orch = OrchestratorAgent()
        with patch(
            "src.agents.orchestrator.get_heartbeat_detail",
            new=AsyncMock(return_value={"status": "ok", "updated_at": "1712700000"}),
        ):
            issues = await orch._check_agent_health()
        self.assertEqual(issues, [])

    async def test_error_agent_detected(self) -> None:
        """collector가 error → issues에 포함."""
        orch = OrchestratorAgent()

        async def mock_detail(agent_id: str):
            if agent_id == "collector_agent":
                return {"status": "error", "mode": "websocket", "error_count": "3"}
            return {"status": "ok", "updated_at": "1712700000"}

        with patch(
            "src.agents.orchestrator.get_heartbeat_detail",
            new=AsyncMock(side_effect=mock_detail),
        ):
            issues = await orch._check_agent_health()

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["agent_id"], "collector_agent")
        self.assertEqual(issues[0]["status"], "error")
        self.assertEqual(issues[0]["mode"], "websocket")
        self.assertEqual(issues[0]["error_count"], 3)

    async def test_offline_agent_detected(self) -> None:
        """heartbeat 없음(offline) → issues에 포함."""
        orch = OrchestratorAgent()

        async def mock_detail(agent_id: str):
            if agent_id == "notifier_agent":
                return None
            return {"status": "ok", "updated_at": "1712700000"}

        with patch(
            "src.agents.orchestrator.get_heartbeat_detail",
            new=AsyncMock(side_effect=mock_detail),
        ):
            issues = await orch._check_agent_health()

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["agent_id"], "notifier_agent")
        self.assertEqual(issues[0]["status"], "offline")

    async def test_degraded_agent_detected(self) -> None:
        """degraded 상태 에이전트 감지."""
        orch = OrchestratorAgent()

        async def mock_detail(agent_id: str):
            if agent_id == "collector_agent":
                return {"status": "degraded", "mode": "fdr", "error_count": "1"}
            return {"status": "ok", "updated_at": "1712700000"}

        with patch(
            "src.agents.orchestrator.get_heartbeat_detail",
            new=AsyncMock(side_effect=mock_detail),
        ):
            issues = await orch._check_agent_health()

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["status"], "degraded")
        self.assertEqual(issues[0]["mode"], "fdr")


class SendAgentHealthAlertTest(unittest.IsolatedAsyncioTestCase):
    """NotifierAgent.send_agent_health_alert() 단위 테스트."""

    async def test_message_format(self) -> None:
        """메시지 포맷 검증 (emoji, 필드)."""
        agent = NotifierAgent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as send_mock:
            ok = await agent.send_agent_health_alert(
                agent_id="collector_agent",
                status="error",
                mode="websocket",
                error_count=3,
            )

        self.assertTrue(ok)
        send_mock.assert_awaited_once()
        args, _ = send_mock.await_args
        self.assertEqual(args[0], "agent_health_alert")
        msg = args[1]
        self.assertIn("🔴", msg)
        self.assertIn("collector_agent", msg)
        self.assertIn("error", msg)
        self.assertIn("websocket", msg)
        self.assertIn("에러 횟수: 3", msg)

    async def test_offline_emoji(self) -> None:
        """offline 상태의 emoji 확인."""
        agent = NotifierAgent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as send_mock:
            await agent.send_agent_health_alert(
                agent_id="notifier_agent",
                status="offline",
            )

        args, _ = send_mock.await_args
        msg = args[1]
        self.assertIn("⚫", msg)
        self.assertIn("offline", msg)
        # mode/error_count 미지정 시 해당 라인 없어야 함
        self.assertNotIn("모드:", msg)
        self.assertNotIn("에러 횟수:", msg)

    async def test_degraded_emoji(self) -> None:
        """degraded 상태의 emoji 확인."""
        agent = NotifierAgent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as send_mock:
            await agent.send_agent_health_alert(
                agent_id="collector_agent",
                status="degraded",
                mode="fdr",
            )

        args, _ = send_mock.await_args
        msg = args[1]
        self.assertIn("⚠️", msg)
        self.assertIn("degraded", msg)
        self.assertIn("fdr", msg)


class RunCycleHealthCheckIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """run_cycle에서 health check가 호출되는지 검증."""

    @patch("src.agents.orchestrator.insert_heartbeat", new=AsyncMock())
    @patch("src.agents.orchestrator.set_heartbeat", new=AsyncMock())
    @patch("src.agents.orchestrator.insert_operational_audit", new=AsyncMock())
    async def test_health_check_called_on_cycle_success(self) -> None:
        """사이클 성공 후 _check_agent_health가 호출된다."""
        orch = OrchestratorAgent()

        # run_strategies → 예측 1건 반환
        pred = PredictionSignal(
            agent_id="test",
            llm_model="test",
            strategy="A",
            ticker="005930",
            signal="HOLD",
            confidence=0.5,
            reasoning_summary="test",
            trading_date=date(2026, 4, 10),
        )
        orch.run_strategies = AsyncMock(return_value={"A": [pred]})

        with (
            patch.object(orch, "_execute_blended_signals", new=AsyncMock(return_value=[])),
            patch.object(orch, "_check_agent_health", new=AsyncMock(return_value=[])) as health_mock,
            patch("src.utils.market_hours.is_market_open_now", new=AsyncMock(return_value=True)),
            patch("src.agents.orchestrator.store_blend_results", new=AsyncMock()),
            patch("src.agents.orchestrator.store_orders", new=AsyncMock()),
            patch.object(orch, "_record_daily_rankings", new=AsyncMock()),
            patch.object(orch, "_record_paper_trading_run", new=AsyncMock()),
        ):
            result = await orch.run_cycle(["005930"])

        health_mock.assert_awaited_once()
        self.assertGreater(result["predicted"], 0)


if __name__ == "__main__":
    unittest.main()
