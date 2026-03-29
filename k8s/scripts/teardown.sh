#!/usr/bin/env bash
set -euo pipefail

# k8s/scripts/teardown.sh — K8s 리소스 삭제
#
# 사용법:
#   ./k8s/scripts/teardown.sh          # dev 환경 (기본)
#   ./k8s/scripts/teardown.sh prod     # prod 환경
#   ./k8s/scripts/teardown.sh --all    # namespace 전체 삭제 (PVC 포함)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")"

if [[ "${1:-}" == "--all" ]]; then
    echo "=== 전체 삭제 (namespace + PVC) ==="
    read -p "alpha-trading namespace 전체를 삭제합니다. 계속? (y/N) " confirm
    if [[ "$confirm" == "y" ]]; then
        kubectl delete namespace alpha-trading --ignore-not-found
        echo "Namespace alpha-trading 삭제 완료"
    else
        echo "취소됨"
    fi
    exit 0
fi

ENV="${1:-dev}"
OVERLAY="$K8S_DIR/overlays/$ENV"

echo "=== Alpha Trading Teardown ($ENV) ==="
kubectl delete -k "$OVERLAY" --ignore-not-found
echo "리소스 삭제 완료 (PVC는 유지됨)"
