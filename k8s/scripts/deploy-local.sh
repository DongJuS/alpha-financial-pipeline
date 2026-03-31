#!/bin/bash
# K3s 로컬 배포 자동화 — main merge 후 1커맨드로 빌드→배포→검증
#
# 사용법:
#   ./k8s/scripts/deploy-local.sh          # 전체 (build + deploy + verify)
#   ./k8s/scripts/deploy-local.sh --skip-build   # 빌드 스킵, 배포만
#   ./k8s/scripts/deploy-local.sh --build-only    # 빌드만, 배포 안 함
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
NAMESPACE="alpha-trading"
IMAGE="alpha-trading:latest"
DOCKER_HOST="${DOCKER_HOST:-unix://$HOME/.colima/default/docker.sock}"
export DOCKER_HOST

SKIP_BUILD=false
BUILD_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=true ;;
    --build-only) BUILD_ONLY=true ;;
  esac
done

cd "$REPO_ROOT"

# ── 1. Git pull (최신 main 반영) ──
echo "=== [1/5] git pull ==="
git pull origin main --ff-only 2>/dev/null || echo "  (worktree — skip pull)"

# ── 2. Docker build ──
if [ "$SKIP_BUILD" = false ]; then
  echo "=== [2/5] docker build ==="
  docker build --target prod -t "$IMAGE" . 2>&1 | tail -3
  echo "  image: $IMAGE ($(docker images "$IMAGE" --format '{{.Size}}'))"
else
  echo "=== [2/5] docker build — SKIPPED ==="
fi

if [ "$BUILD_ONLY" = true ]; then
  echo "=== build-only 완료 ==="
  exit 0
fi

# ── 3. Kustomize apply (Secret + ConfigMap + Deployments) ──
echo "=== [3/5] kubectl apply ==="
kubectl apply -k k8s/base/ 2>&1 | grep -v "PersistentVolumeClaim\|is forbidden" || true

# ── 4. Rolling restart (새 이미지 강제 적용) ──
echo "=== [4/5] rollout restart ==="
for deploy in worker api; do
  kubectl rollout restart deployment/$deploy -n "$NAMESPACE" 2>/dev/null && echo "  $deploy restarted" || echo "  $deploy not found"
done

# ── 5. 검증 ──
echo "=== [5/5] 검증 (30초 대기) ==="
sleep 30
echo ""
echo "--- Pod 상태 ---"
kubectl get pods -n "$NAMESPACE" --no-headers | while read -r line; do
  echo "  $line"
done

echo ""
echo "--- Worker 최근 로그 ---"
kubectl logs deployment/worker -n "$NAMESPACE" --tail=5 2>/dev/null | while read -r line; do
  echo "  $line"
done

echo ""
HEALTHY=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l | tr -d ' ')
TOTAL=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo "=== 배포 완료: $HEALTHY/$TOTAL Running ==="
