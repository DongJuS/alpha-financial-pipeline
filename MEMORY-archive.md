# 🗄️ MEMORY-archive.md — 완료된 기술적 결정 이력

> **이 파일은 MEMORY.md에서 분리된 아카이브입니다.**
> 이미 구현 완료된 결정의 상세 이력을 원문 그대로 보존합니다.
> 활성 운영 규칙과 미해결 이슈는 `MEMORY.md`를 참조하세요.

---

## 2026-03-29 — 문서 정비 + smoke test 통과 (PR #53)

- **작업:** README 정량 지표 섹션 추가, Airflow 비교 문서 신규 작성, README 빠른 시작 minio 누락 수정
- **의사결정:**
  - Airflow 전면 마이그레이션 대신 "비교 스파이크" 접근 — Alpha의 실시간 요구사항(30초 인터벌, 이벤트 드리븐)에는 APScheduler+Redis가 적합. Airflow의 실행 이력 UI/backfill CLI/DAG 시각화만 선별 도입 검토.
  - README 빠른 시작에 minio 서비스 필수 — docker-compose.yml에서 api/worker가 `minio: service_healthy`에 의존하므로 누락 시 시작 불가.
- **산출물:** `docs/airflow-comparison.md` (15항목 비교표, 9개 구현체↔Airflow 매핑, 9개 잡 DAG 매핑), README.md 정량 지표
- **검증:** smoke test 전체 통과 (DB/Redis/FastAPI/FDR)

---

## 2026-03-18 — 데이터 수집/저장 경로 전수 감사 (상세)

- **작업:** 코드 기반으로 전체 데이터 수집 소스 9개, 저장소 4종(PG 20테이블, Redis 13키+5 Pub/Sub, S3 4 DataType, 로컬 파일 2경로)을 매핑.
- **산출물:** `DATA-STOCK_ARCHITECTURE.md` (상세 문서), `architecture.md` 데이터 아키텍처 섹션 갱신 (참조 링크 추가)
- **발견된 끊어진 파이프라인 (Critical 3건, Warning 5건, Notice 3건):**
  1. 🔴 **SearchAgent 완전 stub** — `run_research()`에 TODO 3개만 있고 항상 neutral/0.5 반환. SearXNG 클라이언트는 완성되어 있으나 SearchAgent에서 호출 안 함.
  2. 🔴 **Orchestrator CLI에서 Runner 미등록** — `_main_async()`에서 StrategyRegistry가 비어 있어 전략 실행 0건.
  3. 🔴 **LLM 프로바이더 전원 장애** — Docker 내 Claude CLI 부재, GPT 미사용 정책, Gemini ADC 미마운트 → Predictor 전체 실패.
  4. 🟡 **Yahoo 일봉 Redis/S3 미저장** — `collect_yahoo_daily_bars()`는 PG만 사용.
  5. 🟡 **실시간 틱 S3 미저장** — `store_tick_data()` 함수 미구현 (enum만 존재).
  6. 🟡 **Historical Bulk Redis/S3 미사용** — 벌크 시드 후 Redis 캐시 빈 채로 남음.
  7. 🟡 **IndexCollector DB 미저장** — Redis 120초 캐시만, 지수 이력 분석 불가.
  8. 🟡 **debate_transcripts/rl_episodes S3 미구현** — DataType enum만 존재.
  9. 🟠 **스케줄러가 IndexCollector만 가동** — 일봉/매크로/종목마스터 자동 수집 없음.
  10. 🟠 **ticker_master 테이블 누락 가능성** — lifespan에서 조회하지만 init_db에 DDL 미확인.
  11. 🟠 **RLRunner 활성 정책 0건** — 학습 → 활성화 파이프라인 미실행 시 RL 시그널 0건.

---

## 2026-03-17 — 에이전트 레지스트리 PostgreSQL 중앙 관리 (상세)

- **문제:** 에이전트 ID가 여러 곳에 하드코딩(API 라우터 `AGENT_IDS` 리스트, 각 에이전트 클래스 기본값)되어 불일치 발생. `OrchestratorAgent(agent_id="orchestrator")`이 하트비트를 `"orchestrator"`로 기록하지만 API는 `"orchestrator_agent"`를 조회 → 영원히 "연결 끊김" 표시.
- **결정:** `agent_registry` PostgreSQL 테이블로 에이전트 목록을 중앙 관리. API는 DB에서 동적 조회, 폴백 하드코딩 유지.
- **수정사항:**
  - `scripts/db/init_db.py`: `agent_registry` 테이블 DDL + 11개 시드 데이터
  - `src/api/routers/agents.py`: `AGENT_IDS` 하드코딩 → `_load_agent_registry()` DB 조회 (폴백 포함)
  - `src/agents/orchestrator.py`: `agent_id` 기본값 `"orchestrator"` → `"orchestrator_agent"`, PM/Notifier 인스턴스도 정규 ID 사용
  - 레지스트리 CRUD API: `/registry/list`, `/registry/register`, `/registry/{id}` DELETE

---

## 2026-03-17 — LLM 프로바이더 운영 정책 (상세)

- **현황:** Predictor 1~5 모든 종목 예측 실패 (0성공/3실패)
- **원인 추정:** Claude CLI 또는 Gemini OAuth 호출이 Docker 컨테이너 내에서 실패 중. 컨테이너 로그(`docker compose logs worker`) 확인 필요.

---

## 2026-03-16 — N+1 쿼리 배치 최적화 executemany (상세)

- **결정:** 수집-저장 파이프라인의 모든 bulk upsert 함수(`for + await execute()` 패턴)를 `asyncpg executemany()`로 전환. 실시간 틱에는 메모리 버퍼 도입.
- **근거:**
  - `for + await execute()`는 매 반복마다 커넥션 acquire/release + 네트워크 왕복 발생 → 2,400건 기준 10~30초
  - `executemany`는 내부적으로 PostgreSQL extended protocol pipelining 사용 → 네트워크 왕복 1회, 0.1~0.5초
  - `max_size`를 200으로 올려도 해결 불가: 직렬 `await`라 커넥션 1개만 사용, PostgreSQL 커넥션 비용(5~10MB/개), `max_connections=100` 초과 위험
- **구현:**
  - `db_client.py`: `executemany()` 헬퍼 (chunk_size=5,000 자동 분할)
  - `queries.py`: `upsert_market_data()` 전환
  - `marketplace_queries.py`: 4개 함수 전환 (stock_master/theme/macro/rankings)
  - `collector.py`: `_tick_buffer` + `_flush_tick_buffer()` (100건 또는 1초 주기)
- **AI 합의:** GitHub Copilot + Claude Opus 모두 Option A(executemany) 추천. UNNEST(Option B)는 복잡도 대비 이점 미미, COPY(Option C)는 upsert 불가로 부적합.

---

## 2026-03-16 — Strategy S Orchestrator 통합 + 마켓플레이스 Closure (상세)

- **결정:** SearchRunner를 StrategyRunner Protocol로 구현하여 Orchestrator에 등록. 4-way 블렌딩(A:0.3/B:0.3/S:0.2/RL:0.2) 완성.
- **구현:**
  - `src/agents/search_runner.py` — StrategyRunner Protocol 구현, ResearchPortfolioManager 래핑
  - `test/test_search_runner_integration.py` — Protocol 준수/에러 핸들링/Orchestrator 등록 테스트
  - `orchestrator.py` TYPE_CHECKING import 수정
- **마켓플레이스 Closure:** Week 1~5 전체 구현 완료 확인. `roadmap.md`에 Phase 13 추가. 논의 문서 closed.
- **README 전면 업데이트:** 4전략 N-way 블렌딩 아키텍처, 확장 상태 표 반영.

---

## 2026-03-16 — Copilot 리뷰 코드 품질 수정 PR #11 후속 (상세)

- **수정 내역:**
  1. **orchestrator.py — risk_summary dict→dataclass:** `risk_summary.get("violations")` → `risk_summary.warnings`. `AggregateRiskMonitor.get_risk_summary()`는 `RiskSummary` dataclass를 반환하며, 필드명은 `warnings`(list[str]).
  2. **orchestrator.py — StrategyPromoter 파라미터:** `evaluate_promotion_readiness(strategy_name)` → `evaluate_promotion_readiness(strategy_name, from_mode="virtual", to_mode="paper")`. 메서드는 3개 필수 파라미터 필요.
  3. **orchestrator.py — PromotionCheckResult 필드명:** `readiness.is_ready` → `readiness.ready`. dataclass 필드명은 `ready: bool`.
  4. **WalkForwardResult.overall_approved:** 모든 소비자에서 일관되게 사용 확인 — 변경 불필요.
- **교훈:** dataclass 반환값을 dict처럼 사용하는 패턴은 런타임까지 발견 안 되므로, 향후 `mypy --strict` 도입 검토 필요.

---

## 2026-03-15 — Search Strategy (S) 파이프라인 통합 (상세)

**결정**: 기존 Strategy A/B 구조를 유지하면서 Search Strategy (S)를 4번째 전략으로 추가.

**배경**:
- RL Trading 및 검색 파이프라인 확장이 필요함
- 기존 구조의 변경을 최소화해야 함
- 멀티 에이전트 시스템의 N-way 블렌딩이 이미 구현되어 있음

**구현**:
- `ResearchPortfolioManager`: SearchAgent를 래핑하여 종목별 리서치 수행
- `SearchRunner`: StrategyRunner 프로토콜 준수하는 새로운 전략 러너
- Sentiment → Signal 매핑: bullish=BUY, bearish=SELL, neutral/mixed=HOLD
- Redis 캐싱: 4시간 TTL로 동일 쿼리 중복 실행 방지
- PortfolioManagerAgent의 주문 권한 분리: 시그널만 생성

**결과**:
- N-way 블렌딩에 자연스럽게 통합
- `strategy_blend_weights`의 `"S": 0.20` 추가로 20% 가중치 부여
- 기존 Strategy A/B 동작에 영향 없음

---

## 2026-03-15 — Phase 9 RL Trading Lane 전체 구현 완료 (상세)

- **구현 항목:**
  1. `src/agents/rl_dataset_builder_v2.py` — SMA(5/20/60), RSI(14), 변동성(10일), 거래량비율, 수익률 + 매크로 컨텍스트(KOSPI/KOSDAQ/USD/VIX/섹터) 확장 데이터셋
  2. `src/agents/rl_environment.py` — Gymnasium 호환 TradingEnv, 4-action(BUY/SELL/HOLD/CLOSE), 기회비용+포지션 리워드+거래 페널티, MDD 조기종료, numpy 사전 계산
  3. `src/api/routers/rl.py` — 17개 REST 엔드포인트 (정책 CRUD 5개 + 실험 2개 + 평가 1개 + 학습 2개 + walk-forward 1개 + shadow 4개 + promotion 2개)
  4. `src/agents/rl_walk_forward.py` — N-fold expanding/sliding window 교차검증, consistency_score(positive_ratio × CV 보정), 자동 승인 판정
  5. `src/agents/rl_shadow_inference.py` — ShadowInferenceEngine(shadow 시그널 생성/성과추적), PaperPromotionCriteria(shadow→paper 6개 조건), RealPromotionCriteria(paper→real 6개 조건), 시뮬레이션 수익률/MDD 계산
- **승격 파이프라인:** 학습 → 오프라인 평가 → shadow 추론(is_shadow=True, 블렌딩 제외) → paper 승격 게이트 → paper 운용 → real 승격 게이트
- **테스트:** `test/test_phase9_rl.py` 5개 클래스

---

## 2026-03-15 — Phase 2 후속: 독립 포트폴리오 인프라 구현 (상세)

- **VirtualBroker 시뮬레이션:** 슬리피지 0~N bps (BUY 상승/SELL 하락), 부분 체결 50~100% (10주 초과 시), 체결 지연 0~N초. 모두 config로 조정 가능.
- **승격 기준:** virtual→paper (30일 운영, 20건 거래, 0% 수익, -15% DD, 0.5 Sharpe), paper→real (60일, 50건, 5%, -10%, 1.0). `PROMOTION_CRITERIA_OVERRIDE` env로 JSON 오버라이드 가능.
- **합산 리스크:** 단일 종목 노출 한도 (`MAX_SINGLE_STOCK_EXPOSURE_PCT`), 전략 간 종목 중복 한도 (`MAX_STRATEGY_OVERLAP_COUNT`). 스냅샷을 `aggregate_risk_snapshots` 테이블에 JSONB로 기록.
- **DB 확장:** `strategy_id VARCHAR(10)` 컬럼을 5개 테이블에 추가, `COALESCE(strategy_id, '')` 패턴으로 하위 호환 유지. account_scope CHECK에 'virtual' 추가.
- **핵심 파일:** `src/brokers/virtual_broker.py`, `src/utils/strategy_promotion.py`, `src/utils/aggregate_risk.py`, `scripts/seed_historical_data.py`, `scripts/promote_strategy.py`

---

## 2026-03-15 — Index Collector 에이전트 추가 (상세)

- `IndexCollector`: KIS API를 통해 KOSPI(0001), KOSDAQ(1001) 수집
- `index_scheduler.py`: APScheduler 사용
  - 08:55 KST: 사전 워밍업 (1회)
  - 장중 매 30초: 정기 수집 (시장 열려있을 때만)
- Redis 캐시: `market_index:{...}` 키로 저장, TTL 1분

---

## 2026-03-15 — Sentiment → Signal 매핑 규칙 (상세)

```python
SENTIMENT_TO_SIGNAL = {
    "bullish": "BUY",
    "bearish": "SELL",
    "neutral": "HOLD",
    "mixed": "HOLD",
}
```

**신뢰도 (confidence) 기준**:
- `< 0.3`: HOLD로 fallback (항상)
- `sources = 0`: confidence를 0.3 이하로 하향
- `> 1.0`: 1.0으로 클립
- `[0, 1]`: 4자리 반올림

---

## 2026-03-15 — 캐싱 전략 (상세)

- 검색 결과를 Redis에 4시간 캐싱
- `ResearchPortfolioManager._get_cached_signal(ticker)`: 캐시 조회
- `ResearchPortfolioManager._cache_signal(ticker, signal)`: 캐시 저장
- Key: `research:signal:{ticker}`

---

## 2026-03-15 — 에러 핸들링 정책 (상세)

- 리서치 실패 시 항상 HOLD 신호로 fallback
- `ResearchPortfolioManager._research_single_ticker()`: try-except로 예외 처리
- `ResearchPortfolioManager.run_research_cycle()`: 부분 장애 감지 및 로깅

---

*Archived from MEMORY.md on 2026-03-28*
