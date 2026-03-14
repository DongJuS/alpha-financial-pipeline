# Discussion: Strategy A/B + RL 확장 통합 설계

status: open
created_at: 2026-03-14
topic_slug: strategy-ab-rl-extension
owner: user
related_files:
- src/agents/orchestrator.py
- src/agents/blending.py
- src/agents/rl_trading.py
- src/agents/rl_trading_v2.py
- src/agents/portfolio_manager.py
- src/agents/strategy_a_tournament.py
- src/agents/strategy_b_consensus.py
- src/db/models.py

## 1. Question

기존 Strategy A(토너먼트) / B(합의) 2-way 블렌딩 구조에 RL Trading V2 시그널을 3-way로 통합하려면 어떤 변경이 필요하고, 각 변경의 우선순위와 구현 순서는 어떻게 되어야 하는가?

## 2. Background

### 현재 구조

Orchestrator의 `run_cycle`은 `elif` 체인으로 전략을 **상호 배타적**으로 실행한다:

```
if use_blend:       → A + B 동시 실행 → blend_strategy_signals → BLEND 소스
elif use_consensus: → B만 실행
elif use_tournament:→ A만 실행
elif use_rl:        → RL만 실행 → RL 소스
else:               → 단일 predictor
```

이 구조의 한계:
1. **RL은 A/B와 동시에 실행 불가** — `use_rl`과 `use_blend`를 동시에 켤 수 없음
2. **blending.py는 A/B 2-way 전용** — RL 시그널 입력을 받을 파라미터 없음
3. **PredictionSignal.strategy**는 `Literal["A", "B", "RL"]`이지만, BLEND 소스는 DB 제약 우회로 `strategy="A"`에 저장
4. **PaperOrderRequest.signal_source**는 `Literal["A", "B", "BLEND", "RL"]`이지만 `"BLEND_RL"` 같은 3-way 소스 없음

### RL V2 현재 상태

- `rl_trading_v2.py`: TabularQTrainerV2 구현 완료, 5-bucket state + momentum + volatility, 3-position(-1/0/+1), 4-action(BUY/SELL/HOLD/CLOSE)
- 크래프톤(259960.KS) 대상 +47.84% 수익률 달성 (승인 기준 5% 초과)
- `artifacts/rl/models/259960.KS/` 에 정책 아티팩트 저장 중
- 테스트 8개 전부 통과

### 필요한 변경 포인트

| 영역 | 현재 | 목표 |
|------|------|------|
| Orchestrator | elif 체인 (상호배타) | A/B/RL 병렬 실행 + 3-way 병합 |
| blending.py | A/B 2-way only | A/B/RL 3-way 가중 병합 |
| PredictionSignal | strategy Literal["A","B","RL"] | 변경 없음 (RL 입력으로 충분) |
| PaperOrderRequest | signal_source Literal["A","B","BLEND","RL"] | "BLEND_RL" 또는 "BLEND3" 추가 |
| DB predictions 테이블 | strategy CHECK("A","B","RL") | 변경 불필요 (개별 저장) |
| RLPolicyStore | 로컬 JSON (artifacts/rl/ 직접) | artifacts/rl/models/<algorithm>/<ticker>/ 재구성 (문서 3 정안) |
| V2 시그널 매핑 | V2 action(BUY/SELL/HOLD/CLOSE) → ? | PredictionSignal(BUY/SELL/HOLD) 매핑 |

## 3. Constraints

1. **기존 A/B 단독 모드 유지** — `--tournament`, `--consensus`, `--blend`가 기존과 동일하게 동작해야 함
2. **RL은 PortfolioManager를 통해서만 주문** — 직접 브로커 호출 금지 (`tech_stack.md` 규칙)
3. **PredictionSignal의 signal은 BUY/SELL/HOLD 3종** — RL V2의 CLOSE 액션은 매핑 필요
4. **V1 코드(rl_trading.py) 원본 유지** — V2는 별도 파일로 관리
5. **DB 마이그레이션 최소화** — 기존 predictions/orders 테이블 스키마를 가능한 유지
6. **승인된 기술 스택만 사용** — `.agent/tech_stack.md` 범위 내

## 4. Options

### Option A: Orchestrator 분기 확장 (최소 변경)

기존 elif 체인에 `use_blend_rl` 분기를 추가하고, `blend_3way()` 함수를 blending.py에 신설한다.

```python
# orchestrator.py 변경
elif self.use_blend_rl:
    # A, B, RL 병렬 실행
    predictions_a = ...
    predictions_b = ...
    predictions_rl, rl_summaries = await self.rl.run_cycle(cycle_tickers)
    predictions = self._blend_3way(predictions_a, predictions_b, predictions_rl, ratio_b, ratio_rl)
    orders = await self.portfolio.process_predictions(predictions, signal_source_override="BLEND3")
```

장점: 기존 코드 변경 최소, 이해 쉬움
단점: elif 체인 계속 비대, 조합이 늘어날 때마다 분기 추가 필요

### Option B: Strategy Registry 패턴 (중간 리팩토링)

각 전략을 `StrategyRunner` 인터페이스로 추상화하고, Orchestrator는 활성화된 Runner들을 병렬 실행한 뒤 결과를 Blender에 넘긴다.

```python
class StrategyRunner(Protocol):
    async def run(self, tickers: list[str]) -> list[PredictionSignal]: ...

class OrchestratorAgent:
    def __init__(self):
        self.runners: dict[str, StrategyRunner] = {}
        if use_tournament: self.runners["A"] = TournamentRunner(...)
        if use_consensus: self.runners["B"] = ConsensusRunner(...)
        if use_rl: self.runners["RL"] = RLRunner(...)

    async def run_cycle(self, tickers):
        results = await asyncio.gather(*[r.run(tickers) for r in self.runners.values()])
        predictions = self.blender.blend(results, weights)
```

장점: 확장성 우수, 새 전략 추가 시 Runner만 구현
단점: 리팩토링 범위 넓음, 기존 테스트 깨질 수 있음

### Option C: 하이브리드 (elif 유지 + RL 오버레이)

기존 elif 체인은 그대로 두되, RL을 **독립 shadow lane**으로 항상 실행하고, blend 모드일 때만 3-way 결과를 생성한다.

```python
# RL은 항상 shadow로 실행 (비차단)
rl_task = asyncio.create_task(self.rl.run_cycle(cycle_tickers))

# 기존 elif 체인 그대로 실행
if self.use_blend:
    ...
    rl_predictions, rl_summaries = await rl_task
    # shadow 결과를 로깅만 하거나, blend3 플래그가 켜져 있으면 병합
```

장점: 기존 코드 거의 안 건드림, RL 데이터 축적 가능
단점: shadow/active 전환 로직 별도 필요, 복잡도 증가

## 5. AI Opinions

### Claude (구조 설계)

**Option A를 1차로 구현하되, Option B로의 마이그레이션 경로를 열어둘 것을 권장한다.**

이유:
- 현재 전략 수는 A/B/RL 3개뿐이므로 elif 확장의 유지보수 부담이 아직 크지 않다
- Option B의 Registry 패턴은 전략이 4개 이상 될 때 도입해도 늦지 않다
- 우선 동작하는 3-way blend를 확보하고, 운영 데이터로 가중치 튜닝 근거를 마련하는 것이 급선무다
- V2의 CLOSE 액션은 `position=0`이므로 `HOLD`로 매핑하면 PredictionSignal 호환 유지

구현 순서 제안:
1. `blending.py`에 `blend_3way_signals()` 함수 추가
2. Orchestrator에 `use_blend_rl` 분기 추가 (기존 분기 건드리지 않음)
3. V2 action → PredictionSignal 매핑 함수 작성 (`rl_trading_v2.py` 내부)
4. `PaperOrderRequest.signal_source`에 `"BLEND3"` 리터럴 추가
5. 통합 테스트 작성

### Gemini (리스크 관점)

**Option C의 shadow lane 접근을 병행할 것을 권장한다.**

이유:
- RL V2가 실전 검증을 충분히 거치지 않은 상태에서 바로 3-way blend에 넣으면 과적합 정책이 실주문에 영향을 줄 수 있다
- Shadow 모드로 먼저 축적하고, paper 환경에서 A/B 대비 RL 추가 시 성과 개선을 확인한 후 활성화하는 것이 안전하다
- `approved` 상태의 정책만 active blend에 참여하고, 나머지는 shadow 로깅만 하는 게이트가 필요하다

### GPT (실용 관점)

**Option A를 선택하되, 가중치 설정을 DB/환경변수로 외부화할 것을 권장한다.**

이유:
- 3-way blend의 가중치(ratio_a, ratio_b, ratio_rl)를 코드에 하드코딩하면 튜닝할 때마다 배포가 필요하다
- `settings.strategy_blend_ratio`처럼 기존 설정 패턴에 `strategy_rl_blend_ratio`를 추가하면 운영 중 조정 가능하다
- CLOSE → HOLD 매핑은 단순하지만, confidence 전파 방식(RL은 Q-value 기반 vs LLM은 0~1 범위)의 정규화가 중요하다

### Codex (레포 적합성)

**1차 구현은 Option A + shadow gate가 맞지만, 현재 코드 기준으로는 blend 함수와 저장 모델을 먼저 바로잡는 것이 우선이다.**

현재 레포에서 바로 보이는 구현 이슈:
- `blend_strategy_signals()`는 사실상 "2개 입력 + 충돌 시 HOLD" 규칙 엔진이다. 여기에 RL만 얹으면 3-way weighted blend라기보다 예외 케이스가 늘어난 2-way 확장본이 되기 쉽다
- `scripts/db/init_db.py`의 `predictions.strategy` 제약은 아직 `A/B`만 허용하므로, RL 시그널을 장기적으로 같은 히스토리 테이블에 남길지 여부를 먼저 결정해야 shadow 평가도 일관되게 쌓인다

구현 제안:
- `blend_3way_signals()`를 바로 만들기보다, `BlendInput(strategy, signal, confidence, weight)` 리스트를 받아 점수화하는 일반 함수로 바꾸는 편이 이후 확장에 유리하다
- 신호 결정과 confidence 합산을 분리한다. 예를 들어 signal은 `BUY=+1`, `HOLD=0`, `SELL=-1` 점수 합으로 정하고, confidence는 참여 전략의 정규화된 점수로 별도 계산하면 규칙이 덜 흔들린다
- `BLEND3` 같은 소스 문자열을 계속 늘리기보다 주문 소스는 기존 `BLEND`로 유지하고, 어떤 전략이 참여했는지는 메타데이터로 남기는 편이 스키마 churn이 적다
- `CLOSE -> HOLD`는 너무 단순하다. 현재 포지션이 있는 경우에는 "포지션 청산 의도"가 사라지므로, 최소한 long-only 경로에서는 `CLOSE`를 `SELL` 또는 `HOLD`로 포지션 상태에 따라 다르게 매핑하는 편이 맞다

## 6. Interim Conclusion

**Option A(최소 변경) + Gemini의 shadow gate 조건을 결합한다.**

구체적 결정 사항:
1. `blending.py`에 `blend_3way_signals()` 추가 — A/B/RL 각각의 signal/confidence + 가중치 3개를 입력받음
2. Orchestrator에 `--blend-rl` CLI 플래그와 `use_blend_rl` 분기 추가
3. RL V2 action 매핑: `BUY→BUY, SELL→SELL, HOLD→HOLD, CLOSE→HOLD`
4. RL confidence 정규화: Q-value spread를 0~1 범위로 min-max 정규화
5. `PaperOrderRequest.signal_source`에 `"BLEND3"` 추가
6. RL 정책이 `approved=true`일 때만 blend 참여, 아니면 shadow 로깅
7. 가중치는 `settings.strategy_rl_blend_ratio` (기본값 0.2)로 외부화

## 7. Final Decision

(논의 후 확정)

## 8. Follow-up Actions

- [ ] `blending.py`에 `blend_3way_signals()` 함수 구현
- [ ] `orchestrator.py`에 `use_blend_rl` 분기 및 CLI 플래그 추가
- [ ] `rl_trading_v2.py`에 `map_v2_action_to_signal()` 매핑 함수 추가
- [ ] `rl_trading_v2.py`에 Q-value → confidence 정규화 로직 추가
- [ ] `src/db/models.py` PaperOrderRequest.signal_source에 `"BLEND3"` 추가
- [ ] `src/utils/config.py` settings에 `strategy_rl_blend_ratio` 추가
- [ ] shadow 로깅 테이블/경로 설계 (predictions 테이블에 `is_shadow` 컬럼 또는 별도 테이블)
- [ ] 통합 테스트: 3-way blend가 기존 2-way와 호환되는지 검증
- [ ] 통합 테스트: RL 정책 미승인 시 blend에서 제외되는지 검증

## 9. Closure Checklist

- [ ] 구조/장기 방향 변경 사항을 `.agent/roadmap.md`에 반영
- [ ] 이번 세션의 할 일을 `progress.md`에 반영
- [ ] 계속 유지되어야 하는 운영 규칙을 `MEMORY.md`에 반영
- [ ] 필요한 영구 문서 반영 후 이 논의 문서를 삭제
