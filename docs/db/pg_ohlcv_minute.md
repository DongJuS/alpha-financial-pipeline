> 정책: 항상 200줄 이내를 유지한다.

# ohlcv_minute

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db / alpha_gen_db |
| 테이블 | `ohlcv_minute` |
| 역할 | 1분봉 집계 테이블. tick_data에서 1분 단위로 OHLCV+VWAP+trade_count 집계. PARTITION BY RANGE(bucket_at) 월별 분할. |
| 사용 여부 | ✅ 활성 — 15:50 KST 배치 크론잡으로 매일 집계 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| instrument_id | VARCHAR(20) PK | 종목 ID |
| bucket_at | TIMESTAMPTZ PK | 분봉 시각 |
| open | INTEGER | 시가 |
| high | INTEGER | 고가 |
| low | INTEGER | 저가 |
| close | INTEGER | 종가 |
| volume | BIGINT | 거래량 |
| trade_count | INTEGER | 체결 건수 |
| vwap | NUMERIC(15,2) | 거래량 가중 평균 가격 |

## 파티셔닝

- PARTITION BY RANGE(bucket_at) — 월별 파티션
- 초기: `ohlcv_minute_2026_04` ~ `ohlcv_minute_2026_06`

## 테이블 관계

- → `instruments(instrument_id)` 논리적 참조
- 소스: `tick_data`에서 `aggregate_ticks_to_minutes()`로 집계

## 관련 파일

- `src/db/queries.py` — aggregate_ticks_to_minutes(), fetch_minute_bars()
- `src/schedulers/unified_scheduler.py` — minute_aggregation 크론잡
- `scripts/db/migrate_ohlcv_minute.py` — 테이블 생성 마이그레이션
