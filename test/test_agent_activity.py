from datetime import datetime, timedelta, timezone
import unittest

from src.utils.agent_activity import classify_agent_activity


class AgentActivityClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 12, 15, 0, tzinfo=timezone.utc)

    def test_offline_when_dead(self) -> None:
        state, label = classify_agent_activity(
            status="dead",
            is_alive=False,
            last_action="예측 완료",
            updated_at="2026-03-12T14:59:00Z",
            now_utc=self.now,
        )
        self.assertEqual(state, "offline")
        self.assertEqual(label, "중지")

    def test_idle_when_not_alive_but_has_recent_history(self) -> None:
        state, label = classify_agent_activity(
            status="healthy",
            is_alive=False,
            last_action="예측 완료",
            updated_at=(self.now - timedelta(minutes=6)).isoformat().replace("+00:00", "Z"),
            now_utc=self.now,
        )
        self.assertEqual(state, "idle")
        self.assertEqual(label, "대기 중")

    def test_investing_when_recent_trade_action(self) -> None:
        state, label = classify_agent_activity(
            status="healthy",
            is_alive=True,
            last_action="주문 처리 완료 (3건)",
            updated_at=(self.now - timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
            now_utc=self.now,
        )
        self.assertEqual(state, "investing")
        self.assertEqual(label, "투자 실행 중")

    def test_analyzing_when_recent_prediction_action(self) -> None:
        state, label = classify_agent_activity(
            status="healthy",
            is_alive=True,
            last_action="예측 완료 (20종목)",
            updated_at=(self.now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
            now_utc=self.now,
        )
        self.assertEqual(state, "analyzing")
        self.assertEqual(label, "신호 분석 중")

    def test_idle_when_stale_heartbeat(self) -> None:
        state, label = classify_agent_activity(
            status="healthy",
            is_alive=True,
            last_action="사이클 완료",
            updated_at=(self.now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            now_utc=self.now,
        )
        self.assertEqual(state, "idle")
        self.assertEqual(label, "대기 중")

    def test_degraded_when_stale_and_degraded(self) -> None:
        state, label = classify_agent_activity(
            status="degraded",
            is_alive=True,
            last_action="알림 처리 실패",
            updated_at=(self.now - timedelta(minutes=8)).isoformat().replace("+00:00", "Z"),
            now_utc=self.now,
        )
        self.assertEqual(state, "degraded")
        self.assertEqual(label, "점검 필요")


if __name__ == "__main__":
    unittest.main()
