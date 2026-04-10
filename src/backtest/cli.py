"""
src/backtest/cli.py — 백테스트 CLI 인터페이스

사용법:
    python -m src.backtest run \
        --ticker 005930 --strategy RL \
        --train-start 2024-01-01 --train-end 2025-06-30 \
        --test-start 2025-07-01 --test-end 2025-12-31

    python -m src.backtest optimize \
        --ticker 005930 \
        --test-start 2025-07-01 --test-end 2025-12-31
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from src.backtest.cost_model import CostModel
from src.backtest.engine import BacktestEngine
from src.backtest.models import BacktestConfig, BacktestResult
from src.backtest.signal_source import ReplaySignalSource, RLSignalSource

# ── RL profile 매핑 ──────────────────────────────────────────────────
_RL_PROFILES = {
    "tabular_q_v1_baseline": {
        "algorithm": "tabular_q_learning",
        "state_version": "qlearn_v1",
        "trainer_cls_path": "src.agents.rl_trading.TabularQTrainer",
    },
    "tabular_q_v2_momentum": {
        "algorithm": "tabular_q_v2_momentum",
        "state_version": "qlearn_v2",
        "trainer_cls_path": "src.agents.rl_trading_v2.TabularQTrainerV2",
    },
}
DEFAULT_RL_PROFILE = "tabular_q_v2_momentum"


# ── 데이터 로딩 ──────────────────────────────────────────────────────

async def _load_ohlcv(ticker: str, start: date, end: date) -> list[dict]:
    """ohlcv_daily에서 start~end 구간 데이터를 로딩합니다."""
    from src.db.queries import fetch_recent_market_data

    total_days = (end - start).days + 30  # 여유분
    rows = await fetch_recent_market_data(ticker, days=total_days)
    filtered = [
        r for r in rows
        if start <= (r["traded_at"] if isinstance(r["traded_at"], date) else r["traded_at"].date()) <= end
    ]
    return sorted(filtered, key=lambda r: r["traded_at"])


# ── RL 시그널 소스 구성 ───────────────────────────────────────────────

def _build_rl_signal_source(
    *,
    ticker: str,
    train_prices: list[float],
    train_timestamps: list[str],
    profile_name: str,
    policy_id: Optional[str],
) -> RLSignalSource:
    """RL 정책을 학습하거나 로드하여 RLSignalSource를 생성합니다."""
    from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
    from src.agents.rl_trading import RLDataset, RLPolicyArtifact, TabularQTrainer
    from src.agents.rl_trading_v2 import TabularQTrainerV2

    profile = _RL_PROFILES[profile_name]

    if policy_id:
        # 특정 정책 로드
        store = RLPolicyStoreV2()
        artifact = store.load_policy(policy_id, ticker=ticker)
        if artifact is None:
            raise SystemExit(f"정책을 찾을 수 없습니다: policy_id={policy_id}, ticker={ticker}")
    else:
        # train 데이터로 학습
        dataset = RLDataset(
            ticker=ticker,
            closes=train_prices,
            timestamps=train_timestamps,
        )
        if profile["state_version"] == "qlearn_v1":
            trainer = TabularQTrainer()
            artifact = trainer.train(dataset, train_ratio=1.0)
        else:
            trainer = TabularQTrainerV2()
            artifact = trainer.train(dataset, train_ratio=1.0)

    return RLSignalSource(
        q_table=artifact.q_table,
        algorithm=profile["state_version"],
        lookback=artifact.lookback,
    )


# ── Replay 시그널 소스 구성 ──────────────────────────────────────────

async def _build_replay_signal_source(
    ticker: str,
    strategy: str,
    test_start: date,
    test_end: date,
) -> ReplaySignalSource:
    """predictions DB에서 시그널을 로드하여 ReplaySignalSource를 생성합니다."""
    from src.backtest.repository import fetch_predictions_for_replay

    predictions = await fetch_predictions_for_replay(
        ticker, test_start, test_end, strategy,
    )
    signals: dict[date, str] = {}
    for p in predictions:
        d = p["trading_date"] if isinstance(p["trading_date"], date) else p["trading_date"].date()
        signals[d] = p["signal"]
    return ReplaySignalSource(signals=signals)


# ── 결과 출력 ─────────────────────────────────────────────────────────

def _format_result(result: BacktestResult, profile_name: str | None = None) -> str:
    """백테스트 결과를 테이블 형식 문자열로 포매팅합니다."""
    cfg = result.config
    m = result.metrics

    strategy_label = cfg.strategy
    if cfg.strategy == "RL" and profile_name:
        strategy_label = f"RL ({profile_name})"

    # 비용 합산
    total_commission = sum(t.commission for t in result.trades)
    total_tax = sum(t.tax for t in result.trades)
    total_slippage = sum(t.slippage_cost for t in result.trades)

    lines = [
        "========== Backtest Result ==========",
        f"Ticker:          {cfg.ticker}",
        f"Strategy:        {strategy_label}",
        f"Test Period:     {cfg.test_start} ~ {cfg.test_end}",
        "",
        "--- Performance ---",
        f"Total Return:    {m.total_return_pct:+.2f}%",
        f"Annual Return:   {m.annual_return_pct:+.2f}%",
        f"Sharpe Ratio:    {m.sharpe_ratio:.2f}",
        f"Max Drawdown:    {m.max_drawdown_pct:.2f}%",
        f"Win Rate:        {m.win_rate:.1f}%",
        f"Total Trades:    {m.total_trades}",
        f"Avg Holding:     {m.avg_holding_days:.1f} days",
        "",
        "--- Benchmark ---",
        f"Buy & Hold:      {m.baseline_return_pct:+.2f}%",
        f"Excess Return:   {m.excess_return_pct:+.2f}%",
        "",
        "--- Cost Summary ---",
        f"Total Commission: {total_commission:,.0f} KRW",
        f"Total Tax:        {total_tax:,.0f} KRW",
        f"Total Slippage:   {total_slippage:,.0f} KRW",
        "=====================================",
    ]
    return "\n".join(lines)


def _result_to_dict(result: BacktestResult) -> dict:
    """BacktestResult를 JSON 직렬화 가능한 dict로 변환합니다."""
    from dataclasses import asdict
    raw = asdict(result)
    # date → ISO string
    def _convert(obj):  # noqa: ANN001, ANN202
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(v) for v in obj]
        return obj
    return _convert(raw)


# ── run 서브커맨드 ────────────────────────────────────────────────────

async def _run_backtest(args: argparse.Namespace) -> None:
    """단일 백테스트 실행."""
    config = BacktestConfig(
        ticker=args.ticker,
        strategy=args.strategy,
        train_start=args.train_start,
        train_end=args.train_end,
        test_start=args.test_start,
        test_end=args.test_end,
        initial_capital=args.initial_capital,
        commission_rate_pct=args.commission,
        tax_rate_pct=args.tax,
        slippage_bps=args.slippage_bps,
    )

    # 전체 기간 데이터 로드 (train + test)
    all_rows = await _load_ohlcv(config.ticker, config.train_start, config.test_end)
    if not all_rows:
        raise SystemExit(f"데이터가 없습니다: ticker={config.ticker}, "
                         f"기간={config.train_start}~{config.test_end}")

    # train / test 분리
    train_rows = [r for r in all_rows
                  if r["traded_at"] >= config.train_start and r["traded_at"] <= config.train_end]
    test_rows = [r for r in all_rows
                 if r["traded_at"] >= config.test_start and r["traded_at"] <= config.test_end]

    if not test_rows:
        raise SystemExit(f"테스트 구간 데이터가 없습니다: {config.test_start}~{config.test_end}")

    test_prices = [float(r["close"]) for r in test_rows]
    test_dates = [r["traded_at"] if isinstance(r["traded_at"], date) else r["traded_at"].date()
                  for r in test_rows]

    # 시그널 소스 구성
    profile_name = getattr(args, "profile", None) or DEFAULT_RL_PROFILE
    if config.strategy == "RL":
        train_prices = [float(r["close"]) for r in train_rows]
        train_timestamps = [str(r["traded_at"]) for r in train_rows]
        signal_source = _build_rl_signal_source(
            ticker=config.ticker,
            train_prices=train_prices,
            train_timestamps=train_timestamps,
            profile_name=profile_name,
            policy_id=getattr(args, "policy_id", None),
        )
    elif config.strategy in ("A", "B"):
        signal_source = await _build_replay_signal_source(
            config.ticker, config.strategy, config.test_start, config.test_end,
        )
    elif config.strategy == "BLEND":
        raise SystemExit("BLEND 전략은 optimize 서브커맨드를 사용하세요.")
    else:
        raise SystemExit(f"지원하지 않는 전략: {config.strategy}")

    # 엔진 실행
    cost_model = CostModel(config.commission_rate_pct, config.tax_rate_pct, config.slippage_bps)
    engine = BacktestEngine(
        config=config,
        signal_source=signal_source,
        cost_model=cost_model,
    )
    result = engine.run(prices=test_prices, dates=test_dates)

    # 결과 출력
    print(_format_result(result, profile_name=profile_name))

    # JSON 출력
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_result_to_dict(result), indent=2, ensure_ascii=False))
        print(f"\nJSON 저장: {output_path}")

    # DB 저장
    if args.save_db:
        from src.backtest.repository import save_backtest
        run_id = await save_backtest(result)
        print(f"\nDB 저장 완료: run_id={run_id}")


# ── optimize 서브커맨드 ───────────────────────────────────────────────

async def _run_optimize(args: argparse.Namespace) -> None:
    """가중치 최적화 실행."""
    from src.backtest.optimizer import BlendOptimizer

    optimizer = BlendOptimizer()
    opt_result = await optimizer.optimize(
        ticker=args.ticker,
        train_start=args.train_start,
        train_end=args.train_end,
        test_start=args.test_start,
        test_end=args.test_end,
        initial_capital=args.initial_capital,
        commission=args.commission,
        tax=args.tax,
        slippage_bps=args.slippage_bps,
        mdd_constraint=args.mdd_constraint,
    )

    # 결과 출력
    print("========== Blend Optimization ==========")
    print(f"Ticker:      {args.ticker}")
    print(f"Test Period: {args.test_start} ~ {args.test_end}")
    print(f"MDD 제약:    {args.mdd_constraint:.1f}%")
    print(f"유효 조합:   {opt_result.valid_count} / {opt_result.total_count}")
    print()
    if opt_result.best is None:
        print("MDD 제약을 만족하는 조합이 없습니다.")
    else:
        print("--- Best Weights ---")
        for strategy, weight in opt_result.best.weights.items():
            print(f"  {strategy}: {weight:.2f}")
        print(f"\nSharpe:      {opt_result.best.sharpe:.4f}")
        print(f"Return:      {opt_result.best.total_return_pct:+.2f}%")
        print(f"MDD:         {opt_result.best.max_drawdown_pct:.2f}%")

    if opt_result.top_n:
        print(f"\n--- Top {len(opt_result.top_n)} ---")
        for i, combo in enumerate(opt_result.top_n, 1):
            w = ", ".join(f"{k}={v:.2f}" for k, v in combo.weights.items())
            print(f"  {i}. [{w}] sharpe={combo.sharpe:.4f} ret={combo.total_return_pct:+.2f}% mdd={combo.max_drawdown_pct:.2f}%")
    print("=========================================")

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(opt_result.to_dict(), indent=2, ensure_ascii=False))
        print(f"\nJSON 저장: {output_path}")


# ── argparse ──────────────────────────────────────────────────────────

def _date_type(s: str) -> date:
    """YYYY-MM-DD 형식 날짜 파싱."""
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"날짜 형식이 올바르지 않습니다: {s} (YYYY-MM-DD)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.backtest",
        description="백테스트 시뮬레이션 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="서브커맨드")

    # ── run ──
    run_parser = subparsers.add_parser("run", help="단일 백테스트 실행")
    run_parser.add_argument("--ticker", required=True, help="종목 코드 (예: 005930)")
    run_parser.add_argument("--strategy", required=True, choices=["RL", "A", "B", "BLEND"],
                            help="전략 (RL, A, B, BLEND)")
    run_parser.add_argument("--train-start", required=True, type=_date_type, help="학습 시작일 (YYYY-MM-DD)")
    run_parser.add_argument("--train-end", required=True, type=_date_type, help="학습 종료일 (YYYY-MM-DD)")
    run_parser.add_argument("--test-start", required=True, type=_date_type, help="테스트 시작일 (YYYY-MM-DD)")
    run_parser.add_argument("--test-end", required=True, type=_date_type, help="테스트 종료일 (YYYY-MM-DD)")
    run_parser.add_argument("--initial-capital", type=int, default=10_000_000, help="초기 자본 (기본: 10,000,000)")
    run_parser.add_argument("--commission", type=float, default=0.015, help="수수료율 %% (기본: 0.015)")
    run_parser.add_argument("--tax", type=float, default=0.18, help="세금률 %% (기본: 0.18)")
    run_parser.add_argument("--slippage-bps", type=int, default=3, help="슬리피지 bps (기본: 3)")
    run_parser.add_argument("--save-db", action="store_true", help="결과를 DB에 저장")
    run_parser.add_argument("--output-json", type=str, default=None, help="JSON 결과 파일 경로")
    run_parser.add_argument("--profile", type=str, default=DEFAULT_RL_PROFILE,
                            choices=list(_RL_PROFILES.keys()),
                            help=f"RL 프로필 (기본: {DEFAULT_RL_PROFILE})")
    run_parser.add_argument("--policy-id", type=str, default=None, help="특정 RL 정책 ID (미지정 시 학습)")

    # ── optimize ──
    opt_parser = subparsers.add_parser("optimize", help="가중치 최적화")
    opt_parser.add_argument("--ticker", required=True, help="종목 코드")
    opt_parser.add_argument("--train-start", required=True, type=_date_type, help="학습 시작일")
    opt_parser.add_argument("--train-end", required=True, type=_date_type, help="학습 종료일")
    opt_parser.add_argument("--test-start", required=True, type=_date_type, help="테스트 시작일")
    opt_parser.add_argument("--test-end", required=True, type=_date_type, help="테스트 종료일")
    opt_parser.add_argument("--initial-capital", type=int, default=10_000_000, help="초기 자본")
    opt_parser.add_argument("--commission", type=float, default=0.015, help="수수료율 %%")
    opt_parser.add_argument("--tax", type=float, default=0.18, help="세금률 %%")
    opt_parser.add_argument("--slippage-bps", type=int, default=3, help="슬리피지 bps")
    opt_parser.add_argument("--mdd-constraint", type=float, default=-20.0, help="MDD 제약 %% (기본: -20.0)")
    opt_parser.add_argument("--output-json", type=str, default=None, help="JSON 결과 파일 경로")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "run":
        asyncio.run(_run_backtest(args))
    elif args.command == "optimize":
        asyncio.run(_run_optimize(args))
