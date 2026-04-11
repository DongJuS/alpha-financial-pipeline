> 정책: 항상 200줄 이내를 유지한다.

# trading_accounts

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `trading_accounts` |
| 역할 | 계좌 메타데이터. paper/real/virtual 계좌별 잔고, 매수력, 총자산 관리. |
| 사용 여부 | ✅ 활성 — portfolio_manager, broker에서 잔고 동기화 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| account_scope | VARCHAR(10) PK | paper / real / virtual |
| broker_name | TEXT | 브로커명 (한국투자증권 KIS) |
| seed_capital | BIGINT | 시드 자본금 |
| cash_balance | BIGINT | 현금 잔고 |
| buying_power | BIGINT | 매수 가능 금액 |
| total_equity | BIGINT | 총 자산 |
| strategy_id | VARCHAR(10) | 전략별 계좌 분리 시 사용 |
| is_active | BOOLEAN | 활성 여부 |

## 테이블 관계

- ← `portfolio_positions(account_scope)` — 동일 scope 포지션
- ← `trade_history(account_scope)` — 동일 scope 거래
- ← `broker_orders(account_scope)` — 동일 scope 주문
- ← `account_snapshots(account_scope)` — 동일 scope 스냅샷
