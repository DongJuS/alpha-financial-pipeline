"""
test/test_kis_approval_retry.py — KIS approval_key 무효화 감지 + 자동 재발급 + Telegram 알림

invalid approval 응답 시:
  1. Redis 캐시 삭제
  2. 새 approval_key로 1회 재연결
  3. Telegram 알림 발송
  4. 재발급 후에도 실패 시 재시도 중단 + 실패 알림
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

KST = ZoneInfo("Asia/Seoul")
pytestmark = [pytest.mark.unit]


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KIS_APP_KEY", "fake-key")
    monkeypatch.setenv("KIS_APP_SECRET", "fake-secret")


@pytest.fixture()
def collector(_env):
    from src.agents.collector import CollectorAgent
    return CollectorAgent(agent_id="test_approval")


# =============================================================================
# _is_invalid_approval
# =============================================================================


class TestIsInvalidApproval:
    """invalid approval 메시지 판별 테스트."""

    def test_detects_invalid_approval(self, collector):
        raw = json.dumps({
            "header": {"tr_id": "H0STCNT0", "tr_key": "005930"},
            "body": {"rt_cd": "1", "msg_cd": "OPSP0011",
                     "msg1": "invalid approval : b3947a71-9766-4bf2-adca-1a312ab5c14e"},
        })
        assert collector._is_invalid_approval(raw) is True

    def test_ignores_normal_control_message(self, collector):
        raw = json.dumps({
            "header": {"tr_id": "H0STCNT0"},
            "body": {"rt_cd": "0", "msg_cd": "OPSP0000", "msg1": "SUBSCRIBE SUCCESS"},
        })
        assert collector._is_invalid_approval(raw) is False

    def test_ignores_non_json(self, collector):
        raw = "0|H0STCNT0|1|005930^0^72000"
        assert collector._is_invalid_approval(raw) is False

    def test_ignores_empty_string(self, collector):
        assert collector._is_invalid_approval("") is False

    def test_case_insensitive(self, collector):
        raw = json.dumps({
            "header": {},
            "body": {"msg1": "Invalid Approval : some-key"},
        })
        assert collector._is_invalid_approval(raw) is True


# =============================================================================
# _invalidate_ws_approval_key
# =============================================================================


class TestInvalidateApprovalKey:
    """Redis 캐시 삭제 테스트."""

    async def test_deletes_redis_cache(self, collector):
        mock_redis = AsyncMock()
        with patch(
            "src.agents.collector._base.get_redis",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ):
            await collector._invalidate_ws_approval_key()

        mock_redis.delete.assert_called_once()
        call_arg = mock_redis.delete.call_args[0][0]
        assert "approval_key" in call_arg


# =============================================================================
# _notify_kis_approval_invalid
# =============================================================================


class TestNotifyKisApprovalInvalid:
    """Telegram 알림 발송 테스트."""

    async def test_sends_telegram_on_invalid(self, collector):
        mock_send = AsyncMock(return_value=True)
        with patch(
            "src.agents.notifier.NotifierAgent.send_kis_approval_alert",
            mock_send,
        ):
            await collector._notify_kis_approval_invalid("old-key-12345678")

        mock_send.assert_called_once_with(
            old_key="old-key-12345678",
            retry_exhausted=False,
        )

    async def test_sends_retry_exhausted_alert(self, collector):
        mock_send = AsyncMock(return_value=True)
        with patch(
            "src.agents.notifier.NotifierAgent.send_kis_approval_alert",
            mock_send,
        ):
            await collector._notify_kis_approval_invalid(
                "old-key-12345678", retry_exhausted=True,
            )

        mock_send.assert_called_once_with(
            old_key="old-key-12345678",
            retry_exhausted=True,
        )

    async def test_swallows_notification_error(self, collector):
        """알림 발송 실패 시 예외를 삼킨다 (수집 중단 방지)."""
        with patch(
            "src.agents.notifier.NotifierAgent.send_kis_approval_alert",
            side_effect=RuntimeError("Telegram down"),
        ):
            # 예외 없이 통과해야 함
            await collector._notify_kis_approval_invalid("key")


# =============================================================================
# NotifierAgent.send_kis_approval_alert
# =============================================================================


class TestSendKisApprovalAlert:
    """NotifierAgent.send_kis_approval_alert 메서드 테스트."""

    async def test_first_attempt_message(self):
        from src.agents.notifier import NotifierAgent

        notifier = NotifierAgent()
        with patch.object(notifier, "send", new_callable=AsyncMock, return_value=True) as mock:
            result = await notifier.send_kis_approval_alert(
                old_key="b3947a71-9766-4bf2-adca-1a312ab5c14e",
            )

        assert result is True
        call_kwargs = mock.call_args
        msg = call_kwargs.kwargs.get("message") or call_kwargs[1].get("message")
        assert "b3947a71..." in msg
        assert "자동 재발급" in msg

    async def test_retry_exhausted_message(self):
        from src.agents.notifier import NotifierAgent

        notifier = NotifierAgent()
        with patch.object(notifier, "send", new_callable=AsyncMock, return_value=True) as mock:
            result = await notifier.send_kis_approval_alert(
                old_key="b3947a71-9766-4bf2-adca-1a312ab5c14e",
                retry_exhausted=True,
            )

        assert result is True
        call_kwargs = mock.call_args
        msg = call_kwargs.kwargs.get("message") or call_kwargs[1].get("message")
        assert "수동 확인" in msg
