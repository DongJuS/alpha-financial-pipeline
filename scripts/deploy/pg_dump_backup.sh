#!/usr/bin/env bash
# pg_dump_backup.sh — PostgreSQL alpha_db 의 전체 dump 를 OCI Object Storage
# (Archive tier, agents-investing-backups 버킷) 의 alpha/postgres/ prefix 로 업로드.
# crontab: 0 23 * * *   /home/ubuntu/deploy/pg_dump_backup.sh  (KST 23:00)
#
# 환경변수 (~/deploy/.env.bootstrap + .env.runtime 에서 로드):
#   OCI_BACKUP_ENDPOINT      예: https://axpz2lvut9bp.compat.objectstorage.ap-chuncheon-1.oraclecloud.com
#   OCI_BACKUP_BUCKET        예: agents-investing-backups
#   OCI_BACKUP_ACCESS_KEY    OCI customer secret key 의 id
#   OCI_BACKUP_SECRET_KEY    OCI customer secret key 의 key
#   POSTGRES_USER, POSTGRES_PASSWORD  (Infisical 또는 .env)
set -euo pipefail

# OCI Object Storage 는 AWS chunked encoding (sigv4 streaming) 을 지원 안 함 (NotImplemented).
# aws CLI v2.30+ 의 새 기본은 checksum 을 streaming 으로 계산하는데, 이를 when_required
# 로 낮춰 chunked encoding 회피.
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/alpha-financial-pipeline}"
DEPLOY_HOME="${DEPLOY_HOME:-$HOME/deploy}"
LOG_FILE="$DEPLOY_HOME/pg_dump.log"
mkdir -p "$DEPLOY_HOME"
exec >> "$LOG_FILE" 2>&1

echo "=== pg_dump START $(date -u +%FT%TZ) ==="

BOOTSTRAP="${INFISICAL_BOOTSTRAP:-$DEPLOY_HOME/.env.bootstrap}"
ENV_FILE="$PROJECT_DIR/.env.runtime"
[ -f "$ENV_FILE" ] || ENV_FILE="$PROJECT_DIR/.env"

# shellcheck disable=SC1090
[ -f "$BOOTSTRAP" ] && { set -a; . "$BOOTSTRAP"; set +a; }
[ -f "$ENV_FILE" ] || { echo "FAIL: $ENV_FILE 없음"; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

: "${POSTGRES_USER:?POSTGRES_USER 미설정}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD 미설정}"
: "${OCI_BACKUP_ENDPOINT:?OCI_BACKUP_ENDPOINT 미설정 — bootstrap 확인}"
: "${OCI_BACKUP_BUCKET:?OCI_BACKUP_BUCKET 미설정}"
: "${OCI_BACKUP_ACCESS_KEY:?OCI_BACKUP_ACCESS_KEY 미설정}"
: "${OCI_BACKUP_SECRET_KEY:?OCI_BACKUP_SECRET_KEY 미설정}"
: "${OCI_BACKUP_REGION:=ap-chuncheon-1}"

DATE_TAG=$(date +%F)
DUMP_KEY="alpha/postgres/alpha_db_${DATE_TAG}.sql.gz"

docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" \
            alpha-financial-pipeline-postgres-1 \
            pg_dump -U "$POSTGRES_USER" --no-owner --no-acl alpha_db \
  | gzip \
  | AWS_ACCESS_KEY_ID="$OCI_BACKUP_ACCESS_KEY" \
    AWS_SECRET_ACCESS_KEY="$OCI_BACKUP_SECRET_KEY" \
    /usr/local/bin/aws --endpoint-url "$OCI_BACKUP_ENDPOINT" --region "$OCI_BACKUP_REGION" \
        s3 cp - "s3://${OCI_BACKUP_BUCKET}/${DUMP_KEY}" \
        --no-progress

SIZE=$(AWS_ACCESS_KEY_ID="$OCI_BACKUP_ACCESS_KEY" \
       AWS_SECRET_ACCESS_KEY="$OCI_BACKUP_SECRET_KEY" \
       /usr/local/bin/aws --endpoint-url "$OCI_BACKUP_ENDPOINT" --region "$OCI_BACKUP_REGION" \
           s3api head-object --bucket "$OCI_BACKUP_BUCKET" --key "$DUMP_KEY" \
           --query 'ContentLength' --output text 2>/dev/null || echo "0")

echo "    dump: $DUMP_KEY  size=${SIZE} bytes"

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  MB=$(( SIZE / 1024 / 1024 ))
  curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
       -d chat_id="${TELEGRAM_CHAT_ID}" \
       -d text="[pg_dump] ${DATE_TAG} 완료 — ${MB} MB → OCI Archive" || true
fi

echo "=== pg_dump DONE $(date -u +%FT%TZ) ==="
