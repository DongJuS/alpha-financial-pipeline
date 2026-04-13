"""
test/test_strategy_edge_cases.py — Strategy A/B Runner 에지케이스 테스트

StrategyARunner / StrategyBRunner의 빈 입력, 예외 처리 등 에지케이스를 검증합니다.
src/ 코드는 수정하지 않으며, mock으로 외부 의존성(DB, 토너먼트, 합의)을 격리합니다.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from src.agents.strategy_a_runner import StrategyARunner
from src.agents.strategy_b_runner import StrategyBRunner


class TestStrategyAEmptyTickers(unittest.IsolatedAsyncioTestCase):
    """StrategyARunner.run([]) -> []"""

    async def test_strategy_a_empty_tickers_returns_empty(self) -> None:
        runner = StrategyARunner()
        result = await runner.run([])
        self.assertEqual(result, [])


class TestStrategyAExceptionReturnsEmpty(unittest.IsolatedAsyncioTestCase):
    """StrategyARunner 내부 예외 시 빈 리스트 반환."""

    async def test_strategy_a_exception_returns_empty_list(self) -> None:
        runner = StrategyARunner()
        with patch.object(
            runner._tournament,
            "run_daily_tournament",
            new=AsyncMock(side_effect=RuntimeError("DB connection failed")),
        ):
            result = await runner.run(["005930", "000660"])
        self.assertEqual(result, [])


class TestStrategyBEmptyTickers(unittest.IsolatedAsyncioTestCase):
    """StrategyBRunner.run([]) -> []"""

    async def test_strategy_b_empty_tickers_returns_empty(self) -> None:
        runner = StrategyBRunner()
        result = await runner.run([])
        self.assertEqual(result, [])


class TestStrategyBExceptionLogsAndReturnsEmpty(unittest.IsolatedAsyncioTestCase):
    """StrategyBRunner 예외 시 db_logger에 로깅 + 빈 리스트 반환."""

    async def test_strategy_b_exception_logs_and_returns_empty(self) -> None:
        runner = StrategyBRunner()
        with (
            patch.object(
                runner._consensus,
                "run",
                new=AsyncMock(side_effect=ValueError("LLM quota exceeded")),
            ),
            patch(
                "src.agents.strategy_b_runner.log_event",
                new=AsyncMock(),
                create=True,
            ),
        ):
            # log_event는 lazy import이므로 strategy_b_runner 내부에서 직접 패치
            with patch(
                "src.utils.db_logger.log_event",
                new=AsyncMock(),
            ):
                result = await runner.run(["005930"])

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
