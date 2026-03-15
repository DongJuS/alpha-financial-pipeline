# 🧠 MEMORY.md — 기술적 결정 및 문제 해결 누적 기록

> **작성일**: 2026-03-15  
> **담당자**: Agent  
> **상태**: 진행 중

---

## 📌 Recent Decisions

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

### 2026-03-16 — 피드백 루프 파이프라인 도입 (S3 Data Lake → 모델 개선)
- **결정:** S3 Data Lake에 저장된 과거 데이터를 읽어 LLM/RL 모델 성능을 지속적으로 개선하는 자동 피드백 루프를 구축.
- **배경:** S3에 7가지 DataType을 쓰는 인프라는 있었지만, 읽어서 개선하는 경로가 전혀 없었음. `download_bytes()`, `list_objects()` 등 읽기 함수는 존재하나 한 번도 호출되지 않는 상태.
- **4개 파이프라인:**
  1. **LLM 피드백 루프** (`llm_feedback.py`): predictions+daily_bars 매칭 → 정확도/P&L/오류 패턴 분석(BUY 편향, 과도한 자신감, 반복 실패, 연속 실패, HOLD 남발) → Redis 캐시 → PredictorAgent 프롬프트 자동 주입
  2. **RL 재학습** (`rl_retrain_pipeline.py`): S3 daily_bars → RLDataset → TabularQTrainerV2 → walk-forward 검증 → 기존 정책 대비 비교 → 합격 시 RLPolicyStoreV2 저장
  3. **백테스트 엔진** (`backtest_engine.py`): 시그널 기반 가상 포트폴리오 시뮬레이션(슬리피지+수수료+종목별 최대 비중), 전략 간 비교(A vs B vs RL)
  4. **피드백 오케스트레이터** (`feedback_orchestrator.py`): 일일 배치로 3개 파이프라인 통합 실행
- **PredictorAgent 연동:** `_get_feedback_context()` → Redis에서 `feedback:llm_context:{strategy}` 읽기 → 프롬프트 맨 앞에 주입. 캐시 없으면 기존 프롬프트 그대로 (graceful degradation).
- **REST API:** `src/api/routers/feedback.py`에 7개 엔드포인트 (정확도 조회, LLM 컨텍스트 확인, 백테스트 실행/비교, RL 단일/일괄 재학습, 피드백 사이클 수동 트리거)
- **설계 원칙:**
  - 모든 읽기는 S3 Data Lake 전용 (운영 DB 부하 없음)
  - 실패 시 서비스 중단 없음 (graceful degradation)
  - RL 재학습은 walk-forward + 기존 정책 비교 통과 필수
  - Redis 캐시 TTL 24시간, 매일 장 마감 후 갱신

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
