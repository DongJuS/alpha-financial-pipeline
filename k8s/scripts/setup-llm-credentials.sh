#!/bin/bash
# K3s에 LLM 인증 정보를 Secret으로 생성하는 스크립트
#
# 사전 요구사항:
#   1. claude setup-token 실행 후 토큰 복사
#   2. gcloud auth application-default login 완료
#
# 사용법:
#   ./k8s/scripts/setup-llm-credentials.sh <CLAUDE_TOKEN>

set -euo pipefail

NAMESPACE="alpha-trading"
ADC_PATH="${HOME}/.config/gcloud/application_default_credentials.json"
CLAUDE_TOKEN="${1:-}"

echo "=== LLM 인증 Secret 설정 ==="

# Gemini ADC 확인
if [ ! -f "$ADC_PATH" ]; then
    echo "[ERROR] gcloud ADC 파일 없음: $ADC_PATH"
    echo "  → gcloud auth application-default login 을 먼저 실행하세요."
    exit 1
fi
echo "[OK] Gemini ADC 파일 확인: $ADC_PATH"

# Claude Token 확인
if [ -z "$CLAUDE_TOKEN" ]; then
    echo ""
    echo "[INFO] Claude OAuth Token이 제공되지 않았습니다."
    echo "  → 터미널에서 'claude setup-token' 을 실행하고 토큰을 복사하세요."
    echo "  → 그 후: $0 <토큰>"
    echo ""
    echo "Claude 없이 Gemini만 설정할까요? (y/N)"
    read -r answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        exit 1
    fi
    echo "[SKIP] Claude OAuth Token — Gemini만 설정합니다."
    kubectl create secret generic llm-credentials \
        --namespace "$NAMESPACE" \
        --from-file=gcloud-adc.json="$ADC_PATH" \
        --dry-run=client -o yaml | kubectl apply -f -
else
    echo "[OK] Claude OAuth Token 제공됨"
    kubectl create secret generic llm-credentials \
        --namespace "$NAMESPACE" \
        --from-literal=CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_TOKEN" \
        --from-file=gcloud-adc.json="$ADC_PATH" \
        --dry-run=client -o yaml | kubectl apply -f -
fi

echo ""
echo "=== Secret 확인 ==="
kubectl get secret llm-credentials -n "$NAMESPACE" -o jsonpath='{.data}' | python3 -c "
import sys, json
data = json.load(sys.stdin)
for key in data:
    val_len = len(data[key])
    print(f'  {key}: {val_len} chars (base64)')
" 2>/dev/null || kubectl get secret llm-credentials -n "$NAMESPACE"

echo ""
echo "[DONE] llm-credentials Secret 생성 완료."
echo "  → worker/api Pod를 재시작하면 적용됩니다:"
echo "     kubectl rollout restart deployment/worker deployment/api -n $NAMESPACE"
