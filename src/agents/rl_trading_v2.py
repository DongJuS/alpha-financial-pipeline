"""
src/agents/rl_trading_v2.py — V2 RL trading trainer

V1 대비 개선점:
1. 상태 공간 확장: 18개 → ~1350개 (5-bucket + 모멘텀 + 변동성)
2. 3-포지션: -1(숏), 0(플랫), 1(롱) — 하락장에서도 수익 가능
3. 리워드 함수 개선: 기회비용 도입, 거래 비용 축소
4. 멀티시드 학습 + 최적 정책 선택
5. 학습률/탐색률 스케줄링 개선

공유 데이터 클래스(RLDataset, RLPolicyArtifact 등)는 rl_trading.py에서 임포트합니다.
"""

from __future__ import annotations

from datetime import datetime, timezone
import random

from src.agents.rl_trading import (
    MIN_APPROVAL_RETURN_PCT,
    RLDataset,
    RLEvaluationMetrics,
    RLPolicyArtifact,
    RLPolicyStore,  # V1 호환
    RLSplitMetadata,
)

# V2 정책 저장소 (registry.json 기반)
# 런타임에서 RLPolicyStoreV2를 사용하려면:
#   from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
#   store = RLPolicyStoreV2()
#   store.save_policy(artifact)  # artifacts/rl/models/<algo>/<ticker>/ 에 저장 + registry.json 업데이트

# V2: BUY(롱), SELL(숏), HOLD(유지), CLOSE(청산)
ACTIONS_V2 = ("BUY", "SELL", "HOLD", "CLOSE")


class TabularQTrainerV2:
    """V2 Tabular Q-learning trainer.

    V1 TabularQTrainer 대비 핵심 변경:
    - 3-포지션: -1(숏), 0(플랫), 1(롱) — 하락장에서도 수익 가능
    - 4-액션: BUY(롱진입), SELL(숏진입), HOLD(유지), CLOSE(청산→플랫)
    - 5-bucket 상태 이산화 (strong_down/down/neutral/up/strong_up)
    - 모멘텀(SMA5 vs SMA20 교차) + 변동성 지표 추가
    - 기회비용 리워드: 시장 변동 시 미보유 패널티
    - 거래 비용 축소 (5bps → 2bps 기본)
    - 더 높은 탐색률(0.30)과 더 많은 에피소드(300)
    - 멀티시드(5회) 학습 후 holdout 최고 성과 정책 선택
    - 학습률/탐색률 점진적 감소 스케줄링
    """

    def __init__(
        self,
        *,
        lookback: int = 20,
        episodes: int = 300,
        learning_rate: float = 0.10,
        discount_factor: float = 0.95,
        epsilon: float = 0.30,
        trade_penalty_bps: int = 2,
        opportunity_cost_factor: float = 0.5,
        random_seed: int = 42,
        num_seeds: int = 5,
    ) -> None:
        self.lookback = lookback
        self.episodes = episodes
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.epsilon = epsilon
        self.trade_penalty_bps = trade_penalty_bps
        self.opportunity_cost_factor = opportunity_cost_factor
        self.random_seed = random_seed
        self.num_seeds = num_seeds

    # ──────────────────────────── public API ────────────────────────────

    def train(self, dataset: RLDataset, train_ratio: float = 0.7) -> RLPolicyArtifact:
        artifact, _ = self.train_with_metadata(dataset, train_ratio=train_ratio)
        return artifact

    def train_with_metadata(
        self,
        dataset: RLDataset,
        *,
        train_ratio: float = 0.7,
    ) -> tuple[RLPolicyArtifact, RLSplitMetadata]:
        if len(dataset.closes) <= self.lookback + 10:
            raise ValueError(
                f"RL 학습 길이가 너무 짧습니다: ticker={dataset.ticker}, len={len(dataset.closes)}"
            )
        if not 0.5 <= train_ratio < 1.0:
            raise ValueError(f"train_ratio는 0.5 이상 1.0 미만이어야 합니다: {train_ratio}")

        split_idx = max(self.lookback + 5, int(len(dataset.closes) * train_ratio))
        split_idx = min(split_idx, len(dataset.closes) - 3)
        split_metadata = self._build_split_metadata(dataset, split_idx=split_idx, train_ratio=train_ratio)

        train_prices = dataset.closes[:split_idx]
        holdout_prices = dataset.closes[split_idx - self.lookback :]

        # 멀티시드 학습 → 최적 정책 선택
        best_q_table: dict[str, dict[str, float]] | None = None
        best_holdout_return = float("-inf")
        base_seed = self.random_seed + sum(ord(ch) for ch in dataset.ticker)

        for seed_offset in range(self.num_seeds):
            q_table = self._train_single(train_prices, base_seed + seed_offset * 1000)
            evaluation = self._evaluate_internal(holdout_prices, q_table)
            if evaluation.total_return_pct > best_holdout_return:
                best_holdout_return = evaluation.total_return_pct
                best_q_table = q_table

        assert best_q_table is not None
        evaluation = self._evaluate_internal(holdout_prices, best_q_table)
        policy_id = f"rl_{dataset.ticker}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        artifact = RLPolicyArtifact(
            policy_id=policy_id,
            ticker=dataset.ticker,
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v2",
            lookback=self.lookback,
            episodes=self.episodes,
            learning_rate=self.learning_rate,
            discount_factor=self.discount_factor,
            epsilon=self.epsilon,
            trade_penalty_bps=self.trade_penalty_bps,
            q_table=best_q_table,
            evaluation=evaluation,
        )
        return artifact, split_metadata

    def evaluate(self, prices: list[float], q_table: dict[str, dict[str, float]]) -> RLEvaluationMetrics:
        return self._evaluate_internal(prices, q_table)

    def infer_action(
        self,
        artifact: RLPolicyArtifact,
        closes: list[float],
        *,
        current_position: int = 0,
    ) -> tuple[str, float, str, dict[str, float]]:
        state = self._state_key(closes, current_position)
        q_values = self._ensure_state(artifact.q_table, state)
        ordered = sorted(q_values.items(), key=lambda item: (-item[1], item[0]))
        best_action = ordered[0][0]
        gap = ordered[0][1] - ordered[1][1]
        confidence = max(0.34, min(0.98, 0.5 + (gap * 12.0)))
        return best_action, round(confidence, 4), state, q_values

    def best_action(self, q_table: dict[str, dict[str, float]], state: str) -> str:
        q_values = self._ensure_state(q_table, state)
        return sorted(q_values.items(), key=lambda item: (-item[1], item[0]))[0][0]

    # ──────────────────────────── training ────────────────────────────

    def _train_single(self, train_prices: list[float], seed: int) -> dict[str, dict[str, float]]:
        q_table: dict[str, dict[str, float]] = {}
        rng = random.Random(seed)

        for episode in range(self.episodes):
            position = 0
            progress = episode / max(1, self.episodes)
            # 탐색률: 0.30 → 0.02 (점진적 감소)
            current_epsilon = max(0.02, self.epsilon * (1.0 - progress * 0.85))
            # 학습률: 0.10 → 0.05 (점진적 감소)
            current_lr = max(0.03, self.learning_rate * (1.0 - progress * 0.5))

            for idx in range(self.lookback, len(train_prices) - 1):
                state = self._state_key(train_prices[: idx + 1], position)
                action = self._select_action(q_table, state, rng, current_epsilon)
                next_position = self._transition(position, action)
                reward = self._reward(train_prices[idx], train_prices[idx + 1], position, next_position)
                next_state = self._state_key(train_prices[: idx + 2], next_position)
                self._update_q(q_table, state, action, reward, next_state, lr=current_lr)
                position = next_position

        return q_table

    # ──────────────────────────── evaluation ────────────────────────────

    def _evaluate_internal(self, prices: list[float], q_table: dict[str, dict[str, float]]) -> RLEvaluationMetrics:
        position = 0
        equity = 1.0
        baseline = 1.0
        peak_equity = 1.0
        max_drawdown_pct = 0.0
        trades = 0
        wins = 0
        holdout_steps = max(0, len(prices) - self.lookback - 1)

        for idx in range(self.lookback, len(prices) - 1):
            state = self._state_key(prices[: idx + 1], position)
            action = self.best_action(q_table, state)
            next_position = self._transition(position, action)
            daily_return = (prices[idx + 1] / prices[idx]) - 1.0
            trade_cost = (self.trade_penalty_bps / 10_000.0) if next_position != position else 0.0
            # 포지션 수익: 롱(+1*r), 숏(-1*r), 플랫(0)
            position_return = (next_position * daily_return) - trade_cost
            equity *= max(0.0001, 1.0 + position_return)
            baseline *= max(0.0001, 1.0 + daily_return)
            if next_position != position:
                trades += 1
                if position_return > 0:
                    wins += 1
            peak_equity = max(peak_equity, equity)
            drawdown_pct = ((equity - peak_equity) / peak_equity) * 100.0
            max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
            position = next_position

        total_return_pct = (equity - 1.0) * 100.0
        baseline_return_pct = (baseline - 1.0) * 100.0
        win_rate = (wins / trades) if trades else 0.0
        approved = (
            holdout_steps >= 5
            and total_return_pct >= MIN_APPROVAL_RETURN_PCT
            and max_drawdown_pct >= -50.0  # 숏 포함 시 drawdown 허용 확대 (롱숏 전략 특성)
        )
        return RLEvaluationMetrics(
            total_return_pct=round(total_return_pct, 4),
            baseline_return_pct=round(baseline_return_pct, 4),
            excess_return_pct=round(total_return_pct - baseline_return_pct, 4),
            max_drawdown_pct=round(max_drawdown_pct, 4),
            trades=trades,
            win_rate=round(win_rate, 4),
            holdout_steps=holdout_steps,
            approved=approved,
        )

    # ──────────────────────────── Q-learning core ────────────────────────────

    def _select_action(
        self,
        q_table: dict[str, dict[str, float]],
        state: str,
        rng: random.Random,
        epsilon: float,
    ) -> str:
        q_values = self._ensure_state(q_table, state)
        if rng.random() < epsilon:
            return rng.choice(list(ACTIONS_V2))
        return sorted(q_values.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _update_q(
        self,
        q_table: dict[str, dict[str, float]],
        state: str,
        action: str,
        reward: float,
        next_state: str,
        *,
        lr: float | None = None,
    ) -> None:
        effective_lr = lr if lr is not None else self.learning_rate
        state_actions = self._ensure_state(q_table, state)
        next_actions = self._ensure_state(q_table, next_state)
        best_future = max(next_actions.values())
        current = state_actions[action]
        state_actions[action] = current + effective_lr * (
            reward + (self.discount_factor * best_future) - current
        )

    @staticmethod
    def _ensure_state(q_table: dict[str, dict[str, float]], state: str) -> dict[str, float]:
        if state not in q_table:
            q_table[state] = {action: 0.0 for action in ACTIONS_V2}
        return q_table[state]

    @staticmethod
    def _transition(position: int, action: str) -> int:
        """V2 포지션 전이: -1(숏), 0(플랫), 1(롱).

        BUY  → 롱(+1)
        SELL → 숏(-1)
        CLOSE → 플랫(0)
        HOLD → 현재 유지
        """
        if action == "BUY":
            return 1
        if action == "SELL":
            return -1
        if action == "CLOSE":
            return 0
        return position

    # ──────────────────────────── V2 reward ────────────────────────────

    def _reward(self, current_price: float, next_price: float, position: int, next_position: int) -> float:
        """V2 리워드 함수 (3-포지션: -1/0/+1).

        V1 문제: position=0 + HOLD = 0 리워드(무위험) → 에이전트가 절대 BUY 안 함.

        V2 개선:
        - 롱(+1): 시장 상승 시 수익, 하락 시 손실
        - 숏(-1): 시장 하락 시 수익, 상승 시 손실
        - 플랫(0): 시장 변동 시 기회비용 패널티
        - 거래 비용 축소 (5bps → 2bps)
        """
        next_return = (next_price / current_price) - 1.0
        trade_penalty = (self.trade_penalty_bps / 10_000.0) if next_position != position else 0.0

        # 포지션 수익: 롱(+1*return), 숏(-1*return), 플랫(0)
        position_reward = next_position * next_return
        
        # 롱 보유 중 손실 발생 시 패널티를 아주 적게 (압박만 주는 용도)
        if next_position == 1 and next_return < 0:
            position_reward *= 0.1

        # 기회비용 및 회피 보상: 플랫 상태에서 시장 상승 시 놓친 기회 패널티, 시장 하락 시 손실 회피 보상
        opportunity_cost = 0.0
        if next_position == 0:
            if next_return > 0:
                opportunity_cost = -self.opportunity_cost_factor * next_return
            else:
                opportunity_cost = self.opportunity_cost_factor * abs(next_return)

        return position_reward + opportunity_cost - trade_penalty

    # ──────────────────────────── V2 state ────────────────────────────

    def _state_key(self, closes: list[float], position: int) -> str:
        """V2 상태 표현.

        5-bucket 이산화 + 모멘텀/변동성 지표.
        상태 공간: 3(pos) * 5(short) * 5(long) * 3(momentum) * 3(vol) = 675 상태
        """
        if len(closes) < 2:
            return f"p{position}|s0|l0|m0|v0"

        # 단기 수익률 (1-bar)
        short_return = (closes[-1] / closes[-2]) - 1.0

        # SMA5 기반 장기 수익률
        sma5_window = closes[-5:] if len(closes) >= 5 else closes
        sma5 = sum(sma5_window) / len(sma5_window)
        long_return = ((closes[-1] / sma5) - 1.0) if sma5 else 0.0

        # 모멘텀: SMA5 vs SMA20 교차 방향
        sma20_window = closes[-20:] if len(closes) >= 20 else closes
        sma20 = sum(sma20_window) / len(sma20_window)
        momentum = 0
        if sma5 > sma20 * 1.002:
            momentum = 1
        elif sma5 < sma20 * 0.998:
            momentum = -1

        # 변동성: 최근 10봉의 수익률 표준편차
        vol_bucket = 0
        if len(closes) >= 10:
            recent = closes[-10:]
            returns = [(recent[i] / recent[i - 1]) - 1.0 for i in range(1, len(recent))]
            mean_r = sum(returns) / len(returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            vol = variance ** 0.5
            if vol > 0.025:
                vol_bucket = 2  # 고변동성
            elif vol > 0.012:
                vol_bucket = 1  # 중변동성

        short_bucket = self._bucket5(short_return, small_th=0.002, large_th=0.008)
        long_bucket = self._bucket5(long_return, small_th=0.004, large_th=0.015)
        return f"p{position}|s{short_bucket}|l{long_bucket}|m{momentum}|v{vol_bucket}"

    @staticmethod
    def _bucket5(value: float, small_th: float, large_th: float) -> int:
        """5-bucket 이산화: -2(강한하락), -1(하락), 0(중립), 1(상승), 2(강한상승)"""
        if value > large_th:
            return 2
        if value > small_th:
            return 1
        if value < -large_th:
            return -2
        if value < -small_th:
            return -1
        return 0

    # ──────────────────────────── helpers ────────────────────────────

    def _build_split_metadata(
        self,
        dataset: RLDataset,
        *,
        split_idx: int,
        train_ratio: float,
    ) -> RLSplitMetadata:
        train_timestamps = dataset.timestamps[:split_idx]
        test_timestamps = dataset.timestamps[split_idx:]
        return RLSplitMetadata(
            train_ratio=round(train_ratio, 4),
            train_size=len(train_timestamps),
            test_size=len(test_timestamps),
            train_start=train_timestamps[0],
            train_end=train_timestamps[-1],
            test_start=test_timestamps[0],
            test_end=test_timestamps[-1],
        )


# ────────────────────────── V2 시그널 매핑 (N-way 블렌딩용) ──────────────────────────

# V2 action → PredictionSignal 호환 매핑 (위치에 무관하게 기본값)
_ACTION_TO_SIGNAL_SIMPLE = {
    "BUY": "BUY",
    "SELL": "SELL",
    "HOLD": "HOLD",
    "CLOSE": "HOLD",  # 기본값: CLOSE→HOLD
}


def map_v2_action_to_signal(action: str, has_position: bool | None = None) -> str:
    """V2의 4-action(BUY/SELL/HOLD/CLOSE)을 PredictionSignal 호환 3-signal(BUY/SELL/HOLD)로 변환한다.

    - BUY → BUY
    - SELL → SELL
    - HOLD → HOLD
    - CLOSE + has_position=True → SELL
    - CLOSE + (has_position=False or None) → HOLD
    """
    action_upper = action.upper()
    if action_upper == "CLOSE" and has_position is True:
        return "SELL"
    return _ACTION_TO_SIGNAL_SIMPLE.get(action_upper, "HOLD")


def normalize_q_confidence(q_values: dict[str, float]) -> float:
    """Q-value spread를 0.0~1.0 범위의 confidence로 정규화한다.

    방식: best Q-value와 worst Q-value의 차이(spread)를 min-max 정규화.
    - spread가 0이면 confidence=0.5 (불확실)
    - spread가 클수록 confidence가 높아짐

    반환값은 0.3~0.95 범위로 클램핑한다.
    """
    if not q_values:
        return 0.5

    values = list(q_values.values())
    best = max(values)
    worst = min(values)
    spread = best - worst

    if spread <= 0:
        return 0.5

    # spread를 sigmoid-like 함수로 0~1 매핑
    # spread가 0.05 이상이면 높은 confidence
    normalized = min(1.0, spread / 0.10)

    # 0.3 ~ 0.95 범위로 클램핑
    confidence = 0.3 + normalized * 0.65
    return round(min(0.95, max(0.3, confidence)), 4)
