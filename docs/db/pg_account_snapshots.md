> 정책: 항상 200줄 이내를 유지한다.

# account_snapshots

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `account_snapshots` |
| 역할 | 계좌 PnL 스냅샷. 실현/미실현 손익, 포지션 시가, 총자산 기록. |
| 사용 여부 | ✅ 활성 — orchestrator 사이클 종료 시 기록, API 대시보드 차트 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| account_scope | VARCHAR(10) | paper / real / virtual |
| cash_balance | BIGINT | 현금 잔고 |
| position_market_value | BIGINT | 포지션 시가 |
| total_equity | BIGINT | 총 자산 |
| realized_pnl | BIGINT | 실현 손익 |
| unrealized_pnl | BIGINT | 미실현 손익 |
| position_count | INTEGER | 보유 종목 수 |
| strategy_id | VARCHAR(10) | 전략 ID |
| snapshot_at | TIMESTAMPTZ | 스냅샷 시각 |

## 테이블 관계

- → `trading_accounts(account_scope)` 논리적 참조
