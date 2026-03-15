"""
scripts/run_yahoo_krafton_rl.py — Yahoo Finance 기반 크래프톤 1년치 RL 학습/테스트

기본값:
- 종목: 259960.KS (KRAFTON, Inc.)
- 데이터: 최근 1년 60분봉
- 분할: 80% 학습 / 20% 테스트
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.rl_trading import RLDataset, RLPolicyStore, TabularQTrainer
from src.services.yahoo_finance import bars_from_chart_payload, fetch_daily_bars, quote_page_url


async def _main_async(args: argparse.Namespace) -> None:
    try:
        bars = await fetch_daily_bars(args.ticker, range_=args.range, interval=args.interval)
        source_mode = "direct_http"
    except Exception:
        payload = _fetch_chart_payload_via_playwright(args.ticker, range_=args.range, interval=args.interval)
        bars = bars_from_chart_payload(args.ticker, payload)
        source_mode = "playwright_fallback"
    output_dir = ROOT / "artifacts" / "rl" / "yahoo"
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / f"{args.ticker}_{args.range}_{args.interval}.csv"
    _write_csv(csv_path, bars)

    dataset = RLDataset(
        ticker=args.ticker,
        closes=[bar.close for bar in bars],
        timestamps=[bar.date for bar in bars],
    )

    trainer = TabularQTrainer(
        episodes=args.episodes,
        lookback=args.lookback,
        learning_rate=args.learning_rate,
        discount_factor=args.discount_factor,
        epsilon=args.epsilon,
        trade_penalty_bps=args.trade_penalty_bps,
    )
    artifact, split_metadata = trainer.train_with_metadata(dataset, train_ratio=args.train_ratio)

    policy_store = RLPolicyStore()
    artifact = policy_store.save_policy(artifact)
    if artifact.evaluation.approved:
        policy_store.activate_policy(artifact)

    latest_action, latest_confidence, latest_state, latest_q_values = trainer.infer_action(
        artifact,
        dataset.closes,
        current_position=0,
    )

    result = {
        "company": "KRAFTON, Inc.",
        "ticker": args.ticker,
        "source": {
            "api": "Yahoo Finance chart API",
            "quote_page": quote_page_url(args.ticker),
            "collection_mode": source_mode,
            "range": args.range,
            "interval": args.interval,
        },
        "data_period": {
            "from": dataset.timestamps[0],
            "to": dataset.timestamps[-1],
            "rows": len(dataset.timestamps),
            "csv_path": str(csv_path),
        },
        "split": asdict(split_metadata),
        "evaluation": asdict(artifact.evaluation),
        "latest_inference": {
            "action": latest_action,
            "confidence": latest_confidence,
            "state": latest_state,
            "q_values": latest_q_values,
        },
        "policy": {
            "policy_id": artifact.policy_id,
            "artifact_path": artifact.artifact_path,
            "approved": artifact.evaluation.approved,
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _write_csv(csv_path: Path, bars) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"],
        )
        writer.writeheader()
        for bar in bars:
            writer.writerow(bar.to_dict())


def _fetch_chart_payload_via_playwright(ticker: str, *, range_: str, interval: str) -> dict:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    pwcli = codex_home / "skills" / "playwright" / "scripts" / "playwright_cli.sh"
    session = f"krafton_{uuid4().hex[:8]}"
    chart_url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?range={range_}&interval={interval}&includeAdjustedClose=true&events=div,splits"
    )
    open_cmd = (
        f"{shlex.quote(str(pwcli))} --session {shlex.quote(session)} "
        f"open {shlex.quote(quote_page_url(ticker))}"
    )
    eval_source = f"() => fetch('{chart_url}').then(r => r.json())"
    eval_cmd = (
        f"{shlex.quote(str(pwcli))} --session {shlex.quote(session)} "
        f"eval {shlex.quote(eval_source)}"
    )
    close_cmd = f"{shlex.quote(str(pwcli))} --session {shlex.quote(session)} close"

    subprocess.run(["zsh", "-lc", open_cmd], capture_output=True, text=True, timeout=90, check=True)
    try:
        result = subprocess.run(["zsh", "-lc", eval_cmd], capture_output=True, text=True, timeout=120, check=True)
        match = re.search(r"### Result\n(.*?)\n### Ran Playwright code", result.stdout, re.S)
        if not match:
            raise ValueError(f"Playwright 결과 파싱 실패: {result.stdout[:500]}")
        return json.loads(match.group(1))
    finally:
        subprocess.run(["zsh", "-lc", close_cmd], capture_output=True, text=True, timeout=30, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Yahoo Finance 크래프톤 RL 학습/테스트")
    parser.add_argument("--ticker", default="259960.KS", help="Yahoo Finance ticker")
    parser.add_argument("--range", default="1y", help="Yahoo Finance chart range")
    parser.add_argument("--interval", default="60m", help="Yahoo Finance chart interval")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="학습 데이터 비율 (기본 0.8)")
    parser.add_argument("--episodes", type=int, default=120, help="Q-learning episodes")
    parser.add_argument("--lookback", type=int, default=6, help="state lookback window")
    parser.add_argument("--learning-rate", type=float, default=0.18, help="learning rate")
    parser.add_argument("--discount-factor", type=float, default=0.92, help="discount factor")
    parser.add_argument("--epsilon", type=float, default=0.15, help="exploration epsilon")
    parser.add_argument("--trade-penalty-bps", type=int, default=5, help="trade penalty in bps")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
