> 정책: 항상 200줄 이내를 유지한다.

# ticker_master

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `ticker_master` |
| 역할 | 정규화 티커 통합 관리. canonical(005930.KS) ↔ raw_code(005930) 매핑. |
| 사용 여부 | ✅ 활성 — 시드 20개 core 종목 포함 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| canonical | VARCHAR(20) PK | 정규화 티커 (005930.KS) |
| raw_code | VARCHAR(10) | 원본 코드 (005930) |
| name | TEXT | 종목명 |
| market | VARCHAR(20) | 시장 (KOSPI, KOSDAQ) |
| suffix | VARCHAR(5) | 접미사 (KS, KQ) |
| asset_type | VARCHAR(10) | stock/etf/etn/index/commodity/currency/rate |
| is_active | BOOLEAN | 활성 여부 |

## 테이블 관계

- 독립 마스터 (instruments, krx_stock_master와 별도)
- UNIQUE: raw_code WHERE is_active = TRUE
