> 정책: 항상 200줄 이내를 유지한다.

# backtest_daily

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `backtest_daily` |
| 역할 | 백테스트 일별 스냅샷. 일자별 포트폴리오 가치, 포지션, 일일 수익률. |
| 사용 여부 | ✅ 활성 — backtest/repository.py |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| run_id | BIGINT FK | → backtest_runs.id |
| date | DATE | 날짜 |
| close_price | NUMERIC(15,4) | 종가 |
| cash | NUMERIC(15,2) | 현금 |
| position_qty | INTEGER | 보유 수량 |
| position_value | NUMERIC(15,2) | 포지션 가치 |
| portfolio_value | NUMERIC(15,2) | 총 포트폴리오 가치 |
| daily_return_pct | NUMERIC(10,6) | 일일 수익률 |

## 테이블 관계

- → `backtest_runs(id)` FK
- UNIQUE: (run_id, date)
