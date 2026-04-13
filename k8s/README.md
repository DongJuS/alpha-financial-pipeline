# K3s 배포 가이드

> **현재 상태 (2026-04-13):** 클라우드 배포는 **Docker Compose**(`docker-compose.prod.yml`)를 사용합니다.
> 이 K3s 매니페스트는 **지금 당장 사용하지 않습니다.**

## 이 문서는 언제 필요한가

K3s 배포가 필요한 시점은 다음과 같습니다:

- **롤링 업데이트가 필요할 때** — Docker Compose는 서비스 재시작 시 다운타임이 발생하지만, K3s는 rolling update로 무중단 배포 가능
- **종목 수가 늘어나 서버를 분리할 때** — K3s는 멀티 노드 확장이 자연스러움
- **네임스페이스 격리가 필요할 때** — 서비스 간 RBAC, 리소스 쿼터 등

## Docker Compose → K3s 원복 매뉴얼

K3s 매니페스트는 이전에 사용하던 상태 그대로 보존되어 있습니다.
앱 코드 변경 없이 아래 절차만 따르면 원복됩니다.

**K3s를 마지막으로 사용하던 시점의 git 이력:**
```bash
# K3s 관련 마지막 커밋들을 확인하려면:
git log --oneline --all -- k8s/

# 주요 커밋:
# e22ea4a docs: K3s 배포 가이드 README 추가 (#185)
# f411e02 feat: K3s 마이그레이션에 ohlcv_minute DDL 단계 추가 (#182)
# a605a06 fix: deploy-local.sh에 RL 프로파일 PVC 동기화 단계 추가
# d2325cb feat: instruments v2 마이그레이션 + trading_universe 시드 스크립트 + K3s Job
#
# 당시 K3s가 어떻게 동작했는지 확인하려면 해당 커밋의 k8s/ 디렉토리를 참고:
# git show e22ea4a:k8s/base/configmap.yaml
```

### 사전 결정: S3 스토리지

K3s로 돌아갈 때 S3 스토리지를 어떻게 할지 먼저 결정합니다.

| 선택지 | 조치 | 언제 선택 |
|--------|------|----------|
| **R2 유지** | `k8s/overlays/prod/kustomization.yaml`에서 S3_ENDPOINT_URL 주석 해제 후 R2 URL 입력 | 데이터 이전 없이 바로 전환하고 싶을 때 |
| **MinIO 복귀** | ConfigMap 그대로 사용 (`S3_ENDPOINT_URL: http://minio:9000`). R2 데이터를 MinIO로 복사 필요 | 외부 의존성 없이 자체 운영하고 싶을 때 |

### Step 1: K3s 클러스터 준비

```bash
# 로컬 (Colima 사용 시)
colima start --kubernetes --cpu 4 --memory 8

# 또는 클라우드 서버에 K3s 직접 설치
curl -sfL https://get.k3s.io | sh -
```

### Step 2: 인프라 설치 (PostgreSQL, Redis, MinIO)

```bash
# Helm으로 Bitnami 차트 설치 (values 파일은 k8s/helm/bitnami-values/ 에 보존됨)
bash k8s/scripts/deploy.sh prod
```

이 스크립트가 설치하는 것:
- PostgreSQL 15 (`alpha-pg-postgresql`, Helm values: `k8s/helm/bitnami-values/postgres-values.yaml`)
- Redis 7 (`alpha-redis-master`, Helm values: `k8s/helm/bitnami-values/redis-values.yaml`)
- MinIO (`minio`, Helm values: `k8s/helm/bitnami-values/minio-values.yaml`) — R2 유지 시에도 설치는 해둠

### Step 3: 시크릿 적용

```bash
# SOPS 부트스트랩 (age 키가 없으면 최초 1회)
bash k8s/scripts/secrets-bootstrap.sh

# 시크릿 복호화 → K8s에 적용
sops --decrypt k8s/secrets/app-secret.enc.yaml | kubectl apply -f -
```

시크릿에 포함된 것: `DATABASE_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, KIS API 키 등.
Compose의 `.env`에 있던 값과 동일한 값을 SOPS 파일에 넣어야 합니다.

**주의:** Compose에서 사용하던 `.env`의 시크릿 값이 SOPS 파일과 다르면
`sops k8s/secrets/app-secret.enc.yaml`로 편집하여 맞춥니다.

### Step 4: S3 설정 (R2 유지 시)

R2를 유지하기로 했다면:

```bash
# k8s/overlays/prod/kustomization.yaml 편집
# configMapGenerator 섹션에서 S3_ENDPOINT_URL 주석 해제 후 실제 R2 URL 입력
```

MinIO 복귀라면: 이 단계를 건너뜁니다 (ConfigMap 기본값이 MinIO를 가리킴).

### Step 5: 데이터 이전

```bash
# 1. Compose 서비스 중단
ssh hetzner "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down"

# 2. PostgreSQL 덤프 → 전송 → K3s에 복원
ssh hetzner "docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm \
  -e PGPASSWORD=\$POSTGRES_PASSWORD postgres \
  pg_dump -h postgres -U alpha_user -Fc alpha_db" > alpha_db.dump

# K3s PostgreSQL에 포트포워딩
kubectl port-forward svc/alpha-pg-postgresql 5433:5432 -n alpha-trading &

# 복원
pg_restore -h localhost -p 5433 -U alpha_user -d alpha_db -Fc alpha_db.dump

# 3. S3 데이터 (MinIO 복귀 시만)
# R2 → MinIO 복사
rclone sync r2:alpha-datalake minio:alpha-lake --progress
rclone check r2:alpha-datalake minio:alpha-lake
```

### Step 6: 앱 배포

```bash
# Docker 이미지 빌드
docker build -t alpha-api:latest --target prod .

# 앱 배포
kubectl apply -k k8s/overlays/prod/

# DB 마이그레이션 (자동 — init container가 4단계 실행)
# 로그 확인:
kubectl logs deployment/api -n alpha-trading -c db-migrate -f
```

### Step 7: 검증

```bash
# 1. 모든 Pod가 Running인지 확인
kubectl get pods -n alpha-trading
# 기대: api, worker, tick-collector, ui 모두 Running

# 2. DB/Redis 연결 확인
kubectl exec deployment/api -n alpha-trading -- python scripts/health_check.py

# 3. 스모크 테스트
kubectl exec deployment/api -n alpha-trading -- python scripts/smoke_test.py --skip-telegram

# 4. 데이터 무결성 확인
kubectl exec deployment/api -n alpha-trading -- python -c "
from src.utils.db_client import get_db_client
import asyncio
async def check():
    db = get_db_client()
    rows = await db.fetch('SELECT COUNT(*) FROM market_data')
    print(f'market_data: {rows[0][\"count\"]} rows')
    rows = await db.fetch('SELECT COUNT(*) FROM instruments')
    print(f'instruments: {rows[0][\"count\"]} rows')
asyncio.run(check())
"

# 5. 1 사이클 완주 확인 (장중이면)
kubectl logs deployment/worker -n alpha-trading -f --tail=100
```

### Step 8: Compose 환경 정리

검증이 완료되면:

```bash
# Hetzner 서버의 Compose 환경은 2주간 유지 (롤백 대비)
# 2주 후 문제없으면:
ssh hetzner "cd /app && docker compose down -v"
```

### 문제 발생 시

| 증상 | 원인 | 해결 |
|------|------|------|
| Pod CrashLoopBackOff | 환경변수 누락 또는 DB 연결 실패 | `kubectl logs <pod>`, `kubectl describe pod <pod>` |
| DB 연결 실패 | SOPS 시크릿의 DATABASE_URL이 Helm release명과 불일치 | `k8s/base/configmap.yaml`의 서비스명 확인 (`alpha-pg-postgresql`) |
| S3 업로드 실패 | R2 URL 오타 또는 MinIO 미기동 | ConfigMap의 S3_ENDPOINT_URL 확인 |
| init container 실패 | 마이그레이션 스크립트 오류 | `kubectl logs deployment/api -n alpha-trading -c db-migrate` |
| 전체 롤백 | K3s 전환 포기 | Hetzner의 Compose 환경으로 복귀 (`docker compose up -d`) |

### Docker Compose ↔ K3s 대응 관계

| 역할 | Docker Compose | K3s |
|------|---------------|-----|
| 서비스 정의 | `docker-compose.prod.yml` | `k8s/base/*.yaml` |
| 환경변수 | `.env` 파일 | `k8s/base/configmap.yaml` + overlay |
| 시크릿 | `.env` 파일 내 변수 | `k8s/secrets/*.enc.yaml` (SOPS) |
| DB 마이그레이션 | `db-init-migrate` 서비스 | `migration-job.yaml` + API init container |
| RL 학습 비활성화 | `ORCH_ENABLE_RL_AUTO_RETRAIN=false` | `overlays/prod/patches/worker-env.yaml` |
| S3 스토리지 | `.env`의 `S3_ENDPOINT_URL` | ConfigMap의 `S3_ENDPOINT_URL` |
| tick-collector | tick-collector 서비스 override | `k8s/base/tick-collector.yaml` |

### 참고: Compose와의 설정 차이 (2026-04-13 감사 기준)

아래는 원복 시 깨지는 것이 아니라, Compose와 설정을 완벽히 일치시키고 싶을 때
추가로 맞출 수 있는 차이점입니다. K3s를 쓰던 당시에도 이 차이는 있었고,
코드의 기본값으로 정상 동작했습니다.

1. **ConfigMap에 없는 환경변수 8개** — `ORCH_DAILY_REPORT_*`, `ORCH_CONSENSUS_*`, `ORCH_TOURNAMENT_*`, `ORCH_TICKERS`. 코드 기본값으로 동작하지만, Compose와 맞추려면 `k8s/base/configmap.yaml`에 추가. 대조 소스: `docker-compose.yml` worker environment (109~131행)
2. **리소스 제한** — K8s prod overlay에서 api/worker가 2Gi/2cpu인데 Compose는 1G/1cpu. Hetzner CX22에서 K3s를 돌리면 K3s 자체 오버헤드(~500MB)로 OOM 위험. `k8s/overlays/prod/patches/resource-limits.yaml` 축소 권장
3. **S3_BUCKET_NAME** — ConfigMap은 `alpha-lake`, config.py 기본값은 `alpha-datalake`. 실제 사용 중인 버킷명으로 통일 필요

---

아래는 K3s 환경에서의 실제 배포 절차입니다 (위 원복 매뉴얼과 별개로, 처음부터 K3s를 세팅할 때 참고).

## 구조

```
k8s/
  base/           # Kustomize base (api, worker, tick-collector, ui, ingress)
  overlays/       # 환경별 overlay (dev, prod, gen)
  helm/           # Bitnami Helm values (PostgreSQL, Redis, MinIO)
  secrets/        # SOPS 암호화 시크릿 (*.enc.yaml)
  scripts/        # 배포·마이그레이션 스크립트
```

## 빠른 시작 (로컬 K3s)

### 1. 사전 준비

```bash
# 인프라 Helm 설치 (최초 1회)
bash k8s/scripts/deploy.sh dev

# SOPS 부트스트랩 (최초 1회)
bash k8s/scripts/secrets-bootstrap.sh
```

### 2. 배포

```bash
# 전체 (빌드 + 시크릿 + 배포 + 검증)
bash k8s/scripts/deploy-local.sh

# 빌드 스킵 (배포만)
bash k8s/scripts/deploy-local.sh --skip-build

# 빌드만 (배포 안 함)
bash k8s/scripts/deploy-local.sh --build-only
```

`deploy-local.sh`가 수행하는 단계:

| 단계 | 내용 |
|------|------|
| 1/7 | `git pull` (최신 main 반영) |
| 2/7 | Docker build (`alpha-api:latest`) |
| 3/7 | SOPS secrets decrypt + kubectl apply |
| 4/7 | `kubectl apply -k k8s/base/` |
| 5/7 | rollout restart (worker, api) |
| 6/7 | RL 프로파일 PVC 동기화 |
| 7/7 | Pod 상태 검증 |

### 3. DB 마이그레이션 (자동)

API Deployment의 **init container**가 매 배포마다 마이그레이션을 자동 실행합니다.
모든 스크립트가 idempotent(`IF NOT EXISTS`)라 중복 실행해도 안전합니다.

```
[1/4] migrate_to_v2_instruments.py  — instruments v2 스키마
[2/4] migrate_ohlcv_minute.py       — ohlcv_minute 테이블 + 월별 파티션
[3/4] seed_all_instruments.py       — KRX 종목 마스터 시딩
[4/4] seed_trading_universe.py      — 트레이딩 유니버스 시딩
```

init container 로그 확인:

```bash
kubectl logs deployment/api -n alpha-trading -c db-migrate
```

### 4. 검증

```bash
# Pod 상태
kubectl get pods -n alpha-trading

# API 헬스체크
kubectl exec deployment/api -n alpha-trading -- python scripts/health_check.py

# init container 마이그레이션 로그
kubectl logs deployment/api -n alpha-trading -c db-migrate
```

## 수동 마이그레이션 (선택)

자동 init container 외에 수동 실행이 필요한 경우:

### 방법 A: K8s Job

```bash
# 기존 Job 삭제 후 재생성
kubectl delete job instruments-migration -n alpha-trading --ignore-not-found
kubectl apply -f k8s/base/migration-job.yaml
kubectl logs job/instruments-migration -n alpha-trading -f
```

### 방법 B: 로컬 port-forward

```bash
bash k8s/scripts/run_db_migration.sh
```

포트포워딩으로 K3s PostgreSQL에 접속하여 로컬에서 마이그레이션 스크립트를 실행합니다.

## 환경별 배포

```bash
# dev (기본)
bash k8s/scripts/deploy.sh dev

# prod
bash k8s/scripts/deploy.sh prod

# dry-run (실제 배포 안 함)
bash k8s/scripts/deploy.sh dev --dry-run

# gen 시뮬레이터 (주말/장외용)
kubectl apply -k k8s/overlays/gen/
```

## 시크릿 관리

SOPS + age로 암호화. 상세: [docs/secrets.md](../docs/secrets.md)

```bash
# 시크릿 편집
sops k8s/secrets/app-secret.enc.yaml

# 시크릿 적용 (deploy-local.sh에서 자동 수행)
sops --decrypt k8s/secrets/app-secret.enc.yaml | kubectl apply -f -
```

## 주요 서비스

| 서비스 | 설명 | 포트 |
|--------|------|------|
| api | FastAPI 서버 | 8000 |
| worker | Orchestrator + 스케줄러 | - |
| tick-collector | KIS WebSocket 틱 수집 | - |
| ui | React 프론트엔드 | 80 |
| alpha-pg-postgresql | PostgreSQL | 5432 |
| alpha-redis-master | Redis | 6379 |
| minio | MinIO (S3 호환) | 9000/9001 |

## 동기화 유지 원칙

Docker Compose에 새 서비스나 환경변수를 추가할 때,
K3s 매니페스트도 함께 업데이트해야 전환 시 문제가 없습니다.

**체크리스트 (Compose 변경 시마다):**

- [ ] 새 서비스 추가 → `k8s/base/`에 대응 Deployment 추가 + `kustomization.yaml`에 등록
- [ ] 새 환경변수 추가 → `k8s/base/configmap.yaml` 또는 해당 Deployment의 `env`에 추가
- [ ] 리소스 제한 변경 → `k8s/overlays/prod/patches/resource-limits.yaml` 반영
- [ ] DB 마이그레이션 스크립트 추가 → `migration-job.yaml` + `api.yaml` init container 반영
- [ ] 새 크론잡 추가 → `k8s/base/`에 CronJob 매니페스트 추가 여부 판단

*Last updated: 2026-04-13*
