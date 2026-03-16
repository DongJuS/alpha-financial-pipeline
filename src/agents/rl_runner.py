"""
src/agents/rl_runner.py — Strategy RL StrategyRunner 어댑터

RLPolicyStoreV2 + TabularQTrainerV2를 래핑하여 StrategyRunner 프로토콜을 구현한다.
활성 정책이 있는 티커에 대해 Q-table 추론을 실행하고 PredictionSignal을 반환한다.
활성 정책이 없는 티커는 HOLD 시그널을 생성한다.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading_v2 import TabularQTrainerV2
from src.db.models import PredictionSignal
from src.db.queries import fetch_recent_ohlcv
from src.utils.logging import get_logger

logger = get_logger(__name__)

# 추론에 필요한 최소 종가 데이터 수 (lookback + 여유)
_MIN_CLOSES_FOR_INFERENCE = 10


class RLRunner:
    """
    Strategy RL (Reinforcement Learning) StrategyRunner 구현.

    활성화된 정책이 있는 각 티커에 대해 TabularQTrainerV2.infer_action()을 호출하고,
    BUY/SELL/HOLD/CLOSE → BUY/SELL/HOLD로 매핑하여 PredictionSignal을 반환한다.
    """

    name: str = "RL"

    def __init__(
        self,
        policy_store: RLPolicyStoreV2 | None = None,
        trainer: TabularQTrainerV2 | None = None,
    ) -> None:
        self._store = policy_store or RLPolicyStoreV2()
        self._trainer = trainer or TabularQTrainerV2()

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        """주어진 티커에 대해 RL 추론을 실행합니다."""
        if not tickers:
            return []

        try:
            registry = self._store.load_registry()
        except Exception as e:
            logger.error("RLRunner: 정책 레지스트리 로드 실패: %s", e)
            return []

        active_map = registry.list_active_policies()
        if not active_map:
            logger.info("RLRunner: 활성 정책이 없습니다. 건너뜁니다.")
            return []

        signals: list[PredictionSignal] = []
        for ticker in tickers:
            policy_id = active_map.get(ticker)
            if not policy_id:
                logger.debug("RLRunner: %s에 활성 정책 없음, 건너뜁니다.", ticker)
                continue

            try:
                signal = await self._infer_for_ticker(ticker, policy_id)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.warning("RLRunner: %s 추론 실패: %s", ticker, e)

        logger.info("RLRunner: %d/%d 티커에서 %d 신호 생성", len(signals), len(tickers), len(signals))
        return signals

    async def _infer_for_ticker(
        self,
        ticker: str,
        policy_id: str,
    ) -> PredictionSignal | None:
        """단일 티커에 대해 RL 추론을 실행합니다."""
        # 정책 아티팩트 로드
        artifact = self._store.load_policy(policy_id, ticker)
        if artifact is None:
            logger.warning("RLRunner: 정책 파일 로드 실패: %s/%s", policy_id, ticker)
            return None

        # 최근 OHLCV 데이터 조회
        candles = await fetch_recent_ohlcv(ticker=ticker, days=60)
        if not candles or len(candles) < _MIN_CLOSES_FOR_INFERENCE:
            logger.warning(
                "RLRunner: %s 캔들 데이터 부족 (%d건, 최소 %d건 필요)",
                ticker,
                len(candles) if candles else 0,
                _MIN_CLOSES_FOR_INFERENCE,
            )
            return None

        closes = [float(c["close"]) for c in candles]

        # Q-table 추론
        action, confidence, state, q_values = self._trainer.infer_action(
            artifact,
            closes,
            current_position=0,  # stateless: 매 사이클 새로 시작
        )

        # RL 액션 → 표준 signal 매핑
        signal = self._map_action_to_signal(action)

        return PredictionSignal(
            agent_id=f"rl_agent_{policy_id}",
            llm_model="tabular-q-learning-v2",
            strategy="RL",
            ticker=ticker,
            signal=signal,
            confidence=confidence,
            target_price=None,
            stop_loss=None,
            reasoning_summary=(
                f"[RL] policy={policy_id}, state={state}, action={action}, "
                f"q_values={_format_q_values(q_values)}"
            ),
            trading_date=date.today(),
        )

    @staticmethod
    def _map_action_to_signal(action: str) -> str:
        """RL 4-action을 표준 3-signal로 변환합니다.

        BUY -> BUY, SELL -> SELL, HOLD -> HOLD, CLOSE -> HOLD
        """
        action_upper = action.upper()
        if action_upper == "BUY":
            return "BUY"
        elif action_upper == "SELL":
            return "SELL"
        else:
            return "HOLD"


def _format_q_values(q_values: dict[str, float]) -> str:
    """Q-values를 가독성 높은 문자열로 포맷합니다."""
    return ", ".join(f"{k}={v:.4f}" for k, v in sorted(q_values.items()))
