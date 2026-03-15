# 🧠 MEMORY.md — 기술적 결정 및 문제 해결 누적 기록

> 이 파일은 에이전트의 장기 기억입니다.
> 세션이 새로 시작되어도 같은 실수를 반복하지 않기 위해 여기에 기록합니다.

---

## 📌 기술적 결정 사항

### 2026-03-12 — 페이퍼 트레이딩 기본값 설정
- **결정:** `KIS_IS_PAPER_TRADING=true`를 기본값으로 설정. 실거래는 명시적 플래그 변경 + 대시보드 확인 단계 필요.
- **이유:** 개발/테스트 중 실수로 실제 자금이 움직이는 것을 방지. 안전이 최우선.

### 2026-03-12 — LangGraph 오케스트레이션 채택
- **결정:** OrchestratorAgent에 LangGraph + PostgreSQL AsyncPostgresSaver 사용.
- **이유:** 내장 상태 영속화, 재시도 로직, Claude Agent SDK 통합. 워크플로우 상태 기계를 직접 구현하는 것보다 효율적.

### 2026-03-12 — FinanceDataReader 주 데이터 소스 채택
- **결정:** KRX EOD 데이터는 `FinanceDataReader (fdr)`를 주 소스, KRX 직접 API를 보조로 사용.
- **이유:** fdr은 활발히 유지되고, API 키 없이 무료로 KRX 데이터에 접근 가능. KIS WebSocket은 장중 실시간 틱만 담당.

### 2026-03-12 — 3종 LLM 멀티 운용 결정
- **결정:** Claude CLI, OpenAI GPT-4o (OAuth), Gemini CLI를 동시에 운용.
- **이유:** 단일 LLM 의존 위험 분산, Strategy A 토너먼트에서 다양한 분석 관점 확보, Strategy B 토론에서 실질적인 이견 유도.
- **Strategy A 구성:** Claude 2개 + GPT 2개 + Gemini 1개 (총 5 인스턴스)
- **Strategy B 역할:** Proposer(Claude) → Challenger1(GPT) + Challenger2(Gemini) → Synthesizer(Claude)

### 2026-03-12 — 알림 채널 Telegram 단일화
- **결정:** KakaoTalk 대신 Telegram Bot API 사용.
- **이유:** Telegram Bot API가 더 개방적이고, 개인 개발자 접근이 쉬우며, `python-telegram-bot` 라이브러리가 안정적.

### 2026-03-14 — RL/Search 통합 순서 고정
- **결정:** Search/Scraping의 데이터 계약과 저장 구조를 먼저 고정하고, RL은 offline-first 학습/평가 lane부터 편입.
- **이유:** 검색 결과와 추출 결과의 출처 추적이 먼저 있어야 RL feature와 Strategy B 입력이 같은 계약을 공유할 수 있음. RL을 먼저 실시간으로 붙이면 회귀 원인 추적이 어려워짐.

### 2026-03-14 — 5-Agent 의사결정 계층 추가
- **결정:** `FastFlowAgent`, `SlowMeticulousAgent`, `OptimistAgent`, `PessimistAgent`, `DecisionDirectorAgent`를 확장 계획 계층으로 정의.
- **이유:** 확장 기능 도입 시 속도, 구조, 기회, 리스크, 최종 결정을 분리해 문서화하면 방향 합의와 변경 추적이 쉬워짐.

### 2026-03-14 — RL trading 최소 runnable lane 구현
- **결정:** 외부 RL 프레임워크 의존 없이 tabular Q-learning 기반의 최소 RL lane을 먼저 구현.
- **이유:** 현재 저장소의 코어 파이프와 빠르게 연결하고, `train -> evaluate -> infer -> paper order` 자동 검증을 가장 짧은 경로로 확보하기 위함.

### 2026-03-14 — RL V2 트레이너: V1 핵심 버그 해결
- **결정:** `rl_trading_v2.py`로 V2 트레이너를 별도 파일로 구현. V1은 원본 유지.
- **V1 문제 진단:**
  - 리워드 함수 구조적 편향: position=0+HOLD=0(무위험) → BUY의 Q-value가 항상 음수 수렴 → 거래 0건
  - 상태 공간 18개(3-bucket × 2-position)로 시장 구분 불가
  - 에피소드 60~120개로 수렴 불충분
- **V2 해결책:**
  - 기회비용 리워드: 비보유 시 시장 변동분의 50%를 패널티
  - 5-bucket 이산화 + 모멘텀(SMA5 vs SMA20) + 변동성 지표 → 675개 상태
  - 3-포지션(-1/0/+1): 숏으로 하락장 수익 가능
  - 멀티시드(5~10회) 학습 후 holdout 최고 성과 선택
  - 결과: 크래프톤 +47.84% (V1: 0%, 0거래)

### 2026-03-14 — RL 모델 저장 구조 결정 (v2: PolicyRegistry 도입)
- **결정:** `artifacts/rl/models/<algorithm>/<ticker>/` 하위에 정책 JSON 저장 + `registry.json` 통합 인덱스 도입
- **구조:** `tabular/`, `dqn/`, `ppo/` 알고리즘 네임스페이스 + Pydantic 기반 PolicyRegistry
- **핵심 파일:**
  - `src/agents/rl_policy_registry.py` — PolicyEntry, TickerPolicies, PolicyRegistry, PromotionGate, CleanupPolicy
  - `src/agents/rl_policy_store_v2.py` — RLPolicyStoreV2 (registry.json 연동, V1 호환)
  - `artifacts/rl/models/registry.json` — 통합 인덱스 (활성 정책 포인터 포함)
- **승격 게이트:** return_pct > 기존 활성, max_drawdown >= -50%, approved=true (paper only 자동 승격)
- **자동 정리:** 미승인 30일 후 삭제, 승인 종목당 5개 보존, 활성 삭제 불가
- **V1 호환:** active_policies.json 읽기 지원, registry.json이 single source of truth
- **이유:** 종목 확장 시 파일 스캔 없이 즉시 조회, Orchestrator 부팅 시 registry.json만 로드
- **후속 구현(2026-03-15):** `src/agents/orchestrator.py`가 RL 모드에서 기본적으로 `RLPolicyStoreV2`를 사용하고, 부팅 시 `registry.json`을 로드해 활성 정책 스냅샷을 로그와 cycle metrics(`rl_registry_state`)에 포함
- **Git 추적 정책(2026-03-15):** `artifacts/`는 기본 ignore를 유지하되, RL 운영 메타파일인 `artifacts/rl/models/README.md`와 `artifacts/rl/models/registry.json`은 Git 추적 허용. tabular 정책 JSON/Q-table은 계속 ignore하고, 향후 DQN/PPO 예제 가중치는 `artifacts/rl/models/dqn/samples/`, `artifacts/rl/models/ppo/samples/` 하위에서만 샘플 형태로 버전 관리

### 2026-03-14 — Strategy A/B + RL 확장 필요사항 정리
- **현황:** ~~RL은 `orchestrator --rl`로 독립 실행만 가능 (A/B와 상호 배타)~~
- **해결 완료 (2026-03-15):** N-way 블렌딩 + StrategyRunner Registry로 전면 리팩토링
  1. ✅ 블렌딩 확장: `BlendInput` + `blend_signals()` N-way 일반화
  2. ✅ 오케스트레이터: elif 체인 → `StrategyRegistry` 기반 병렬 실행
  3. ✅ V2 시그널 호환: `map_v2_action_to_signal()` (CLOSE→HOLD), `normalize_q_confidence()`
  4. ✅ DB 스키마: `predictions.strategy` CHECK에 'R','S','L' 추가, `is_shadow` 컬럼
  5. ✅ RLPolicyStore 경로: `models/<algorithm>/<ticker>/` 하위 구조 사용 (마이그레이션 완료)

### 2026-03-15 — N-way 블렌딩 + StrategyRunner Registry 구현 완료
- **결정:** Option B(Strategy Registry) + N-way blend + shadow gate + 가중치 외부화
- **핵심 변경 파일:**
  - `src/agents/strategy_runner.py` — `StrategyRunner` Protocol + `StrategyRegistry`
  - `src/agents/blending.py` — `BlendInput`, `NWayBlendResult`, `blend_signals()` N-way 일반화, 기존 `blend_strategy_signals()` 래퍼 유지
  - `src/agents/orchestrator.py` — `TournamentRunner`, `ConsensusRunner`, `RLRunner` 래핑, `--strategies A,B,RL` CLI
  - `src/agents/rl_trading_v2.py` — `map_v2_action_to_signal()`, `normalize_q_confidence()`
  - `src/db/models.py` — `PredictionSignal.strategy`에 "S"/"L" 추가, `is_shadow` 필드, `PaperOrderRequest.blend_meta`
  - `scripts/db/init_db.py` — `predictions.is_shadow`, `blend_meta JSONB`, signal_source CHECK 확장
  - `src/utils/config.py` — `strategy_blend_weights` JSON 설정
- **설계 원칙:**
  - 시그널 점수화: BUY=+1, HOLD=0, SELL=-1 가중합 → threshold(0.15) 기반 결정
  - 가중치 자동 정규화: 활성 전략의 weight 합이 1.0이 되도록
  - 기존 단독 모드 완전 호환: `--tournament`, `--consensus`, `--rl`, `--blend` 그대로 동작
  - CLOSE→HOLD: blend 레벨에서는 단순 매핑, 포지션 청산은 PortfolioManager 책임
  - signal_source는 `BLEND` 통일 + `blend_meta` JSONB로 참여 전략/가중치 기록

### 2026-03-15 — RL 실험 관리 구조 결정 (Option B+C 하이브리드)
- **결정:** `artifacts/rl/profiles/`에 재사용 가능한 하이퍼파라미터 프로파일을 두고, 모든 학습은 `artifacts/rl/experiments/<run_id>/`에 run 단위로 기록한다.
- **구조:** config.json + dataset_meta.json + split.json + metrics.json + artifact_link.json + notes.md
- **핵심 파일:** `src/agents/rl_experiment_manager.py` (RLExperimentManager)
- **이유:** 정책 파일과 실험 기록을 분리해야 승격 이유를 설명 가능하고, 프로파일 재사용으로 관리 부담을 줄인다. DB 없이 파일 기반으로 동작하도록 설계.
- **dataset_hash:** SHA256 기반, closes 데이터의 해시로 데이터 재현성 보장

### 2026-03-15 — SearXNG 검색 파이프라인 구조 결정 (Option C 하이브리드)
- **결정:** SearchAgent가 전체 파이프라인을 조율하되, fetch만 asyncio.gather로 병렬화하는 하이브리드 구조.
- **구성:** SearXNG(Docker) → httpx async fetch → HTML→text MVP 추출 → Claude CLI reasoning
- **저장:** 4-테이블 DB 구조 (search_queries, search_results, page_extractions, research_outputs)
- **핵심 파일:** `src/utils/searxng_client.py`, `src/agents/search_agent.py`, `src/utils/reasoning_client.py`
- **이유:** 현재 규모에서 Redis 큐 기반 3-stage는 과도하지만, 저장은 단계별로 분리해야 재사용과 디버깅이 가능하다.
- **캐싱:** URL 단위 24시간 캐시, 도메인별 rate limit 1req/sec
- **Research Contract:** JSON 포맷으로 Strategy B prompt와 RL feature에 공급

### 2026-03-15 — 공통 실험 메타데이터 추적 구조(GitOps) 도입
- **결정:** A/B/RL/Search 도메인 전반의 실험 메타데이터를 추적/비교하기 위해 `config/experiments/`와 `config/active/` 디렉터리 기반의 GitOps 구조를 채택함.
- **내용:** MLflow 등의 무거운 MLOps 플랫폼 대신, JSON 파일에 `commit_hash`를 기록하고 버전 관리(Git)를 연동해 **[설정값] - [소스코드] - [실행결과]** 범위를 보장.
- **운영 승격:** 운영 환경은 무조건 `config/active/`만 바라보도록 제한하며, 승격(Promotion)은 설정 파일을 이 폴더로 복사하는 행위로 명확히 정의함.
- **코드 레벨:** `src/utils/experiment_tracker.py` (`ExperimentTracker` 클래스)를 통해 모든 도메인의 로깅 JSON 스키마를 단일화함.

### 2026-03-15 — Phase 9 RL Trading Lane 전체 구현 완료
- **결정:** Phase 9의 남은 5개 작업 항목을 모두 구현하여 RL Trading Lane을 완성.
- **구현 항목:**
  1. `src/agents/rl_dataset_builder_v2.py` — SMA(5/20/60), RSI(14), 변동성(10일), 거래량비율, 수익률 + 매크로 컨텍스트(KOSPI/KOSDAQ/USD/VIX/섹터) 확장 데이터셋
  2. `src/agents/rl_environment.py` — Gymnasium 호환 TradingEnv, 4-action(BUY/SELL/HOLD/CLOSE), 기회비용+포지션 리워드+거래 페널티, MDD 조기종료, numpy 사전 계산
  3. `src/api/routers/rl.py` — 17개 REST 엔드포인트 (정책 CRUD 5개 + 실험 2개 + 평가 1개 + 학습 2개 + walk-forward 1개 + shadow 4개 + promotion 2개)
  4. `src/agents/rl_walk_forward.py` — N-fold expanding/sliding window 교차검증, consistency_score(positive_ratio × CV 보정), 자동 승인 판정
  5. `src/agents/rl_shadow_inference.py` — ShadowInferenceEngine(shadow 시그널 생성/성과추적), PaperPromotionCriteria(shadow→paper 6개 조건), RealPromotionCriteria(paper→real 6개 조건), 시뮬레이션 수익률/MDD 계산
- **승격 파이프라인:** 학습 → 오프라인 평가 → shadow 추론(is_shadow=True, 블렌딩 제외) → paper 승격 게이트 → paper 운용 → real 승격 게이트
- **테스트:** `test/test_phase9_rl.py` 5개 클래스 (DatasetBuilderV2, TradingEnv, WalkForward, ShadowInference, API 구조 검증)

### 2026-03-15 — Phase 2 후속: 독립 포트폴리오 인프라 구현
- **결정:** 전략별 독립 포트폴리오 운영을 위해 virtual → paper → real 3단계 승격 파이프라인과 합산 리스크 모니터링을 구현.
- **VirtualBroker 시뮬레이션:** 슬리피지 0~N bps (BUY 상승/SELL 하락), 부분 체결 50~100% (10주 초과 시), 체결 지연 0~N초. 모두 config로 조정 가능.
- **승격 기준:** virtual→paper (30일 운영, 20건 거래, 0% 수익, -15% DD, 0.5 Sharpe), paper→real (60일, 50건, 5%, -10%, 1.0). `PROMOTION_CRITERIA_OVERRIDE` env로 JSON 오버라이드 가능.
- **합산 리스크:** 단일 종목 노출 한도 (`MAX_SINGLE_STOCK_EXPOSURE_PCT`), 전략 간 종목 중복 한도 (`MAX_STRATEGY_OVERLAP_COUNT`). 스냅샷을 `aggregate_risk_snapshots` 테이블에 JSONB로 기록.
- **DB 확장:** `strategy_id VARCHAR(10)` 컬럼을 5개 테이블에 추가, `COALESCE(strategy_id, '')` 패턴으로 하위 호환 유지. account_scope CHECK에 'virtual' 추가.
- **핵심 파일:** `src/brokers/virtual_broker.py`, `src/utils/strategy_promotion.py`, `src/utils/aggregate_risk.py`, `scripts/seed_historical_data.py`, `scripts/promote_strategy.py`

### 2026-03-15 — 백테스트 시뮬레이션 엔진 구현
- **결정:** `src/services/backtest_engine.py`에 독립 백테스트 엔진을 구현. 기존 VirtualBroker와 별도로 과거 데이터 전용.
- **시그널 소스 4가지:** rule(골든/데드크로스), momentum(5일 수익률), mean_reversion(볼린저밴드), random
- **시뮬레이션:** 슬리피지 bps, 수수료 bps, 단일 종목 최대 비중(%), 일별 스냅샷(equity/drawdown/PnL), MDD/Sharpe/Profit Factor/승률/연환산수익률
- **API:** `POST /api/v1/backtest/run`(전체 결과), `POST /api/v1/backtest/run/summary`(핵심 지표만)
- **DB 연동:** `run_backtest_from_db()`로 `market_data` 테이블에서 OHLCV 조회 후 시뮬레이션
- **이유:** Phase 2 독립 포트폴리오 인프라의 마지막 퍼즐. 전략의 과거 성과를 사전 검증한 후 virtual→paper 승격 판단에 활용.

### 2026-03-15 — 전략별 대시보드 UI 구현
- **결정:** `GET /strategy/dashboard-status` 단일 엔드포인트로 5개 전략의 모드/성과/승격 상태/가상 자금을 통합 조회.
- **프론트엔드:** `StrategyDashboard.tsx` — StrategyCard(모드 배지+성과 행+승격 뱃지+가상잔고), Toss 스타일 디자인
- **이유:** 5×3=15 포트폴리오 매트릭스를 한눈에 모니터링하기 위함. 개별 API 15번 호출 대신 단일 집계.

---

## 🐛 문제 해결 기록

### 2026-03-12 — KRX 휴장일 미처리 주의
- **문제:** FinanceDataReader는 한국 공휴일/임시 휴장일을 자동으로 제외하지 않음.
- **원인:** fdr의 캘린더 데이터가 불완전함.
- **해결:** 부팅 시 `scripts/fetch_krx_holidays.py`로 KRX 공식 휴장일 목록을 가져와 Redis `krx:holidays:{year}`에 저장. CollectorAgent는 매 작업 전에 이 키를 확인.

### 2026-03-12 — KIS OAuth 토큰 만료 주의
- **문제:** KIS OAuth 토큰은 24시간 후 만료됨. 갱신하지 않으면 모든 트레이딩 API 호출이 조용히 실패함.
- **해결:** PortfolioManagerAgent가 매일 06:00 KST에 토큰을 갱신, Redis `kis:oauth_token`에 TTL 23시간으로 저장. 토큰 만료 1시간 전 NotifierAgent에 알림 발송.

---

## 🏗️ 아키텍처 변경 이력

### 2026-03-12 — 초기 아키텍처 확정
- 5개 에이전트 구조 (Collector, Predictor, PortfolioManager, Notifier, Orchestrator)
- Strategy A (Tournament) + Strategy B (Consensus) 동시 운용
- Redis Pub/Sub 기반 에이전트 간 통신
- 메모리 3-tier: Redis (Hot) / PostgreSQL (Warm) / PostgreSQL Archive (Cold)

### 2026-03-14 — 확장 아키텍처 문서화
- RL Trading lane, Search/Scraping stack, 5-agent review council 문서를 별도 `docs/` 파일로 분리
- 기존 코어 문서는 유지하고 확장 섹션/별도 문서만 추가

### 2026-03-14 — RL lane 실행 경로 추가
- `src/agents/rl_trading.py`에 dataset builder, trainer, evaluator, policy store, inference agent 추가
- `src/agents/orchestrator.py`와 `scripts/run_orchestrator_worker.py`에 RL 실행 모드 추가
- 주문 파이프는 계속 `PortfolioManagerAgent`를 통해서만 실행

---

## ⚠️ 주의 사항 (Gotchas)

1. **`kis_place_order`는 PortfolioManagerAgent만 호출 가능.** 다른 에이전트가 주문 API를 직접 호출하면 안 됨.
2. **서킷브레이커(-3% 일손실)는 절대 LLM이 오버라이드 불가.** 코드에서 하드코딩된 체크가 먼저 실행됨.
3. **데이터 신선도 확인.** Predictor는 30분 이상 오래된 장중 데이터로 예측하면 안 됨.
4. **KIS 페이퍼와 실거래 엔드포인트가 다름.** `openapivts` (페이퍼) vs `openapi` (실거래), `tr_id`도 다름.
5. **fdr은 EOD만.** 장중 실시간 데이터는 반드시 KIS WebSocket 사용.

---

*Last updated: 2026-03-15*
