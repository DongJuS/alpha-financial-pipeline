> 정책: 항상 200줄 이내를 유지한다.

# theme_stocks

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `theme_stocks` |
| 역할 | 테마 → 종목 매핑. 테마별 대장주(is_leader) 표시. |
| 사용 여부 | ✅ 활성 — marketplace_queries에서 테마 조회 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| theme_slug | VARCHAR(60) | 테마 슬러그 |
| theme_name | TEXT | 테마 이름 |
| ticker | VARCHAR(10) | 종목코드 |
| is_leader | BOOLEAN | 대장주 여부 |

## 테이블 관계

- → `krx_stock_master(ticker)` LEFT JOIN
- UNIQUE: (theme_slug, ticker)
