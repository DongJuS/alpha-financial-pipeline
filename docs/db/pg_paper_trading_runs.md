> 정책: 항상 200줄 이내를 유지한다.

# paper_trading_runs

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `paper_trading_runs` |
| 역할 | 페이퍼 트레이딩 장기 검증 이력. baseline/high_volatility/load 시나리오 결과. |
| 사용 여부 | ✅ 활성 — orchestrator에서 모의투자 회차 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| scenario | VARCHAR(30) | baseline / high_volatility / load |
| simulated_days | INTEGER | 시뮬레이션 일수 |
| start_date / end_date | DATE | 시작/종료일 |
| trade_count | INTEGER | 거래 횟수 |
| return_pct | NUMERIC(7,3) | 수익률 |
| max_drawdown_pct | NUMERIC(7,3) | 최대 낙폭 |
| sharpe_ratio | NUMERIC(10,4) | 샤프 비율 |
| passed | BOOLEAN | 통과 여부 |
| report | JSONB | 상세 리포트 |

## 테이블 관계

- 독립 테이블 (FK 없음)
