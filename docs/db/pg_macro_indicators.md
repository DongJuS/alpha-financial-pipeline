> 정책: 항상 200줄 이내를 유지한다.

# macro_indicators

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `macro_indicators` |
| 역할 | 거시경제 지표. 해외지수/환율/원자재/금리 일별 스냅샷. |
| 사용 여부 | ✅ 활성 — macro_collector에서 수집, 전략 LLM 입력용 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| category | VARCHAR(30) | index / currency / commodity / rate |
| symbol | VARCHAR(30) | 심볼 (DJI, USD/KRW 등) |
| name | TEXT | 지표 이름 |
| value | NUMERIC(18,4) | 현재값 |
| change_pct | NUMERIC(8,4) | 변동률 |
| snapshot_date | DATE | 스냅샷 날짜 |
| source | VARCHAR(30) | 소스 (fdr 기본) |

## 테이블 관계

- 독립 테이블 (FK 없음)
- UNIQUE: (symbol, snapshot_date)
