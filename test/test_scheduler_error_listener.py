"""APScheduler JOB_ERROR 리스너 훅 테스트."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.schedulers.unified_scheduler import (
    _extract_job_error_payload,
    _make_job_error_listener,
)


def _make_event(
    *,
    job_id: str | None = "collector_daily",
    exception: Exception | None = None,
    traceback: str | None = None,
) -> SimpleNamespace:
    """JobExecutionEvent 최소 스텁."""
    return SimpleNamespace(
        job_id=job_id,
        exception=exception,
        traceback=traceback,
    )


def _make_scheduler_with_job(job_id: str, name: str) -> MagicMock:
    sched = MagicMock()
    job = MagicMock()
    job.name = name
    sched.get_job.return_value = job
    return sched


class TestExtractJobErrorPayload(unittest.TestCase):
    def test_happy_path_extracts_name_and_exception(self) -> None:
        sched = _make_scheduler_with_job("collector_daily", "CollectorAgent daily")
        event = _make_event(
            job_id="collector_daily",
            exception=ConnectionError("KIS timeout"),
        )
        payload = _extract_job_error_payload(event, sched)
        self.assertEqual(payload["job_id"], "collector_daily")
        self.assertEqual(payload["job_name"], "CollectorAgent daily")
        self.assertIn("ConnectionError", payload["exception"])
        self.assertIn("KIS timeout", payload["exception"])
        self.assertEqual(payload["traceback_excerpt"], "")

    def test_missing_job_falls_back_to_job_id(self) -> None:
        sched = MagicMock()
        sched.get_job.return_value = None
        event = _make_event(
            job_id="orphan_job",
            exception=ValueError("oops"),
        )
        payload = _extract_job_error_payload(event, sched)
        self.assertEqual(payload["job_id"], "orphan_job")
        self.assertEqual(payload["job_name"], "orphan_job")

    def test_null_job_id_becomes_unknown(self) -> None:
        sched = MagicMock()
        event = _make_event(
            job_id=None,
            exception=RuntimeError("boom"),
        )
        payload = _extract_job_error_payload(event, sched)
        self.assertEqual(payload["job_id"], "unknown")
        self.assertEqual(payload["job_name"], "unknown")

    def test_null_exception_reports_unknown_error(self) -> None:
        sched = _make_scheduler_with_job("x", "x")
        event = _make_event(job_id="x", exception=None)
        payload = _extract_job_error_payload(event, sched)
        self.assertEqual(payload["exception"], "unknown error")

    def test_traceback_is_truncated_to_last_10_lines(self) -> None:
        sched = _make_scheduler_with_job("x", "x")
        tb = "\n".join(f"line-{i}" for i in range(20))
        event = _make_event(job_id="x", exception=ValueError("x"), traceback=tb)
        payload = _extract_job_error_payload(event, sched)
        lines = payload["traceback_excerpt"].split("\n")
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[0], "line-10")
        self.assertEqual(lines[-1], "line-19")


class TestMakeJobErrorListener(unittest.IsolatedAsyncioTestCase):
    """_make_job_error_listener가 NotifierAgent에 올바른 payload를 전달하는지 검증."""

    async def test_listener_triggers_send_with_payload(self) -> None:
        sched = _make_scheduler_with_job("collector_daily", "CollectorAgent daily")
        listener = _make_job_error_listener(sched)

        captured: dict = {}

        class FakeNotifier:
            async def send_scheduler_error_alert(self, **kwargs):
                captured.update(kwargs)
                return True

        with patch(
            "src.agents.notifier.NotifierAgent",
            return_value=FakeNotifier(),
        ):
            event = _make_event(
                job_id="collector_daily",
                exception=ConnectionError("KIS timeout"),
            )
            listener(event)
            # create_task로 스케줄된 알림 코루틴이 돌 시간 부여
            await asyncio.sleep(0.05)

        self.assertEqual(captured.get("job_id"), "collector_daily")
        self.assertEqual(captured.get("job_name"), "CollectorAgent daily")
        self.assertIn("ConnectionError", captured.get("exception", ""))

    async def test_listener_swallows_notifier_exceptions(self) -> None:
        """NotifierAgent가 터져도 리스너가 예외를 밖으로 던지면 안 된다."""
        sched = _make_scheduler_with_job("x", "x")
        listener = _make_job_error_listener(sched)

        class BrokenNotifier:
            async def send_scheduler_error_alert(self, **kwargs):
                raise RuntimeError("telegram down")

        with patch(
            "src.agents.notifier.NotifierAgent",
            return_value=BrokenNotifier(),
        ):
            event = _make_event(job_id="x", exception=ValueError("boom"))
            # 예외가 밖으로 새지 않아야 한다
            listener(event)
            await asyncio.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
