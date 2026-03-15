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
