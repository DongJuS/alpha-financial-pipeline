"""src/agents/collector/models.py — Collector 전용 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TickData:
    """실시간 틱 데이터. WebSocket 수신 즉시 생성, 틱 전략이 직접 소비."""

    instrument_id: str
    price: float
    volume: int
    timestamp_kst: datetime
    name: str = ""
    market: str = "KOSPI"
    change_pct: float | None = None
    source: str = "kis_ws"
