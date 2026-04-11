> 정책: 항상 200줄 이내를 유지한다.

# portfolio_positions

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `portfolio_positions` |
| 역할 | 현재 보유 포지션. 종목별 수량, 평균 매입가, 현재가 관리. |
| 사용 여부 | ✅ 활성 — portfolio_manager, API 대시보드 핵심 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| ticker | VARCHAR(10) | 종목코드 |
| name | TEXT | 종목명 |
| quantity | INTEGER | 보유 수량 |
| avg_price | INTEGER | 평균 매입가 |
| current_price | INTEGER | 현재가 |
| account_scope | VARCHAR(10) | paper / real / virtual |
| strategy_id | VARCHAR(10) | 전략 ID (독립 포트폴리오 모드) |

## 테이블 관계

- → `trading_accounts(account_scope)` 논리적 참조
- UNIQUE: (ticker, account_scope, COALESCE(strategy_id, ''))
