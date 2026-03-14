# Discussion: A/B/RL/Search 전반의 설정 변경과 성능 영향 관리 구조

status: resolved
created_at: 2026-03-14
topic_slug: cross-strategy-performance-management
owner: user
related_files:
- src/agents/orchestrator.py
- src/agents/strategy_a_tournament.py
- src/agents/strategy_b_consensus.py
- src/agents/rl_trading.py
- src/agents/rl_trading_v2.py
- docs/SEARCH_PIPELINE.md
- docs/SEARCH_STORAGE.md
- .agent/roadmap.md

## 1. Question

RL뿐 아니라 Strategy A, Strategy B, Search/Scraping pipeline까지 포함해, 성능에 영향을 주는 설정 변경과 그 결과를 어떤 공통 구조로 기록/비교/승격 관리해야 하는가?

## 2. Background

현재 시스템에는 RL 외에도 결과가 설정에 따라 크게 달라질 수 있는 영역이 많다.

예시:
- Strategy A: predictor 조합, 토너먼트 rolling window, 최소 샘플 수, winner selection 규칙
- Strategy B: proposer/challenger/synthesizer 모델 구성, consensus threshold, round 수, prompt 변화
- RL: 하이퍼파라미터, reward 설계, split, feature 구성, 승인 게이트
- Search/Scraping: query template, source selection 기준, fetch/render 정책, extraction schema, top-N reasoning 규칙

문제는 각 영역이 따로 발전하면 아래 문제가 생긴다는 점이다.

1. 어떤 설정 변경이 성능 개선을 만들었는지 비교하기 어렵다
2. 운영에 반영된 설정과 실험 중인 설정을 구분하기 어렵다
3. Search 결과 품질과 전략 성과의 연결 고리를 남기기 어렵다
4. 시간이 지나면 왜 현재 설정이 표준이 되었는지 설명하기 어려워진다

즉, RL 전용 실험 관리와 별도로 시스템 전반의 "설정 변경 이력 + 성능 결과 + 승격 기준"을 다루는 공통 논의가 필요하다.

## 3. Constraints

1. **도메인별 특성 유지** — A/B/RL/Search는 성능 지표가 완전히 같지 않으므로, 완전 단일 스키마 강제는 피해야 한다
2. **공통 메타데이터는 필요** — 누가, 언제, 무엇을, 왜 바꿨는지는 공통으로 남아야 한다
3. **운영값과 실험값 분리** — 현재 활성 설정과 테스트 중 설정이 섞이면 안 된다
4. **문서/코드/실행 결과 연결** — discussion 문서, 실제 설정 파일, 실행 결과를 추적 가능해야 한다
5. **과도한 플랫폼화 금지** — 지금 단계에서 MLflow급 대규모 시스템은 과할 수 있다

## 4. Options

### Option A: 영역별 개별 관리

각 도메인이 자기 방식으로 설정과 결과를 관리한다.

- A/B: 코드 + 설정 DB + 테스트
- RL: 아티팩트/실험 파일
- Search: 쿼리/추출/리서치 결과 테이블

장점:
- 구현이 빠르다
- 각 영역 특성에 맞게 유연하게 관리 가능하다

단점:
- 시스템 전체 관점의 비교와 감사가 어렵다
- 변경 이력이 흩어진다

### Option B: 공통 Experiment/Promotion 메타 레이어

도메인별 실행은 그대로 두되, 그 위에 공통 메타데이터 구조를 둔다.

예시 공통 필드:
- `domain`: strategy_a / strategy_b / rl / search
- `config_version`
- `run_id`
- `metrics`
- `status`: draft / testing / approved / active / retired
- `changed_by`
- `discussion_doc`
- `promoted_at`

장점:
- 도메인별 자율성을 유지하면서도 공통 비교와 감사가 가능하다
- 운영 승격 절차를 통일하기 좋다

단점:
- 메타 스키마와 도메인 스키마를 모두 관리해야 한다

### Option C: 완전 통합 Config Registry

모든 전략과 검색 파이프라인 설정을 하나의 중앙 registry에서 버전 관리하고, 실행도 그 registry를 기준으로만 하게 한다.

장점:
- 중앙 통제가 강하다
- 어떤 설정이 운영 중인지 명확하다

단점:
- 초기 비용이 크다
- 각 도메인의 세부 속성을 담기 위해 registry가 지나치게 복잡해질 수 있다

## 5. AI Opinions

### Codex

**Option B가 가장 현실적이다. 각 도메인의 실행/저장 구조는 유지하되, 공통 "실험-검증-승격" 메타 레이어를 하나 두는 편이 좋다.**

왜냐하면:
- RL과 Search는 파일/테이블 중심 구조가 필요하고, A/B는 오케스트레이션/프롬프트/설정 조합이 더 중요해서 저장 구조를 완전히 통합하기 어렵다
- 하지만 운영 측면에서는 "어떤 변경이 언제 들어갔고, 어떤 지표가 개선됐으며, 지금 active인 설정이 무엇인가"는 공통으로 보여야 한다

권장 구조:

```text
config/
├── experiments/
│   ├── strategy_a/
│   ├── strategy_b/
│   ├── rl/
│   └── search/
├── active/
└── base/
```

또는 파일 시스템이 아니라도 아래 개념은 공통으로 둔다.

공통 메타 레코드 예시:

```json
{
  "run_id": "strategy_b-20260314-consensus-v3",
  "domain": "strategy_b",
  "config_version": "consensus_v3",
  "status": "testing",
  "discussion_doc": ".agent/discussions/20260314-cross-strategy-performance-management.md",
  "metrics": {
    "primary": "consensus_rate",
    "values": {
      "consensus_rate": 0.61,
      "hold_rate": 0.22,
      "paper_return_pct": 4.1
    }
  }
}
```

도메인별 필수 관리 대상:
- Strategy A: runner 조합, scoring rule, evaluation window, winner tie-break
- Strategy B: prompt version, role-model mapping, rounds, threshold, HOLD rule
- RL: profile, dataset, split, reward, hyperparameters, approval gate
- Search: query template, source filter, extraction schema, citation policy, freshness window

추가 제안:
- "실험 메타데이터"와 "실제 런타임 설정"을 분리한다
- 운영 반영은 `approved -> active` 상태 전환으로만 하게 한다
- discussion 문서에서 결정된 변경은 반드시 `config_version` 또는 `profile_id`로 남긴다
- 도메인별 성능 지표는 다르더라도, `primary_metric`, `secondary_metrics`, `risk_metrics` 3계층으로 묶으면 비교가 쉬워진다

### Antigravity

Codex의 핵심 제안인 **Option B(공통 메타 레이어 도입)**에 전적으로 동의합니다. 이는 현재 프로젝트 단계에서 도메인별 자율성(유연성)과 시스템 전체의 통제력(표준화)을 모두 확보할 수 있는 가장 균형 잡힌 접근입니다.

이를 실현하고 안착시키기 위해 다음과 같은 실무적, 구조적 관점의 보완 의견을 덧붙입니다.

**1. 경량화된 기록과 GitOps 기반의 추적 (Traceability)**
MLflow 같은 무거운 플랫폼을 지양하는 제약 조건을 만족하려면, 실험 메타데이터를 파일(주로 JSON/YAML)로 저장하고 이를 Git으로 관리하는 것이 최적입니다.
- 메타데이터 필수 필드에 `commit_hash` (또는 브랜치명)를 추가하여 **[설정값] - [당시의 소스코드] - [실행 결과]** 간의 완벽한 추적성을 보장해야 합니다.
- 이렇게 하면 특정 시점의 성능이 왜 나왔는지 코드로 돌아가 분석하기가 매우 쉬워집니다.

**2. 지표의 계층화 및 표준 규격화 (Metrics Standardization)**
Codex의 3계층(primary/secondary/risk) 지표 제안은 훌륭합니다. 한 걸음 더 나아가, 서로 다른 도메인이라도 최종적으로는 **공통된 재무적/비즈니스적 지표**로 평가될 수 있는 연결고리가 필요합니다.
- 예를 들어, Search 파이프라인의 1차 지표는 '정보 추출 성공률'이겠지만, 이 변경이 어떤 Strategy의 '수익률(paper_return_pct)' 개선에 기여할 것으로 기대하는지 나타내는 `expected_impact` 같은 필드가 있으면 좋습니다. 이를 통해 기반 시스템(Search)의 개선이 실제 트레이딩 성과로 직결되는지 추적할 수 있습니다.

**3. 운영(Active) 설정의 단일 진실 공급원 (Single Source of Truth) 강제**
실험값과 운영값이 섞이는 것을 원천 차단하기 위해, 시스템 실행부(Orchestrator 등)는 반드시 고정된 경로(예: `config/active/` 또는 `.env.production` 등)의 설정 파일만 읽도록 구조화하는 것을 권장합니다.
- 즉, '승격(Promotion)' 행위 자체를 **"해당 실험용 설정 파일을 `active` 디렉토리로 복사/병합하는과정"**으로 명확히 정의하는 것입니다. 단순히 JSON 데이터 내의 `status: active`라는 메타데이터 텍스트 변경만으로는 실제 시스템 구동 상태를 100% 보장하기 어렵습니다.

**4. 최소한의 공통 로깅 인터페이스 제공 (Action Item)**
각 도메인(A, B, RL, Search) 논리가 각자 메타데이터 JSON을 생성하게 두면 필연적으로 스니펫 파편화가 발생합니다.
따라서 `src/utils/experiment_tracker.py`와 같은 초경량 공통 헬퍼 클래스를 하나 만들어, 모든 도메인은 이 클래스의 `log_experiment(...)` 메서드를 통해서만 결과를 기록하도록 초기 통제선을 구축하는 것을 첫 번째 Follow-up Action으로 제안합니다.

**확장 제안된 공통 메타 레코드 스키마 예시:**
```json
{
  "run_id": "search-20260314-new-schema-v2",
  "domain": "search",
  "config_version": "extractor_v2",
  "status": "testing",
  "commit_hash": "a1b2c3d4",
  "discussion_doc": ".agent/discussions/20260314-cross-strategy-performance-management.md",
  "expected_impact": ["strategy_b"], 
  "metrics": {
    "primary": "extraction_success_rate",
    "values": {
      "extraction_success_rate": 0.95,
      "latency_ms": 1200,
      "api_cost": 0.05
    }
  }
}
```

## 6. Interim Conclusion

현재로서는 **Option B(공통 메타 레이어)** 가 가장 적절하다.

핵심 방향:

1. 도메인별 저장 방식은 유지한다
2. 대신 실험/검증/승격의 공통 메타 구조를 만든다
3. discussion 문서, 설정 버전, 실행 결과, active 상태를 서로 연결한다
4. 나중에 대시보드나 API에서 "현재 active 설정"과 "최근 테스트 결과"를 조회할 수 있게 설계한다

## 7. Final Decision

**결론: Option B (공통 메타 레이어 도입) + 최상위 `config/` 디렉터리 통폐합(대안 2) 구조 채택**

AI 에이전트(Codex, Antigravity)의 제안과 사용자의 검토를 종합하여, 아래와 같은 구조를 최종 통합 방향으로 확정한다.

**결정 사항 1: 디렉터리 구조 통폐합 (`config/` 하위)**
실험 메타데이터가 `.gitignore` 설정에 막혀 추적성을 잃는 문제를 방지하고, 직관적인 승격 파이프라인을 구축하기 위해 프로젝트 루트 하단의 `config/` 폴더를 기준으로 메타 레이어 구조를 신설한다.
```text
(root)/
├── config/
│   ├── experiments/  <- 테스트 중인 실험 메타데이터와 설정 저장 (Git 추적 대상)
│   │   ├── strategy_a/
│   │   ├── rl/
│   │   └── search/ ...
│   ├── active/       <- 운영 서버가 바라보는 파일들로, 최종 승격된 설정만 존재
│   └── base/         <- 공통으로 쓰이는 베이스 설정값
```

**결정 사항 2: GitOps 기반 추적 (Traceability)**
무거운 MLOps 플랫폼(예: MLflow) 대신, `config/experiments/` 하위의 JSON/YAML 메타데이터 파일에 `commit_hash`를 필수로 기록하여 버전 관리한다. 이로써 **[설정값] - [당시의 소스코드] - [실행 결과]** 간의 완벽한 추적성을 보장한다.

**결정 사항 3: 운영(Active) 설정의 단일 진실 공급원 (Single Source of Truth) 강제**
운영 상태로의 '승격(Promotion)' 행위는 파일 내 `status: active` 텍스트 수정이 아니라, **"검증이 완료된 실험 설정 파일을 `config/active/` 디렉터리로 복사하는 행위"** 자체로 정의한다. 운영 시스템(오케스트레이터 등)은 오직 `config/active/` 안의 파일들만 읽도록 통제한다.

**결정 사항 4: 지표의 계층화 및 표준화**
도메인별 특화 지표(예: 검색 추출 성공률) 외에도, 해당 실험이 전체 시스템 수익 등 최종 목표에 어떻게 기여할 것인지를 나타내는 `expected_impact` 메타 필드를 필수로 포함하여 비교 가능성을 확보한다.

**결정 사항 5: 공통 메타 로깅 인터페이스 구축 (Action Item 시작점)**
도메인마다 각자의 방식으로 JSON을 생성하지 않도록, `src/utils/experiment_tracker.py`와 같은 초경량 공통 헬퍼 클래스를 가장 먼저 구축해 통제선을 마련한다.

## 8. Follow-up Actions

- [x] 공통 experiment metadata 스키마 초안 작성
- [ ] domain별 필수 config 항목 목록 정리
- [x] `status` 전이 규칙(draft/testing/approved/active/retired) 정의
- [x] discussion 문서와 config version 연결 규칙 정의
- [ ] active 설정 조회 경로(DB/API/파일) 후보 정리
- [ ] Search 품질 지표와 Strategy 성과 지표 연결 방식 검토
- [ ] 향후 UI에 노출할 운영/실험 상태 파트 정의

## 9. Closure Checklist

- [x] 구조/장기 방향 변경 사항을 `.agent/roadmap.md`에 반영
- [x] 이번 세션의 할 일을 `progress.md`에 반영
- [x] 계속 유지되어야 하는 운영 규칙을 `MEMORY.md`에 반영
- [ ] 필요한 영구 문서 반영 후 이 논의 문서를 삭제
