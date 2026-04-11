> 정책: 항상 200줄 이내를 유지한다.

# krx_stock_master

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `krx_stock_master` |
| 역할 | KRX 전종목 + ETF/ETN 마스터. 마켓플레이스 API의 종목 조회 기반. |
| 사용 여부 | ✅ 활성 — marketplace_queries.py 핵심 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| ticker | VARCHAR(10) PK | 종목코드 |
| name | TEXT | 종목명 |
| market | VARCHAR(10) | KOSPI / KOSDAQ / KONEX |
| sector / industry | VARCHAR | 섹터 / 산업 |
| market_cap | BIGINT | 시가총액 |
| is_etf / is_etn | BOOLEAN | ETF/ETN 여부 |
| tier | VARCHAR(10) | core / extended / universe |
| is_active | BOOLEAN | 활성 여부 |

## 테이블 관계

- ← `theme_stocks(ticker)` JOIN
- ← `watchlist(ticker)` JOIN
- 독립 마스터 (instruments와 별도 운영)
