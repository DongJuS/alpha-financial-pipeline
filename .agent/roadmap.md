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
- [ ] SearXNG 서비스와 검색 요청 계약 정의
- [ ] fetch/render worker 계층 설계
- [ ] ScrapeGraphAI 구조화 출력 포맷 확정
- [ ] Claude CLI 추출 포맷과 citation 규칙 정의
- [ ] 검색 질의/결과/source/extraction 저장 스키마 확정
- [ ] Strategy B와 RL feature용 공통 research contract 정의

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
- [ ] RL dataset builder를 market/research feature 기준으로 확장
- [ ] trading simulator/environment 정의 고도화
- [ ] 정책 레지스트리 조회 API 추가 (REST 엔드포인트)
- [ ] walk-forward / out-of-sample 평가 기준을 DB/API로 노출
- [ ] shadow inference와 paper promotion gate 정교화

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
- [ ] Search 추출 결과를 Strategy B prompt와 RL feature에 연결
- [ ] RL policy inference를 signal 후보로 추가하되 기본값은 shadow 또는 paper-only
- [ ] 대시보드에 검색 출처, RL 평가, 활성 정책 상태 표시
- [ ] 운영 감사와 통합 테스트 체크리스트 반영
- [ ] 공통 `ExperimentTracker`를 Strategy A, B, RL, Search 에이전트에 전부 연동 적용
- [ ] README의 `통합 테스트 진행 중` 문구를 실제 상태에 맞게 갱신

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

## 현재 상태 요약

- 코어 트레이딩 트랙: 구현 완료 및 유지보수 단계
- RL 트레이딩: 최소 runnable lane 구현 완료, 통합 테스트 진행 중
- 검색/스크래핑 스택: 구조 편입 및 설계 단계, 구현은 다음 우선순위
