> 정책: 항상 200줄 이내를 유지한다.

# ohlcv_daily

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db / alpha_gen_db |
| 테이블 | `ohlcv_daily` |
| 역할 | 일봉 OHLCV 데이터. PARTITION BY RANGE(traded_at)로 연도별 분할. |
| 사용 여부 | ✅ 활성 — collector, screener, RL, backtest에서 핵심 사용 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| instrument_id | VARCHAR(20) PK | 종목 ID |
| traded_at | DATE PK | 거래일 |
| open/high/low/close | NUMERIC(15,4) | OHLC 가격 |
| volume | BIGINT | 거래량 |
| change_pct | NUMERIC(8,4) | 전일 대비 변동률 |
| market_cap | BIGINT | 시가총액 |
| foreign_ratio | NUMERIC(5,2) | 외국인 비율 |
| adj_close | NUMERIC(15,4) | 수정 종가 |

## 파티셔닝

- `ohlcv_daily_2010` ~ `ohlcv_daily_2027` (연도별)
- `ohlcv_daily_default` (범위 밖 데이터)

## 테이블 관계

- → `instruments(instrument_id)` 논리적 참조
- JOIN: queries.py에서 `instruments` 와 JOIN하여 이름/시장 정보 조회
