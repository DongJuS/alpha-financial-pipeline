> 정책: 항상 200줄 이내를 유지한다.

# tick_data

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db / alpha_gen_db |
| 테이블 | `tick_data` |
| 역할 | 실시간 틱 데이터. KIS WebSocket에서 수집. PARTITION BY RANGE(timestamp_kst). |
| 사용 여부 | ✅ 활성 — collector_realtime, tick_collector에서 적재 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| instrument_id | VARCHAR(20) PK | 종목 ID |
| timestamp_kst | TIMESTAMPTZ PK | KST 타임스탬프 |
| price | INTEGER | 체결가 |
| volume | INTEGER | 체결량 |
| change_pct | NUMERIC(8,4) | 변동률 |
| source | VARCHAR(20) | 소스 (kis_ws 기본) |

## 파티셔닝

- PARTITION BY RANGE(timestamp_kst) — 시간별 파티션

## 테이블 관계

- → `instruments(instrument_id)` 논리적 참조
- 집계: queries.py에서 5min/15min/1h 분봉으로 GROUP BY 집계
