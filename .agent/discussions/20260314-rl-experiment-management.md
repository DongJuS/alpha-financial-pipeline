# Discussion: RL 하이퍼파라미터/실험 추적 및 재현성 관리 구조

status: open
created_at: 2026-03-14
topic_slug: rl-experiment-management
owner: user
related_files:
- src/agents/rl_trading.py
- src/agents/rl_trading_v2.py
- artifacts/rl/active_policies.json
- artifacts/rl/models/README.md
- .agent/roadmap.md
- progress.md

## 1. Question

RL lane에서 하이퍼파라미터, train/test split 비율, feature 버전, seed, reward 설계, 데이터 소스 차이 등 결과값을 바꾸는 요소들을 어떤 구조로 기록/비교/승격 관리해야 하는가?

## 2. Background

현재 RL 구현은 이미 여러 결과 민감 요소를 가지고 있다.

- V1/V2가 분리되어 있고 state_version이 다르다
- `lookback`, `episodes`, `learning_rate`, `discount_factor`, `epsilon`, `trade_penalty_bps` 등 핵심 하이퍼파라미터가 존재한다
- V2에는 `opportunity_cost_factor`, `num_seeds` 같은 추가 요소가 있다
- `train_ratio`, 데이터 길이, 데이터 소스(Yahoo/TrueFX 등), 종목, 평가 구간에 따라 결과가 크게 달라질 수 있다
- 현재 정책 JSON에는 일부 메타데이터만 남고, 어떤 실험 조합이 왜 좋은 결과를 냈는지 체계적으로 비교하기 어렵다

지금 필요한 것은 "좋은 정책 파일 하나 저장"을 넘어서 아래를 가능하게 하는 구조다.

1. 어떤 설정으로 학습했는지 재현 가능해야 한다
2. 실험 간 성능 비교가 가능해야 한다
3. 승인/미승인 정책 승격 기준이 설명 가능해야 한다
4. 나중에 성능 회귀가 생겼을 때 원인을 되짚을 수 있어야 한다

## 3. Constraints

1. **파일 기반 우선** — 오프라인 학습 환경을 고려해 DB 의존 없이도 관리 가능해야 한다
2. **기존 정책 호환** — 이미 저장된 `artifacts/rl/*.json` 및 `active_policies.json`과 충돌 없이 확장해야 한다
3. **표준 라이브러리 + 현재 스택 중심** — 무거운 외부 실험 관리 툴 도입 없이 시작할 수 있어야 한다
4. **승인된 정책과 실험 기록 분리** — 실험 전체와 실제 활성 정책은 구분 관리해야 한다
5. **재현성 우선** — 단순 최고 수익률보다, 어떤 입력과 설정에서 나온 결과인지 추적 가능한 구조가 우선이다

## 4. Options

### Option A: 정책 아티팩트 내부 메타데이터 확장

각 정책 JSON 파일 안에 하이퍼파라미터, split, 데이터 소스, feature 버전, seed 목록을 모두 넣는다.

예시:

```json
{
  "policy_id": "rl_259960.KS_20260314T061942Z",
  "algorithm": "tabular_q_learning",
  "state_version": "qlearn_v2",
  "dataset": {
    "source": "yfinance",
    "range": "10y",
    "train_ratio": 0.7
  },
  "trainer_params": {
    "episodes": 300,
    "learning_rate": 0.1,
    "discount_factor": 0.95,
    "epsilon": 0.3,
    "num_seeds": 5
  }
}
```

장점:
- 구현이 가장 단순하다
- 파일 하나만 있으면 정책 정보를 볼 수 있다

단점:
- 실험 비교와 집계가 어렵다
- 승인 안 된 수많은 실험 기록을 별도로 관리하기 어렵다
- 정책 파일이 곧 실험 로그가 되어 역할이 섞인다

### Option B: 실험 런 디렉토리 + 정책 아티팩트 분리

정책 파일과 별도로, 모든 학습/평가를 `experiments/` 아래 run 단위로 기록한다.

예시:

```text
artifacts/rl/
├── experiments/
│   └── 20260314T061942Z-259960.KS-qlearn_v2/
│       ├── config.json
│       ├── dataset_meta.json
│       ├── metrics.json
│       ├── split.json
│       └── notes.md
├── models/
│   └── tabular/259960.KS/...
└── active_policies.json
```

장점:
- 실험 기록과 승격된 정책을 분리할 수 있다
- 재현성과 비교 가능성이 높다
- 실패 실험도 남겨 회귀 분석에 활용할 수 있다

단점:
- 파일 수가 많아진다
- run과 policy의 연결 규칙을 별도로 정의해야 한다

### Option C: 설정 프로파일 + 결과 레저

사전에 버전 관리되는 프로파일(`profiles/*.json`)을 만들고, 실행 결과만 ledger 파일에 쌓는다.

예시:

```text
artifacts/rl/
├── profiles/
│   ├── tabular_v1_baseline.json
│   └── tabular_v2_momentum.json
├── experiment_ledger.json
└── models/
```

장점:
- 설정 재사용이 쉽다
- 어떤 프로파일이 운영 표준인지 관리하기 좋다

단점:
- ad-hoc 실험 추적이 약하다
- 데이터셋과 실행 환경 차이를 세밀하게 남기기 어렵다

## 5. AI Opinions

### Codex

**Option B를 중심으로 두고, Option C의 "프로파일" 개념을 위에 얹는 구조가 가장 균형이 좋다.**

이유:
- RL은 결과가 설정 조합에 민감하므로, "활성 정책"과 "실험 run"을 분리하지 않으면 나중에 왜 승격됐는지 설명이 안 된다
- 반대로 run마다 모든 값을 수기로 넣으면 관리가 지저분해지므로, 재사용 가능한 baseline profile을 두는 편이 좋다

권장 구조:

```text
artifacts/rl/
├── profiles/
│   ├── tabular_q_v1_baseline.json
│   ├── tabular_q_v2_krafton.json
│   └── tabular_q_v2_fx.json
├── experiments/
│   └── <run_id>/
│       ├── config.json
│       ├── dataset_meta.json
│       ├── split.json
│       ├── metrics.json
│       ├── artifact_link.json
│       └── notes.md
├── models/
│   └── <algorithm>/<ticker>/<policy>.json
└── active_policies.json
```

반드시 기록할 메타데이터:
- `profile_id`
- `algorithm`
- `state_version`
- `feature_version`
- `data_source`
- `dataset_hash`
- `train_ratio`
- `train_start`, `train_end`, `test_start`, `test_end`
- `trainer_params`
- `random_seed` 또는 `seed_list`
- `evaluation_metrics`
- `approved`
- `promoted_to_active_at`

운영 규칙 제안:
- 모든 학습 실행은 먼저 `experiments/<run_id>/`를 만들고 시작한다
- 승인된 경우에만 `models/`와 `active_policies.json` 갱신 대상으로 승격한다
- 정책 파일에는 run_id를 넣고, experiment 쪽에는 artifact path를 넣어 양방향 참조를 만든다

## 6. Interim Conclusion

현재로서는 **Option B(실험 run 추적) + Option C(프로파일 재사용)** 조합이 가장 유력하다.

정리하면:

1. RL 실험 기록은 정책 저장과 분리한다
2. 운영 표준 하이퍼파라미터는 profile로 관리한다
3. 승격된 정책은 기존 `active_policies.json` 흐름과 연결하되, 실험 run_id를 반드시 남긴다
4. 향후 registry가 도입되더라도 run metadata를 잃지 않도록 설계한다

## 7. Final Decision

(논의 후 확정)

## 8. Follow-up Actions

- [ ] `artifacts/rl/profiles/` 디렉토리 표준 설계
- [ ] `artifacts/rl/experiments/` run 디렉토리 규칙 정의
- [ ] RL 실험 메타데이터 JSON 스키마 초안 작성
- [ ] `run_id`, `profile_id`, `dataset_hash`의 생성 규칙 정의
- [ ] `rl_trading_v2.py` 학습 시 실험 기록 생성 포인트 설계
- [ ] 정책 승격 시 experiment ↔ policy 링크 규칙 정의
- [ ] 실험 비교용 요약 인덱스 파일(`experiments/index.json` 등) 필요 여부 검토
- [ ] README 또는 `docs/RL_*` 문서에 운영 절차 반영

## 9. Closure Checklist

- [ ] 구조/장기 방향 변경 사항을 `.agent/roadmap.md`에 반영
- [ ] 이번 세션의 할 일을 `progress.md`에 반영
- [ ] 계속 유지되어야 하는 운영 규칙을 `MEMORY.md`에 반영
- [ ] 필요한 영구 문서 반영 후 이 논의 문서를 삭제
