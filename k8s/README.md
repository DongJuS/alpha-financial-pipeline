# K3s 배포 가이드

K3s(로컬) 및 클라우드 K8s 환경 배포 절차.

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

*Last updated: 2026-04-12*
