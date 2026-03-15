# 교차 전략 성능 관리 및 실험 추적 (Experiment Tracking)

본 문서는 Strategy A, Strategy B, RL Trading, 그리고 Search/Scraping 파이프라인 전반의 설정 변경과 성능(Metrics)을 공통된 규격으로 추적하고 비교하기 위한 시스템 디자인 및 운영 가이드를 제공합니다.

MLflow와 같은 무거운 외부 의존성을 배제하고, 파일 기반의 **GitOps 추적 모델**을 채택하여 "[설정값] - [소스코드 커밋] - [실행 결과]"의 강한 결합을 보장합니다.

---

## 1. 아키텍처 및 디렉터리 구조

모든 실험 메타데이터와 활성 설정 파일은 프로젝트 루트의 `config/` 디렉터리 하위에서 집중 관리합니다.

```text
(root)/
├── config/
│   ├── experiments/      # 테스트 중인 실험 메타데이터 (Git 추적 대상)
│   │   ├── strategy_a/   # Strategy A 실험 로그 (.json)
│   │   ├── strategy_b/
│   │   ├── rl/
│   │   └── search/
│   ├── active/           # 운영 환경에서 실제로 로드되는 최종 승격 설정
│   └── base/             # 전역/기본 설정 파일
```

*   **실험 추적 원칙:** 모든 전략/파이프라인 실행 결과는 `config/experiments/{domain}` 하위에 JSON 형태로 기록되어야 하며 누락 없는 Git 추적을 위해 자동으로 `commit_hash`를 포함해야 합니다.
*   **단일 진실 공급원 (Single Source of Truth):** 오케스트레이터를 비롯한 운영 시스템은 오직 `config/active/` 안의 파일만 참조합니다. 따라서 "운영으로의 승격(Promotion)" 행위는 검증된 JSON 파일을 `active/` 디렉터리로 복사/이동하는 것으로 일원화됩니다.

---

## 2. 도메인별 필수 Config 기록 항목 (Mandatory Configs)

각 도메인별로 실험 로그(`config_version` 또는 세부 필드)에 반드시 남겨야 성능 차이를 설명할 수 있는 필수 설정 항목들입니다.

### 2.1 Strategy A (Tournament)
- **사용되는 모델 (LLMs):** Predictor들이 각각 사용하는 모델 목록 (예: `claude-3-opus`, `gpt-4o`)
- **평가 윈도우 (Rolling Window):** 최근 며칠의 정답률을 기반으로 승자를 산출할 것인지 (`strategy_a_rolling_days`)
- **최소 샘플 수:** 승자로 평가되기 위한 최소 예측 건수 가드 (`strategy_a_min_samples`)

### 2.2 Strategy B (Consensus)
- **에이전트 역할 및 모델 할당:** Proposer, Challenger, Synthesizer에 각각 어떤 모델을 할당했는지.
- **최대 라운드 수 및 합의 임계치:** `strategy_b_max_rounds`, `strategy_b_consensus_threshold`
- **프롬프트 버전:** 의사결정에 사용된 시스템 프롬프트의 버전 해시 또는 식별 태그.

### 2.3 RL Trading
- **학습 알고리즘 및 하이퍼파라미터:** `tabular`, `dqn`, `ppo` 구분, 학습률(LR), Discount Factor(Gamma).
- **상태 및 행동 공간 (State/Action Space):** 5-bucket 이산화, 3-포지션 배분 등 피처 구성 로직의 버전.
- **보상 함수 (Reward Function) 설계:** 기회비용 패널티 존재 여부 등 (예: `v2_opportunity_cost`).

### 2.4 Search/Scraping
- **검색 소스 제한:** Reddit, 뉴스 등 검색 출처에 대한 필터/가중치.
- **정형화 스키마 (Extraction Schema):** 응답 포맷을 강제하는 JSON Schema.
- **요약 프롬프트:** Top-N 리서치 요약을 도출하는 지침.

---

## 3. 지표 간 연결 및 통합 스키마 설계

### 3.1 공통 메타데이터 로깅 (ExperimentTracker)
시스템 내장 래퍼인 `src.utils.experiment_tracker.ExperimentTracker`를 통해 아래와 같은 공통 스키마를 강제합니다.

```json
{
  "run_id": "search-20260315-new-schema",
  "domain": "search",
  "config_version": "extractor_v2",
  "status": "testing",
  "commit_hash": "a1b2c3d4",
  "expected_impact": ["strategy_b", "rl"],
  "metrics": {
    "primary": "extraction_success_rate",
    "values": {
      "extraction_success_rate": 0.95,
      "latency_ms": 1200
    }
  }
}
```

### 3.2 선행 지표와 후행 지표의 연결 (Search -> Strategy)
*   `expected_impact` 체계: 파이프라인 상단의 인프라(Search 파트)를 개선할 때, 이 변경이 어느 다운스트림 전략(예: Strategy B의 토론 정확도)에 영향을 미칠 것인지 명시합니다.
*   분석 시, Search `extraction_success_rate`가 증가한 특정 시점(commit) 이후에 과연 Strategy B의 `paper_return_pct`가 함께 상승했는지를 교차 검증하는 데 사용합니다.

---

## 4. UI 반영 및 상태 조회 (Future Scope)

향후 개발될 UI/API의 **실험 관제 파트**는 다음과 같은 규격을 지원해야 합니다.

1.  **조회 경로:**
    *   API 서버는 `config/active/` 디렉터리에 존재하는 도메인별 JSON 파일을 `/portfolio/config/active` 엔드포인트로 서빙합니다.
2.  **UI 대시보드 내 "Experiments" 탭:**
    *   **현재 운영 중인 설정 (Active Config):** 각 전략별로 현재 어떤 설정이 Active 인지 표시.
    *   **테스트 중 내역:** 폴더 상태가 `testing` 이거나 `active/` 로 넘어가지 않은 최신 `experiments/` 내역들을 나열하여, 현재 진행 중인 백테스트/페이퍼 모의투자 최신 지표 비교 노출.
