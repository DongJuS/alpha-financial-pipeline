#!/usr/bin/env bash
# scripts/deploy/deploy.sh — 서버에서 실행되는 멱등 배포 진입점.
# - GHA deploy-prod 워크플로우가 SSH 로 호출하거나 사람이 수동 실행.
# - 사용법:
#     ~/deploy/deploy.sh <git-sha>
#     ~/deploy/deploy.sh <prev-sha>      # 롤백
set -euo pipefail

IMAGE_TAG="${1:?usage: deploy.sh <git-sha>}"
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/alpha-financial-pipeline}"
DEPLOY_HOME="${DEPLOY_HOME:-$HOME/deploy}"
STATE_FILE="$DEPLOY_HOME/.last_good_tag"
LOG_FILE="$DEPLOY_HOME/deploy.log"

mkdir -p "$DEPLOY_HOME"
exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== deploy.sh START $(date -u +%FT%TZ) — tag=$IMAGE_TAG ==="

cd "$PROJECT_DIR"

# 1) 코드도 같이 끌어내림 (compose 파일, 마이그레이션 SQL 변경 반영)
echo "[1/6] fetch + reset to $IMAGE_TAG"
git fetch origin main --quiet
git reset --hard "$IMAGE_TAG"

# 2) 이전 태그 저장 (롤백용)
PREV="$(cat "$STATE_FILE" 2>/dev/null || echo '')"
echo "[2/6] previous good tag: ${PREV:-<없음>}"

# 3) Infisical 로 .env.runtime 머티리얼라이즈 (Workstream C 가 완성 전엔 기존 .env 사용)
echo "[3/6] render env"
if [ -x "$DEPLOY_HOME/render-env.sh" ]; then
  "$DEPLOY_HOME/render-env.sh" > "$PROJECT_DIR/.env.runtime"
  ENV_FILE_ARG="--env-file $PROJECT_DIR/.env.runtime"
else
  echo "    (render-env.sh 없음 — 기존 .env 사용)"
  ENV_FILE_ARG=""
fi

# 4) registry pull + up
echo "[4/6] docker compose pull + up"
export IMAGE_TAG
docker compose -f docker-compose.yml -f docker-compose.prod.yml $ENV_FILE_ARG pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml $ENV_FILE_ARG up -d --remove-orphans

# 5) Health check (4 critical services)
echo "[5/6] health check"
"$DEPLOY_HOME/wait-healthy.sh" api worker tick-collector ui || {
  echo "FAILED — 4개 중 일부가 healthy 가 아님"
  if [ -n "$PREV" ]; then
    echo "    ↪ 롤백을 직접 수행하려면: $0 $PREV"
  fi
  exit 1
}

# 6) 성공 시 태그 저장
echo "[6/6] mark $IMAGE_TAG as last good"
echo "$IMAGE_TAG" > "$STATE_FILE"

echo "=== deploy.sh DONE $(date -u +%FT%TZ) — tag=$IMAGE_TAG ==="
