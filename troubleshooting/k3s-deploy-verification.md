# K3s 실배포 검증 (2026-03-29)

> Colima + K3s에서 Helm(인프라) + Kustomize(앱) 실배포 결과.
> 상태: **인프라 3개 + 앱 2개 Running 확인. UI는 별도 이미지 빌드 필요.**

---

## 환경

```
Colima:  v0.10.1, macOS Virtualization.Framework
K3s:     v1.35.0+k3s1
Node:    colima (Ready, 4 CPU, 8GB RAM, 40GB disk)
```

---

## 배포 결과

### Helm 인프라 (3/3 ✅)

| Release | Chart | Status | 서비스명 |
|---------|-------|--------|---------|
| alpha-pg | bitnami/postgresql 18.5.14 | deployed ✅ | `alpha-pg-postgresql:5432` |
| alpha-redis | bitnami/redis 25.3.9 | deployed ✅ | `alpha-redis-master:6379` |
| alpha-minio | minio/minio 5.4.0 | deployed ✅ | `alpha-minio:9000` |

### Kustomize 앱 (2/3 Running)

| Deployment | Status | 비고 |
|-----------|--------|------|
| api | Running ✅ | FastAPI 정상 기동 |
| worker | Running ✅ | Orchestrator worker 정상 기동 |
| ui | ImagePullBackOff | `alpha-trading-ui:latest` 이미지 미빌드 (별도 빌드 필요) |

---

## 발견된 이슈 + 해결

### 1. Bitnami MinIO 이미지 유료화 → 공식 MinIO chart로 전환

- **증상:** `docker.io/bitnami/minio-object-browser:2.0.2-debian-12-r3: not found`
- **원인:** Bitnami가 2025년 이후 일부 이미지를 유료 구독 전용으로 전환
- **해결:** `bitnami/minio` → `minio/minio` (공식 chart, `charts.min.io`) 전환
- **영향:** minio-values.yaml 형식이 Bitnami 스키마에서 공식 MinIO 스키마로 변경됨

### 2. Secret의 DATABASE_URL이 ConfigMap을 오버라이드

- **증상:** `password authentication failed for user "alpha_user"` — 비밀번호 `CHANGE_ME`
- **원인:** `app-secret`에 `DATABASE_URL: postgresql://alpha_user:CHANGE_ME@...`가 있어서 ConfigMap의 올바른 URL을 오버라이드
- **해결:** Secret에서 DATABASE_URL/REDIS_URL 제거 (인프라 접속 정보는 ConfigMap에서 관리)
- **교훈:** envFrom에서 Secret이 ConfigMap보다 나중에 로드되면 동일 키를 덮어씀

### 3. UI 이미지 미빌드

- **증상:** `alpha-trading-ui:latest` ImagePullBackOff
- **원인:** UI는 별도 Dockerfile(`ui/web/Dockerfile`)로 빌드해야 하는데 스킵됨
- **해결:** `docker build -t alpha-trading-ui:latest ui/web/` 실행 필요 (다음 배포 시)
- **영향:** API/Worker 동작에는 영향 없음

---

## 배포 명령어 (검증 완료)

```bash
# 1회차: 전체 배포
./k8s/scripts/deploy.sh dev

# 이미지 빌드 스킵 (이미 빌드된 경우)
./k8s/scripts/deploy.sh dev --skip-build

# dry-run
./k8s/scripts/deploy.sh dev --dry-run

# 삭제
./k8s/scripts/teardown.sh dev           # 앱만 삭제
./k8s/scripts/teardown.sh --infra       # Helm 인프라 삭제
./k8s/scripts/teardown.sh --all         # namespace 전체 삭제
```

---

*작성: 2026-03-29*
