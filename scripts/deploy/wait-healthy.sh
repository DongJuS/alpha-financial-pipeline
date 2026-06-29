#!/usr/bin/env bash
# wait-healthy.sh — 인자로 받은 docker compose 서비스 이름이 모두 healthy 가 될 때까지 대기.
# 사용법: wait-healthy.sh api worker tick-collector ui
# 환경변수:
#   TIMEOUT_SECONDS (기본 180)
#   POLL_INTERVAL_SECONDS (기본 5)
set -euo pipefail

TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-180}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
SERVICES=("$@")
[ ${#SERVICES[@]} -gt 0 ] || { echo "usage: $0 <service> [<service>...]"; exit 2; }

# compose 프로젝트 이름 (현재 디렉터리의 compose 파일 기준)
PROJECT="${COMPOSE_PROJECT_NAME:-alpha-financial-pipeline}"

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
echo "wait-healthy: ${SERVICES[*]} (timeout=${TIMEOUT_SECONDS}s)"

while :; do
  all_ok=1
  for svc in "${SERVICES[@]}"; do
    container="${PROJECT}-${svc}-1"
    # health 가 정의돼 있으면 healthy 확인, 아니면 running 으로 OK
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || echo "missing")
    state=$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || echo "missing")

    if [ "$health" = "healthy" ]; then
      :  # ok
    elif [ "$health" = "none" ] && [ "$state" = "running" ]; then
      :  # no healthcheck defined, running counts as ok
    else
      all_ok=0
      printf "  %-20s health=%-10s state=%s\n" "$svc" "$health" "$state"
    fi
  done

  if [ $all_ok -eq 1 ]; then
    echo "wait-healthy: all ${SERVICES[*]} OK"
    exit 0
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "wait-healthy: TIMEOUT (${TIMEOUT_SECONDS}s)"
    exit 1
  fi
  sleep "$POLL_INTERVAL_SECONDS"
done
