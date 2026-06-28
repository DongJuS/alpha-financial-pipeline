"""
test/test_run_tick_collector_market_close.py — 장 마감 요약 함수 unit test

검증 대상 (scripts/run_tick_collector.py 의 신규 함수 3종):
1. _fmt_size — 바이트 → 사람이 읽기 좋은 단위
2. _send_market_close_summary — 평일 15:35 이후 첫 진입 시 1회 트리거,
                                  하루 1회 멱등성, 토/일 비활성, stop_event 종료
3. _build_and_send_close_summary — DB/디스크 조회 후 Telegram 메시지 구성
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("KIS_IS_PAPER_TRADING", "true")

from scripts.run_tick_collector import (  # noqa: E402
    _build_and_send_close_summary,
    _fmt_size,
    _send_market_close_summary,
)

KST = ZoneInfo("Asia/Seoul")
pytestmark = [pytest.mark.unit]


# ───────────────────────────────────────────────────────────────────────────
# _fmt_size — 단위 변환 경계값
# ───────────────────────────────────────────────────────────────────────────


class TestFmtSize:
    def test_zero_and_small_bytes(self):
        assert _fmt_size(0) == "0 B"
        assert _fmt_size(1) == "1 B"
        assert _fmt_size(1023) == "1023 B"

    def test_kb_boundary(self):
        # 정확히 1KB 부터 KB 표시
        assert _fmt_size(1024) == "1.0 KB"
        assert _fmt_size(1024 + 512) == "1.5 KB"

    def test_mb_boundary(self):
        assert _fmt_size(1 << 20) == "1.0 MB"
        assert _fmt_size((1 << 20) + (1 << 19)) == "1.5 MB"

    def test_gb_boundary(self):
        # GB 는 소수 2자리 표시
        assert _fmt_size(1 << 30) == "1.00 GB"
        assert _fmt_size((1 << 30) * 2 + (1 << 29)) == "2.50 GB"

    def test_ordering_smaller_unit_wins_just_below_threshold(self):
        # 1KB - 1B = 여전히 B 단위
        assert _fmt_size((1 << 10) - 1) == "1023 B"
        # 1MB - 1B = 여전히 KB 단위
        assert _fmt_size((1 << 20) - 1).endswith(" KB")
        # 1GB - 1B = 여전히 MB 단위
        assert _fmt_size((1 << 30) - 1).endswith(" MB")


# ───────────────────────────────────────────────────────────────────────────
# _send_market_close_summary — 트리거 조건
# ───────────────────────────────────────────────────────────────────────────


class TestSendMarketCloseSummary:
    @pytest.mark.asyncio
    async def test_triggers_once_on_weekday_after_close(self):
        """평일 15:35 이후 첫 진입 시 _build_and_send_close_summary 1회 호출."""
        stop = asyncio.Event()
        build_calls: list[tuple[str, str]] = []

        async def fake_build(today_str: str, today_ymd: str):
            build_calls.append((today_str, today_ymd))
            stop.set()

        # 2026-06-29 (월요일) 15:36 KST
        fake_now = datetime(2026, 6, 29, 15, 36, tzinfo=KST)

        with patch(
            "scripts.run_tick_collector._build_and_send_close_summary",
            new=fake_build,
        ), patch("scripts.run_tick_collector.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            await asyncio.wait_for(_send_market_close_summary(stop), timeout=2.0)

        assert build_calls == [("2026-06-29", "20260629")]

    @pytest.mark.asyncio
    async def test_idempotent_within_same_day(self):
        """같은 날 두 번째 iteration 에서 sent_today 가 막아 중복 호출 안 됨.
        루프는 stop_event 가 set 될 때까지 1분 간격으로 폴링하므로,
        본 테스트는 첫 호출이 build 1회 → sent_today 갱신을 시뮬레이션."""
        stop = asyncio.Event()
        build_count = 0

        async def fake_build(today_str: str, today_ymd: str):
            nonlocal build_count
            build_count += 1

        fake_now = datetime(2026, 6, 29, 15, 40, tzinfo=KST)

        async def fake_wait_for(awaitable, timeout):
            # 첫 wait_for 직후 stop_event 가 set 된 것처럼 → break
            stop.set()
            # 원본 awaitable 코루틴 정리
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            # stop_event.wait() 가 깨어났다고 시뮬레이션 → 정상 종료
            return None

        with patch(
            "scripts.run_tick_collector._build_and_send_close_summary",
            new=fake_build,
        ), patch("scripts.run_tick_collector.datetime") as mock_dt, patch(
            "scripts.run_tick_collector.asyncio.wait_for", new=fake_wait_for
        ):
            mock_dt.now.return_value = fake_now
            await _send_market_close_summary(stop)

        assert build_count == 1

    @pytest.mark.asyncio
    async def test_weekend_does_not_trigger(self):
        """토(weekday=5) / 일(weekday=6) 에는 build 호출 X."""
        stop = asyncio.Event()
        build_calls: list = []

        async def fake_build(today_str: str, today_ymd: str):
            build_calls.append(1)

        async def fake_wait_for(awaitable, timeout):
            stop.set()
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            return None

        # 2026-06-27 = 토요일
        fake_now = datetime(2026, 6, 27, 15, 36, tzinfo=KST)

        with patch(
            "scripts.run_tick_collector._build_and_send_close_summary",
            new=fake_build,
        ), patch("scripts.run_tick_collector.datetime") as mock_dt, patch(
            "scripts.run_tick_collector.asyncio.wait_for", new=fake_wait_for
        ):
            mock_dt.now.return_value = fake_now
            await _send_market_close_summary(stop)

        assert build_calls == []

    @pytest.mark.asyncio
    async def test_before_3_35_pm_does_not_trigger(self):
        """평일이지만 minute<35 일 때는 build 호출 X."""
        stop = asyncio.Event()
        build_calls: list = []

        async def fake_build(today_str: str, today_ymd: str):
            build_calls.append(1)

        async def fake_wait_for(awaitable, timeout):
            stop.set()
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            return None

        # 2026-06-29 (월) 15:34 — 1분 전
        fake_now = datetime(2026, 6, 29, 15, 34, tzinfo=KST)

        with patch(
            "scripts.run_tick_collector._build_and_send_close_summary",
            new=fake_build,
        ), patch("scripts.run_tick_collector.datetime") as mock_dt, patch(
            "scripts.run_tick_collector.asyncio.wait_for", new=fake_wait_for
        ):
            mock_dt.now.return_value = fake_now
            await _send_market_close_summary(stop)

        assert build_calls == []

    @pytest.mark.asyncio
    async def test_build_failure_is_swallowed(self):
        """build 함수가 예외 던져도 루프는 죽지 않음 — 다음 iteration 진행."""
        stop = asyncio.Event()

        async def failing_build(today_str: str, today_ymd: str):
            raise RuntimeError("DB 다운")

        async def fake_wait_for(awaitable, timeout):
            stop.set()
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            return None

        fake_now = datetime(2026, 6, 29, 15, 36, tzinfo=KST)

        with patch(
            "scripts.run_tick_collector._build_and_send_close_summary",
            new=failing_build,
        ), patch("scripts.run_tick_collector.datetime") as mock_dt, patch(
            "scripts.run_tick_collector.asyncio.wait_for", new=fake_wait_for
        ):
            mock_dt.now.return_value = fake_now
            # 예외 전파되지 않아야 함
            await _send_market_close_summary(stop)


# ───────────────────────────────────────────────────────────────────────────
# _build_and_send_close_summary — 메시지 구성
# ───────────────────────────────────────────────────────────────────────────


class TestBuildAndSendCloseSummary:
    @pytest.mark.asyncio
    async def test_message_contains_counts_and_sizes_real_mode(self):
        """DB 결과 + 디스크 사용량 + real 모드 가 메시지에 정확히 들어감."""
        row_today = {"cnt": 12345, "bytes": 50 * (1 << 20)}  # 50 MB
        row_cum = {"bytes": 250 * (1 << 20)}  # 250 MB

        fetchrow_mock = AsyncMock(side_effect=[row_today, row_cum])
        telegram_mock = AsyncMock()

        disk_stat = MagicMock()
        disk_stat.total = 200 * (1 << 30)  # 200 GB
        disk_stat.free = 180 * (1 << 30)

        settings_mock = MagicMock()
        settings_mock.kis_is_paper_trading = False  # → "real"

        with patch("src.utils.db_client.fetchrow", new=fetchrow_mock), patch(
            "shutil.disk_usage", return_value=disk_stat
        ), patch(
            "scripts.run_tick_collector.get_settings", return_value=settings_mock
        ), patch(
            "scripts.run_tick_collector._send_telegram", new=telegram_mock
        ):
            await _build_and_send_close_summary("2026-06-29", "20260629")

        telegram_mock.assert_called_once()
        msg = telegram_mock.call_args.args[0]
        assert "2026-06-29 장 마감 리포트" in msg
        assert "12,345건" in msg
        assert "50.0 MB" in msg  # 당일 파티션 크기
        assert "250.0 MB" in msg  # 누적
        assert "200.00 GB" in msg  # 디스크 총량
        assert "real" in msg

    @pytest.mark.asyncio
    async def test_message_paper_mode(self):
        """KIS_IS_PAPER_TRADING=True → 모드 'paper' 표시."""
        row_today = {"cnt": 0, "bytes": 0}
        row_cum = {"bytes": 0}

        settings_mock = MagicMock()
        settings_mock.kis_is_paper_trading = True
        telegram_mock = AsyncMock()

        with patch(
            "src.utils.db_client.fetchrow",
            new=AsyncMock(side_effect=[row_today, row_cum]),
        ), patch(
            "shutil.disk_usage",
            return_value=MagicMock(total=1 << 30, free=1 << 30),
        ), patch(
            "scripts.run_tick_collector.get_settings", return_value=settings_mock
        ), patch(
            "scripts.run_tick_collector._send_telegram", new=telegram_mock
        ):
            await _build_and_send_close_summary("2026-06-29", "20260629")

        msg = telegram_mock.call_args.args[0]
        assert "paper" in msg
        assert "0건" in msg

    @pytest.mark.asyncio
    async def test_handles_missing_row(self):
        """fetchrow 가 None 을 반환해도 0 건 / 0 바이트로 처리."""
        telegram_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.kis_is_paper_trading = True

        with patch(
            "src.utils.db_client.fetchrow",
            new=AsyncMock(side_effect=[None, None]),
        ), patch(
            "shutil.disk_usage",
            return_value=MagicMock(total=1 << 30, free=1 << 30),
        ), patch(
            "scripts.run_tick_collector.get_settings", return_value=settings_mock
        ), patch(
            "scripts.run_tick_collector._send_telegram", new=telegram_mock
        ):
            await _build_and_send_close_summary("2026-06-29", "20260629")

        msg = telegram_mock.call_args.args[0]
        assert "0건" in msg
        # _fmt_size(0) = "0 B"
        assert "0 B" in msg
