"""
scripts/run_tick_collector.py — Docker/운영용 실시간 틱 수집 서비스

Orchestrator worker 와 분리된 독립 프로세스로 KIS WebSocket 틱 수집만 담당합니다.
100-종목 규모에서 worker 장애가 틱 수집에 영향을 주지 않도록 fault isolation 목적.

환경변수:
  TICK_TICKERS=005930,000660 (기본: 비어있음 = DB instruments 테이블 사용)
  TICK_DURATION_SECONDS=3600 (기본: 없음 = 무한 수집)
  TICK_RECONNECT_MAX=10 (기본: 10, WebSocket 재연결 한도)
  TICK_MARKET_HOURS_ONLY=true (기본: true, 장 시간(09:00-15:30 KST)에만 수집)
  TICK_SLEEP_OUTSIDE_HOURS=60 (기본: 60, 장외 시간 대기 주기 초)
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.utils.config import get_settings
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import set_heartbeat

setup_logging()
logger = get_logger(__name__)

_KST = ZoneInfo("Asia/Seoul")
_KEEPALIVE_INTERVAL = 30  # 초 — TTL_HEARTBEAT(90s)보다 충분히 짧게
_TICK_AGENT_ID = "collector_agent"

# ── Environment Helpers ──────────────────────────────────────────────────────


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_tickers(raw: str) -> list[str] | None:
    tickers = [t.strip() for t in raw.split(",") if t.strip()]
    return tickers or None


def _optional_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s 파싱 실패(%s), 기본값(%s) 사용.", name, raw, default)
        return default


# ── Heartbeat Keepalive ──────────────────────────────────────────────────────


async def _heartbeat_keepalive(stop_event: asyncio.Event) -> None:
    """백그라운드에서 주기적으로 tick collector heartbeat를 갱신합니다."""
    while not stop_event.is_set():
        try:
            await set_heartbeat(_TICK_AGENT_ID)
        except Exception as e:
            logger.warning("Heartbeat keepalive 실패 (계속 진행): %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_KEEPALIVE_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass


# ── Market Hours Check ───────────────────────────────────────────────────────

_MARKET_OPEN = time(9, 0)
_MARKET_CLOSE = time(15, 30)


def _is_market_hours(now: datetime | None = None) -> bool:
    """KST 기준 장 시간(09:00-15:30, 평일)인지 확인합니다.

    KRX 공휴일 캘린더가 있으면 활용하되, 없어도 실패하지 않습니다.
    """
    current = now or datetime.now(_KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_KST)
    else:
        current = current.astimezone(_KST)

    # 주말 체크
    if current.weekday() > 4:
        return False

    # KRX 공휴일 캘린더 시도 (없으면 무시)
    try:
        import exchange_calendars as xcals
        krx = xcals.get_calendar("XKRX")
        if not krx.is_session(current.strftime("%Y-%m-%d")):
            return False
    except Exception:
        pass  # 라이브러리 미설치 또는 오류 — 평일이면 장 시간으로 간주

    return _MARKET_OPEN <= current.time() <= _MARKET_CLOSE


# ── Ticker Resolution ────────────────────────────────────────────────────────


async def _fetch_tickers_from_db() -> list[str]:
    """instruments 테이블에서 활성 종목의 instrument_id 목록을 조회합니다."""
    try:
        from src.db.queries import list_tickers

        rows = await list_tickers(mode="paper")
        ids = [row["instrument_id"] for row in rows]
        if ids:
            logger.info("DB에서 종목 %d개 로드: %s", len(ids), ids[:5])
        return ids
    except Exception as e:
        logger.warning("DB 종목 조회 실패 (빈 목록 반환): %s", e)
        return []


# ── Main ─────────────────────────────────────────────────────────────────────


async def main_async() -> int:
    tickers = _parse_tickers(os.getenv("TICK_TICKERS", ""))
    duration_seconds = _optional_int("TICK_DURATION_SECONDS", default=None)
    reconnect_max = _optional_int("TICK_RECONNECT_MAX", default=10) or 10
    market_hours_only = _env_bool("TICK_MARKET_HOURS_ONLY", default=True)
    sleep_outside = _optional_int("TICK_SLEEP_OUTSIDE_HOURS", default=60) or 60

    # DB 로그 핸들러 활성화
    try:
        from src.utils.db_logger import setup_db_logging, start_log_flusher
        setup_db_logging(source="tick_collector")
        asyncio.create_task(start_log_flusher())
    except Exception as e:
        logger.warning("DB 로그 핸들러 초기화 실패 (비필수): %s", e)

    # CollectorAgent 생성
    from src.agents.collector import CollectorAgent
    collector = CollectorAgent(agent_id=_TICK_AGENT_ID)

    logger.info(
        "Tick collector 시작: tickers=%s, duration=%s, reconnect_max=%d, "
        "market_hours_only=%s, sleep_outside=%ds",
        tickers or "(DB 조회)",
        duration_seconds or "(무한)",
        reconnect_max,
        market_hours_only,
        sleep_outside,
    )

    # ── Graceful shutdown 핸들링 ─────────────────────────────────────
    stop_event = asyncio.Event()

    def _signal_handler(signum: int, _frame: object) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Tick collector 종료 신호 수신: %s", sig_name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _signal_handler)

    # ── Heartbeat keepalive 시작 ─────────────────────────────────────
    keepalive_task = asyncio.create_task(_heartbeat_keepalive(stop_event))
    logger.info("Heartbeat keepalive 시작: agent=%s, interval=%ds", _TICK_AGENT_ID, _KEEPALIVE_INTERVAL)

    # ── 메인 수집 루프 ──────────────────────────────────────────────
    try:
        while not stop_event.is_set():
            # 장 시간 체크
            if market_hours_only and not _is_market_hours():
                now_kst = datetime.now(_KST)
                logger.info(
                    "장외 시간 (%s KST, weekday=%d) — %ds 후 재확인",
                    now_kst.strftime("%H:%M:%S"),
                    now_kst.weekday(),
                    sleep_outside,
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=sleep_outside)
                    break  # stop_event 수신
                except asyncio.TimeoutError:
                    continue

            # 종목 결정
            resolved = tickers
            if not resolved:
                resolved = await _fetch_tickers_from_db()
            if not resolved:
                logger.error(
                    "실행할 종목이 없습니다 (TICK_TICKERS 미설정, DB 조회 결과 없음). "
                    "%ds 후 재시도.",
                    sleep_outside,
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=sleep_outside)
                    break
                except asyncio.TimeoutError:
                    continue

            logger.info("틱 수집 시작: %d종목, reconnect_max=%d", len(resolved), reconnect_max)

            try:
                received = await collector.collect_realtime_ticks(
                    tickers=resolved,
                    duration_seconds=duration_seconds,
                    reconnect_max=reconnect_max,
                )
                logger.info("틱 수집 세션 종료: %d건 수신", received)
            except Exception as e:
                logger.error("틱 수집 오류 (재시도 예정): %s", e, exc_info=True)

            # 수집 종료 후 잠시 대기 (즉시 재연결 방지)
            if not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5)
                    break
                except asyncio.TimeoutError:
                    pass

    finally:
        # 틱 버퍼 강제 flush
        logger.info("Tick collector 종료 중 — 버퍼 flush 시작")
        try:
            flushed = await collector._flush_tick_buffer(force=True)
            if flushed:
                logger.info("종료 전 틱 버퍼 flush: %d건", flushed)
        except Exception as e:
            logger.warning("종료 전 버퍼 flush 실패: %s", e)

        stop_event.set()
        await keepalive_task
        logger.info("Tick collector 종료 완료")

    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(main_async()))
    except KeyboardInterrupt:
        logger.info("Tick collector 종료 신호 수신 (KeyboardInterrupt)")
        sys.exit(0)


if __name__ == "__main__":
    main()
