> 정책: 항상 200줄 이내를 유지한다.

# market_data

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db / alpha_gen_db |
| 테이블 | `market_data` |
| 역할 | 레거시 OHLCV+틱 통합 테이블. daily/tick 구분을 interval 컬럼으로 처리. |
| 사용 여부 | 🔄 레거시 — ohlcv_daily + tick_data로 마이그레이션 예정. 일부 코드에서 아직 참조. |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 ID |
| ticker | VARCHAR(10) | 종목코드 |
| name | TEXT | 종목명 |
| market | VARCHAR(10) | KOSPI / KOSDAQ |
| timestamp_kst | TIMESTAMPTZ | KST 타임스탬프 |
| interval | VARCHAR(10) | daily / tick |
| open/high/low/close | INTEGER | OHLC 가격 |
| volume | BIGINT | 거래량 |
| change_pct | NUMERIC(6,3) | 변동률 |

## 테이블 관계

- 독립 테이블 (FK 없음)
- 대체: `ohlcv_daily` (daily), `tick_data` (tick)

## 비고

- collector, gen_collector, rl_trading 등 12개 파일에서 아직 참조
- 신규 코드는 ohlcv_daily/tick_data 사용 권장
