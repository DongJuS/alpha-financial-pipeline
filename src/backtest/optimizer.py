"""
src/backtest/optimizer.py — 전략 가중치 그리드 서치 최적화 (P2)

3전략(RL, A, B) 가중치를 0.05 단위로 탐색하여 샤프 비율이 최대인 조합을 찾습니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.backtest.cost_model import CostModel
from src.backtest.engine import BacktestEngine
from src.backtest.models import BacktestConfig, BacktestResult


@dataclass(frozen=True)
class WeightCombo:
    """단일 가중치 조합의 결과."""

    weights: dict[str, float]  # {"RL": 0.5, "A": 0.3, "B": 0.2}
    sharpe: float
    total_return_pct: float
    max_drawdown_pct: float


@dataclass
class OptimizationResult:
    """최적화 결과."""

    best: Optional[WeightCombo]
    top_n: list[WeightCombo] = field(default_factory=list)
    total_count: int = 0
    valid_count: int = 0  # MDD 제약 통과 수

    def to_dict(self) -> dict:
        def _combo_dict(c: WeightCombo) -> dict:
            return {
                "weights": c.weights,
                "sharpe": c.sharpe,
                "total_return_pct": c.total_return_pct,
                "max_drawdown_pct": c.max_drawdown_pct,
            }

        return {
            "best": _combo_dict(self.best) if self.best else None,
            "top_n": [_combo_dict(c) for c in self.top_n],
            "total_count": self.total_count,
            "valid_count": self.valid_count,
        }


def _generate_weight_combos(
    strategies: list[str],
    step: float = 0.05,
) -> list[dict[str, float]]:
    """합계 1.0이 되는 가중치 조합을 생성합니다.

    3전략, 0.05 단위 → C(22,2) = 231개.
    """
    n = len(strategies)
    steps = int(round(1.0 / step))  # 20
    combos: list[dict[str, float]] = []

    # n개 전략의 가중치 (0, 1, ..., steps)에서 합이 steps인 조합
    if n == 2:
        for w0 in range(steps + 1):
            w1 = steps - w0
            combos.append({
                strategies[0]: w0 * step,
                strategies[1]: w1 * step,
            })
    elif n == 3:
        for w0 in range(steps + 1):
            for w1 in range(steps + 1 - w0):
                w2 = steps - w0 - w1
                combos.append({
                    strategies[0]: w0 * step,
                    strategies[1]: w1 * step,
                    strategies[2]: w2 * step,
                })
    else:
        raise ValueError(f"전략 수는 2~3개만 지원합니다 (got {n})")

    return combos


class BlendOptimizer:
    """전략 가중치 그리드 서치 최적화."""

    STRATEGIES = ["RL", "A", "B"]
    TOP_N = 10

    async def optimize(
        self,
        *,
        ticker: str,
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
        initial_capital: int = 10_000_000,
        commission: float = 0.015,
        tax: float = 0.18,
        slippage_bps: int = 3,
        mdd_constraint: float = -20.0,
        step: float = 0.05,
    ) -> OptimizationResult:
        """그리드 서치를 실행하여 최적 가중치를 찾습니다."""
        from src.backtest.signal_source import ReplaySignalSource, RLSignalSource

        # 각 전략별 일별 수익률 시리즈를 먼저 계산
        strategy_daily_returns = await self._compute_strategy_returns(
            ticker=ticker,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            initial_capital=initial_capital,
            commission=commission,
            tax=tax,
            slippage_bps=slippage_bps,
        )

        combos = _generate_weight_combos(self.STRATEGIES, step=step)
        results: list[WeightCombo] = []

        for weights in combos:
            # 가중 평균 일별 수익률
            blended_returns = self._blend_returns(strategy_daily_returns, weights)
            if not blended_returns:
                continue

            # 지표 산출
            metrics = self._compute_metrics_from_returns(
                blended_returns, initial_capital,
            )
            if metrics is None:
                continue

            combo = WeightCombo(
                weights=weights,
                sharpe=metrics["sharpe"],
                total_return_pct=metrics["total_return_pct"],
                max_drawdown_pct=metrics["max_drawdown_pct"],
            )

            # MDD 제약
            if combo.max_drawdown_pct >= mdd_constraint:
                results.append(combo)

        # 샤프 비율 내림차순 정렬
        results.sort(key=lambda c: -c.sharpe)

        return OptimizationResult(
            best=results[0] if results else None,
            top_n=results[: self.TOP_N],
            total_count=len(combos),
            valid_count=len(results),
        )

    async def _compute_strategy_returns(
        self,
        *,
        ticker: str,
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
        initial_capital: int,
        commission: float,
        tax: float,
        slippage_bps: int,
    ) -> dict[str, list[float]]:
        """각 전략별 일별 수익률(%)을 산출합니다."""
        from src.backtest.cli import _build_rl_signal_source, _build_replay_signal_source, _load_ohlcv

        # 데이터 로드
        all_rows = await _load_ohlcv(ticker, train_start, test_end)
        train_rows = [r for r in all_rows
                      if r["traded_at"] >= train_start and r["traded_at"] <= train_end]
        test_rows = [r for r in all_rows
                     if r["traded_at"] >= test_start and r["traded_at"] <= test_end]

        if not test_rows:
            return {}

        test_prices = [float(r["close"]) for r in test_rows]
        test_dates = [r["traded_at"] if isinstance(r["traded_at"], date) else r["traded_at"].date()
                      for r in test_rows]

        result: dict[str, list[float]] = {}

        for strategy in self.STRATEGIES:
            config = BacktestConfig(
                ticker=ticker,
                strategy=strategy,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                initial_capital=initial_capital,
                commission_rate_pct=commission,
                tax_rate_pct=tax,
                slippage_bps=slippage_bps,
            )
            cost_model = CostModel(config)

            if strategy == "RL":
                train_prices = [float(r["close"]) for r in train_rows]
                train_timestamps = [str(r["traded_at"]) for r in train_rows]
                signal_source = _build_rl_signal_source(
                    ticker=ticker,
                    train_prices=train_prices,
                    train_timestamps=train_timestamps,
                    profile_name="tabular_q_v2_momentum",
                    policy_id=None,
                )
            else:
                signal_source = await _build_replay_signal_source(
                    ticker, strategy, test_start, test_end,
                )

            engine = BacktestEngine(
                config=config,
                signal_source=signal_source,
                cost_model=cost_model,
            )
            bt_result = engine.run(prices=test_prices, dates=test_dates)
            result[strategy] = [s.daily_return_pct for s in bt_result.daily_snapshots]

        return result

    @staticmethod
    def _blend_returns(
        strategy_returns: dict[str, list[float]],
        weights: dict[str, float],
    ) -> list[float]:
        """가중 평균 일별 수익률을 계산합니다."""
        if not strategy_returns:
            return []
        # 모든 전략의 길이가 같아야 함
        lengths = [len(v) for v in strategy_returns.values()]
        if len(set(lengths)) != 1:
            min_len = min(lengths)
        else:
            min_len = lengths[0]

        blended = []
        for i in range(min_len):
            r = sum(
                weights.get(s, 0.0) * strategy_returns[s][i]
                for s in strategy_returns
            )
            blended.append(r)
        return blended

    @staticmethod
    def _compute_metrics_from_returns(
        daily_returns: list[float],
        initial_capital: int,
    ) -> Optional[dict]:
        """일별 수익률 시리즈에서 성과 지표를 산출합니다."""
        if not daily_returns:
            return None

        # 누적 수익률
        cumulative = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in daily_returns:
            cumulative *= (1.0 + r / 100.0)
            if cumulative > peak:
                peak = cumulative
            dd = (cumulative - peak) / peak * 100.0
            if dd < max_dd:
                max_dd = dd

        total_return_pct = (cumulative - 1.0) * 100.0

        # 연환산
        n_days = len(daily_returns)
        annual_factor = 252.0 / n_days if n_days > 0 else 1.0
        annual_return_pct = ((cumulative ** annual_factor) - 1.0) * 100.0

        # 샤프
        if n_days < 2:
            sharpe = 0.0
        else:
            mean_r = sum(daily_returns) / n_days
            variance = sum((r - mean_r) ** 2 for r in daily_returns) / (n_days - 1)
            std_r = variance ** 0.5
            sharpe = (mean_r / std_r * (252 ** 0.5)) if std_r > 0 else 0.0

        return {
            "total_return_pct": total_return_pct,
            "annual_return_pct": annual_return_pct,
            "sharpe": sharpe,
            "max_drawdown_pct": max_dd,
        }
