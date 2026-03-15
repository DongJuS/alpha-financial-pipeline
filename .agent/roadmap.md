# roadmap.md — 프로젝트 전체 마일스톤

이 파일은 이 저장소의 canonical roadmap입니다.
기존 Strategy A/B 기반 자동 투자 시스템을 유지한 채, RL Trading과 Search/Scraping pipeline을 어떤 순서로 편입할지 정리합니다.

## 기본 전제

- 기존 Strategy A / Strategy B / PortfolioManager / paper-real 구조는 유지합니다.
- RL Trading은 기존 전략을 대체하지 않고 별도 signal lane으로 추가합니다.
- Search/Scraping은 기존 전략을 대체하지 않고 연구와 feature 공급 레이어로 편입합니다.
- 최종 주문 권한은 계속 `PortfolioManagerAgent`에만 있습니다.
- 검색 스택은 `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI -> Claude CLI`를 기준으로 합니다.
- README 상태 표기는 현재 기준 `통합 테스트 진행 중`입니다.

## 5-Agent 의사결정 결과

| Agent | 관점 | 핵심 제안 |
|-------|------|-----------|
| `FastFlowAgent` | 빠른 구조 설계 | 검색 데이터 계약을 먼저 고정하고, RL은 그 계약에 맞춰 병렬 준비 |
| `SlowMeticulousAgent` | 꼼꼼한 검증 | 저장 스키마, 평가 게이트, 감사 로그 없이 다음 단계로 넘기지 않기 |
| `OptimistAgent` | 확장 기회 | 검색 결과를 Strategy B와 RL feature에 함께 공급해 조기 가치 확보 |
| `PessimistAgent` | 실패 가능성 | 검증 없는 웹 데이터와 과적합 정책의 조기 연결을 차단 |
| `DecisionDirectorAgent` | 최종 결정 | Search foundation 먼저, RL은 offline-first로 붙인 뒤 paper gate 이후 승격 |

## 완료된 코어 트랙

### Phase 1 — 인프라 기반 구축
- [x] 프로젝트 구조와 기본 문서 체계 수립
- [x] PostgreSQL / Redis / FastAPI / UI 기동 구조 확보
- [x] 기본 DB 스키마 및 운영 스크립트 구축

### Phase 2 — 코어 에이전트 구현
- [x] CollectorAgent
- [x] PredictorAgent
- [x] PortfolioManagerAgent
- [x] NotifierAgent
- [x] OrchestratorAgent
- [x] 헬스비트 및 운영 상태 기록

### Phase 3 — Strategy A
- [x] predictor 다중 인스턴스 운영
- [x] 토너먼트 스코어링
- [x] winner 기반 시그널 선택

### Phase 4 — Strategy B
- [x] 토론형 합의 구조
- [x] transcript 저장
- [x] confidence / HOLD 규칙 반영

### Phase 5 — 대시보드와 운영 화면
- [x] 핵심 대시보드 UI
- [x] 전략/포트폴리오/설정/모의투자 화면
- [x] 모델 관리와 paper/real 운영 제어

### Phase 6 — 페이퍼 운용과 검증
- [x] 페이퍼 트레이딩 검증 경로
- [x] 운영 감사 / 리스크 검증
- [x] 장외 주문 차단 정책

### Phase 7 — 실거래 준비
- [x] readiness 체크 체계
- [x] real/paper 분리 계좌 구조
- [x] 운영 가이드 및 감사 로그

## 확장 트랙

### Phase 8 — Search/Scraping Foundation

목표:
- `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI -> Claude CLI` 파이프라인을 구조적으로 편입
- 출처 저장, 추출 결과 저장, 재실행 가능성을 확보

작업 항목:
- [x] SearXNG 서비스와 검색 요청 계약 정의
- [x] fetch/render worker 계층 설계
- [x] ScrapeGraphAI 구조화 출력 포맷 확정
- [x] Claude CLI 추출 포맷과 citation 규칙 정의
- [x] 검색 질의/결과/source/extraction 저장 스키마 확정
- [x] Strategy B와 RL feature용 공통 research contract 정의

완료 기준:
- 동일 질의의 검색 결과, 원문 출처, 추출 결과를 각각 조회 가능
- 실패 케이스가 `partial` 또는 `failed` 상태로 구분 기록
- Strategy/RL이 재사용 가능한 JSON contract 확보

### Phase 9 — RL Trading Lane

목표:
- RL을 기존 전략의 대체가 아닌 별도 offline-first lane으로 편입
- 학습, 평가, 정책 저장, 추론, 주문 경계가 분리된 구조 확보

현재 상태:
- [x] 최소 runnable RL lane 구현 (`src/agents/rl_trading.py`)
- [x] tabular Q-learning 기반 `train -> evaluate -> infer` 경로 구현
- [x] `orchestrator --rl` 및 `scripts/run_rl_trading.py` 실행 경로 추가
- [x] `PortfolioManagerAgent`를 통한 `RL` signal source 연결
- [x] `scripts/validate_rl_trading.py`와 `test/test_rl_trading.py`로 자동 검증 추가

다음 작업:
- [x] 정책 레지스트리(PolicyRegistry) 및 RLPolicyStoreV2 구현
- [x] 알고리즘 네임스페이스(tabular/dqn/ppo) 도입 및 기존 아티팩트 마이그레이션
- [x] 승격 게이트 및 자동 정리 규칙 구현
- [x] RL 실험 관리 시스템 구현 (profiles/ + experiments/ 디렉터리, RLExperimentManager)
- [x] RL 하이퍼파라미터 프로파일 기반 재사용 구조 확보
- [x] RL dataset builder를 market/research feature 기준으로 확장 (RLDatasetBuilderV2)
- [x] trading simulator/environment 정의 고도화 (TradingEnv Gymnasium 호환)
- [x] 정책 레지스트리 조회 API 추가 (REST 17개 엔드포인트)
- [x] walk-forward / out-of-sample 평가 기준을 DB/API로 노출 (WalkForwardEvaluator)
- [x] shadow inference와 paper promotion gate 정교화 (ShadowInferenceEngine)

완료 기준:
- 학습 결과가 dataset version, config, artifact hash와 함께 저장
- 승인된 정책과 보류 정책을 구분해 조회 가능
- RL signal의 생성/차단 이유를 run 단위로 추적 가능

### Phase 10 — 확장 통합 운영

목표:
- Search와 RL을 기존 Strategy A/B 위에 레이어로 연결
- A/B/RL/Search 전반의 설정 변경과 성능 관리를 위한 공통 메타 레이어 구축 (GitOps 기반 `config/` 통합)
- 통합 테스트를 거쳐 paper 운영 단계에서만 승격

작업 항목:
- [x] `config/` 기반 공통 메타데이터 실험 추적 구조(GitOps) 확정 및 `ExperimentTracker` 클래스 도입
- [x] Search 추출 결과를 Strategy B prompt와 RL feature에 연결 — `search_bridge.py` + Orchestrator 통합
- [x] RL policy inference를 signal 후보로 추가하되 기본값은 shadow 또는 paper-only — `RLSignalProvider` (RL_SIGNAL_MODE=shadow 기본)
- [x] 대시보드에 검색 출처, RL 평가, 활성 정책 상태 표시 — `IntegrationDashboard.tsx` + `/integration/*` API 4개
- [x] 운영 감사와 통합 테스트 체크리스트 반영 — `IntegrationAuditChecker` 7항목 자동 검증
- [x] 공통 `ExperimentTracker`를 Strategy A, B, RL, Search 에이전트에 전부 연동 적용 — 4개 에이전트 모두 try/except 래핑
- [x] README의 `통합 테스트 진행 중` 문구를 실제 상태에 맞게 갱신 — "Phase 10 확장 통합 완료"로 변경

완료 기준:
- RL/Search 핵심 경로가 paper 환경에서 재현 가능하게 검증됨
- query/job/policy/config 기준으로 회귀 원인 추적 가능
- 공통 `config/experiments`에 A, B, RL, Search의 메타데이터가 단일 스키마로 로깅됨
- 운영 문서와 API 문서가 현재 구현 상태와 일치

## 자동 완료 조건

현재 확장 트랙의 자동 개발 완료 조건은 아래 기준을 통과하는 것입니다.

1. RL trading lane이 실제로 실행된다.
2. `train -> evaluate -> infer -> order route` 자동 테스트가 통과한다.
3. RL이 직접 브로커를 호출하지 않고 `PortfolioManagerAgent`를 통해서만 주문 경로에 들어간다.

### Phase 11 — N-way 블렌딩 + StrategyRunner Registry

목표:
- 기존 elif 체인을 `StrategyRunner` Protocol + Registry 패턴으로 리팩토링
- A/B/RL 3개 전략을 N-way `blend_signals()`로 통합
- 향후 S/L 전략 추가 시 Runner만 구현하면 되는 구조 확보

작업 항목:
- [x] `StrategyRunner` Protocol + `StrategyRegistry` 신설 (`src/agents/strategy_runner.py`)
- [x] N-way `blend_signals()` 일반화 (`src/agents/blending.py`)
- [x] Orchestrator Registry 기반 병렬 실행 리팩토링 + `--strategies` CLI
- [x] RL V2 시그널 매핑 (`map_v2_action_to_signal`, `normalize_q_confidence`)
- [x] shadow gate 기반 인프라 (`predictions.is_shadow` 컬럼, `PredictionSignal.is_shadow` 필드)
- [x] 전략별 가중치 외부화 (`STRATEGY_BLEND_WEIGHTS`)
- [x] DB 스키마 확장 (`blend_meta JSONB`, `strategy CHECK S/L`, `is_shadow`)
- [x] `BlendInput` + `NWayBlendResult` 데이터 클래스
- [x] 통합 테스트 (`test/test_blend_nway.py`)

완료 기준:
- `--strategies A,B,RL` 플래그로 N개 전략 병렬 실행 + 블렌딩 동작
- 기존 단독 모드(`--tournament`, `--consensus`, `--rl`)가 그대로 동작
- shadow 전략 시그널이 DB에 기록되되 blend에는 참여하지 않음

논의 문서: `.agent/discussions/20260314-strategy-ab-rl-extension.md`

### Phase 12 — 전략별 독립 포트폴리오 + 가상 트레이딩

목표:
- 각 전략이 독립적인 포트폴리오를 운용 (블렌딩 → 독립 전환)
- 전략별 real/paper/virtual 3-모드 운용
- KIS API 과거 데이터 수집 → 학습/백테스트 → 가상 트레이딩 → 모의 → 실전 승격 파이프라인

전환 포인트:
- Phase 11의 `StrategyRunner` 인터페이스를 그대로 활용
- Orchestrator에서 blend 대신 각 Runner의 결과를 개별 PortfolioManager에 전달
- 전략 코드 변경 없이 Orchestrator 레벨에서만 전환

전체 매트릭스 (최대 5 × 3 = 15개 독립 포트폴리오):
```
Strategy A  → [real] [paper] [virtual]
Strategy B  → [real] [paper] [virtual]
Strategy RL → [real] [paper] [virtual]
Strategy S  → [real] [paper] [virtual]
Strategy L  → [real] [paper] [virtual]
```

현재 상태:
- [x] DB 격리: `strategy_id` 컬럼 + `COALESCE(strategy_id, '')` 유니크 인덱스
- [x] VirtualBroker: 슬리피지(0~N bps), 부분 체결(50~100%), 체결 지연(0~N초) 시뮬레이션
- [x] 전략 승격 파이프라인: `StrategyPromoter` (virtual→paper→real 평가/실행/DB 기록)
- [x] 합산 리스크 모니터링: `AggregateRiskMonitor` (단일 종목 노출/전략 간 중복도)
- [x] 데이터 파이프라인: Historical OHLCV 벌크 수집 (FinanceDataReader + KIS API)
- [x] Orchestrator `--independent-portfolio` 모드: 전략별 독립 PM 인스턴스 + 합산 리스크 체크 + 승격 알림
- [x] 승격 알림: NotifierAgent `send_promotion_alert()` Telegram 연동
- [x] 승격 CLI: `scripts/promote_strategy.py` (--check, --list, --force)
- [x] 승격 API: 3개 엔드포인트 (promotion-status, promotion-readiness, promote)

다음 작업:
- [ ] Docker 환경 통합 테스트 (pytest)
- [ ] 대시보드에 전략별 모드/성과/승격 상태 UI 추가
- [ ] 전략별 가상 자금 잔고 대시보드 표시
- [ ] 백테스트 시뮬레이션 모드 (과거 데이터 기반 가상 트레이딩)

논의 문서: `.agent/discussions/20260315-independent-portfolio-per-strategy.md`

## 현재 상태 요약

- 코어 트레이딩 트랙: 구현 완료 및 유지보수 단계
- RL 트레이딩: Phase 9 전체 구현 완료 (dataset builder v2, trading env, walk-forward, shadow inference, promotion gate, REST API 17개)
- 검색/스크래핑 스택: 파이프라인 설계 완료, MVP 구현 완료
- N-way 블렌딩: 설계 확정, 구현 완료 (Phase 11)
- 독립 포트폴리오: 핵심 인프라 + Orchestrator 통합 완료 (Phase 12)
