> 정책: 항상 200줄 이내를 유지한다.

# Redis 캐시 키 + Pub/Sub

| 항목 | 내용 |
|------|------|
| 종류 | Redis 7 |
| DB | redis:6379/0 |
| 역할 | 핫 데이터 캐시, 에이전트 상태 추적, Pub/Sub 메시징 |
| 사용 여부 | ✅ 활성 |

## 캐시 키 패턴

| 키 패턴 | TTL | 용도 |
|---------|-----|------|
| `heartbeat:{agent_id}` | 90초 | 에이전트 생존 신호 (Hash) |
| `kis:oauth_token:{scope}` | 23시간 | KIS API OAuth 토큰 |
| `krx:holidays:{year}` | 24시간 | KRX 휴장일 캘린더 |
| `redis:cache:latest_ticks:{ticker}` | 60초 | 최근 틱 |
| `redis:cache:realtime_series:{ticker}` | 1시간 | 실시간 시계열 |
| `redis:cache:krx_stock_master` | 24시간 | 전종목 마스터 |
| `redis:cache:macro:{category}` | 1시간 | 거시경제 지표 |
| `redis:cache:market_index` | 120초 | KOSPI/KOSDAQ 지수 |
| `memory:macro_context` | 4시간 | 거시경제 컨텍스트 (LLM 입력) |
| `redis:usage:llm:{provider}:{date}` | 24시간 | LLM 일일 사용량 |

## Pub/Sub 채널

| 채널 | 발행자 | 구독자 | 용도 |
|------|--------|--------|------|
| `redis:topic:market_data` | CollectorAgent | OrchestratorAgent | 시장 데이터 수집 완료 |
| `redis:topic:signals` | PredictorAgent | PortfolioManagerAgent | 예측 시그널 전달 |
| `redis:topic:orders` | PortfolioManagerAgent | NotifierAgent | 주문 결과 알림 |
| `redis:topic:heartbeat` | 모든 에이전트 | 모니터링 | 상태 공지 |
| `redis:topic:alerts` | NotifierAgent | Telegram 봇 | 외부 알림 |

## 테이블 관계

- `heartbeat:{agent_id}` ↔ PostgreSQL `agent_heartbeats` (이중 기록)
- `redis:cache:krx_stock_master` ↔ PostgreSQL `krx_stock_master` (캐시)
- `redis:cache:macro:*` ↔ PostgreSQL `macro_indicators` (캐시)
