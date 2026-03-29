# K3s 실배포 e2e 검증 (Colima)

> 생성일: 2026-03-30
> 상태: 대부분 성공, UI OOMKilled 1건 잔여

---

## 검증 환경

- Colima v0.8+ (macOS, Virtualization.Framework)
- K3s v1.35.0, 단일 노드 (4 CPU, 8GB RAM, 40GB disk)
- 인프라: Bitnami PostgreSQL + Redis (Helm), MinIO (직접 Deployment)
- 앱: Kustomize overlays/dev

---

## 결과

| 컴포넌트 | 상태 | 비고 |
|---|---|---|
| PostgreSQL (Bitnami) | ✅ Running | 2/2 (metrics sidecar 포함) |
| Redis (Bitnami) | ✅ Running | 2/2 (metrics sidecar 포함) |
| MinIO | ✅ Running | 공식 `minio/minio:latest` 이미지 |
| API | ✅ Running | healthy, 스케줄러 9잡, DB/Redis ok |
| Worker | ✅ Running | A/B/RL 3전략 등록 + 사이클 실행 |
| UI | ❌ OOMKilled | Vite dev server 메모리 부족 (128Mi 제한) |
| DB Init | ✅ 31개 테이블 | API Pod에서 수동 실행 |
| PVC | ✅ 4개 Bound | PostgreSQL 10Gi, Redis 2Gi, MinIO 20Gi, RL data 2Gi |

---

## 해결한 이슈 3건

### 1. Kustomize configmap 서비스명 불일치
- **증상**: API `InvalidPasswordError`, Worker `Name or service not known`
- **원인**: configmap에서 `alpha-redis-redis-master` (틀림) → 실제 `alpha-redis-master`
- **해결**: `k8s/base/configmap.yaml` 수정 — REDIS_URL, S3_ENDPOINT_URL 서비스명 정합

### 2. Secret과 ConfigMap의 DATABASE_URL 중복
- **증상**: API가 Secret의 `CHANGE_ME` 패스워드로 DB 연결 시도 → 인증 실패
- **원인**: Secret과 ConfigMap 둘 다 DATABASE_URL을 정의 → Secret이 ConfigMap을 덮어씀
- **해결**: `k8s/base/secrets.yaml`에서 DATABASE_URL, REDIS_URL 제거 (ConfigMap에서만 관리)

### 3. Bitnami MinIO 이미지 pull 실패
- **증상**: `minio-object-browser:2.0.2-debian-12-r3` 이미지 not found
- **원인**: Bitnami MinIO chart가 참조하는 console 이미지가 레지스트리에 없음
- **해결**: Bitnami chart 대신 공식 `minio/minio:latest` Deployment로 직접 배포

---

## 미해결

### UI OOMKilled
- **증상**: Vite dev server가 128Mi 메모리 제한에서 OOMKilled
- **해결 방안**: 리소스 제한 상향 (`256Mi` 이상) 또는 프로덕션 빌드(nginx static serving)로 전환

### DB Init 자동화
- K8s 환경에서도 docker compose의 `db-init` 서비스와 동일한 Job이 필요
- 현재는 `kubectl exec deployment/api -- python scripts/db/init_db.py` 수동 실행

---

*작성: 2026-03-30*
