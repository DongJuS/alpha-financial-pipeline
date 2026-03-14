"""
scripts/run_yfinance_krafton_rl.py — yfinance 기반 크래프톤 RL 학습/테스트

기본값:
- 종목: 259960.KS (KRAFTON, Inc.)
- 데이터: Yahoo/yfinance 최대 가용 장기 이력(기본 요청: 10y, 1d)
- 분할: 80% 학습 / 20% 테스트
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import sys

from dotenv import load_dotenv
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.rl_trading import RLDataset, RLPolicyStore, TabularQTrainer


def _download_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    data = yf.download(
        ticker,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False,
        actions=False,
        threads=False,
    )
    if data.empty:
        raise ValueError(
            f"yfinance 데이터가 비어 있습니다: ticker={ticker}, period={period}, interval={interval}"
        )

    if isinstance(data.columns, pd.MultiIndex):
        try:
            data = data.xs(ticker, axis=1, level="Ticker")
        except Exception:
            data.columns = [col[0] for col in data.columns]

    return data.reset_index()


def _timestamp_label(value: pd.Timestamp, interval: str) -> str:
    ts = pd.Timestamp(value)
    if interval.endswith(("m", "h")):
        if ts.tzinfo is not None:
            return ts.tz_convert("Asia/Seoul").isoformat(timespec="minutes")
        return ts.isoformat(timespec="minutes")
    return ts.date().isoformat()


def _save_price_csv(path: Path, ticker: str, history: pd.DataFrame, interval: str) -> None:
    fieldnames = ["ticker", "timestamp", "open", "high", "low", "close", "adj_close", "volume"]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in history.to_dict(orient="records"):
            writer.writerow(
                {
                    "ticker": ticker,
                    "timestamp": _timestamp_label(row["Date"], interval),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "adj_close": float(row["Adj Close"]),
                    "volume": int(row["Volume"]),
                }
            )


def _build_stock_info(ticker: str, recent_close: float, history: pd.DataFrame) -> dict[str, object]:
    stock = yf.Ticker(ticker)
    info = stock.info
    dividends = stock.dividends
    latest_dividend = "No dividends" if dividends.empty else float(dividends.iloc[-1])
    return {
        "Ticker": ticker,
        "Long Name": info.get("longName", ""),
        "Short Name": info.get("shortName", ""),
        "Sector": info.get("sector", ""),
        "Industry": info.get("industry", ""),
        "Dividend Yield": info.get("dividendYield", ""),
        "Dividends": latest_dividend,
        "Price to Book(PBR)": info.get("priceToBook", ""),
        "Trailing EPS(EPS)": info.get("trailingEps", ""),
        "Trailing PE(PER)": info.get("trailingPE", ""),
        "Return on Equity(ROE)": info.get("returnOnEquity", ""),
        "Total Cash Per Share": info.get("totalCashPerShare", ""),
        "Revenue Per Share": info.get("revenuePerShare", ""),
        "Beta": info.get("beta", ""),
        "MarketCap": info.get("marketCap", ""),
        "RevenueGrowth": info.get("revenueGrowth", ""),
        "EarningsGrowth": info.get("earningsGrowth", ""),
        "Current Price": info.get("currentPrice", ""),
        "Recent Close": recent_close,
        "History Start": pd.Timestamp(history["Date"].iloc[0]).date().isoformat(),
        "History End": pd.Timestamp(history["Date"].iloc[-1]).date().isoformat(),
        "History Rows": int(len(history)),
    }


def _save_stock_info_csv(path: Path, stock_info: dict[str, object]) -> None:
    pd.DataFrame.from_dict({stock_info["Ticker"]: stock_info}, orient="index").to_csv(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="yfinance 기반 크래프톤 RL 학습/테스트")
    parser.add_argument("--ticker", default="259960.KS", help="Yahoo Finance ticker")
    parser.add_argument("--period", default="10y", help="yfinance period")
    parser.add_argument("--interval", default="1d", help="yfinance interval")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="학습 데이터 비율 (기본 0.8)")
    parser.add_argument("--episodes", type=int, default=120, help="Q-learning episodes")
    parser.add_argument("--lookback", type=int, default=6, help="state lookback window")
    parser.add_argument("--learning-rate", type=float, default=0.18, help="learning rate")
    parser.add_argument("--discount-factor", type=float, default=0.92, help="discount factor")
    parser.add_argument("--epsilon", type=float, default=0.15, help="exploration epsilon")
    parser.add_argument("--trade-penalty-bps", type=int, default=5, help="trade penalty in bps")
    args = parser.parse_args()

    output_dir = ROOT / "artifacts" / "rl" / "yfinance"
    output_dir.mkdir(parents=True, exist_ok=True)

    history = _download_history(args.ticker, args.period, args.interval)
    price_csv_path = output_dir / f"{args.ticker}_{args.period}_{args.interval}_prices.csv"
    _save_price_csv(price_csv_path, args.ticker, history, args.interval)

    recent_close = float(history["Close"].iloc[-1])
    stock_info = _build_stock_info(args.ticker, recent_close, history)
    stock_info_csv_path = output_dir / f"{args.ticker}_{args.period}_{args.interval}_stock_info.csv"
    _save_stock_info_csv(stock_info_csv_path, stock_info)

    dataset = RLDataset(
        ticker=args.ticker,
        closes=[float(value) for value in history["Close"].tolist()],
        timestamps=[_timestamp_label(value, args.interval) for value in history["Date"].tolist()],
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
        "company": stock_info.get("Long Name") or stock_info.get("Short Name") or args.ticker,
        "ticker": args.ticker,
        "source": {
            "api": "yfinance",
            "period": args.period,
            "interval": args.interval,
            "actual_history_start": dataset.timestamps[0],
            "actual_history_end": dataset.timestamps[-1],
        },
        "data_period": {
            "from": dataset.timestamps[0],
            "to": dataset.timestamps[-1],
            "rows": len(dataset.timestamps),
            "price_csv_path": str(price_csv_path),
            "stock_info_csv_path": str(stock_info_csv_path),
        },
        "stock_info": stock_info,
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


if __name__ == "__main__":
    main()
