#!/usr/bin/env bash
# render-env.sh — Infisical 에서 prod 환경의 시크릿을 dotenv 형식으로 출력.
# deploy.sh 가 호출해서 결과를 .env.runtime 으로 받음.
#
# 의존:
# - infisical CLI 가 PATH 또는 ~/.local/bin 에 설치돼 있어야 함
#   설치: curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | sudo -E bash
#         sudo apt install infisical
# - 부트스트랩 env (사용자 ~/.profile 또는 ~/deploy/.env.bootstrap 에서 로드):
#     INFISICAL_TOKEN          (machine identity token)
#     INFISICAL_PROJECT_ID
#     INFISICAL_ENV=prod
#     INFISICAL_API_URL=http://127.0.0.1:80   (self-hosted on same host)
set -euo pipefail

BOOTSTRAP="${INFISICAL_BOOTSTRAP:-$HOME/deploy/.env.bootstrap}"
if [ -f "$BOOTSTRAP" ]; then
  set -a; . "$BOOTSTRAP"; set +a
fi

: "${INFISICAL_TOKEN:?INFISICAL_TOKEN 미설정 — ~/deploy/.env.bootstrap 확인}"
: "${INFISICAL_PROJECT_ID:?INFISICAL_PROJECT_ID 미설정}"
: "${INFISICAL_ENV:=prod}"

# 별도 export domain (self-hosted Infisical) 가 있으면 --domain
DOMAIN_ARG=""
if [ -n "${INFISICAL_API_URL:-}" ]; then
  DOMAIN_ARG="--domain $INFISICAL_API_URL"
fi

# Infisical export: --format dotenv → KEY=VALUE 라인. --recursive 로 폴더 전체.
exec infisical export \
  --token "$INFISICAL_TOKEN" \
  --projectId "$INFISICAL_PROJECT_ID" \
  --env "$INFISICAL_ENV" \
  --format dotenv \
  --recursive \
  $DOMAIN_ARG
