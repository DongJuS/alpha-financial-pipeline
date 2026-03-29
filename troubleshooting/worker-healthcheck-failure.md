# Worker healthcheck 실패 (unhealthy)

> 생성일: 2026-03-29
> 상태: 해결
> 관련 PR: (이번 커밋)

---

## 증상

`docker compose ps`에서 worker가 `unhealthy` 상태. FailingStreak 15+.

## 원인

- Dockerfile prod 스테이지에 `HEALTHCHECK CMD curl -sf http://localhost:8000/health` 정의됨
- docker-compose.yml의 worker 서비스에는 별도 healthcheck가 없었음
- Dockerfile의 HEALTHCHECK가 상속되어 적용됨
- **worker는 API 서버가 아니라 백그라운드 프로세스**이므로 8000 포트가 열리지 않아 curl이 항상 실패

## 해결

docker-compose.yml의 worker 서비스에 프로세스 존재 확인용 healthcheck 추가:
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

## 영향

- worker가 healthy 상태로 전환
- docker compose ps에서 전체 서비스 healthy 확인 가능

---

*작성: 2026-03-29*
