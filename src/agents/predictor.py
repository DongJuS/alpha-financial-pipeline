"""
src/agents/predictor.py — PredictorAgent MVP (Claude 단일 인스턴스 + 규칙 피드백)
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, PredictionSignal
from src.db.queries import (
    fetch_recent_ohlcv,
    get_position,
    insert_heartbeat,
    insert_prediction,
    list_tickers,
    upsert_tournament_score,
)
from src.llm.claude_client import ClaudeClient
from src.llm.gemini_client import GeminiClient
from src.llm.gpt_client import GPTClient
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import TOPIC_SIGNALS, publish_message, set_heartbeat

setup_logging()
logger = get_logger(__name__)


class PredictorAgent:
    def __init__(
        self,
        agent_id: str = "predictor_1",
        strategy: str = "A",
        llm_model: str = "claude-3-5-sonnet-latest",
        persona: str = "MVP Claude 단일 인스턴스",
    ) -> None:
        self.agent_id = agent_id
        self.strategy = strategy
        self.llm_model = llm_model
        self.persona = persona
        self.claude = ClaudeClient(model=llm_model if "claude" in llm_model.lower() else "claude-3-5-sonnet-latest")
        self.gpt = GPTClient(model=llm_model if "gpt" in llm_model.lower() else "gpt-4o-mini")
        self.gemini = GeminiClient(model=llm_model if "gemini" in llm_model.lower() else "gemini-1.5-pro")
        # 에이전트별 temperature 다양성 (동일 데이터에서 다른 응답 유도)
        self._temperature = self._compute_temperature(agent_id)

    @staticmethod
    def _compute_temperature(agent_id: str) -> float:
        """에이전트 ID 기준으로 temperature를 분산시켜 예측 다양성을 확보합니다."""
        temp_map = {
            "predictor_1": 0.3,
            "predictor_2": 0.5,
            "predictor_3": 0.7,
            "predictor_4": 0.6,
            "predictor_5": 0.4,
        }
        return temp_map.get(agent_id, 0.5)

    def _provider_name(self) -> str:
        model = self.llm_model.lower()
        if "gpt" in model:
            return "gpt"
        if "gemini" in model:
            return "gemini"
        return "claude"

    def _provider_order(self) -> list[str]:
        primary = self._provider_name()
        rest = [p for p in ["claude", "gpt", "gemini"] if p != primary]
        return [primary, *rest]

    async def _llm_signal(self, ticker: str, candles: list[dict], position: dict | None = None) -> dict[str, Any]:
        compact = [
            {
                "ts": str(c.get("timestamp_kst") or c.get("traded_at", "")),
                "o": int(c["open"]),
                "h": int(c["high"]),
                "l": int(c["low"]),
                "c": int(c["close"]),
                "v": int(c["volume"]),
            }
            for c in candles[:20]
        ]

        # 보유 포지션 캐텍스트
        position_context = ""
        if position and int(position.get("quantity", 0)) > 0:
            avg_price = int(position.get("avg_price", 0))
            qty = int(position["quantity"])
            current_price = int(candles[0]["close"]) if candles else 0
            pnl_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            position_context = f"""

현재 보유 포지션:
  - 수량: {qty}주
  - 평균 매수가: {avg_price:,}원
  - 현재가: {current_price:,}원
  - 평가 손익률: {pnl_pct:+.2f}%
  - 매도를 고려해야 할 상황이면 SELL을 권고해라 (익절: +5% 이상, 손절: -3% 이하 권장)
"""
        else:
            position_context = "\n\n현재 보유 포지션: 없음 (매수 가능 상태)\n"

        prompt = f"""
너는 한국주식 단기 예측 분석가다.
현재 페르소나: {self.persona}
티커: {ticker}
최근 데이터(최신순): {json.dumps(compact, ensure_ascii=False)}
{position_context}
아래 JSON 형식으로만 답해라:
{{
  "signal": "BUY|SELL|HOLD",
  "confidence": 0.0~1.0,
  "target_price": 정수 또는 null,
  "stop_loss": 정수 또는 null,
  "reasoning_summary": "한 줄 요약"
}}
"""
        attempted_providers: list[str] = []
        temp = self._temperature
        for provider in self._provider_order():
            attempted_providers.append(provider)
            try:
                if provider == "gpt" and self.gpt.is_configured:
                    raw = await self.gpt.ask_json(prompt, temperature=temp)
                elif provider == "gemini" and self.gemini.is_configured:
                    raw = await self.gemini.ask_json(prompt, temperature=temp)
                elif provider == "claude" and self.claude.is_configured:
                    raw = await self.claude.ask_json(prompt, temperature=temp)
                else:
                    continue

                signal = str(raw.get("signal", "HOLD")).upper()
                if signal not in {"BUY", "SELL", "HOLD"}:
                    signal = "HOLD"
                confidence = raw.get("confidence")
                return {
                    "signal": signal,
                    "confidence": float(confidence) if confidence is not None else 0.5,
                    "target_price": raw.get("target_price"),
                    "stop_loss": raw.get("stop_loss"),
                    "reasoning_summary": raw.get("reasoning_summary") or "LLM reasoning omitted",
                }
            except Exception as e:
                message = str(e)
                if "일일 사용 한도" in message:
                    logger.warning("%s 신호 생성 스킵 [%s]: %s", provider, ticker, message)
                elif provider == "gemini" and (
                    "Gemini 인증이 불가해 비활성화합니다" in message
                    or "Gemini quota exhausted." in message
                ):
                    logger.warning("%s 신호 생성 스킵 [%s]: %s", provider, ticker, message)
                else:
                    logger.error(
                        "%s 신호 생성 실패 [%s]: %s",
                        provider, ticker, e,
                        exc_info=True,
                    )

        raise RuntimeError(
            f"사용 가능한 LLM provider가 없어 예측을 생성하지 못했습니다. providers={attempted_providers}, ticker={ticker}"
        )

    async def run_once(self, tickers: list[str] | None = None, limit: int = 10) -> list[PredictionSignal]:
        if tickers is None:
            ticker_rows = await list_tickers(limit=limit)
            tickers = [r["ticker"] for r in ticker_rows]

        # ── 1단계: 데이터 일괄 조회 (병렬) ──
        candle_tasks = [fetch_recent_ohlcv(t, days=30) for t in tickers]
        position_tasks = [get_position(t, account_scope="paper") for t in tickers]
        all_candles = await asyncio.gather(*candle_tasks, return_exceptions=True)
        all_positions = await asyncio.gather(*position_tasks, return_exceptions=True)

        # ── 2단계: LLM 추론 (병렬, 동시 실행 수 제한) ──
        sem = asyncio.Semaphore(3)  # LLM 동시 호출 제한

        async def _predict_one(
            ticker: str, candles: list, position: dict | None,
        ) -> PredictionSignal | None:
            async with sem:
                try:
                    llm_output = await self._llm_signal(
                        ticker=ticker, candles=candles, position=position,
                    )
                except Exception as e:
                    logger.error(
                        "%s 예측 실패 [%s]: %s",
                        self.agent_id, ticker, e,
                        exc_info=True,
                    )
                    # 실패 레코드도 DB에 기록하여 추적 가능하게 함
                    try:
                        await insert_prediction(PredictionSignal(
                            agent_id=self.agent_id,
                            llm_model=self.llm_model,
                            strategy=self.strategy,
                            ticker=ticker,
                            signal="HOLD",
                            confidence=0.0,
                            reasoning_summary=f"[ERROR] 예측 실패: {str(e)[:200]}",
                            trading_date=date.today(),
                        ))
                    except Exception:
                        logger.error("예측 실패 레코드 DB 저장도 실패 [%s]", ticker, exc_info=True)
                    return None
                return PredictionSignal(
                    agent_id=self.agent_id,
                    llm_model=self.llm_model,
                    strategy=self.strategy,
                    ticker=ticker,
                    signal=llm_output["signal"],
                    confidence=llm_output.get("confidence"),
                    target_price=llm_output.get("target_price"),
                    stop_loss=llm_output.get("stop_loss"),
                    reasoning_summary=llm_output.get("reasoning_summary"),
                    trading_date=date.today(),
                )

        prediction_tasks = []
        for idx, ticker in enumerate(tickers):
            candles = all_candles[idx] if not isinstance(all_candles[idx], Exception) else []
            position = all_positions[idx] if not isinstance(all_positions[idx], Exception) else None
            prediction_tasks.append(_predict_one(ticker, candles, position))

        predictions = await asyncio.gather(*prediction_tasks)

        # ── 3단계: DB 저장 + 결과 수집 ──
        results: list[PredictionSignal] = []
        failed_tickers: list[str] = []
        for idx, pred in enumerate(predictions):
            if pred is None:
                failed_tickers.append(tickers[idx])
                continue
            await insert_prediction(pred)
            results.append(pred)

        if self.strategy == "A":
            await upsert_tournament_score(
                agent_id=self.agent_id,
                llm_model=self.llm_model,
                persona=self.persona,
                trading_date=date.today(),
                correct=0,
                total=0,
                is_winner=True,
            )

        await publish_message(
            TOPIC_SIGNALS,
            json.dumps(
                {
                    "type": "signals_ready",
                    "agent_id": self.agent_id,
                    "strategy": self.strategy,
                    "count": len(results),
                    "failed_tickers": failed_tickers,
                    "tickers": [s.ticker for s in results],
                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                },
                ensure_ascii=False,
            ),
        )

        heartbeat_status = "healthy"
        if failed_tickers and results:
            heartbeat_status = "degraded"
            logger.warning(
                "%s 부분 실패: 성공 %d / 실패 %d — %s",
                self.agent_id, len(results), len(failed_tickers), failed_tickers,
            )
        elif failed_tickers and not results:
            heartbeat_status = "error"
            logger.error(
                "%s 전체 실패: %d종목 전부 예측 불가 — LLM 프로바이더 설정을 확인하세요",
                self.agent_id, len(failed_tickers),
            )

        await set_heartbeat(self.agent_id)
        await insert_heartbeat(
            AgentHeartbeatRecord(
                agent_id=self.agent_id,
                status=heartbeat_status,
                last_action=f"예측 완료 ({len(results)}종목, 실패 {len(failed_tickers)}종목)",
                metrics={
                    "predictions": len(results),
                    "failed_tickers": len(failed_tickers),
                    "strategy": self.strategy,
                },
            )
        )
        logger.info("PredictorAgent 실행 완료: %d종목", len(results))
        return results


async def _main_async(args: argparse.Namespace) -> None:
    agent = PredictorAgent(
        agent_id=args.agent_id,
        strategy=args.strategy,
        llm_model=args.model,
    )
    tickers = args.tickers.split(",") if args.tickers else None
    await agent.run_once(tickers=tickers, limit=args.limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="PredictorAgent MVP")
    parser.add_argument("--agent-id", default="predictor_1")
    parser.add_argument("--strategy", default="A", choices=["A", "B"])
    parser.add_argument("--model", default="claude-3-5-sonnet-latest")
    parser.add_argument("--tickers", default="", help="쌍표 구분 티커 목록")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
