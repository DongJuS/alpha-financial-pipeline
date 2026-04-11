> 정책: 항상 200줄 이내를 유지한다.

# daily_rankings

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `daily_rankings` |
| 역할 | 일별 사전 계산 랭킹. 시총/거래량/상승률/하락률 등 7개 유형. |
| 사용 여부 | ✅ 활성 — ranking_calculator에서 생성, API 마켓 화면 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| ranking_date | DATE | 랭킹 날짜 |
| ranking_type | VARCHAR(30) | market_cap/volume/turnover/gainer/loser/new_high/new_low |
| rank | INTEGER | 순위 (1부터) |
| ticker | VARCHAR(10) | 종목코드 |
| name | TEXT | 종목명 |
| value | NUMERIC(18,4) | 랭킹 기준 값 |
| change_pct | NUMERIC(8,4) | 변동률 |
| extra | JSONB | 추가 데이터 |

## 테이블 관계

- → `krx_stock_master(ticker)` 논리적 참조
- UNIQUE: (ranking_date, ranking_type, rank)
