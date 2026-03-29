#!/usr/bin/env bash
set -euo pipefail

# k8s/scripts/deploy.sh — Helm(인프라) + Kustomize(앱) 배포
#
# 사용법:
#   ./k8s/scripts/deploy.sh              # dev 환경 (기본)
#   ./k8s/scripts/deploy.sh prod         # prod 환경
#   ./k8s/scripts/deploy.sh dev --dry-run  # dry-run (실제 배포 안 함)
#   ./k8s/scripts/deploy.sh dev --skip-build  # 이미지 빌드 스킵

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$K8S_DIR")"
BITNAMI_VALUES="$K8S_DIR/helm/bitnami-values"

ENV="${1:-dev}"
shift || true
DRY_RUN=false
SKIP_BUILD=false
for arg in "$@"; do
    case "$arg" in
        --dry-run)   DRY_RUN=true ;;
        --skip-build) SKIP_BUILD=true ;;
    esac
done

if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo "Usage: $0 [dev|prod] [--dry-run] [--skip-build]"
    exit 1
fi

OVERLAY="$K8S_DIR/overlays/$ENV"
NS="alpha-trading"

echo "============================================="
echo "  Alpha Trading K8s Deploy"
echo "  Environment: $ENV"
echo "  Dry-run:     $DRY_RUN"
echo "============================================="
echo ""

# ── Step 1: Namespace ─────────────────────────────────────────
echo "[1/5] Namespace..."
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# ── Step 2: Bitnami Helm 인프라 ──────────────────────────────
echo "[2/5] Bitnami Helm 인프라 (PostgreSQL, Redis, MinIO)..."
helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || true
helm repo add minio https://charts.min.io 2>/dev/null || true
helm repo update

if $DRY_RUN; then
    echo "  [dry-run] helm install postgresql --dry-run"
    helm install alpha-pg bitnami/postgresql -n "$NS" -f "$BITNAMI_VALUES/postgres-values.yaml" --dry-run 2>&1 | tail -5
    echo "  [dry-run] helm install redis --dry-run"
    helm install alpha-redis bitnami/redis -n "$NS" -f "$BITNAMI_VALUES/redis-values.yaml" --dry-run 2>&1 | tail -5
    echo "  [dry-run] helm install minio --dry-run"
    helm install alpha-minio minio/minio -n "$NS" -f "$BITNAMI_VALUES/minio-values.yaml" --dry-run 2>&1 | tail -5
else
    # upgrade --install: 이미 설치되어 있으면 업그레이드
    helm upgrade --install alpha-pg bitnami/postgresql \
        -n "$NS" -f "$BITNAMI_VALUES/postgres-values.yaml" --wait --timeout 3m
    echo "  PostgreSQL ✅"

    helm upgrade --install alpha-redis bitnami/redis \
        -n "$NS" -f "$BITNAMI_VALUES/redis-values.yaml" --wait --timeout 2m
    echo "  Redis ✅"

    helm upgrade --install alpha-minio minio/minio \
        -n "$NS" -f "$BITNAMI_VALUES/minio-values.yaml" --wait --timeout 2m
    echo "  MinIO ✅"
fi

# ── Step 3: Docker 이미지 빌드 ────────────────────────────────
if $SKIP_BUILD; then
    echo "[3/5] 이미지 빌드 스킵 (--skip-build)"
elif $DRY_RUN; then
    echo "[3/5] 이미지 빌드 스킵 (dry-run)"
else
    echo "[3/5] Docker 이미지 빌드..."
    docker build -t alpha-trading:latest "$ROOT_DIR"
    if [[ -d "$ROOT_DIR/ui/web" ]]; then
        docker build -t alpha-trading-ui:latest "$ROOT_DIR/ui/web"
    fi

    # Colima/K3s: 로컬 이미지를 K3s에 import
    if command -v k3s &>/dev/null; then
        echo "  K3s 이미지 import..."
        docker save alpha-trading:latest | sudo k3s ctr images import -
        docker save alpha-trading-ui:latest | sudo k3s ctr images import - 2>/dev/null || true
    fi
    echo "  이미지 빌드 ✅"
fi

# ── Step 4: Kustomize 앱 배포 ─────────────────────────────────
echo "[4/5] Kustomize 앱 배포 ($ENV)..."
if $DRY_RUN; then
    kubectl apply -k "$OVERLAY" --dry-run=client
    echo ""
    echo "  [dry-run] 위 리소스가 생성됩니다."
    echo ""
    echo "=== Dry-run 완료 ==="
    exit 0
fi

kubectl apply -k "$OVERLAY"

# ── Step 5: 헬스체크 ─────────────────────────────────────────
echo "[5/5] 헬스체크..."

echo "  Helm releases:"
helm list -n "$NS"
echo ""

echo "  Rollout status:"
kubectl -n "$NS" rollout status deployment/api --timeout=120s
kubectl -n "$NS" rollout status deployment/worker --timeout=120s
echo ""

echo "  All pods:"
kubectl -n "$NS" get pods -o wide
echo ""

echo "============================================="
echo "  Deploy Complete ($ENV)"
echo "============================================="
echo ""
echo "  API:    kubectl -n $NS port-forward svc/api 8000:8000"
echo "  MinIO:  kubectl -n $NS port-forward svc/alpha-minio 9001:9001"
