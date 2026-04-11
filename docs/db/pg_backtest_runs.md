> 정책: 항상 200줄 이내를 유지한다.

# backtest_runs

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `backtest_runs` |
| 역할 | 백테스트 실행 메타데이터. 전략/기간/수익률/샤프비율 등 요약. |
| 사용 여부 | ✅ 활성 — backtest/repository.py, API backtest 라우터 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| ticker | VARCHAR(10) | 종목코드 |
| strategy | VARCHAR(10) | 전략명 |
| train_start / train_end | DATE | 학습 기간 |
| test_start / test_end | DATE | 테스트 기간 |
| initial_capital | INTEGER | 초기 자본 |
| total_return_pct | NUMERIC(10,4) | 총 수익률 |
| sharpe_ratio | NUMERIC(10,4) | 샤프 비율 |
| max_drawdown_pct | NUMERIC(10,4) | 최대 낙폭 |
| excess_return_pct | NUMERIC(10,4) | 초과 수익률 |

## 테이블 관계

- ← `backtest_daily(run_id)` FK
