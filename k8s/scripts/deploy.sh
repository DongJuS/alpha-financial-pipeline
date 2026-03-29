#!/usr/bin/env bash
set -euo pipefail

# k8s/scripts/deploy.sh — K3s 배포 스크립트
#
# 사용법:
#   ./k8s/scripts/deploy.sh          # dev 환경 (기본)
#   ./k8s/scripts/deploy.sh prod     # prod 환경
#   ./k8s/scripts/deploy.sh dev --dry-run  # dry-run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$K8S_DIR")"

ENV="${1:-dev}"
EXTRA_ARGS="${@:2}"

if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo "Usage: $0 [dev|prod] [--dry-run]"
    exit 1
fi

OVERLAY="$K8S_DIR/overlays/$ENV"

echo "=== Alpha Trading K8s Deploy ==="
echo "Environment: $ENV"
echo "Overlay:     $OVERLAY"
echo ""

# 1. Docker 이미지 빌드 (K3s에서 로컬 이미지 사용)
echo "[1/3] Building Docker images..."
docker build -t alpha-trading:latest "$ROOT_DIR"
if [[ -d "$ROOT_DIR/ui/web" ]]; then
    docker build -t alpha-trading-ui:latest "$ROOT_DIR/ui/web"
fi

# K3s: 로컬 이미지를 K3s에 import
if command -v k3s &> /dev/null; then
    echo "[1/3] Importing images to K3s..."
    docker save alpha-trading:latest | sudo k3s ctr images import -
    docker save alpha-trading-ui:latest | sudo k3s ctr images import - 2>/dev/null || true
fi

# 2. Kustomize 적용
echo "[2/3] Applying Kustomize overlay: $ENV"
if [[ "$EXTRA_ARGS" == *"--dry-run"* ]]; then
    kubectl apply -k "$OVERLAY" --dry-run=client
    echo ""
    echo "[dry-run] 위 리소스가 생성됩니다."
    exit 0
fi

kubectl apply -k "$OVERLAY"

# 3. 롤아웃 대기
echo "[3/3] Waiting for rollout..."
kubectl -n alpha-trading rollout status deployment/postgres --timeout=120s
kubectl -n alpha-trading rollout status deployment/redis --timeout=60s
kubectl -n alpha-trading rollout status deployment/minio --timeout=60s
kubectl -n alpha-trading rollout status deployment/api --timeout=120s
kubectl -n alpha-trading rollout status deployment/worker --timeout=120s

echo ""
echo "=== Deploy Complete ==="
kubectl -n alpha-trading get pods
