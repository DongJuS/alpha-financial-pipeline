#!/usr/bin/env bash
# scripts/oci_instance_retry.sh — Oracle Cloud Ampere A1 인스턴스 생성 재시도
#
# 사용법:
#   1. OCI CLI 설치: https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm
#   2. OCI CLI 설정: oci setup config
#   3. 아래 변수를 자신의 Oracle Cloud 환경에 맞게 수정
#   4. chmod +x scripts/oci_instance_retry.sh
#   5. 수동 실행: ./scripts/oci_instance_retry.sh
#   6. 크론 등록 (5분마다):
#      crontab -e
#      */5 * * * * /path/to/scripts/oci_instance_retry.sh >> /tmp/oci_retry.log 2>&1
#
# 성공 시 인스턴스 OCID를 파일에 기록하고 이후 실행을 자동 스킵합니다.
#
set -uo pipefail

# ── 설정 (자신의 환경에 맞게 수정) ──────────────────────────────────
COMPARTMENT_ID="${OCI_COMPARTMENT_ID:-ocid1.compartment.oc1..CHANGE_ME}"
AVAILABILITY_DOMAIN="${OCI_AVAILABILITY_DOMAIN:-CHANGE_ME:AP-SEOUL-1-AD-1}"
SUBNET_ID="${OCI_SUBNET_ID:-ocid1.subnet.oc1.ap-seoul-1..CHANGE_ME}"
IMAGE_ID="${OCI_IMAGE_ID:-ocid1.image.oc1.ap-seoul-1..CHANGE_ME}"  # Ubuntu 22.04 ARM
SSH_KEY_FILE="${OCI_SSH_KEY_FILE:-$HOME/.ssh/id_ed25519.pub}"
SHAPE="VM.Standard.A1.Flex"
OCPUS=4
MEMORY_GB=24
BOOT_VOLUME_GB=200
DISPLAY_NAME="alpha-trading-server"

# ── 성공 마커 파일 ──────────────────────────────────────────────────
MARKER_FILE="/tmp/oci_instance_created.txt"

if [[ -f "$MARKER_FILE" ]]; then
    echo "[$(date)] 인스턴스 이미 생성됨 ($(cat "$MARKER_FILE")). 스킵."
    exit 0
fi

echo "[$(date)] Oracle Ampere A1 인스턴스 생성 시도..."

# ── OCI CLI 인스턴스 생성 ──────────────────────────────────────────
RESULT=$(oci compute instance launch \
    --compartment-id "$COMPARTMENT_ID" \
    --availability-domain "$AVAILABILITY_DOMAIN" \
    --shape "$SHAPE" \
    --shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEMORY_GB}" \
    --image-id "$IMAGE_ID" \
    --subnet-id "$SUBNET_ID" \
    --assign-public-ip true \
    --boot-volume-size-in-gbs "$BOOT_VOLUME_GB" \
    --display-name "$DISPLAY_NAME" \
    --metadata "{\"ssh_authorized_keys\": \"$(cat "$SSH_KEY_FILE")\"}" \
    2>&1)
EXIT_CODE=$?

if [[ $EXIT_CODE -ne 0 ]] || echo "$RESULT" | grep -qi "error\|exception\|capacity"; then
    echo "[$(date)] 실패 (용량 부족 등): $RESULT"
    exit 0  # 크론에서 재시도하도록 exit 0
fi

# ── 성공 시 OCID 저장 ──────────────────────────────────────────────
INSTANCE_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])" 2>/dev/null)
if [[ -z "$INSTANCE_ID" ]]; then
    echo "[$(date)] 실패 (OCID 추출 불가): $RESULT"
    exit 0
fi
echo "$INSTANCE_ID" > "$MARKER_FILE"
echo "[$(date)] 인스턴스 생성 성공: $INSTANCE_ID"

# 성공 알림 (optional — 텔레그램 토큰이 있으면 발송)
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=Oracle A1 인스턴스 생성 성공: ${INSTANCE_ID}" \
        > /dev/null || true
fi
