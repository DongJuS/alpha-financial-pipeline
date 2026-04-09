#!/bin/bash
# K3s 로컬 배포 자동화 — main merge 후 1커맨드로 빌드→배포→검증
#
# 사용법:
#   ./k8s/scripts/deploy-local.sh          # 전체 (build + deploy + verify)
#   ./k8s/scripts/deploy-local.sh --skip-build   # 빌드 스킵, 배포만
#   ./k8s/scripts/deploy-local.sh --build-only    # 빌드만, 배포 안 함
#
# Cluster Secret 은 SOPS 로 관리한다 (k8s/secrets/*.enc.yaml).
# 본 스크립트가 kustomize apply 직전에 sops --decrypt | kubectl apply 단계를
# 자동 수행하므로 별도 secret manifest 작성/수동 apply 가 필요 없다.
# 운영 가이드: docs/secrets.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
NAMESPACE="alpha-trading"
IMAGE="alpha-trading:latest"
DOCKER_HOST="${DOCKER_HOST:-unix://$HOME/.colima/default/docker.sock}"
export DOCKER_HOST
AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"

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
echo "=== [1/6] git pull ==="
git pull origin main --ff-only 2>/dev/null || echo "  (worktree — skip pull)"

# ── 2. Docker build ──
if [ "$SKIP_BUILD" = false ]; then
  echo "=== [2/6] docker build ==="
  docker build --target prod -t "$IMAGE" . 2>&1 | tail -3
  echo "  image: $IMAGE ($(docker images "$IMAGE" --format '{{.Size}}'))"
else
  echo "=== [2/6] docker build — SKIPPED ==="
fi

if [ "$BUILD_ONLY" = true ]; then
  echo "=== build-only 완료 ==="
  exit 0
fi

# ── 3. SOPS Secrets decrypt and apply ──
echo "=== [3/6] SOPS secrets decrypt and apply ==="
if ! command -v sops >/dev/null 2>&1; then
  echo "  ERROR: sops binary 미설치. 'brew install sops age' 실행 후 재시도하세요." >&2
  exit 1
fi
if [ ! -f "$AGE_KEY_FILE" ]; then
  echo "  ERROR: age private key 미존재 ($AGE_KEY_FILE)." >&2
  echo "         k8s/scripts/secrets-bootstrap.sh 를 먼저 실행하세요." >&2
  exit 1
fi
# sops 자식 프로세스에 키 위치를 명시 전달.
# macOS sops 의 기본 키 위치는 ~/Library/Application Support/sops/age/keys.txt 인데
# 우리 부트스트랩은 ~/.config/sops/age/keys.txt (XDG 스타일) 에 쓰므로 export 필수.
export SOPS_AGE_KEY_FILE="$AGE_KEY_FILE"

shopt -s nullglob
SECRET_FILES=(k8s/secrets/*.enc.yaml)
shopt -u nullglob
if [ "${#SECRET_FILES[@]}" -eq 0 ]; then
  echo "  WARN: k8s/secrets/*.enc.yaml 없음 — secret apply 스킵 (최초 부트스트랩 전이라면 정상)"
else
  for f in "${SECRET_FILES[@]}"; do
    echo "  decrypting $f"
    if ! sops --decrypt "$f" | kubectl apply -f -; then
      echo "  ERROR: $f decrypt/apply 실패" >&2
      exit 1
    fi
  done
fi

# ── 4. Kustomize apply (ConfigMap + Deployments + llm-credentials) ──
echo "=== [4/6] kubectl apply -k k8s/base/ ==="
kubectl apply -k k8s/base/ 2>&1 | grep -v "PersistentVolumeClaim\|is forbidden" || true

# ── 5. Rolling restart (새 이미지 강제 적용) ──
echo "=== [5/6] rollout restart ==="
for deploy in worker api; do
  kubectl rollout restart "deployment/$deploy" -n "$NAMESPACE" 2>/dev/null && echo "  $deploy restarted" || echo "  $deploy not found"
done

# ── 6. 검증 ──
echo "=== [6/6] 검증 (30초 대기) ==="
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
