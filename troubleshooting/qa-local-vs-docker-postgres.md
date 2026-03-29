# QA: 로컬 psql과 Docker postgres가 다른 인스턴스를 바라봄

> 발생일: 2026-03-29
> 상태: 해결 (원인 파악 완료)

---

## 증상

- `psql "postgresql://alpha_user:alpha_pass@localhost:5432/alpha_db"` 로 market_data 조회 시 **3건만** 반환
- Docker gen-collector 로그에서는 매 사이클 1,700건 DB 저장 성공으로 표시
- 인제스트가 실패한 것처럼 보임

## 원인

**로컬에 별도 PostgreSQL 인스턴스가 실행 중이었음.**

- 로컬 `psql localhost:5432` → 로컬 PostgreSQL (init_db.py로 생성한 빈 DB, 시드 데이터 3건)
- Docker 컨테이너 내부 → Docker compose의 postgres 서비스 (포트 5432가 호스트에 바인딩됨)

포트 5432에 로컬 PostgreSQL과 Docker PostgreSQL이 충돌하거나, Docker가 로컬 인스턴스를 밀어내지 못하고 로컬 psql이 로컬 인스턴스를 우선 접속한 것으로 추정.

## 검증 방법

```bash
# 컨테이너 내부에서 직접 조회 → 정상 (63,100건, 20종목)
docker compose exec postgres psql -U alpha_user -d alpha_db -c "SELECT count(*) FROM market_data;"

# 또는 gen-collector 컨테이너에서 asyncpg로 조회 → 정상 (62,960건)
docker compose exec gen-collector python -c "
import asyncio, os, asyncpg
async def check():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    print(await conn.fetchval('SELECT count(*) FROM market_data'))
asyncio.run(check())
"
```

## 실제 DB 상태 (정상)

| 항목 | 수치 |
|---|---|
| market_data 총 건수 | 63,100 |
| 종목 수 | 20 |
| 최근 데이터 (>=3/25) | 61,320건 |
| S3 daily_bars | 정상 저장 (Parquet) |
| S3 blend_results | 정상 저장 (Parquet) |

## 재발 방지

- QA 시 DB 조회는 항상 `docker compose exec postgres psql` 사용
- 로컬 `psql localhost`는 Docker postgres와 포트가 충돌할 수 있으므로 주의
- 로컬 PostgreSQL이 실행 중인지 `lsof -i :5432` 또는 `brew services list`로 확인

---

*이 파일은 push 후 MEMORY.md에 요약 기록 후 삭제합니다.*
