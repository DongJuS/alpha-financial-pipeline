# 🧠 MEMORY.md — 기술적 결정 및 문제 해결 누적 기록

> **작성일**: 2026-03-15  
> **담당자**: Agent  
> **상태**: 진행 중

---

## 📌 Recent Decisions

### 2026-03-16 — 사용자 방침: LLM은 기존 구독/OAuth만 사용 (API 유료 호출 금지)
- **방침:** LLM API Key 기반 유료 호출(Anthropic API Key, Gemini API Key, OpenAI API Key)을 사용하지 않는다.
- **허용되는 LLM 접근 경로:**
  - **Claude:** CLI (`/usr/bin/claude` 또는 `~/.claude/bin/claude`) — 기존 Claude 구독(OAuth/브라우저 로그인)으로 동작
  - **Gemini:** gcloud OAuth ADC(Application Default Credentials) — `gcloud auth application-default login --scopes="https://www.googleapis.com/auth/generative-language,https://www.googleapis.com/auth/cloud-platform"` 으로 인증. API Key 불필요.
  - **GPT:** 사용 안 함
- **핵심 원칙:** OAuth로 CLI든 브라우저든 프로그램이든 접근 가능하므로, 별도 API 호출 비용이 발생하지 않는다.
- **Gemini ACCESS_TOKEN_SCOPE_INSUFFICIENT 해결:** gcloud ADC 발급 시 `generative-language` scope를 포함하면 해결됨.
- **Docker 환경:** 컨테이너에 `~/.claude` (Claude CLI 인증)와 `~/.config/gcloud/application_default_credentials.json` (Gemini OAuth)을 볼륨 마운트해야 한다.

### 2026-03-16 — Pipeline Refactoring (PR #22)
- **문제:** orchestrator.py에 존재하지 않는 `get_predictor_performance` import, 중복 StrategyRunnerRegistry, worker가 잘못된 9개 kwargs 전달로 crash-loop
- **수정:**
  1. `orchestrator.py` — broken import 제거, StrategyRegistry 통합, N-way 블렌딩 실제 구현
  2. `strategy_a_runner.py` / `strategy_b_runner.py` / `rl_runner.py` — StrategyRunner 어댑터 3종 신규
  3. `run_orchestrator_worker.py` — 환경변수 기반 전략 등록 패턴으로 전면 재작성
  4. `rl.py` — `base_dir` → `models_dir` / `artifacts_dir` 파라미터명 수정
- **결과:** Worker crash-loop 해소, Strategy A/B/RL 3개 등록 및 blend mode 실행 확인

### 2026-03-16 — QA 검증 + MinIO/LLM 연동 수정
- **문제:** docker-compose.yml에 MinIO 서비스 정의가 누락되어 S3/Data Lake 전체 불능, Predictor 5개 전부 실패(0종목/20종목)
- **원인 분석:**
  1. S3: MinIO 컨테이너가 없어 `http://minio:9000` 연결 불가
  2. LLM: `ANTHROPIC_CLI_COMMAND`가 비어있을 때 Claude CLI 자동감지 미동작
- **수정:**
  1. `docker-compose.yml` — minio 서비스(9000/9001포트), minio-init(alpha-lake 버킷 자동생성), api/worker에 minio 의존성+healthcheck 추가
  2. `cli_bridge.py` — `build_cli_command()` 에서 template이 비어있어도 `claude` 바이너리가 PATH에 있으면 자동으로 `[claude, -p, --model, {model}]` 명령 생성
  3. 프로젝트 전체 LLM 연동 명칭 교체: "Anthropic API"→"Claude CLI", "OpenAI API"→"openai SDK", "Google Gemini API"→"Gemini OAuth(ADC)"
- **교훈:** docker-compose에 서비스 추가 시 반드시 healthcheck+depends_on+volumes 3가지를 한 세트로 설정할 것. LLM 클라이언트는 환경변수 없이도 바이너리 자동감지로 작동해야 함.

### 2026-03-16 — Strategy S Orchestrator 통합 + 마켓플레이스 Closure
- **결정:** SearchRunner를 StrategyRunner Protocol로 구현하여 Orchestrator에 등록. 4-way 블렌딩(A:0.3/B:0.3/S:0.2/RL:0.2) 완성.
- **구현:**
  - `src/agents/search_runner.py` — StrategyRunner Protocol 구현, ResearchPortfolioManager 래핑
  - `test/test_search_runner_integration.py` — Protocol 준수/에러 핸들링/Orchestrator 등록 테스트
  - `orchestrator.py` TYPE_CHECKING import 수정
- **마켓플레이스 Closure:** Week 1~5 전체 구현 완료 확인. `roadmap.md`에 Phase 13 추가. 논의 문서 closed.
- **README 전면 업데이트:** 4전략 N-way 블렌딩 아키텍처, 확장 상태 표 반영.

### 2026-03-16 — Copilot 리뷰 코드 품질 수정 (PR #11 후속)
- **결정:** PR #11 머지 후 Copilot이 지적한 3가지 타입/파라미터 불일치를 수정.
- **수정 내역:**
  1. **orchestrator.py — risk_summary dict→dataclass:** `risk_summary.get("violations")` → `risk_summary.warnings`. `AggregateRiskMonitor.get_risk_summary()`는 `RiskSummary` dataclass를 반환하며, 필드명은 `warnings`(list[str]).
  2. **orchestrator.py — StrategyPromoter 파라미터:** `evaluate_promotion_readiness(strategy_name)` → `evaluate_promotion_readiness(strategy_name, from_mode="virtual", to_mode="paper")`. 메서드는 3개 필수 파라미터 필요.
  3. **orchestrator.py — PromotionCheckResult 필드명:** `readiness.is_ready` → `readiness.ready`. dataclass 필드명은 `ready: bool`.
  4. **WalkForwardResult.overall_approved:** 모든 소비자에서 일관되게 사용 확인 — 변경 불필요.
- **교훈:** dataclass 반환값을 dict처럼 사용하는 패턴은 런타임까지 발견 안 되므로, 향후 `mypy --strict` 도입 검토 필요.

### 1. Search Strategy (S) 파이프라인 통합 ✅

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

---

### 2. Index Collector 에이전트 추가 ✅

**결정**: KOSPI/KOSDAQ 지수를 정기적으로 수집하는 독립 에이전트 구현.

**배경**:
- 실시간 시장 상태 파악 필요
- 마켓 타이밍 및 서킷 브레이커 판단에 필수
- KIS API에서 이미 지원

**구현**:
- `IndexCollector`: KIS API를 통해 KOSPI(0001), KOSDAQ(1001) 수집
- `index_scheduler.py`: APScheduler 사용
  - 08:55 KST: 사전 워밍업 (1회)
  - 장중 매 30초: 정기 수집 (시장 열려있을 때만)
- Redis 캐시: `market_index:{...}` 키로 저장, TTL 1분

**결과**:
- 모든 에이전트가 Redis에서 즉시 접근 가능
- 지수 기반 필터링 준비 완료

---

### 3. Sentiment → Signal 매핑 규칙 확정 ✅

**결정**:
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

**배경**:
- LLM 리서치 결과의 신뢰도가 낮을 수 있음
- 소스 없는 분석은 매우 조심스러운 신호
- 기존 Strategy A/B의 confidence 범위와 일치

**결과**:
- 보수적이면서도 합리적인 신뢰도 관리
- 과신 방지

---

### 4. 캐싱 전략 확정 ✅

**결정**: 검색 결과를 Redis에 4시간 캐싱.

**기준**:
- 같은 종목에 대한 중복 검색 방지
- 하루 중 동일 이슈는 반복될 가능성 높음
- 4시간 = 장중(09:00~15:30) 전 기간 커버 + 여유
- 다음 날 새로운 뉴스 반영 필요

**구현**:
- `ResearchPortfolioManager._get_cached_signal(ticker)`: 캐시 조회
- `ResearchPortfolioManager._cache_signal(ticker, signal)`: 캐시 저장
- Key: `research:signal:{ticker}`

**결과**:
- Tavily/SearchEngine 호출 최소화
- API 비용 절감

---

### 5. 에러 핸들링 정책 ✅

**결정**: 리서치 실패 시 항상 HOLD 신호로 fallback.

**이유**:
- 매매하지 않는 것이 가장 안전한 기본값
- 부분 장애 시에도 시스템 계속 작동
- 사용자에게 "정보 부족"을 명확히 전달

**구현**:
- `ResearchPortfolioManager._research_single_ticker()`: try-except로 예외 처리
- `ResearchPortfolioManager.run_research_cycle()`: 부분 장애 감지 및 로깅

**결과**:
- 견고성 향상
- 디버깅 용이

---

## 🔍 Known Issues & Workarounds

### Issue 1: Tavily API 레이트 리미팅
**상태**: 미해결  
**영향**: 종목이 많으면 Tavily API 호출 제한 가능  
**대처**:
- `max_concurrent_searches=3` (기본값)으로 제한
- 캐싱으로 중복 호출 방지
- 장기적: SearXNG 등 로컬 검색 엔진 고려

### Issue 2: SearchAgent 모델 지원 범위
**상태**: 미해결  
**영향**: 일부 LLM 모델에서 지원 안 될 수 있음  
**대처**:
- `model_used` 필드로 어떤 모델을 사용했는지 기록
- 호환성 확인 필요 (Claude, OpenAI, Gemini)

---

## 📚 Architecture Notes

### N-way 블렌딩에 Strategy S 통합

```
Orchestrator
├─ Strategy A (Tournament) → signal_a
├─ Strategy B (Consensus Debate) → signal_b
├─ Strategy RL (미구현) → signal_rl
└─ Strategy S (Search) → signal_s
        │
        └─ blend_signals()
           {
             "A": 0.30,
             "B": 0.30,
             "RL": 0.20,
             "S": 0.20
           }
           ↓
        final_signal
```

### ResearchPortfolioManager 위치

- **역할**: SearchAgent를 전략 수준으로 래핑
- **입력**: 종목 리스트 (tickers)
- **출력**: PredictionSignal 리스트
- **부작용 없음**: 직접 주문 권한 없음 (PortfolioManagerAgent만 주문)

---

## 📋 Checklist for Next Phase

- [ ] RL Trading 파이프라인 구현 (Strategy RL)
- [ ] SearXNG 로컬 검색 엔진 통합 (API 제한 극복)
- [ ] SearchAgent 모델 호환성 테스트
- [ ] 프로덕션 환경 배포 및 모니터링
- [ ] 성능 튜닝 (블렌딩 가중치 최적화)

---

*Last updated: 2026-03-15*
