"""
test/test_collector_models.py — collector/models.py TickData 모델 테스트

TickData 데이터클래스의 필드 초기화, 기본값, 타입 검증.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

pytestmark = [pytest.mark.unit]


class TestTickDataFields:
    """TickData 데이터클래스 필드 검증."""

    def test_required_fields(self):
        """필수 필드(instrument_id, price, volume, timestamp_kst)가 정상 초기화."""
        from src.agents.collector.models import TickData

        now = datetime(2026, 4, 11, 10, 0, 0)
        tick = TickData(
            instrument_id="005930.KS",
            price=72000.0,
            volume=100000,
            timestamp_kst=now,
        )
        assert tick.instrument_id == "005930.KS"
        assert tick.price == 72000.0
        assert tick.volume == 100000
        assert tick.timestamp_kst == now

    def test_default_values(self):
        """기본값 필드(name, market, change_pct, source) 확인."""
        from src.agents.collector.models import TickData

        tick = TickData(
            instrument_id="005930.KS",
            price=72000.0,
            volume=100000,
            timestamp_kst=datetime.now(),
        )
        assert tick.name == ""
        assert tick.market == "KOSPI"
        assert tick.change_pct is None
        assert tick.source == "kis_ws"

    def test_custom_defaults(self):
        """기본값 필드를 커스텀으로 지정."""
        from src.agents.collector.models import TickData

        tick = TickData(
            instrument_id="035720.KQ",
            price=150000.0,
            volume=50000,
            timestamp_kst=datetime.now(),
            name="카카오",
            market="KOSDAQ",
            change_pct=1.5,
            source="kis_rest_backfill",
        )
        assert tick.name == "카카오"
        assert tick.market == "KOSDAQ"
        assert tick.change_pct == 1.5
        assert tick.source == "kis_rest_backfill"

    def test_is_dataclass(self):
        """TickData가 dataclass인지 확인."""
        import dataclasses

        from src.agents.collector.models import TickData

        assert dataclasses.is_dataclass(TickData)

    def test_fields_count(self):
        """TickData 필드가 8개인지 확인."""
        import dataclasses

        from src.agents.collector.models import TickData

        fields = dataclasses.fields(TickData)
        assert len(fields) == 8

    def test_zero_price_allowed(self):
        """price=0 도 허용 (데이터클래스는 검증 없음)."""
        from src.agents.collector.models import TickData

        tick = TickData(
            instrument_id="005930.KS",
            price=0.0,
            volume=0,
            timestamp_kst=datetime.now(),
        )
        assert tick.price == 0.0
        assert tick.volume == 0

    def test_negative_change_pct(self):
        """음수 change_pct 허용."""
        from src.agents.collector.models import TickData

        tick = TickData(
            instrument_id="005930.KS",
            price=70000.0,
            volume=100,
            timestamp_kst=datetime.now(),
            change_pct=-2.5,
        )
        assert tick.change_pct == -2.5

    def test_equality(self):
        """동일 필드값 TickData는 동등."""
        from src.agents.collector.models import TickData

        ts = datetime(2026, 4, 11, 10, 0, 0)
        t1 = TickData(instrument_id="005930.KS", price=72000.0, volume=100, timestamp_kst=ts)
        t2 = TickData(instrument_id="005930.KS", price=72000.0, volume=100, timestamp_kst=ts)
        assert t1 == t2
