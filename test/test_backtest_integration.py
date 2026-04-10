"""test/test_backtest_integration.py — Step 10 모듈 간 통합 테스트.

기존 유닛 테스트는 각 모듈을 mock 으로 격리했다.
이 파일은 engine <-> signal_source <-> cost_model <-> metrics 를
실제 연결하여 인터페이스 일관성을 검증한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.backtest.cost_model import CostModel
from src.backtest.engine import BacktestEngine
from src.backtest.models import (
    BacktestConfig,
    BacktestResult,
    DailySnapshot,
    TradeRecord,
)
from src.backtest.optimizer import BlendOptimizer, OptimizationResult
from src.backtest.signal_source import RLSignalSource

# ── Fixtures ────────────────────────────────────────────────────────────────

# 30 일 가격: 상승 -> 하락 -> 회복 패턴
# V1 state bucket 계산에서 BUY/SELL 시그널이 자연 발생하도록 설계
PRICES: list[float] = [
    100, 102, 105, 108, 110, 112, 115, 118, 120, 122,  # 상승
    120, 117, 114, 110, 107, 105, 103, 101, 100, 99,   # 하락
    100, 102, 104, 107, 110, 113, 115, 118, 120, 123,  # 회복
]
DATES: list[date] = [date(2025, 7, 1) + timedelta(days=i) for i in range(30)]

# V1 Q-table: short_bucket/long_bucket 기반
#  - 미보유 + 단기·장기 모두 상승 -> BUY
#  - 보유 + 단기·장기 모두 하락   -> SELL
Q_TABLE: dict[str, dict[str, float]] = {
    "p0|s1|l1": {"BUY": 1.0, "HOLD": 0.0},
    "p1|s-1|l-1": {"SELL": 1.0, "HOLD": 0.0},
}

# initial_capital=150 → price ~100 대에서 1주만 매수.
# RLSignalSource 의 state_key 는 position 을 그대로 사용하므로 (p{qty}),
# 학습 시 position=0/1 로 훈련된 Q-table 과 일치시키려면 qty=1 이어야 한다.
CONFIG = BacktestConfig(
    ticker="005930",
    strategy="RL",
    train_start=date(2025, 1, 1),
    train_end=date(2025, 6, 30),
    test_start=date(2025, 7, 1),
    test_end=date(2025, 7, 30),
    initial_capital=150,
)


# ── Test 1: Engine + RLSignalSource + CostModel E2E ─────────────────────────


def test_engine_with_rl_signal_source_end_to_end():
    """RLSignalSource -> CostModel -> BacktestEngine -> BacktestResult 전체 경로."""
    signal_source = RLSignalSource(Q_TABLE, algorithm="qlearn_v1", lookback=5)
    cost_model = CostModel()
    engine = BacktestEngine(CONFIG, signal_source, cost_model)

    result = engine.run(PRICES, DATES)

    # 반환 타입
    assert isinstance(result, BacktestResult)

    # 스냅샷 수 == 가격 수
    assert len(result.daily_snapshots) == len(PRICES)

    # 거래 발생 (최소 1 BUY + 1 SELL)
    assert len(result.trades) >= 2
    buy_trades = [t for t in result.trades if t.side == "BUY"]
    sell_trades = [t for t in result.trades if t.side == "SELL"]
    assert len(buy_trades) >= 1
    assert len(sell_trades) >= 1

    # 매매 기록 필드 일관성
    for trade in result.trades:
        assert isinstance(trade, TradeRecord)
        assert trade.ticker == "005930"
        assert trade.quantity > 0
        assert trade.total_cost >= 0
        assert trade.total_cost == pytest.approx(
            trade.commission + trade.tax + trade.slippage_cost
        )

    # 스냅샷 필드 일관성: portfolio_value = cash + position_value
    for snap in result.daily_snapshots:
        assert isinstance(snap, DailySnapshot)
        assert snap.portfolio_value == pytest.approx(
            snap.cash + snap.position_value
        )
        assert snap.position_value == pytest.approx(
            snap.position_qty * snap.close_price
        )

    # metrics 필수 필드 & 합리적 범위
    m = result.metrics
    assert m.total_trades == len(result.trades)
    assert -100 < m.total_return_pct < 1000
    assert -100 < m.max_drawdown_pct <= 0
    assert 0 <= m.win_rate <= 100


# ── Test 2: BlendOptimizer pipeline E2E ──────────────────────────────────────


async def test_blend_optimizer_runs_with_real_metrics():
    """BlendOptimizer: weight generation -> blend -> metrics -> sort 파이프라인.

    _compute_strategy_returns 만 patch 하여 DB/네트워크 의존을 제거하고,
    이후 blend + metrics + MDD 필터 + 정렬은 실제로 실행한다.
    """
    # 30 일 일별 수익률(%) — 전략별로 다른 패턴
    fake_returns: dict[str, list[float]] = {
        "RL": [
            0.5, -0.2, 0.3, 0.1, -0.1, 0.4, -0.3, 0.2, 0.1, 0.0,
            -0.5, 0.3, 0.2, -0.1, 0.4, 0.1, -0.2, 0.3, 0.0, 0.1,
            0.2, -0.1, 0.3, 0.1, -0.2, 0.4, 0.0, 0.1, -0.1, 0.2,
        ],
        "A": [
            0.1, 0.2, -0.1, 0.3, 0.0, 0.1, 0.2, -0.3, 0.4, 0.1,
            0.0, -0.2, 0.3, 0.1, 0.2, -0.1, 0.3, 0.0, 0.1, 0.2,
            -0.1, 0.3, 0.0, 0.2, 0.1, -0.2, 0.3, 0.1, 0.0, 0.2,
        ],
        "B": [
            -0.3, 0.4, 0.2, -0.2, 0.5, -0.1, 0.3, 0.1, -0.4, 0.6,
            0.2, -0.3, 0.1, 0.4, -0.2, 0.3, -0.1, 0.2, 0.5, -0.3,
            0.4, 0.1, -0.2, 0.3, 0.0, 0.1, -0.1, 0.4, 0.2, -0.1,
        ],
    }

    optimizer = BlendOptimizer()

    with patch.object(
        optimizer,
        "_compute_strategy_returns",
        new_callable=AsyncMock,
        return_value=fake_returns,
    ):
        result = await optimizer.optimize(
            ticker="005930",
            train_start=date(2024, 1, 1),
            train_end=date(2024, 12, 31),
            test_start=date(2025, 1, 1),
            test_end=date(2025, 12, 31),
            step=0.5,
            mdd_constraint=-50.0,
        )

    # 반환 타입
    assert isinstance(result, OptimizationResult)

    # 3 전략 step=0.5 -> 6 조합
    assert result.total_count == 6

    # 최적 조합 존재 & 가중치 합 == 1.0
    assert result.best is not None
    assert sum(result.best.weights.values()) == pytest.approx(1.0)

    # top_n 은 sharpe 내림차순
    for i in range(len(result.top_n) - 1):
        assert result.top_n[i].sharpe >= result.top_n[i + 1].sharpe

    # 모든 valid combo 가 MDD 제약 통과
    for combo in result.top_n:
        assert combo.max_drawdown_pct >= -50.0

    # valid_count <= total_count
    assert result.valid_count <= result.total_count
    assert result.valid_count == len(result.top_n)
