# Admin 사용자 생성 절차

> 생성일: 2026-03-29
> 상태: 해결 (수동 절차)

---

## 증상

`docker compose up` 후 API 엔드포인트가 `{"detail":"Not authenticated"}` 반환. 로그인할 사용자가 없음.

## 원인

- `DEFAULT_ADMIN_SEED_ENABLED=false`가 기본값 → init_db.py에서 admin seed 스킵
- `.env`에 admin 시드 설정이 없음

## 해결 (수동 생성)

```bash
# 1. DB에 사용자 행 삽입
docker compose exec postgres psql -U alpha_user -d alpha_db -c "
INSERT INTO users (email, name, password_hash, is_admin)
VALUES ('admin@alpha-trading.com', 'Admin', 'placeholder', true)
ON CONFLICT (email) DO NOTHING;"

# 2. 앱의 hash_password 함수로 패스워드 해시 생성 → 업데이트
docker compose exec api python -c "
import asyncio
from src.api.routers.auth import hash_password
from src.utils.db_client import execute
asyncio.run(execute(
    \"UPDATE users SET password_hash=\$1 WHERE email=\$2\",
    hash_password('admin123'), 'admin@alpha-trading.com'
))
print('OK')"

# 3. 로그인
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@alpha-trading.com","password":"admin123"}'
# → {"token":"eyJ...","expires_in":86400}
```

## 주의사항

- 이메일 도메인에 `.local` 사용 불가 (Pydantic email validation 실패)
- bcrypt 모듈이 Docker 이미지에 없을 수 있음 → `src.api.routers.auth.hash_password` 사용
- 프로덕션에서는 `.env`에 `DEFAULT_ADMIN_SEED_ENABLED=true` + 안전한 비밀번호 설정 권장

---

*작성: 2026-03-29*
