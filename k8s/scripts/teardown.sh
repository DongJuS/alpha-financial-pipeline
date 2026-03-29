#!/usr/bin/env bash
set -euo pipefail

# k8s/scripts/teardown.sh — Helm(인프라) + Kustomize(앱) 삭제
#
# 사용법:
#   ./k8s/scripts/teardown.sh              # dev: 앱만 삭제 (인프라 유지)
#   ./k8s/scripts/teardown.sh prod         # prod: 앱만 삭제
#   ./k8s/scripts/teardown.sh --infra      # 인프라(Helm)도 삭제
#   ./k8s/scripts/teardown.sh --all        # namespace 전체 삭제 (PVC 포함)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")"
NS="alpha-trading"

# ── --all: namespace 전체 삭제 ────────────────────────────────
if [[ "${1:-}" == "--all" ]]; then
    echo "=== 전체 삭제 (namespace + Helm releases + PVC) ==="
    read -p "alpha-trading namespace 전체를 삭제합니다. 계속? (y/N) " confirm
    if [[ "$confirm" == "y" ]]; then
        helm uninstall alpha-minio alpha-redis alpha-pg -n "$NS" 2>/dev/null || true
        kubectl delete namespace "$NS" --ignore-not-found
        echo "Namespace $NS 전체 삭제 완료"
    else
        echo "취소됨"
    fi
    exit 0
fi

# ── --infra: Helm 인프라 삭제 ─────────────────────────────────
if [[ "${1:-}" == "--infra" ]]; then
    echo "=== Helm 인프라 삭제 ==="
    helm uninstall alpha-minio -n "$NS" 2>/dev/null && echo "  MinIO 삭제 ✅" || echo "  MinIO 없음"
    helm uninstall alpha-redis -n "$NS" 2>/dev/null && echo "  Redis 삭제 ✅" || echo "  Redis 없음"
    helm uninstall alpha-pg -n "$NS" 2>/dev/null && echo "  PostgreSQL 삭제 ✅" || echo "  PostgreSQL 없음"
    echo "PVC는 유지됨. 삭제하려면 --all 사용."
    exit 0
fi

# ── 앱만 삭제 (기본) ─────────────────────────────────────────
ENV="${1:-dev}"
OVERLAY="$K8S_DIR/overlays/$ENV"

echo "=== 앱 삭제 ($ENV) ==="
kubectl delete -k "$OVERLAY" --ignore-not-found
echo "앱 리소스 삭제 완료. Helm 인프라는 유지됨."
echo ""
echo "인프라도 삭제하려면: $0 --infra"
echo "전체 삭제하려면:     $0 --all"
