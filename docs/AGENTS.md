# 📋 AGENTS.md — 멀티 에이전트 정의 및 역할 분담

> **작성일**: 2026-03-15  
> **상태**: 모든 에이전트 정의 완료

---

## 🎯 에이전트 역할 맵

| 에이전트 ID | 이름 | 전략 | 입력 | 출력 | 권한 | 상태 |
|-----------|------|------|------|------|------|------|
| `strategy_a_runner` | Strategy A (Tournament) | A | 종목 리스트 | PredictionSignal[] | 시그널만 | ✅ 운영 중 |
| `strategy_b_runner` | Strategy B (Consensus Debate) | B | 종목 리스트 | PredictionSignal[] | 시그널만 | ✅ 운영 중 |
| `rl_trading_runner` | RL Trading Runner | RL | 종목, 시장 상태 | PredictionSignal[] | 시그널만 | ⏳ 구현 예정 |
| `research_portfolio_manager` | Research Portfolio Manager | S | 종목, 검색 키워드 | PredictionSignal[] | 시그널만 | ✅ 새로 추가 |
| `orchestrator` | Orchestrator | 조율 | 종목, 신호들 | BUY/SELL/HOLD 주문 | **주문 실행** | ✅ 운영 중 |
| `portfolio_manager` | Portfolio Manager | 실행 | 최종 신호 | 매수/매도 주문 | **주문 실행** | ✅ 운영 중 |
| `index_collector` | Index Collector | 수집 | - | KOSPI/KOSDAQ 지수 | 읽기만 | ✅ 새로 추가 |

---

## 🏆 Strategy A (Tournament)

### 개요
- **역할**: 여러 Predictor가 경쟁하는 토너먼트 방식
- **Predictor 수**: 5개 (Claude Opus 2, Claude Haiku 1, Gemini Pro 2)
- **평가 기준**: `rolling_accuracy` (최근 N일 정확도)
- **출력**: 가장 정확한 predictor의 신호

### Predictor 설정

```python
P1: Claude Opus (가치투자형), temp=0.3
P2: Claude Opus (기술분석형), temp=0.5
P3: Gemini Pro (모멘텀형), temp=0.7
P4: Gemini Pro (역추세형), temp=0.6
P5: Claude Haiku (거시경제형), temp=0.4
```

### 동작 흐름

1. 각 Predictor에게 종목 정보 전달
2. LLM 호출 (병렬)
3. `rolling_accuracy` 기반 점수 집계
4. 가장 높은 점수의 Predictor 신호 선택
5. Provider Fallback (실패 시 Claude → OpenAI → Gemini)

---

## 💬️ Strategy B (Consensus Debate)

### 개요
- **역할**: Proposer와 Challenger들의 토론으로 합의점 도출
- **역할 분담**:
  - **Proposer**: 매매 주장 제시 (temp=0.5)
  - **Challenger 1, 2**: 반론 제시 (temp=0.7)
  - **Synthesizer**: 종합 판단 (temp=0.3)
- **합의 조건**: confidence ≥ 0.67
- **최대 라운드**: `strategy_b_max_rounds` (기본 2)

### 동작 흐름

1. Proposer가 매매 주장 제시
2. Challenger 1, 2가 반론 제시 (병렬)
3. Synthesizer가 종합 판단
4. confidence ≥ 0.67 이면 신호 확정
5. confidence < 0.67 이고 라운드 < max_rounds이면 다음 라운드
6. max_rounds 도달 시 HOLD 확정

---

## 🔍 Strategy S (Search)

### 개요
- **역할**: 웹 검색 및 스크래핑으로 리서치 기반 신호 생성
- **에이전트**: `ResearchPortfolioManager`
- **검색 엔진**: Tavily Search API (또는 SearXNG)
- **기본값**:
  - `max_concurrent`: 3 종목 병렬
  - `categories`: "news"
  - `max_sources`: 5개 소스
  - `cache_ttl`: 4시간

### Sentiment → Signal 매핑

| Sentiment | Signal | 조건 |
|-----------|--------|------|
| bullish | BUY | confidence ≥ 0.3 |
| bearish | SELL | confidence ≥ 0.3 |
| neutral | HOLD | - |
| mixed | HOLD | - |
| any | HOLD | confidence < 0.3 |

### 동작 흐름

1. 종목별 검색 쿼리 생성
2. Redis 캐시 확인 (4시간)
3. 캐시 미스 시 SearchAgent 호출
4. ResearchOutput → PredictionSignal 변환
5. 캐시 저장
6. 신호 반환

---

## ⚙️ Index Collector (신규)

### 개요
- **역할**: KOSPI/KOSDAQ 지수 정기 수집
- **데이터 소스**: KIS API
- **수집 간격**:
  - 08:55 KST: 사전 워밍업
  - 장중 매 30초: 정기 수집 (09:00~15:30 KST, 월~금)
- **저장소**: Redis `market_index` 키 (TTL 1분)

### 수집 데이터

```json
{
  "kospi": {
    "value": 2850.5,
    "change": 15.2,
    "change_pct": 0.53
  },
  "kosdaq": {
    "value": 920.3,
    "change": -5.1,
    "change_pct": -0.55
  }
}
```

### 활용 (기존)
- 서킷 브레이커 판단
- 시장 강도 필터링
- 포트폴리오 리밸런싱

---

## 🎛️ Orchestrator (조율 에이전트)

### 역할
- Strategy A, B, S, RL 신호 수집
- N-way 가중 블렌딩
- 포트폴리오 규칙 적용 (손절, 익절, 일일 한도)
- PortfolioManagerAgent에 최종 신호 전달

### 블렌딩 규칙

```python
strategy_blend_weights = {
    "A": 0.30,  # 토너먼트
    "B": 0.30,  # 합의 토론
    "S": 0.20,  # 검색 리서치
    "RL": 0.20  # 강화학습 (미구현)
}

final_signal = argmax(weighted_signals)
```

---

## 👔 Portfolio Manager (실행 에이전트)

### 역할
- **유일한 주문 권한**
- 최종 신호 → 매수/매도 주문
- 계좌 구분 (Paper / Real)
- KIS Broker 연동

---

## 📊 에이전트 간 데이터 흐름

```
┌─────────────────────────────────────────────┐
│         Market Data Collection              │
│  (KIS API, FinanceDataReader, Index)        │
└──────────────────┬──────────────────────────┘
                   ↓
        ┌──────────┴──────────┐
        │                     │
   ┌────▼─────┐         ┌────▼────┐
   │Strategy A│         │Strategy B│
   │Tournament│         │  Debate  │
   └────┬─────┘         └────┬────┘
        │                     │
        │  ┌─────────────┐    │
        │  │ Strategy S  │    │
        └──┤  (Search)   ├────┘
           └──────┬──────┘
                  ↓
         ┌────────────────┐
         │ Orchestrator   │
         │ (Blend N-way)  │
         └────────┬───────┘
                  ↓
         ┌────────────────┐
         │Portfolio Mgr   │
         │ (Execute Order)│
         └────────────────┘
```

---

## ✅ Status Dashboard

### 구현 완료
- ✅ Strategy A (Tournament)
- ✅ Strategy B (Consensus Debate)
- ✅ Strategy S (Search Research) **← 새로 추가**
- ✅ Orchestrator (N-way Blending)
- ✅ Portfolio Manager (Order Execution)
- ✅ Index Collector (KOSPI/KOSDAQ) **← 새로 추가**

### 구현 예정
- ⏳ Strategy RL (Reinforcement Learning)
- ⏳ Real Trading Readiness Check

---

## 🔐 권한 (Permissions)

| 에이전트 | 신호 생성 | 주문 실행 | 설정 변경 |
|---------|---------|---------|----------|
| Strategy A | ✅ | ❌ | ❌ |
| Strategy B | ✅ | ❌ | ❌ |
| Strategy S | ✅ | ❌ | ❌ |
| Strategy RL | ✅ | ❌ | ❌ |
| Orchestrator | ✅ | ❌ | ❌ |
| Portfolio Mgr | ❌ | ✅ | ❌ |
| Admin | ✅ | ✅ | ✅ |

---

*Last updated: 2026-03-15*
