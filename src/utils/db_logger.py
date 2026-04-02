"""
src/utils/db_logger.py — DB 로그 저장 (event_logs + error_logs)

event_logs: 비즈니스 이벤트 — log_event()로 명시적 호출
error_logs: WARNING 이상 — Python logging handler가 자동 캡처

버퍼링: 50건 또는 10초마다 배치 INSERT (DB 부하 최소화)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback as tb_module
from datetime import datetime, timezone
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)

# ── 설정 ─────────────────────────────────────────────────────────────────

BUFFER_SIZE = 50       # 이 수만큼 모이면 flush
FLUSH_INTERVAL = 10.0  # 초마다 flush
POD_NAME = os.environ.get("HOSTNAME", os.environ.get("POD_NAME", "unknown"))
SOURCE = os.environ.get("APP_SOURCE", "worker")  # worker, api, gen, gen-collector


# ── 버퍼 ─────────────────────────────────────────────────────────────────

_event_buffer: list[tuple] = []
_error_buffer: list[tuple] = []
_lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None
_last_flush = time.monotonic()


async def _flush() -> None:
    """버퍼를 DB에 배치 INSERT합니다."""
    global _last_flush
    from src.utils.db_client import executemany

    events = _event_buffer.copy()
    errors = _error_buffer.copy()
    _event_buffer.clear()
    _error_buffer.clear()
    _last_flush = time.monotonic()

    if events:
        try:
            await executemany(
                "INSERT INTO event_logs (ts, source, event_type, data, pod_name) "
                "VALUES ($1, $2, $3, $4, $5)",
                events,
            )
        except Exception as e:
            logger.debug("event_logs flush 실패: %s", e)

    if errors:
        try:
            await executemany(
                "INSERT INTO error_logs (ts, source, level, logger, message, traceback, pod_name) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                errors,
            )
        except Exception as e:
            logger.debug("error_logs flush 실패: %s", e)


async def _maybe_flush() -> None:
    """버퍼가 가득 차거나 시간이 지나면 flush합니다."""
    total = len(_event_buffer) + len(_error_buffer)
    elapsed = time.monotonic() - _last_flush
    if total >= BUFFER_SIZE or (total > 0 and elapsed >= FLUSH_INTERVAL):
        await _flush()


# ── 공개 API: 이벤트 로깅 ────────────────────────────────────────────────


async def log_event(
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    source: str | None = None,
) -> None:
    """비즈니스 이벤트를 event_logs에 기록합니다.

    사용 예:
        await log_event("cycle_complete", {"collected": 100, "orders": 3})
        await log_event("rl_retrain", {"ticker": "005930", "return": 9.7})
        await log_event("blend_fallback", {"excluded": ["B"]})
    """
    import json
    _event_buffer.append((
        datetime.now(timezone.utc),
        source or SOURCE,
        event_type,
        json.dumps(data, ensure_ascii=False, default=str) if data else None,
        POD_NAME,
    ))
    await _maybe_flush()


# ── Python Logging Handler ───────────────────────────────────────────────


class DBLogHandler(logging.Handler):
    """WARNING 이상 로그를 error_logs 버퍼에 추가하는 핸들러.

    setup_db_logging()으로 root logger에 붙입니다.
    """

    def __init__(self, source: str | None = None, level: int = logging.WARNING):
        super().__init__(level)
        self._source = source or SOURCE

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            tb_text = None
            if record.exc_info and record.exc_info[2]:
                tb_text = "".join(tb_module.format_exception(*record.exc_info))

            _error_buffer.append((
                datetime.now(timezone.utc),
                self._source,
                record.levelname,
                record.name,
                msg[:2000],  # 메시지 길이 제한
                tb_text[:5000] if tb_text else None,
                POD_NAME,
            ))

            # 동기 컨텍스트에서는 flush를 예약만
            try:
                loop = asyncio.get_running_loop()
                if len(_error_buffer) >= BUFFER_SIZE:
                    loop.create_task(_flush())
            except RuntimeError:
                pass  # event loop 없으면 다음 async 호출 시 flush

        except Exception:
            self.handleError(record)


def setup_db_logging(source: str | None = None) -> None:
    """root logger에 DBLogHandler를 추가합니다.

    src/utils/logging.py의 setup_logging() 이후에 호출하세요.
    """
    handler = DBLogHandler(source=source)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    logger.info("DB 로그 핸들러 활성화 (source=%s, level=WARNING+)", source or SOURCE)


# ── 주기적 flush 태스크 ──────────────────────────────────────────────────


async def start_log_flusher() -> None:
    """백그라운드에서 주기적으로 로그 버퍼를 flush합니다."""
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        try:
            await _maybe_flush()
        except Exception:
            pass
