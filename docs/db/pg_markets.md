> 정책: 항상 200줄 이내를 유지한다.

# markets

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db / alpha_gen_db |
| 테이블 | `markets` |
| 역할 | 시장 메타데이터 (KOSPI/KOSDAQ/NYSE/NASDAQ). 시드 4건 고정. |
| 사용 여부 | ✅ 활성 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| market_id | VARCHAR(10) PK | 시장 ID (KOSPI, KOSDAQ 등) |
| name | TEXT | 시장 이름 |
| country | VARCHAR(3) | 국가 코드 (KR, US) |
| timezone | VARCHAR(30) | 타임존 |
| currency | VARCHAR(5) | 통화 (KRW, USD) |
| open_time / close_time | TIME | 장 시작/종료 시각 |
| data_source | VARCHAR(20) | 데이터 소스 (fdr) |
| is_active | BOOLEAN | 활성 여부 |

## 테이블 관계

- ← `instruments.market_id` FK 참조됨
- ← `ohlcv_daily` → instruments 경유 간접 참조
