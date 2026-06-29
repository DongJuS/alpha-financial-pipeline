#!/usr/bin/env bash
# pg_dump_to_r2.sh — PostgreSQL 전체 dump 를 Cloudflare R2 로 업로드.
# crontab: 0 23 * * *   /home/ubuntu/deploy/pg_dump_to_r2.sh  (KST 23:00)
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/alpha-financial-pipeline}"
DEPLOY_HOME="${DEPLOY_HOME:-$HOME/deploy}"
LOG_FILE="$DEPLOY_HOME/pg_dump.log"
mkdir -p "$DEPLOY_HOME"
exec >> "$LOG_FILE" 2>&1

echo "=== pg_dump START $(date -u +%FT%TZ) ==="

# .env.runtime (Infisical) 이 있으면 거기서 S3_* 와 POSTGRES_* 가져옴.
ENV_FILE="$PROJECT_DIR/.env.runtime"
[ -f "$ENV_FILE" ] || ENV_FILE="$PROJECT_DIR/.env"
[ -f "$ENV_FILE" ] || { echo "FAIL: $ENV_FILE 없음"; exit 1; }

set -a; . "$ENV_FILE"; set +a

: "${POSTGRES_USER:?POSTGRES_USER 미설정}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD 미설정}"
: "${S3_ENDPOINT_URL:?S3_ENDPOINT_URL (R2) 미설정}"
: "${S3_BUCKET_NAME:?S3_BUCKET_NAME 미설정}"
: "${S3_ACCESS_KEY:?S3_ACCESS_KEY 미설정}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY 미설정}"

DATE_TAG=$(date +%F)
DUMP_KEY="backups/postgres/alpha_db_${DATE_TAG}.sql.gz"

# postgres 컨테이너 내부에서 pg_dump → gzip → aws s3 cp (호스트 awscli 로)
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" \
            alpha-financial-pipeline-postgres-1 \
            pg_dump -U "$POSTGRES_USER" --no-owner --no-acl alpha_db \
  | gzip \
  | AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
    AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
    aws --endpoint-url "$S3_ENDPOINT_URL" \
        s3 cp - "s3://${S3_BUCKET_NAME}/${DUMP_KEY}" \
        --no-progress

# 결과 사이즈 확인
SIZE=$(AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
       AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
       aws --endpoint-url "$S3_ENDPOINT_URL" \
           s3api head-object --bucket "$S3_BUCKET_NAME" --key "$DUMP_KEY" \
           --query 'ContentLength' --output text 2>/dev/null || echo "0")

echo "    dump: $DUMP_KEY  size=${SIZE} bytes"

# Telegram 알림 (옵션)
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  MB=$(( SIZE / 1024 / 1024 ))
  curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
       -d chat_id="${TELEGRAM_CHAT_ID}" \
       -d text="[pg_dump] ${DATE_TAG} 완료 — ${MB} MB" || true
fi

echo "=== pg_dump DONE $(date -u +%FT%TZ) ==="
