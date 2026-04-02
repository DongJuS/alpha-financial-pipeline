# 🔧 트러블슈팅 이력

> 해결된 트러블슈팅의 요약을 기록합니다.
> 각 항목은 **원인 → 해결법 → 영향 범위**를 포함합니다.
> 개별 트러블슈팅 파일(`{이슈명}.md`)은 해결 후 git push 시 삭제합니다.

---

## 기록 형식

```
### {날짜} — {이슈 제목}
- **증상:** 무엇이 깨졌는가
- **원인:** 왜 깨졌는가 (인과관계)
- **해결:** 어떻게 고쳤는가
- **영향:** 어떤 파일/기능에 영향을 줬는가
```

---

### 2026-03-29 — 테스트 스위트 47건 실패 → 0건 (PR #44/#45/#50)
- **증상:** 전체 테스트 실행 시 47건 실패 (event loop 오염 32건, Python 3.9 문법 8건, 인터페이스 불일치 17건 등)
- **원인:** (1) conftest.py의 session-scoped `event_loop` fixture가 pytest-asyncio 0.26에서 deprecated → `IsolatedAsyncioTestCase`와 충돌하여 cascade 실패. (2) `asyncio.run()` 직접 호출이 event loop를 파괴. (3) SearchAgent 리팩토링 후 테스트 미업데이트.
- **해결:** (1) deprecated `event_loop` fixture 제거. (2) `asyncio.run()` → `IsolatedAsyncioTestCase` + `await` 전환. (3) test_search_pipeline.py 현재 인터페이스에 맞게 재작성. (4) DB 의존 테스트 `@pytest.mark.integration` 마킹.
- **영향:** conftest.py, test_blend_nway.py, test_aggregate_risk.py, test_strategy_promotion.py, test_data_pipeline.py, test_rl_bootstrap.py, test_search_pipeline.py, test_portfolio_manager.py, test_risk_validation.py
- **결과:** 462 passed → **557 passed, 0 failed**

### 2026-03-29 — README 빠른 시작 minio 서비스 누락
- **증상:** README 명령대로 `docker compose up` 실행 시 api/worker가 시작 불가
- **원인:** docker-compose.yml에서 api/worker가 minio에 `service_healthy` 의존하나 README 명령에 minio 누락
- **해결:** README.md 두 곳에 `minio` 서비스 추가 (PR #53)
- **영향:** README.md만 수정, 런타임 코드 변경 없음

### 2026-03-30 — Gemini API Key와 OAuth ADC 충돌
- **증상:** Docker 컨테이너에서 Gemini 호출 시 `client_options.api_key and credentials are mutually exclusive`
- **원인:** `.env`에 `GEMINI_API_KEY=AIza...`가 남아 있으면서 동시에 `~/.config/gcloud/` OAuth ADC도 마운트됨. google-generativeai SDK가 API Key와 OAuth를 동시에 받으면 거부.
- **해결:** `.env`, `.env.example`, `security_audit.py`에서 `GEMINI_API_KEY` 변수 자체 삭제. OAuth(ADC)만 단독 사용. (PR #67)
- **영향:** .env.example, docker-compose 환경변수

### 2026-03-30 — Claude CLI 버전 불일치로 "Not logged in"
- **증상:** 호스트 `~/.claude/`를 bind mount했으나 컨테이너 안에서 `Not logged in`
- **원인:** Claude Code OAuth 세션 토큰이 호스트 바이너리(2.1.84)와 컨테이너 바이너리(2.1.87) 간에 호환되지 않음
- **해결:** bind mount를 `ro` → `rw`로 변경 후 컨테이너 안에서 `claude /login` 실행하여 재인증
- **영향:** docker-compose.yml bind mount 옵션

### 2026-03-30 — K3s ConfigMap 서비스명 불일치 (Helm vs Kustomize)
- **증상:** K3s 배포 후 API `InvalidPasswordError`, Worker `Name or service not known`
- **원인:** Bitnami Helm chart가 생성하는 서비스명(`alpha-pg-postgresql`, `alpha-redis-master`)과 Kustomize configmap의 서비스명(`postgres`, `alpha-redis-redis-master`)이 다름
- **해결:** `k8s/base/configmap.yaml`의 DATABASE_URL, REDIS_URL, S3_ENDPOINT_URL을 실제 Helm release명 기준으로 수정
- **영향:** k8s/base/configmap.yaml

### 2026-03-30 — K8s Secret과 ConfigMap의 DATABASE_URL 중복
- **증상:** API가 Secret의 `CHANGE_ME` 패스워드로 DB 연결 시도 → 인증 실패
- **원인:** `secrets.yaml`과 `configmap.yaml` 둘 다 DATABASE_URL을 정의. K8s에서 Secret이 ConfigMap을 덮어쓰며, Secret의 값은 플레이스홀더(`CHANGE_ME`)
- **해결:** `k8s/base/secrets.yaml`에서 DATABASE_URL, REDIS_URL 제거. ConfigMap에서만 관리.
- **영향:** k8s/base/secrets.yaml

### 2026-03-30 — Bitnami MinIO 이미지 pull 실패
- **증상:** K3s에서 MinIO pod가 `ImagePullBackOff`. `minio-object-browser:2.0.2-debian-12-r3` not found
- **원인:** Bitnami MinIO chart가 참조하는 console 이미지가 레지스트리에 존재하지 않음 (Bitnami 이미지 유료화 영향 추정)
- **해결:** Bitnami chart 대신 공식 `minio/minio:latest` Deployment로 직접 배포
- **영향:** k8s/helm/bitnami-values/minio-values.yaml, deploy.sh
