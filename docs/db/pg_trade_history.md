> 정책: 항상 200줄 이내를 유지한다.

# trade_history

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `trade_history` |
| 역할 | 거래 이력. 매수/매도 체결 기록, 시그널 출처, 블렌딩 메타 포함. |
| 사용 여부 | ✅ 활성 — portfolio_manager, API, backtest 핵심 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| ticker | VARCHAR(10) | 종목코드 |
| side | VARCHAR(4) | BUY / SELL |
| quantity | INTEGER | 체결 수량 |
| price | INTEGER | 체결가 |
| amount | BIGINT | 체결 금액 (price × quantity) |
| signal_source | VARCHAR(10) | A/B/BLEND/RL/S/L/EXIT/VIRTUAL |
| account_scope | VARCHAR(10) | paper / real / virtual |
| strategy_id | VARCHAR(10) | 전략 ID |
| blend_meta | JSONB | N-way 블렌딩 참여 전략/가중치 |
| circuit_breaker | BOOLEAN | 서킷브레이커 강제 청산 여부 |

## 테이블 관계

- → `trading_accounts(account_scope)` 논리적 참조
- → `predictions` — signal_source로 출처 전략 추적
