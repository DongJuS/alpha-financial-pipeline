#!/usr/bin/env bash
# scripts/oci/disk_monitor.sh — Docker 디스크 사용량 모니터링 + Telegram 알림
#
# Docker 볼륨 + 호스트 디스크 사용량을 체크하고,
# 볼륨이 임계값을 초과하면 Telegram 알림을 발송합니다.
#
# 사용법:
#   ./scripts/oci/disk_monitor.sh
#
# 환경변수:
#   TELEGRAM_BOT_TOKEN  — Telegram Bot 토큰 (미설정 시 알림 생략)
#   TELEGRAM_CHAT_ID    — Telegram Chat ID
#   DISK_THRESHOLD_GB   — 알림 임계값 (기본: 50)
#
# 크론 등록 (매일 09:00 KST = 00:00 UTC):
#   crontab -e
#   0 0 * * * /home/ubuntu/alpha-financial-pipeline/scripts/oci/disk_monitor.sh >> /tmp/disk_monitor.log 2>&1
#
set -uo pipefail

THRESHOLD_GB="${DISK_THRESHOLD_GB:-50}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

# ── 데이터 수집 ──────────────────────────────────────────────────
DOCKER_DF=$(docker system df 2>/dev/null || echo "docker system df 실행 실패")
VOLUMES_SIZE=$(du -sh /var/lib/docker/volumes/ 2>/dev/null | cut -f1 || echo "N/A")
VOLUMES_BYTES=$(du -sb /var/lib/docker/volumes/ 2>/dev/null | cut -f1 || echo "0")
DISK_USAGE=$(df -h / 2>/dev/null | tail -1 || echo "N/A")
DISK_PERCENT=$(df / 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%' || echo "0")

# GB 변환
VOLUMES_GB=$((VOLUMES_BYTES / 1073741824))

# ── 리포트 생성 ──────────────────────────────────────────────────
REPORT="[Docker Disk Monitor]
Date: $(date '+%Y-%m-%d %H:%M:%S %Z')
Host: $(hostname)

Docker System DF:
${DOCKER_DF}

Volumes Total: ${VOLUMES_SIZE} (${VOLUMES_GB}GB)
Root Disk: ${DISK_USAGE}"

echo "$REPORT"

# ── 임계값 체크 + 알림 ──────────────────────────────────────────
ALERT_NEEDED=false
ALERT_MSG=""

if [ "$VOLUMES_GB" -ge "$THRESHOLD_GB" ]; then
    ALERT_NEEDED=true
    ALERT_MSG="Docker volumes ${VOLUMES_SIZE} >= ${THRESHOLD_GB}GB"
fi

if [ "$DISK_PERCENT" -ge 80 ]; then
    ALERT_NEEDED=true
    ALERT_MSG="${ALERT_MSG:+${ALERT_MSG} | }Root disk ${DISK_PERCENT}% >= 80%"
fi

if [ "$ALERT_NEEDED" = true ]; then
    FULL_ALERT="⚠️ 디스크 사용량 경고
- ${ALERT_MSG}
- 시각: $(date '+%Y-%m-%d %H:%M:%S')

${REPORT}"

    if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
        curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "text=${FULL_ALERT}" \
            > /dev/null || true
        echo "[$(date)] Telegram 알림 발송 완료."
    else
        echo "[$(date)] WARNING: 임계값 초과이나 Telegram 미설정."
    fi
else
    echo "[$(date)] OK: Volumes ${VOLUMES_SIZE} (${VOLUMES_GB}GB) < ${THRESHOLD_GB}GB, Disk ${DISK_PERCENT}% < 80%."
fi
