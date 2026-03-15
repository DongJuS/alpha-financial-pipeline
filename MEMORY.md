# 🧠 MEMORY.md — 기술적 결정 및 문제 해결 누적 기록

> **작성일**: 2026-03-15  
> **담당자**: Agent  
> **상태**: 진행 중

---

## 📌 Recent Decisions

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
