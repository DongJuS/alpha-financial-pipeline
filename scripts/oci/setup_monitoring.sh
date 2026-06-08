#!/usr/bin/env bash
# scripts/oci/setup_monitoring.sh
#
# Oracle Cloud 호스트/비용 장애 감시 부트스트랩 (멱등).
# 한 번 실행하면 필요한 리소스가 없을 때만 생성하고, 다음부터는 존재 확인만 수행한다.
#
# 만들어 주는 리소스
#   1. ONS Topic (Notification Service)   — 이메일 수신 창구
#   2. Email Subscription                  — 등록 이메일로 실제 알림 전송
#   3. Compute Instance Alarm x3           — CPU / Memory / Filesystem 이용률
#   4. Monthly Budget + Alert Rule         — $0 기반(사실상 $1+1%) 사용 감지
#
# 사전 조건
#   - oci CLI 설치 및 `oci setup config` 완료
#   - 운영 대상 compartment 및 인스턴스 OCID 확보
#   - oci.yaml profile 기본 설정(또는 OCI_CLI_PROFILE 환경변수)
#
# 필수 입력 (환경변수)
#   OCI_COMPARTMENT_OCID     앱이 돌아가는 compartment OCID
#   OCI_TENANCY_OCID         root tenancy OCID (budget 생성에 필요)
#   OCI_INSTANCE_OCID        감시 대상 Compute 인스턴스 OCID
#   OCI_ALERT_EMAIL          알림 수신 이메일 (subscription 확인 메일 1회 클릭 필요)
#
# 선택 입력
#   OCI_REGION               기본값: CLI 설정 프로파일
#   OCI_BUDGET_AMOUNT        기본값 1 (최소값, $0은 API 미지원)
#   OCI_BUDGET_THRESHOLD     기본값 1 (1% = $0.01 spend → 알람)
#   OCI_CPU_THRESHOLD        기본값 90 (%)
#   OCI_MEM_THRESHOLD        기본값 90 (%)
#   OCI_DISK_THRESHOLD       기본값 80 (%)
#   OCI_TOPIC_NAME           기본값 alpha-ops-alerts
#
# 사용법
#   export OCI_COMPARTMENT_OCID=ocid1.compartment.oc1..xxx
#   export OCI_TENANCY_OCID=ocid1.tenancy.oc1..xxx
#   export OCI_INSTANCE_OCID=ocid1.instance.oc1.ap-seoul-1..xxx
#   export OCI_ALERT_EMAIL=ops@example.com
#   ./scripts/oci/setup_monitoring.sh
#
# 종료 시 STDOUT 마지막 줄에 "OCI monitoring setup complete" 를 찍는다.

set -euo pipefail

# ── 입력 검증 ────────────────────────────────────────────────────────────
: "${OCI_COMPARTMENT_OCID:?OCI_COMPARTMENT_OCID required}"
: "${OCI_TENANCY_OCID:?OCI_TENANCY_OCID required (budget은 tenancy scope)}"
: "${OCI_INSTANCE_OCID:?OCI_INSTANCE_OCID required}"
: "${OCI_ALERT_EMAIL:?OCI_ALERT_EMAIL required (subscription confirmation 이메일 1회 클릭 필요)}"

TOPIC_NAME="${OCI_TOPIC_NAME:-alpha-ops-alerts}"
BUDGET_AMOUNT="${OCI_BUDGET_AMOUNT:-1}"
BUDGET_THRESHOLD="${OCI_BUDGET_THRESHOLD:-1}"
CPU_THRESHOLD="${OCI_CPU_THRESHOLD:-90}"
MEM_THRESHOLD="${OCI_MEM_THRESHOLD:-90}"
DISK_THRESHOLD="${OCI_DISK_THRESHOLD:-80}"
REGION_ARG=()
if [[ -n "${OCI_REGION:-}" ]]; then
    REGION_ARG=(--region "$OCI_REGION")
fi

if ! command -v oci >/dev/null 2>&1; then
    echo "✗ oci CLI가 필요합니다. 설치: https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm" >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "✗ jq가 필요합니다. macOS: 'brew install jq', Ubuntu: 'sudo apt-get install -y jq'" >&2
    exit 1
fi

echo "[1/4] ONS topic '$TOPIC_NAME' 확인..."
TOPIC_ID=$(oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} ons topic list \
    --compartment-id "$OCI_COMPARTMENT_OCID" \
    --name "$TOPIC_NAME" \
    --lifecycle-state ACTIVE \
    --all 2>/dev/null | jq -r '.data[0]."topic-id" // empty')

if [[ -z "$TOPIC_ID" ]]; then
    echo "  -> topic 미존재. 생성 중..."
    TOPIC_ID=$(oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} ons topic create \
        --name "$TOPIC_NAME" \
        --compartment-id "$OCI_COMPARTMENT_OCID" \
        --description "alpha-financial-pipeline 운영 알림" \
        2>&1 | jq -r '.data."topic-id" // empty')
    echo "  ✓ topic 생성: $TOPIC_ID"
else
    echo "  ✓ 이미 존재: $TOPIC_ID"
fi

echo "[2/4] Email subscription '$OCI_ALERT_EMAIL' 확인..."
EXISTING_SUB=$(oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} ons subscription list \
    --compartment-id "$OCI_COMPARTMENT_OCID" \
    --topic-id "$TOPIC_ID" \
    --all 2>/dev/null | jq -r \
        --arg email "$OCI_ALERT_EMAIL" \
        '.data[] | select(.endpoint == $email) | .id' \
    | head -n 1)

if [[ -z "$EXISTING_SUB" ]]; then
    echo "  -> subscription 미존재. 생성 중... (확인 이메일 1회 클릭 필요)"
    oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} ons subscription create \
        --compartment-id "$OCI_COMPARTMENT_OCID" \
        --topic-id "$TOPIC_ID" \
        --protocol EMAIL \
        --subscription-endpoint "$OCI_ALERT_EMAIL" >/dev/null
    echo "  ✓ subscription 생성. 수신함에서 Confirm subscription 클릭 필요."
else
    echo "  ✓ 이미 존재: $EXISTING_SUB"
fi

# ── helper: alarm 생성(없으면) ───────────────────────────────────────────
ensure_alarm() {
    local display_name="$1"
    local query="$2"
    local severity="$3"

    local existing_id
    existing_id=$(oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} monitoring alarm list \
        --compartment-id "$OCI_COMPARTMENT_OCID" \
        --display-name "$display_name" \
        --all 2>/dev/null | jq -r '.data[0].id // empty')

    if [[ -n "$existing_id" ]]; then
        echo "  ✓ '$display_name' 이미 존재: $existing_id"
        return
    fi

    echo "  -> '$display_name' 생성 중..."
    oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} monitoring alarm create \
        --compartment-id "$OCI_COMPARTMENT_OCID" \
        --display-name "$display_name" \
        --metric-compartment-id "$OCI_COMPARTMENT_OCID" \
        --namespace oci_computeagent \
        --query-text "$query" \
        --severity "$severity" \
        --destinations "[\"$TOPIC_ID\"]" \
        --is-enabled true \
        --body "resource=$OCI_INSTANCE_OCID" \
        --pending-duration PT5M \
        --repeat-notification-duration PT1H >/dev/null
    echo "  ✓ 생성 완료"
}

echo "[3/4] Compute alarm 세팅 (CPU/MEM/Disk)..."
RESOURCE_CLAUSE="resourceId = \"$OCI_INSTANCE_OCID\""
ensure_alarm \
    "alpha-cpu-high" \
    "CpuUtilization[1m]{$RESOURCE_CLAUSE}.mean() > $CPU_THRESHOLD" \
    CRITICAL
ensure_alarm \
    "alpha-memory-high" \
    "MemoryUtilization[1m]{$RESOURCE_CLAUSE}.mean() > $MEM_THRESHOLD" \
    CRITICAL
ensure_alarm \
    "alpha-disk-high" \
    "FilesystemUtilization[1m]{$RESOURCE_CLAUSE}.mean() > $DISK_THRESHOLD" \
    WARNING

echo "[4/4] Monthly budget + alert rule 세팅..."
BUDGET_DISPLAY="alpha-monthly-budget"
BUDGET_ID=$(oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} budgets budget list \
    --compartment-id "$OCI_TENANCY_OCID" \
    --target-type COMPARTMENT \
    --display-name "$BUDGET_DISPLAY" \
    --all 2>/dev/null | jq -r '.data[0].id // empty')

if [[ -z "$BUDGET_ID" ]]; then
    echo "  -> budget 미존재. 생성 중 (\$$BUDGET_AMOUNT/월 타겟)..."
    BUDGET_ID=$(oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} budgets budget create \
        --compartment-id "$OCI_TENANCY_OCID" \
        --display-name "$BUDGET_DISPLAY" \
        --amount "$BUDGET_AMOUNT" \
        --reset-period MONTHLY \
        --target-type COMPARTMENT \
        --targets "[\"$OCI_COMPARTMENT_OCID\"]" \
        --description "사실상 \$0 사용 감시(최소값 \$1 + 1% threshold)" \
        --query 'data.id' \
        --raw-output)
    echo "  ✓ budget 생성: $BUDGET_ID"
else
    echo "  ✓ budget 이미 존재: $BUDGET_ID"
fi

ALERT_DISPLAY="alpha-any-spend"
EXISTING_ALERT=$(oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} budgets alert-rule list \
    --budget-id "$BUDGET_ID" \
    --all 2>/dev/null | jq -r \
        --arg name "$ALERT_DISPLAY" \
        '.data[] | select(."display-name" == $name) | .id' \
    | head -n 1)

if [[ -z "$EXISTING_ALERT" ]]; then
    echo "  -> alert rule 생성 중 (>=$BUDGET_THRESHOLD% 지출 시 이메일)..."
    oci ${REGION_ARG[@]+"${REGION_ARG[@]}"} budgets alert-rule create \
        --budget-id "$BUDGET_ID" \
        --display-name "$ALERT_DISPLAY" \
        --type ACTUAL \
        --threshold "$BUDGET_THRESHOLD" \
        --threshold-type PERCENTAGE \
        --recipients "$OCI_ALERT_EMAIL" \
        --description "budget의 $BUDGET_THRESHOLD% 이상 지출 시 발생" >/dev/null
    echo "  ✓ alert rule 생성"
else
    echo "  ✓ alert rule 이미 존재: $EXISTING_ALERT"
fi

cat <<MSG

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OCI monitoring setup complete.

다음 수작업이 남아 있습니다:
  1) "$OCI_ALERT_EMAIL" 수신함에서 'Oracle Cloud subscription confirmation'
     메일의 Confirm subscription 링크 1회 클릭 (최초 1회).
  2) Compute 인스턴스에 Oracle Cloud Agent의 'Compute Instance Monitoring'
     플러그인이 활성화되어 있는지 확인 (OS 기본으로 ON이 대부분).
     콘솔: Instance → Oracle Cloud Agent 탭.

생성된 리소스
  - ONS topic      : $TOPIC_ID
  - CPU alarm      : alpha-cpu-high (>${CPU_THRESHOLD}%)
  - Memory alarm   : alpha-memory-high (>${MEM_THRESHOLD}%)
  - Disk alarm     : alpha-disk-high (>${DISK_THRESHOLD}%)
  - Budget         : $BUDGET_ID (\$$BUDGET_AMOUNT/월)
  - Alert rule     : alpha-any-spend (>=${BUDGET_THRESHOLD}%)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MSG
