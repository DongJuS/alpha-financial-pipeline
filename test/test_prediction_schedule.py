"""
test/test_prediction_schedule.py — prediction_schedule 스케줄 판단 로직 테스트

orchestrator 루프에서 전략별 실행 여부를 결정하는 로직을 독립 함수로 추출하여 테스트한다.

DB 쿼리 함수를 mock 하여 외부 의존성 없이 동작:
  - src.db.queries.fetch_prediction_schedules
  - src.db.queries.touch_prediction_schedule

테스트 케이스:
  1. last_run_at 이 interval_minutes 이전 → 실행 대상
  2. last_run_at 이 interval_minutes 이내 → skip
  3. is_enabled=False → skip
  4. 스케줄이 비어있으면 전체 전략 실행 (fallback)
  5. last_run_at=None → 반드시 실행
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any




# ── 스케줄 판단 헬퍼 (테스트 대상) ────────────────────────────────────────────
#
# orchestrator 루프 안에 있는 "이 전략을 지금 실행해야 하나?" 판단 로직을
# 순수 함수로 추출한다.  실제 orchestrator 코드에 이 함수가 추가될 때까지
# 여기서 직접 정의한다.


def is_strategy_due(
    schedule: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """단일 전략 스케줄 레코드를 보고 실행 여부를 반환한다.

    Args:
        schedule: prediction_schedule 행 (dict).
            필수 키: strategy_code, interval_minutes, is_enabled, last_run_at
        now: 현재 시각 (기본: utcnow)

    Returns:
        True 이면 실행 대상, False 이면 skip.
    """
    if not schedule.get("is_enabled", True):
        return False

    last_run = schedule.get("last_run_at")
    if last_run is None:
        # 한 번도 실행된 적 없으면 즉시 실행
        return True

    current = now or datetime.now(timezone.utc)
    interval = timedelta(minutes=schedule.get("interval_minutes", 30))
    return (current - last_run) >= interval


def filter_due_strategies(
    schedules: list[dict[str, Any]],
    all_strategy_codes: list[str],
    *,
    now: datetime | None = None,
) -> list[str]:
    """실행 대상 전략 코드 목록을 반환한다.

    Args:
        schedules: prediction_schedule 행 목록.
        all_strategy_codes: 등록된 전체 전략 코드 (예: ["A", "B", "RL"]).
        now: 현재 시각.

    Returns:
        실행해야 하는 전략 코드 리스트.
        schedules 가 비어있으면 all_strategy_codes 를 그대로 반환 (fallback).
    """
    if not schedules:
        return list(all_strategy_codes)

    return [
        s["strategy_code"]
        for s in schedules
        if is_strategy_due(s, now=now)
    ]


# ── 테스트 ──────────────────────────────────────────────────────────────────


NOW = datetime(2026, 4, 12, 9, 0, 0, tzinfo=timezone.utc)
ALL_STRATEGIES = ["A", "B", "RL"]


class TestIsStrategyDue:
    """is_strategy_due 단일 레코드 판단 테스트"""

    def test_strategy_due_for_execution(self) -> None:
        """last_run_at 이 interval_minutes 이전이면 실행 대상이다."""
        schedule = {
            "strategy_code": "A",
            "interval_minutes": 30,
            "is_enabled": True,
            "last_run_at": NOW - timedelta(minutes=31),
        }
        assert is_strategy_due(schedule, now=NOW) is True

    def test_strategy_not_due(self) -> None:
        """last_run_at 이 interval_minutes 이내이면 skip 한다."""
        schedule = {
            "strategy_code": "B",
            "interval_minutes": 30,
            "is_enabled": True,
            "last_run_at": NOW - timedelta(minutes=10),
        }
        assert is_strategy_due(schedule, now=NOW) is False

    def test_disabled_strategy_skipped(self) -> None:
        """is_enabled=False 이면 last_run_at 에 관계없이 skip 한다."""
        schedule = {
            "strategy_code": "RL",
            "interval_minutes": 30,
            "is_enabled": False,
            "last_run_at": NOW - timedelta(hours=2),  # 충분히 오래됐지만 비활성
        }
        assert is_strategy_due(schedule, now=NOW) is False

    def test_first_run_always_executes(self) -> None:
        """last_run_at=None 이면 반드시 실행한다."""
        schedule = {
            "strategy_code": "A",
            "interval_minutes": 60,
            "is_enabled": True,
            "last_run_at": None,
        }
        assert is_strategy_due(schedule, now=NOW) is True

    def test_exact_boundary_is_due(self) -> None:
        """last_run_at 이 정확히 interval_minutes 전이면 실행 대상이다 (>=)."""
        schedule = {
            "strategy_code": "A",
            "interval_minutes": 30,
            "is_enabled": True,
            "last_run_at": NOW - timedelta(minutes=30),
        }
        assert is_strategy_due(schedule, now=NOW) is True


class TestFilterDueStrategies:
    """filter_due_strategies 다수 레코드 판단 테스트"""

    def test_no_schedules_fallback(self) -> None:
        """스케줄이 비어있으면 전체 전략을 실행한다 (fallback)."""
        result = filter_due_strategies([], ALL_STRATEGIES, now=NOW)
        assert result == ALL_STRATEGIES

    def test_mixed_due_and_not_due(self) -> None:
        """due 인 전략만 반환한다."""
        schedules = [
            {
                "strategy_code": "A",
                "interval_minutes": 30,
                "is_enabled": True,
                "last_run_at": NOW - timedelta(minutes=40),  # due
            },
            {
                "strategy_code": "B",
                "interval_minutes": 30,
                "is_enabled": True,
                "last_run_at": NOW - timedelta(minutes=10),  # not due
            },
            {
                "strategy_code": "RL",
                "interval_minutes": 30,
                "is_enabled": True,
                "last_run_at": None,  # first run → due
            },
        ]
        result = filter_due_strategies(schedules, ALL_STRATEGIES, now=NOW)
        assert "A" in result
        assert "B" not in result
        assert "RL" in result

    def test_all_disabled(self) -> None:
        """모든 전략이 비활성이면 빈 리스트를 반환한다."""
        schedules = [
            {
                "strategy_code": code,
                "interval_minutes": 30,
                "is_enabled": False,
                "last_run_at": None,
            }
            for code in ALL_STRATEGIES
        ]
        result = filter_due_strategies(schedules, ALL_STRATEGIES, now=NOW)
        assert result == []
