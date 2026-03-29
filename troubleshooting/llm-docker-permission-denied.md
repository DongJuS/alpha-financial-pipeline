# Docker LLM 인증 Permission Denied

> 발생일: 2026-03-29
> 상태: 수정 완료 (리빌드 대기)

---

## 증상

- Worker 컨테이너에서 Claude CLI, Gemini OAuth 모두 실패
- `ls /root/.claude/` → Permission denied
- `ls /root/.config/gcloud/` → Permission denied
- 모든 LLM provider 사용 불가 → predictions 0건

## 원인

multi-stage Dockerfile에서 `target` 미지정 시 마지막 스테이지(prod)가 빌드됨.
prod 스테이지에 `USER alpha` (uid 999)가 설정되어 있어 `/root/` 경로의 bind mount를 읽을 수 없었음.

```
docker-compose.yml (수정 전):
  worker:
    build:
      context: .
      dockerfile: Dockerfile    # target 미지정 → prod(USER alpha) 빌드

Dockerfile prod 스테이지:
  USER alpha    # ← 이게 /root/ 마운트 접근을 차단
```

## 해결

docker-compose.yml의 모든 앱 서비스에 `target: dev` 명시:

```yaml
worker:
  build:
    context: .
    dockerfile: Dockerfile
    target: dev    # ← root로 실행, /root/ 마운트 접근 가능
```

수정 대상: api, worker, gen, gen-collector, db-init (5개 서비스)

## 검증 방법

```bash
docker compose down && docker compose up -d --build
docker compose exec worker whoami        # root 확인
docker compose exec worker ls /root/.claude/  # 마운트 확인
docker compose exec worker ls /root/.config/gcloud/application_default_credentials.json
```

---

*리빌드 후 검증 완료되면 MEMORY.md에 요약 기록 후 삭제합니다.*
