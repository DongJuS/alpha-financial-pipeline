> 정책: 항상 200줄 이내를 유지한다.

# users

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `users` |
| 역할 | 대시보드 사용자 인증. UUID PK, bcrypt 해시 패스워드. |
| 사용 여부 | ✅ 활성 — auth 라우터, JWT 발급 기반 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID PK | gen_random_uuid() |
| email | TEXT UNIQUE | 이메일 (로그인 ID) |
| name | TEXT | 사용자 이름 |
| password_hash | TEXT | bcrypt 해시 |
| is_admin | BOOLEAN | 관리자 여부 |
| created_at | TIMESTAMPTZ | 생성 시각 |

## 테이블 관계

- ← `watchlist(user_id)` FK (ON DELETE CASCADE)
