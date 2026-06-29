#!/usr/bin/env bash
# sync-logs-backup.sh — ~/deploy/*.log 들을 일일 gzip 아카이브로 묶어
# OCI Object Storage Archive 의 alpha/logs/<server>/YYYY/MM/DD.tar.gz 에 업로드.
# crontab: 30 23 * * *  /home/ubuntu/deploy/sync-logs-backup.sh  (KST 23:30, pg_dump 다음)
#
# 환경변수 (pg_dump_backup.sh 와 동일): OCI_BACKUP_*
set -euo pipefail

DEPLOY_HOME="${DEPLOY_HOME:-$HOME/deploy}"
HOST_TAG="${HOST_TAG:-$(hostname -s)}"
LOG_FILE="$DEPLOY_HOME/sync-logs.log"
mkdir -p "$DEPLOY_HOME"
exec >> "$LOG_FILE" 2>&1

echo "=== sync-logs START $(date -u +%FT%TZ) ==="

BOOTSTRAP="${INFISICAL_BOOTSTRAP:-$DEPLOY_HOME/.env.bootstrap}"
# shellcheck disable=SC1090
[ -f "$BOOTSTRAP" ] && { set -a; . "$BOOTSTRAP"; set +a; }

: "${OCI_BACKUP_ENDPOINT:?OCI_BACKUP_ENDPOINT 미설정}"
: "${OCI_BACKUP_BUCKET:?OCI_BACKUP_BUCKET 미설정}"
: "${OCI_BACKUP_ACCESS_KEY:?OCI_BACKUP_ACCESS_KEY 미설정}"
: "${OCI_BACKUP_SECRET_KEY:?OCI_BACKUP_SECRET_KEY 미설정}"
: "${OCI_BACKUP_REGION:=ap-chuncheon-1}"

DATE_TAG=$(date +%Y/%m/%d)
ARCHIVE_KEY="alpha/logs/${HOST_TAG}/${DATE_TAG}.tar.gz"

# ~/deploy/*.log 들을 메모리에서 tar+gzip → stdin pipe 로 업로드.
# 파일이 0개여도 빈 아카이브 생성하고 종료.
cd "$DEPLOY_HOME"
log_files=$(find . -maxdepth 1 -name '*.log' -type f 2>/dev/null | head -50)
if [ -z "$log_files" ]; then
  echo "    no logs to archive"; exit 0
fi

# shellcheck disable=SC2086
tar -czf - $log_files \
  | AWS_ACCESS_KEY_ID="$OCI_BACKUP_ACCESS_KEY" \
    AWS_SECRET_ACCESS_KEY="$OCI_BACKUP_SECRET_KEY" \
    /usr/local/bin/aws --endpoint-url "$OCI_BACKUP_ENDPOINT" --region "$OCI_BACKUP_REGION" \
        s3 cp - "s3://${OCI_BACKUP_BUCKET}/${ARCHIVE_KEY}" \
        --no-progress

SIZE=$(AWS_ACCESS_KEY_ID="$OCI_BACKUP_ACCESS_KEY" \
       AWS_SECRET_ACCESS_KEY="$OCI_BACKUP_SECRET_KEY" \
       /usr/local/bin/aws --endpoint-url "$OCI_BACKUP_ENDPOINT" --region "$OCI_BACKUP_REGION" \
           s3api head-object --bucket "$OCI_BACKUP_BUCKET" --key "$ARCHIVE_KEY" \
           --query 'ContentLength' --output text 2>/dev/null || echo "0")

echo "    archive: $ARCHIVE_KEY  size=${SIZE} bytes  files=$(echo "$log_files" | wc -l)"

# 업로드 성공했으면 로컬 로그는 truncate (디스크 사용량 누적 방지) — 단 deploy.log 는
# 진행중인 deploy 가 있을 수 있어 truncate 대신 회전(>200MB 면 archive).
for f in $log_files; do
  size=$(stat -c%s "$f" 2>/dev/null || echo 0)
  if [ "$size" -gt $((200 * 1024 * 1024)) ]; then
    : > "$f"  # truncate
    echo "    rotated $f (was ${size} bytes)"
  fi
done

echo "=== sync-logs DONE $(date -u +%FT%TZ) ==="
