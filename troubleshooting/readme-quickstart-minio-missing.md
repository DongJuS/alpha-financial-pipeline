# README 빠른 시작 — minio 서비스 누락

## 발견일
2026-03-29

## 증상
README "빠른 시작" 섹션의 `docker compose up -d --build postgres redis api worker ui` 명령으로 실행 시,
`api`와 `worker` 서비스가 시작되지 않음 (health check 실패 대기 상태).

## 원인
`docker-compose.yml`에서 `api`, `worker`, `gen-collector` 서비스가 `minio`에 `condition: service_healthy`로 의존.
README 명령에 `minio` 서비스가 누락되어 의존성 조건을 만족하지 못함.

## 해결
README.md의 두 곳(빠른 시작, Docker 런타임 스모크 테스트)에서 `minio` 서비스 추가:
```bash
# Before
docker compose up -d --build postgres redis api worker ui

# After
docker compose up -d --build postgres redis minio api worker ui
```

## 영향 범위
- README.md (2곳)
- 실제 런타임에는 영향 없음 (docker-compose.yml 자체는 정상)

## PR
#53
