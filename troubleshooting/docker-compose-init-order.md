# docker compose 기동 시 DB 초기화 순서 이슈

> 생성일: 2026-03-29
> 상태: 해결 (수동 대응)
> 관련: Step 5 Alpha 안정화

---

## 증상

`docker compose up -d --build` 후 `gen-collector`가 `Restarting` 상태로 반복 크래시.

```
asyncpg.exceptions.UndefinedTableError: relation "market_data" does not exist
```

## 원인

- PostgreSQL 컨테이너는 `service_healthy` 조건으로 기동되지만, **테이블 생성은 자동이 아님**
- `gen-collector`가 DB에 연결 즉시 `market_data` 테이블에 INSERT를 시도하지만 테이블이 없음
- `init_db.py`는 별도 수동 실행이 필요

## 해결

기동 후 수동으로 DB 초기화 실행:
```bash
docker compose exec api python scripts/db/init_db.py
```

## 영구 해결 방안

docker-compose.yml에 init 서비스를 추가하거나, api 서비스의 entrypoint에서 init_db.py를 선행 실행:

```yaml
api:
  command: >
    sh -c "python scripts/db/init_db.py && uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload"
```

---

*작성: 2026-03-29*
