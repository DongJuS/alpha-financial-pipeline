> 정책: 항상 200줄 이내를 유지한다.

# instruments

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db / alpha_gen_db |
| 테이블 | `instruments` |
| 역할 | 정규화된 종목 마스터. 코드, 이름, 섹터, 산업, 시가총액, 상장/폐지일 관리. |
| 사용 여부 | ✅ 활성 — queries.py에서 ohlcv_daily JOIN 시 사용 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| instrument_id | VARCHAR(20) PK | 정규화 ID (예: 005930.KS) |
| raw_code | VARCHAR(15) | 원본 종목코드 (005930) |
| name / name_en | TEXT | 한글/영문 이름 |
| market_id | VARCHAR(10) FK | → markets.market_id |
| sector / industry | TEXT | 섹터/산업 분류 |
| asset_type | VARCHAR(10) | stock, etf, etn, index 등 |
| market_cap | BIGINT | 시가총액 |
| is_active | BOOLEAN | 활성 여부 |

## 테이블 관계

- → `markets(market_id)` FK
- ← `ohlcv_daily(instrument_id)` 데이터 참조
- ← `tick_data(instrument_id)` 데이터 참조
- UNIQUE: (market_id, raw_code)
