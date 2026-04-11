> 정책: 항상 200줄 이내를 유지한다.

# watchlist

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `watchlist` |
| 역할 | 사용자 관심 종목. 그룹별 관리, 가격 알림 상/하한 설정 가능. |
| 사용 여부 | ✅ 활성 — marketplace_queries에서 CRUD |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| user_id | UUID FK | → users.id |
| group_name | VARCHAR(60) | 그룹 이름 (기본 'default') |
| ticker | VARCHAR(10) | 종목코드 |
| name | TEXT | 종목명 |
| price_alert_above | INTEGER | 상한 알림 가격 |
| price_alert_below | INTEGER | 하한 알림 가격 |

## 테이블 관계

- → `users(id)` FK (ON DELETE CASCADE)
- → `krx_stock_master(ticker)` LEFT JOIN
- UNIQUE: (user_id, group_name, ticker)
