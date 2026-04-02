#!/bin/bash
# LLM 인증 초기화 — 최초 1회만 실행
# 이후 kubectl apply -k 시 자동으로 Secret이 생성됨
set -euo pipefail

SECRETS_DIR="$(cd "$(dirname "$0")/../base/.secrets" && pwd)"
ADC_SRC="${HOME}/.config/gcloud/application_default_credentials.json"
CLAUDE_TOKEN_FILE="${SECRETS_DIR}/claude-token"
ADC_DEST="${SECRETS_DIR}/gcloud-adc.json"

mkdir -p "$SECRETS_DIR"

echo "=== LLM 인증 초기화 ==="

# 1. Gemini ADC — 자동 복사
if [ -f "$ADC_SRC" ]; then
    cp "$ADC_SRC" "$ADC_DEST"
    echo "[OK] Gemini ADC 복사 완료: $ADC_DEST"
else
    echo "[WARN] gcloud ADC 없음 — gcloud auth application-default login 먼저 실행"
fi

# 2. Claude Token — 이미 있으면 스킵
if [ -f "$CLAUDE_TOKEN_FILE" ] && [ -s "$CLAUDE_TOKEN_FILE" ]; then
    echo "[OK] Claude token 이미 존재 — 스킵"
else
    echo ""
    echo "Claude OAuth Token이 필요합니다."
    echo "  1. 다른 터미널에서: claude setup-token"
    echo "  2. 발급된 토큰을 아래에 붙여넣기:"
    echo ""
    read -rp "Token: " token
    if [ -n "$token" ]; then
        echo "$token" > "$CLAUDE_TOKEN_FILE"
        echo "[OK] Claude token 저장 완료"
    else
        echo "[SKIP] Claude token 미입력 — Gemini만 사용"
        touch "$CLAUDE_TOKEN_FILE"
    fi
fi

echo ""
echo "[DONE] 초기화 완료. 이후 kubectl apply -k k8s/base/ 만 치면 Secret이 자동 생성됩니다."
