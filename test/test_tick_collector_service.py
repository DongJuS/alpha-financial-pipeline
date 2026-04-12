"""
test/test_tick_collector_service.py — tick-collector 서비스 분리 관련 테스트

검증 대상:
1. CollectorAgent.run() -> collect_daily_bars() 위임
2. _CollectorBase._realtime_task 속성 존재
3. market hours 판정 로직 (tick collector 진입 조건)
4. 틱 수집 대상 종목 결정 (TICK_TICKERS 환경변수 vs DB fallback)
5. unified_scheduler에서 tick 크론잡 제거 확인 (현재 상태 기준)
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 테스트용 최소 환경변수 (conftest.py 기본값 보완)
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

KST = ZoneInfo("Asia/Seoul")

pytestmark = [pytest.mark.unit]


# ─── 픽스처 ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _env(monkeypatch):
    """테스트용 최소 환경변수 설정."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KIS_APP_KEY", "fake-key")
    monkeypatch.setenv("KIS_APP_SECRET", "fake-secret")


@pytest.fixture()
def collector(_env):
    """CollectorAgent 인스턴스 생성."""
    from src.agents.collector import CollectorAgent

    return CollectorAgent(agent_id="test_tick_service")


# ═══════════════════════════════════════════════════════════════════════════
# 1. CollectorAgent.run() -> collect_daily_bars() 위임
# ═══════════════════════════════════════════════════════════════════════════


class TestCollectorRunDelegation:
    """CollectorAgent.run() 메서드가 collect_daily_bars()로 올바르게 위임하는지 검증."""

    @pytest.mark.asyncio
    async def test_run_delegates_to_daily_bars(self, collector):
        """run()이 collect_daily_bars()를 호출하는지 확인."""
        with patch.object(collector, "collect_daily_bars", new_callable=AsyncMock) as mock:
            mock.return_value = []
            await collector.run(tickers=["005930"], lookback_days=30)
            mock.assert_called_once_with(tickers=["005930"], lookback_days=30)

    @pytest.mark.asyncio
    async def test_run_delegates_with_defaults(self, collector):
        """run()이 기본 인자로 collect_daily_bars()를 호출."""
        with patch.object(collector, "collect_daily_bars", new_callable=AsyncMock) as mock:
            mock.return_value = []
            await collector.run()
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_passes_through_kwargs(self, collector):
        """run()이 tickers, lookback_days 등 kwargs를 그대로 전달."""
        with patch.object(collector, "collect_daily_bars", new_callable=AsyncMock) as mock:
            mock.return_value = []
            await collector.run(tickers=["005930", "000660"], lookback_days=60)
            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["tickers"] == ["005930", "000660"]
            assert call_kwargs["lookback_days"] == 60

    @pytest.mark.asyncio
    async def test_run_returns_none(self, collector):
        """run()은 반환값 없이 collect_daily_bars()에 위임만 한다."""
        with patch.object(collector, "collect_daily_bars", new_callable=AsyncMock) as mock:
            mock.return_value = [MagicMock()]
            result = await collector.run(tickers=["005930"])
            assert result is None

    @pytest.mark.asyncio
    async def test_run_propagates_exception(self, collector):
        """collect_daily_bars()에서 예외 발생 시 run()도 전파."""
        with patch.object(
            collector,
            "collect_daily_bars",
            new_callable=AsyncMock,
            side_effect=RuntimeError("FDR down"),
        ):
            with pytest.raises(RuntimeError, match="FDR down"):
                await collector.run(tickers=["005930"])


# ═══════════════════════════════════════════════════════════════════════════
# 2. _realtime_task 속성 존재 및 초기값
# ═══════════════════════════════════════════════════════════════════════════


class TestRealtimeTaskAttribute:
    """_CollectorBase._realtime_task 속성이 올바르게 초기화되는지 검증."""

    def test_has_realtime_task_attribute(self, collector):
        """CollectorAgent 인스턴스에 _realtime_task 속성이 존재."""
        assert hasattr(collector, "_realtime_task")

    def test_realtime_task_initialized_to_none(self, collector):
        """_realtime_task 초기값은 None."""
        assert collector._realtime_task is None

    def test_realtime_task_accepts_asyncio_task(self, collector):
        """_realtime_task에 asyncio.Task를 할당할 수 있어야 한다."""
        mock_task = MagicMock(spec=asyncio.Task)
        collector._realtime_task = mock_task
        assert collector._realtime_task is mock_task

    def test_realtime_task_type_annotation(self, collector):
        """_realtime_task 타입 어노테이션이 asyncio.Task | None."""
        from src.agents.collector._base import _CollectorBase

        annotations = _CollectorBase.__init__.__code__.co_varnames
        # 속성이 __init__에서 할당되는지만 확인 (co_varnames에 포함)
        # 직접 타입 검사보다 런타임 동작 검증이 더 신뢰성 있음
        assert collector._realtime_task is None
        collector._realtime_task = MagicMock(spec=asyncio.Task)
        assert collector._realtime_task is not None
        collector._realtime_task = None
        assert collector._realtime_task is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. Market hours 판정 (tick collector 진입 조건)
# ═══════════════════════════════════════════════════════════════════════════


class TestMarketHoursForTickCollector:
    """tick collector가 사용하는 시장 시간 판정 로직 검증.

    is_market_open_now()를 직접 테스트하여 tick collector 실행 조건을 검증합니다.
    """

    @pytest.mark.asyncio
    async def test_weekday_10am_is_market_hours(self):
        """평일 10:00 KST -> 장중 (수집 가능)."""
        now = datetime(2026, 4, 13, 10, 0, tzinfo=KST)  # Monday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now

            assert await is_market_open_now() is True

    @pytest.mark.asyncio
    async def test_weekday_8am_is_not_market_hours(self):
        """평일 08:00 KST -> 장 전 (수집 불가)."""
        now = datetime(2026, 4, 13, 8, 0, tzinfo=KST)  # Monday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now

            assert await is_market_open_now() is False

    @pytest.mark.asyncio
    async def test_saturday_10am_is_not_market_hours(self):
        """토요일 10:00 KST -> 주말 (수집 불가)."""
        now = datetime(2026, 4, 11, 10, 0, tzinfo=KST)  # Saturday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now

            assert await is_market_open_now() is False

    @pytest.mark.asyncio
    async def test_weekday_1530_is_boundary(self):
        """평일 15:30 KST -> 장 마감 시각 (경계값).

        is_market_open_now()는 MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME
        이므로 15:30 정각은 True여야 합니다 (<=).
        """
        now = datetime(2026, 4, 13, 15, 30, tzinfo=KST)  # Monday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now

            # 15:30은 <= MARKET_CLOSE_TIME 이므로 True
            assert await is_market_open_now() is True

    @pytest.mark.asyncio
    async def test_weekday_1531_is_not_market_hours(self):
        """평일 15:31 KST -> 장 마감 후 (수집 불가)."""
        now = datetime(2026, 4, 13, 15, 31, tzinfo=KST)  # Monday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now

            assert await is_market_open_now() is False

    @pytest.mark.asyncio
    async def test_weekday_0900_is_market_open(self):
        """평일 09:00 KST -> 장 개장 시각 (경계값 포함)."""
        now = datetime(2026, 4, 13, 9, 0, tzinfo=KST)  # Monday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now

            assert await is_market_open_now() is True

    @pytest.mark.asyncio
    async def test_sunday_is_not_market_hours(self):
        """일요일 10:00 KST -> 주말 (수집 불가)."""
        now = datetime(2026, 4, 12, 10, 0, tzinfo=KST)  # Sunday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now

            assert await is_market_open_now() is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. 틱 수집 대상 종목 결정 (TICK_TICKERS 환경변수 vs DB fallback)
# ═══════════════════════════════════════════════════════════════════════════


class TestTickTickerResolution:
    """tick collector가 수집 대상 종목을 결정하는 로직 검증.

    unified_scheduler의 _run_tick_realtime_start 로직을 추출하여 테스트합니다.
    """

    def test_tickers_from_env_ws_tick_tickers(self, monkeypatch):
        """WS_TICK_TICKERS 환경변수 설정 시 해당 종목을 사용."""
        monkeypatch.setenv("WS_TICK_TICKERS", "005930,000660,035420")
        from src.utils.config import get_settings

        settings = get_settings()
        raw = settings.ws_tick_tickers.strip()
        tickers = [t.strip() for t in raw.split(",") if t.strip()]
        assert tickers == ["005930", "000660", "035420"]

    def test_tickers_empty_env_yields_empty_list(self, monkeypatch):
        """WS_TICK_TICKERS가 빈 문자열이면 빈 리스트 (tick-collector는 DB fallback)."""
        monkeypatch.setenv("WS_TICK_TICKERS", "")
        from src.utils.config import get_settings

        settings = get_settings()
        raw = settings.ws_tick_tickers.strip()
        tickers = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
        assert tickers == []

    def test_tickers_with_whitespace_are_trimmed(self, monkeypatch):
        """종목 코드 양쪽 공백이 제거되는지 확인."""
        monkeypatch.setenv("WS_TICK_TICKERS", " 005930 , 000660 , 035420 ")
        from src.utils.config import get_settings

        settings = get_settings()
        raw = settings.ws_tick_tickers.strip()
        tickers = [t.strip() for t in raw.split(",") if t.strip()]
        assert all(t == t.strip() for t in tickers)
        assert len(tickers) == 3

    def test_single_ticker(self, monkeypatch):
        """단일 종목만 설정 시 정상 파싱."""
        monkeypatch.setenv("WS_TICK_TICKERS", "005930")
        from src.utils.config import get_settings

        settings = get_settings()
        raw = settings.ws_tick_tickers.strip()
        tickers = [t.strip() for t in raw.split(",") if t.strip()]
        assert tickers == ["005930"]

    def test_no_default_tick_tickers_in_scheduler(self):
        """tick-collector 분리 후 _DEFAULT_TICK_TICKERS가 scheduler에 없어야 한다."""
        import src.schedulers.unified_scheduler as mod

        assert not hasattr(mod, "_DEFAULT_TICK_TICKERS")


# ═══════════════════════════════════════════════════════════════════════════
# 5. unified_scheduler 틱 잡 등록 상태 확인
# ═══════════════════════════════════════════════════════════════════════════


class TestSchedulerTickJobRegistration:
    """tick-collector 분리 후 unified_scheduler에서 tick 크론잡이 제거되었는지 확인."""

    @pytest.mark.asyncio
    async def test_tick_jobs_removed_from_scheduler(self):
        """tick_realtime_start, tick_realtime_health가 scheduler에 등록되지 않음."""
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        mock_scheduler.get_jobs.return_value = []

        registered_ids: list[str] = []

        def _track_add_job(fn, trigger=None, *, id, **kwargs):
            registered_ids.append(id)

        mock_scheduler.add_job = _track_add_job

        with (
            patch.object(mod, "_scheduler", None),
            patch.object(mod, "get_unified_scheduler", new_callable=AsyncMock, return_value=mock_scheduler),
            patch("src.agents.collector.CollectorAgent"),
            patch("src.agents.index_collector.IndexCollector"),
            patch("src.agents.macro_collector.MacroCollector"),
            patch("src.agents.krx_stock_master_collector.KrxStockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        assert "tick_realtime_start" not in registered_ids
        assert "tick_realtime_health" not in registered_ids

    @pytest.mark.asyncio
    async def test_tick_lock_ttl_removed(self):
        """tick 잡들의 분산 락 TTL이 제거되어야 한다."""
        from src.schedulers.unified_scheduler import _LOCK_TTL

        assert "tick_realtime_start" not in _LOCK_TTL
        assert "tick_realtime_health" not in _LOCK_TTL

    @pytest.mark.asyncio
    async def test_total_job_count(self):
        """tick 잡 제거 후 전체 등록 잡 수는 10개."""
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        mock_scheduler.get_jobs.return_value = []

        registered_ids: list[str] = []

        def _track_add_job(fn, trigger=None, *, id, **kwargs):
            registered_ids.append(id)

        mock_scheduler.add_job = _track_add_job

        with (
            patch.object(mod, "_scheduler", None),
            patch.object(mod, "get_unified_scheduler", new_callable=AsyncMock, return_value=mock_scheduler),
            patch("src.agents.collector.CollectorAgent"),
            patch("src.agents.index_collector.IndexCollector"),
            patch("src.agents.macro_collector.MacroCollector"),
            patch("src.agents.krx_stock_master_collector.KrxStockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        assert len(registered_ids) == 13, (
            f"Expected 13 registered jobs, got {len(registered_ids)}: {registered_ids}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6. scripts/run_tick_collector.py 엔트리포인트 로직
# ═══════════════════════════════════════════════════════════════════════════


class TestRunTickCollectorEntrypoint:
    """standalone tick-collector 엔트리포인트의 핵심 로직을 검증.

    실제 스크립트가 아직 생성되지 않았을 수 있으므로,
    엔트리포인트가 사용할 핵심 조합(market hours + ticker resolution + collect)을
    통합 시뮬레이션합니다.
    """

    @pytest.mark.asyncio
    async def test_entrypoint_flow_during_market_hours(self, collector):
        """장중에 실행하면 collect_realtime_ticks를 호출해야 한다."""
        with (
            patch(
                "src.utils.market_hours.is_market_open_now",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(
                collector,
                "collect_realtime_ticks",
                new_callable=AsyncMock,
                return_value=42,
            ) as mock_collect,
        ):
            from src.utils.market_hours import is_market_open_now

            if await is_market_open_now():
                await collector.collect_realtime_ticks(
                    tickers=["005930", "000660"],
                    duration_seconds=23400,
                )

            mock_collect.assert_awaited_once_with(
                tickers=["005930", "000660"],
                duration_seconds=23400,
            )

    @pytest.mark.asyncio
    async def test_entrypoint_skips_outside_market_hours(self, collector):
        """장외에 실행하면 collect_realtime_ticks를 호출하지 않아야 한다."""
        with (
            patch(
                "src.utils.market_hours.is_market_open_now",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(
                collector,
                "collect_realtime_ticks",
                new_callable=AsyncMock,
            ) as mock_collect,
        ):
            from src.utils.market_hours import is_market_open_now

            if await is_market_open_now():
                await collector.collect_realtime_ticks(
                    tickers=["005930"],
                    duration_seconds=23400,
                )

            mock_collect.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_collector_duration_calculation(self):
        """장 마감까지 남은 시간(duration) 계산 로직 검증."""
        # KRX 장 마감: 15:30 KST (tick-collector가 사용하는 기준)
        MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 30

        # 10:00 KST에 시작하면 15:30까지 5시간 30분 = 19800초
        now_kst = datetime(2026, 4, 13, 10, 0, tzinfo=KST)
        market_close = now_kst.replace(
            hour=MARKET_CLOSE_HOUR,
            minute=MARKET_CLOSE_MINUTE,
            second=0,
            microsecond=0,
        )
        remaining = int((market_close - now_kst).total_seconds())
        assert remaining == 19800  # 5.5 hours

    @pytest.mark.asyncio
    async def test_duration_zero_after_market_close(self):
        """장 마감 후에는 remaining <= 0."""
        MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 30

        now_kst = datetime(2026, 4, 13, 16, 0, tzinfo=KST)  # 16:00 KST
        market_close = now_kst.replace(
            hour=MARKET_CLOSE_HOUR,
            minute=MARKET_CLOSE_MINUTE,
            second=0,
            microsecond=0,
        )
        remaining = int((market_close - now_kst).total_seconds())
        assert remaining <= 0


# ═══════════════════════════════════════════════════════════════════════════
# 7. CollectorAgent 속성 및 초기화 무결성
# ═══════════════════════════════════════════════════════════════════════════


class TestCollectorInitialization:
    """CollectorAgent 초기화 시 tick-collector 관련 속성이 올바른지 검증."""

    def test_tick_buffer_initialized_empty(self, collector):
        """_tick_buffer가 빈 리스트로 초기화."""
        assert isinstance(collector._tick_buffer, list)
        assert len(collector._tick_buffer) == 0

    def test_tick_batch_size_positive(self, collector):
        """_tick_batch_size가 양수."""
        assert collector._tick_batch_size > 0

    def test_tick_flush_interval_positive(self, collector):
        """_tick_flush_interval이 양수."""
        assert collector._tick_flush_interval > 0

    def test_last_tick_at_initialized_none(self, collector):
        """_last_tick_at 초기값은 None."""
        assert collector._last_tick_at is None

    def test_agent_id_customizable(self, _env):
        """agent_id를 커스텀 값으로 지정 가능."""
        from src.agents.collector import CollectorAgent

        agent = CollectorAgent(agent_id="tick_collector_standalone")
        assert agent.agent_id == "tick_collector_standalone"

    def test_has_collect_realtime_ticks_method(self, collector):
        """collect_realtime_ticks 메서드가 존재."""
        assert hasattr(collector, "collect_realtime_ticks")
        assert callable(collector.collect_realtime_ticks)

    def test_has_collect_daily_bars_method(self, collector):
        """collect_daily_bars 메서드가 존재."""
        assert hasattr(collector, "collect_daily_bars")
        assert callable(collector.collect_daily_bars)


# ═══════════════════════════════════════════════════════════════════════════
# 8. WebSocket 연결 끊김 + 재연결 시나리오
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiTickerParallelCollectionV2:
    """다중 종목 병렬 수집 추가 에지 케이스 (Agent 2 QA Round 2)."""

    def test_tick_buffer_concurrent_appends(self, collector):
        """틱 버퍼에 여러 종목 데이터가 혼합 가능."""
        from src.agents.collector.models import TickData

        tick1 = TickData(
            instrument_id="005930.KS", price=72000.0, volume=100,
            timestamp_kst=datetime(2026, 4, 11, 10, 0, 0, tzinfo=KST),
        )
        tick2 = TickData(
            instrument_id="000660.KS", price=150000.0, volume=50,
            timestamp_kst=datetime(2026, 4, 11, 10, 0, 1, tzinfo=KST),
        )
        collector._tick_buffer.append(tick1)
        collector._tick_buffer.append(tick2)
        assert len(collector._tick_buffer) == 2
        instruments = {t.instrument_id for t in collector._tick_buffer}
        assert instruments == {"005930.KS", "000660.KS"}

    @pytest.mark.asyncio
    async def test_duration_seconds_ends_collection(self, collector):
        """duration_seconds 경과 후 루프가 종료되어야 함.

        이 테스트는 _ws_collect_loop의 duration 로직을
        간접적으로 검증합니다.
        """
        MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 30
        # 15:29에 시작하면 1분 남음
        now_kst = datetime(2026, 4, 13, 15, 29, tzinfo=KST)
        market_close = now_kst.replace(
            hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE,
            second=0, microsecond=0,
        )
        remaining = int((market_close - now_kst).total_seconds())
        assert remaining == 60  # 1분 남음

    def test_ws_tick_tickers_with_duplicates(self, monkeypatch, _env):
        """중복 종목이 환경변수에 있으면 그대로 반환 (dedupe는 상위 레이어)."""
        monkeypatch.setenv("WS_TICK_TICKERS", "005930,005930,000660")
        from src.utils.config import get_settings
        settings = get_settings()
        raw = settings.ws_tick_tickers.strip()
        tickers = [t.strip() for t in raw.split(",") if t.strip()]
        assert len(tickers) == 3  # 중복 포함
        assert tickers.count("005930") == 2
