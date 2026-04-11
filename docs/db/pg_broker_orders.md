> 정책: 항상 200줄 이내를 유지한다.

# broker_orders

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `broker_orders` |
| 역할 | 브로커 주문 이력. PENDING → FILLED/REJECTED/CANCELLED 상태 전이. |
| 사용 여부 | ✅ 활성 — virtual_broker, KIS broker에서 주문 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| client_order_id | TEXT UNIQUE | 클라이언트 주문 ID |
| account_scope | VARCHAR(10) | paper / real / virtual |
| ticker | VARCHAR(10) | 종목코드 |
| side | VARCHAR(4) | BUY / SELL |
| order_type | VARCHAR(10) | MARKET / LIMIT |
| requested_quantity | INTEGER | 요청 수량 |
| filled_quantity | INTEGER | 체결 수량 |
| status | VARCHAR(16) | PENDING/FILLED/REJECTED/CANCELLED |
| signal_source | VARCHAR(10) | A/B/BLEND/RL/S/L/EXIT/VIRTUAL |
| blend_meta | JSONB | 블렌딩 메타데이터 |
| strategy_id | VARCHAR(10) | 전략 ID |

## 테이블 관계

- → `trading_accounts(account_scope)` 논리적 참조
- → `trade_history` — 체결 시 trade_history에 기록 생성
