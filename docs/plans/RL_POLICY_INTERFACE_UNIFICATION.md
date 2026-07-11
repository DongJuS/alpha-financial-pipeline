# RL Policy Interface Unification — 후속 리팩터

> **작성일**: 2026-07-05
> **상태**: 후속 작업 (미착수). 우선순위 낮음 — 현재 알고리즘 3종에서 문자열 분기가 실무적으로 감내 가능.
> **관련 코드**: `src/agents/rl_runner.py`, `src/agents/rl_policy_interface.py`, `src/agents/rl_dreamer.py`, `src/agents/rl_trading_sb3.py`
> **선행 커밋**: `fix(rl): live inference for combined-mode policies` (2026-07-05)

---

## 배경

Combined 모드 (일봉 + 분봉 마스킹) DreamerV3 정책을 라이브에서 돌리기 위해 `RLRunner._infer_for_ticker` 에 두 개의 문자열 분기가 남았다.

**데이터 fetch 분기** (`rl_runner.py`):
```python
needs_intraday = artifact.algorithm == "dreamer_v3"
if needs_intraday:
    candles = await fetch_daily_with_intraday(db_ticker, days=60)
else:
    candles = await fetch_recent_ohlcv(ticker=db_ticker, days=60)
```

**추론 라우팅 분기**:
```python
if artifact.algorithm in ("dqn", "a2c", "ppo") and artifact.model_path:
    ... _infer_sb3 ...
elif artifact.algorithm == "dreamer_v3":
    policy = policy_from_artifact(artifact)
    decision = policy.act(closes, features=features, position=0)
else:
    ... TabularQTrainerV2.infer_action ...
```

두 분기 모두 알고리즘 문자열을 하드코드한다. 새 알고리즘 (예: transformer 기반, LLM-in-loop) 을 추가하려면 두 곳에 손을 대야 한다.

---

## 목표 (미래)

`RLRunner` 는 알고리즘 문자열을 몰라야 한다. 데이터 요구도, 추론 로직도 정책 어댑터가 자기 선언한다.

### 인터페이스 확장 (`rl_policy_interface.py`)

```python
class RLPolicy(Protocol):
    algorithm: str
    data_scope: str          # "daily" | "combined" — Runner 가 fetch 를 결정하는 근거

    def act(
        self,
        closes: Sequence[float],
        *,
        position: int = 0,
        features: Sequence[Sequence[float]] | None = None,
    ) -> PolicyDecision: ...
```

### 어댑터 세 종

- `TabularRLPolicy` — `data_scope = "daily"`, features 무시
- `SB3RLPolicy` (신규) — `data_scope = "daily"`, 내부에서 `SB3Trainer.infer_action` 호출. 지금 `_infer_sb3` 에 있는 로직 이관.
- `DreamerRLPolicy` — `data_scope = "combined"`, features 소비 (없으면 auto-mask 폴백, 이미 구현됨)

### RLRunner 리팩터

```python
policy = policy_from_artifact(artifact)
if policy.data_scope == "combined":
    rows = await fetch_daily_with_intraday(db_ticker, days=60)
    closes = [float(r["close"]) for r in rows]
    features = [intraday_obs_vector(r) for r in rows]
else:
    candles = await fetch_recent_ohlcv(db_ticker, days=60)
    closes = [float(c["close"]) for c in candles]
    features = None
decision = policy.act(closes, features=features, position=0)
```

`RLRunner._infer_sb3` 삭제. 알고리즘 분기 완전 제거.

---

## 왜 지금 안 하나

- 알고리즘 3종 (tabular / SB3 3-flavor / dreamer_v3) 만 있고 근시일 폭발적 확장 계획 없음
- 현재 문자열 분기가 못생겨도 라이브 fidelity 는 이미 옳음 (`fix(rl): live inference for combined-mode policies` 로 달성)
- `policy_from_artifact` 팩토리가 SB3 를 아직 지원 안 함 (`policy_from_artifact` 는 tabular/dreamer 만). SB3 어댑터 추가 + 팩토리 확장 필요
- 우선순위 낮음. 새 알고리즘 도입 트리거 시 함께 진행이 자연스러움

---

## 언제 재검토

다음 트리거 중 하나 발생 시:

1. 4번째 이상 RL 알고리즘 도입 논의 (예: 트랜스포머 기반, offline RL, LLM-in-loop)
2. `data_scope` 옵션이 combined 외에 하나 더 늘어남 (예: "combined_tick" — 분봉 대신 원 틱)
3. RLRunner 내 문자열 분기 유지비용이 실제 버그로 나타남 (예: 새 알고리즘 추가 시 한 곳만 고치고 다른 곳 놓침)

---

## 스코프 및 예상 시간

- `RLPolicy` Protocol 확장 (`data_scope` 필드): S
- `SB3RLPolicy` 어댑터 신설 + `policy_from_artifact` 팩토리 확장: M
- `RLRunner` 리팩터 (`_infer_sb3` 삭제, 통합 경로): S
- 테스트: 신규 SB3 어댑터 + 통합 runner + 라이브 회귀: M
- **합계: 반나절**
