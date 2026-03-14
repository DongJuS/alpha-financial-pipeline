# 🤖 AGENTS.md — 에이전트 종류·역할 분담 정의

> 이 파일은 시스템의 모든 에이전트에 대한 정식 명세입니다.
> 각 에이전트는 자신의 역할과 다른 에이전트와의 상호작용 규칙을 이 파일에서 확인합니다.

---

## 🗺️ 시스템 에이전트 맵

| 에이전트 | 역할 | 트리거 | 출력 채널 |
|----------|------|--------|-----------|
| `CollectorAgent` | 시장 데이터 수집 | 크론: 09:00–15:30 KST | `redis:topic:market_data` |
| `PredictorAgent` | LLM 기반 가격 예측 | 이벤트: `data_ready` | `redis:topic:signals` |
| `PortfolioManagerAgent` | 포트폴리오 관리 및 주문 실행 | 이벤트: `signal` | `redis:topic:orders` |
| `NotifierAgent` | Telegram 알림 발송 | 이벤트: 모든 주요 이벤트 | Telegram Bot |
| `OrchestratorAgent` | 전체 워크플로우 조율 | 크론 + 이벤트 | 모든 채널 |
| `FastFlowAgent` | 빠른 전체 흐름 설계 | API 요청: `dual_execution` | API 응답 + heartbeat |
| `SlowMeticulousAgent` | 꼼꼼한 상세 검증 계획 작성 | API 요청: `dual_execution` | API 응답 + heartbeat |

---

## 1. CollectorAgent (수집기)

### 역할
한국 주식시장(KOSPI/KOSDAQ) 데이터를 수집하여 PostgreSQL과 Redis에 저장합니다.
데이터 해석은 하지 않으며, 오직 수집과 저장만 담당합니다.

### 데이터 소스
| 소스 | 용도 | 비용 |
|------|------|------|
| FinanceDataReader (`fdr`) | KOSPI/KOSDAQ EOD OHLCV | 무료 |
| KIS Developers WebSocket | 장중 실시간 틱 데이터 | 무료 (계좌 필요) |
| KRX 정보데이터시스템 | 휴장일 캘린더, 종목 기준정보 | 무료 |

### 수집 스케줄
| 시간 (KST) | 작업 |
|------------|------|
| 08:30 | 전일 OHLCV 일봉 수집 (fdr) |
| 09:00–15:30 | 실시간 틱 스트림 (KIS WebSocket, 30초 집계) |
| 15:40 | 당일 마감 데이터 저장 및 `data_ready` 이벤트 발행 |
| 00:00 | KRX 휴장일 캘린더 갱신 |

### 데이터 스키마
```json
{
  "ticker": "005930",
  "name": "삼성전자",
  "market": "KOSPI",
  "timestamp_kst": "2026-03-12T15:30:00+09:00",
  "open": 72000,
  "high": 73500,
  "low": 71800,
  "close": 73000,
  "volume": 12345678,
  "change_pct": 1.39,
  "market_cap": 4356000000000,
  "foreigner_ratio": 52.3
}
```

### 에러 처리
- API 레이트 리밋 도달 시: fdr 캐시로 폴백, `collector_errors` 테이블에 로깅
- 장 휴장일: 수집 작업 스킵 (Redis `krx:holidays:{year}` 확인 후 판단)
- WebSocket 연결 끊김: 3회 자동 재연결 후 실패 시 OrchestratorAgent에 알림

---

## 2. PredictorAgent (예측 분석가)

### 역할
수집된 시장 데이터를 기반으로 LLM을 활용하여 가격 방향성과 매매 시그널을 예측합니다.
**Strategy A (Tournament)**와 **Strategy B (Consensus)** 두 모드로 동작합니다.

### Strategy A — Tournament Mode

매일 **5개 인스턴스**가 병렬 실행되며, LLM 다양성을 위해 서로 다른 모델을 사용합니다.

| 인스턴스 | LLM | 연동 방식 | 투자 성향 |
|----------|-----|-----------|-----------|
| Predictor-1 | Claude (claude-sonnet-4-6) | CLI | 가치 투자형 |
| Predictor-2 | Claude (claude-sonnet-4-6) | CLI | 기술적 분석형 |
| Predictor-3 | GPT-4o | OAuth (API Key) | 모멘텀형 |
| Predictor-4 | GPT-4o | OAuth (API Key) | 역추세형 |
| Predictor-5 | Gemini 1.5 Pro | CLI | 거시경제형 |

**토너먼트 평가 로직:**
- 매 장 마감 후 OrchestratorAgent가 각 인스턴스의 예측 방향 vs 실제 종가 비교
- 최근 5거래일 누적 정확도가 가장 높은 인스턴스의 시그널이 다음 날 거래에 사용됨
- 점수 저장 테이블: `predictor_tournament_scores`

### Strategy B — Consensus/Debate Mode

4개의 LLM 역할이 구조화된 토론을 통해 합의된 시그널을 도출합니다.

| 역할 | LLM | 담당 |
|------|-----|------|
| Proposer | Claude | 초기 투자 논거 제시 |
| Challenger 1 | GPT-4o | 반론 제기 (매수 논거에 매도 관점) |
| Challenger 2 | Gemini | 반론 제기 (거시/리스크 관점) |
| Synthesizer | Claude | 토론 종합 및 최종 합의 도출 |

**토론 프로토콜:**
1. Proposer가 종목별 매매 논거 JSON 제시 (max 500 tokens)
2. Challenger 1, 2가 순서대로 반론 (max 300 tokens each)
3. Proposer가 반론에 대한 재반박 (max 200 tokens)
4. Synthesizer가 전체 토론 요약 후 최종 시그널 결정
- 최대 3라운드, 합의 threshold: 75%
- 10분 내 합의 실패 시: HOLD 출력 (사유: `no_consensus`)

### 예측 출력 스키마
```json
{
  "agent_id": "predictor_3",
  "llm_model": "gpt-4o",
  "strategy": "A",
  "ticker": "005930",
  "signal": "BUY",
  "confidence": 0.78,
  "target_price": 75000,
  "stop_loss": 71000,
  "reasoning_summary": "5일 이동평균 돌파, 외국인 순매수 전환",
  "debate_transcript_id": null,
  "timestamp_utc": "2026-03-12T00:45:00Z"
}
```

### LLM 컨텍스트 주입 (모든 예측 호출 시 자동 포함)
1. 최근 30거래일 OHLCV (해당 종목)
2. 현재 포트폴리오에서의 해당 종목 보유 현황
3. 이 예측 인스턴스의 최근 5일 정확도 점수 (자기 인식)
4. 거시 컨텍스트 (Redis `memory:macro_context` 키)

---

## 3. PortfolioManagerAgent (운용역)

### 역할
Strategy A와 Strategy B의 시그널을 받아 KIS API를 통해 실제(또는 페이퍼) 주문을 실행합니다.
**이 에이전트만이 `kis_place_order` 도구를 사용할 수 있습니다.**

### 시그널 처리
- Strategy A 시그널 가중치: `STRATEGY_BLEND_RATIO`의 `(1 - ratio)` 비율
- Strategy B 시그널 가중치: `STRATEGY_BLEND_RATIO`의 `ratio` 비율
- 기본값: 50/50 블렌드

### 하드코딩된 리스크 규칙 (LLM이 오버라이드 불가)
| 규칙 | 값 |
|------|-----|
| 최대 단일 종목 비중 | 포트폴리오의 20% |
| 일일 손실 서킷브레이커 | -3% 도달 시 당일 거래 전면 중단 |
| 공매도 | 페이퍼 모드에서 절대 금지 |
| 최소 주문 단위 | 1주 |

### 주문 유형
- 시장가 주문 (즉시 체결)
- 지정가 주문 (현재가 ±1% 범위)
- 손절가 주문 (stop-loss)

### 상태 영속성
- 현재 보유 포지션: PostgreSQL `portfolio_positions` 테이블
- KIS OAuth 토큰: Redis `kis:oauth_token` (매일 06:00 KST 갱신)

---

## 4. NotifierAgent (알리미)

### 역할
시스템의 주요 이벤트를 Telegram을 통해 사용자에게 알립니다.
사용자 친화적인 한국어 메시지를 전송합니다.

### 알림 이벤트 및 채널
| 이벤트 | 발송 시간 | 내용 |
|--------|-----------|------|
| 아침 브리핑 | 08:30 KST | 오늘의 시장 전망, Strategy A/B 예측 요약, 오늘의 감시 종목 |
| 거래 체결 알림 | 즉시 | 종목, 수량, 가격, 매매 사유 요약 |
| 서킷브레이커 발동 | 즉시 | 일일 손실 한도 도달, 거래 중단 알림 |
| 에이전트 장애 알림 | 즉시 | 장애 발생 에이전트, 재시작 여부 |
| 일일 결산 리포트 | 16:30 KST | 당일 P&L, 토너먼트 우승 에이전트, Strategy A vs B 비교 |
| 주간 성과 요약 | 매주 금요일 17:00 KST | 주간 수익률, 전략별 성과, 다음 주 전망 |

### 메시지 형식 규칙
- 언어: 한국어
- 금액: 원화(₩) 표시, 1000단위 콤마
- 수익률: 소수점 2자리 (예: +1.39%)
- 레이트 리밋: 채널당 시간당 최대 10건

---

## 5. OrchestratorAgent (지휘자)

### 역할
전체 시스템의 상태 기계(State Machine)로서 모든 에이전트의 워크플로우를 조율합니다.
투자 의견을 가지지 않으며, 워크플로우 실행만 담당합니다.

### Strategy A 일일 라이프사이클
```
08:45 → PredictorAgent 5개 인스턴스 spawn
09:00 → 장 시작, CollectorAgent 실시간 수집 시작
15:30 → 장 마감
15:35 → 각 예측 인스턴스 성과 평가 (토너먼트 스코어링)
15:40 → 우승 인스턴스 시그널 → PortfolioManagerAgent 전달
15:41 → 결과 → NotifierAgent 전달
```

### Strategy B 일일 라이프사이클
```
08:30 → 토론 세션 시작 (Proposer: Claude)
08:30–08:55 → 최대 3라운드 토론 실행
08:55 → 합의 시그널 → PortfolioManagerAgent 전달
08:56 → 토론 요약 → NotifierAgent 전달
09:00 → 장 시작과 동시에 주문 실행 준비 완료
```

### 헬스 모니터링
- 각 에이전트 heartbeat 폴링 간격: 60초
- 연속 3회 heartbeat 미수신: NotifierAgent 알림 + 프로세스 재시작 시도
- LangGraph StateGraph + Redis 체크포인팅으로 상태 영속화

---

## 6. FastFlowAgent + SlowMeticulousAgent (듀얼 실행)

### 역할
- `FastFlowAgent`: 작업의 전체 흐름을 빠르게 파악하고 우선순위를 제시
- `SlowMeticulousAgent`: 누락 방지를 위해 상세 단계, 검증 게이트, 리스크를 보강

### 실행 순서
1. `/api/v1/agents/dual-execution/run` 호출
2. FastFlowAgent 결과 생성 (요약/우선순위/빠른 리스크)
3. SlowMeticulousAgent 결과 생성 (상세 단계/검증 체크)
4. 통합 실행 계획 응답 + 두 에이전트 heartbeat 기록

### 운영 원칙
- 속도와 품질을 분리해 처리: Fast는 방향, Slow는 검증
- 결과 충돌 시 검증 게이트를 통과하는 보수적 안을 채택
- 작업 완료 시 변경 의도와 검증 결과가 포함된 상세 커밋 메시지를 남김

---

## 📨 에이전트 간 메시지 컨트랙트

모든 에이전트는 아래 JSON 봉투(envelope) 형식을 준수합니다.

```json
{
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "sender": "collector_agent",
  "recipient": "predictor_agent | broadcast",
  "topic": "market_data | signal | order | heartbeat | alert",
  "payload": {},
  "timestamp_utc": "2026-03-12T00:30:00Z",
  "strategy_context": "A | B | system"
}
```

### Redis 채널 네이밍 규칙
| 채널 | 발행자 | 구독자 |
|------|--------|--------|
| `redis:topic:market_data` | CollectorAgent | PredictorAgent, OrchestratorAgent |
| `redis:topic:signals` | PredictorAgent | OrchestratorAgent, PortfolioManagerAgent |
| `redis:topic:orders` | PortfolioManagerAgent | OrchestratorAgent, NotifierAgent |
| `redis:topic:heartbeat` | 모든 에이전트 | OrchestratorAgent |
| `redis:topic:alerts` | OrchestratorAgent | NotifierAgent |

---

## 7. 확장 예정 에이전트 (통합 테스트 진행 중)

이 섹션의 에이전트들은 현재 코어 트레이딩 런타임을 대체하지 않습니다.
기존 Strategy A / Strategy B / PortfolioManager / paper-real 실행 구조를 유지한 채, 확장 레이어로 추가됩니다.

### 7-1. 5-Agent 의사결정 계층

이 계층은 RL Trading과 Search/Scraping 확장을 설계하거나 우선순위를 정할 때 사용합니다.
운영 주문을 실행하지 않으며, `PortfolioManagerAgent`의 주문 권한에도 영향을 주지 않습니다.

| 에이전트 | 성향 | 주요 책임 | 기본 산출물 |
|----------|------|-----------|-------------|
| `FastFlowAgent` | 빠르지만 구조 중심 | 작업을 큰 덩어리로 나누고 의존 관계를 빠르게 정리 | 초기 실행 순서, 구조도, 병렬화 후보 |
| `SlowMeticulousAgent` | 꼼꼼하지만 느림 | 누락 가능성이 큰 제약과 검증 게이트를 보강 | 상세 체크리스트, 검증 조건, 실패 기준 |
| `OptimistAgent` | 낙관적 | 새 기능이 만들 수 있는 기회와 확장 여지를 최대한 발굴 | 빠른 실험안, 조기 가치 창출 포인트 |
| `PessimistAgent` | 비관적 | 장애, 데이터 오염, 과적합, 운영 사고 가능성을 집중 점검 | 리스크 목록, 차단 조건, 보수적 대안 |
| `DecisionDirectorAgent` | 최종 의사결정 | 상충하는 의견을 종합해 기본 개발 방향과 단계별 우선순위를 선택 | 결정문, 채택 이유, 보류 사안 |

운영 원칙:
- `DecisionDirectorAgent`는 방향을 고정하지만, 주문 실행 권한을 갖지 않습니다.
- 의견 충돌 시 `SlowMeticulousAgent`와 `PessimistAgent`가 제시한 차단 조건을 먼저 확인합니다.
- 빠른 추진이 가능하더라도 추적 가능성, 재현성, 출처 저장이 확보되지 않으면 통합 단계로 승격하지 않습니다.

### 7-2. RL Trading 확장 예정 에이전트

아래 에이전트들은 RL lane을 분리된 학습/평가/정책 계층으로 편입하기 위한 계획안입니다.

| 에이전트 | 상태 | 역할 |
|----------|------|------|
| `rl_data_builder_agent` | planned | 시장 데이터, 포트폴리오 상태, 연구 추출 결과를 RL 학습용 feature dataset으로 변환 |
| `rl_trainer_agent` | planned | 환경 정의와 정책 학습 실행, 모델 artifact/version 생성 |
| `rl_evaluator_agent` | planned | 백테스트, out-of-sample 검증, 리스크 지표 평가 |
| `rl_policy_agent` | planned | 승인된 정책을 inference 전용으로 로드해 시그널 후보 생성 |

주의:
- RL 정책은 직접 브로커를 호출하지 않습니다.
- RL 신호도 기존 리스크 가드와 `PortfolioManagerAgent`를 통과해야만 주문 단계로 이동합니다.

### 7-3. Search/Scraping 확장 예정 에이전트

아래 에이전트들은 검색과 스크래핑 파이프라인을 기존 전략의 보조 연구 레이어로 붙이기 위한 계획안입니다.

| 에이전트 | 상태 | 역할 |
|----------|------|------|
| `search_query_agent` | planned | 종목/테마별 검색 질의 생성, SearXNG 호출, 후보 URL 수집 |
| `scrape_worker_agent` | planned | 웹 페이지 fetch/render 후 ScrapeGraphAI로 구조화 데이터 생성 |
| `claude_extraction_agent` | planned | 구조화된 페이지 내용을 요약, 근거 추출, 전략/RL용 feature로 정리 |

검색 파이프라인 원칙:
- Tavily는 사용하지 않습니다.
- 검색 흐름은 `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI -> Claude CLI`를 따릅니다.
- 검색 결과는 출처와 추출 결과를 함께 저장해 추후 감사가 가능해야 합니다.

*Last updated: 2026-03-14*
