#!/bin/bash
# secrets-edit.sh — SOPS 파일을 안전하게 편집한다.
#
# sops 가 자동으로 decrypt → $EDITOR 호출 → 종료 시 re-encrypt 한다.
# 평문은 메모리 buffer + mlock 된 임시 파일에만 존재하고 디스크에 평문이
# 떨어지지 않는다.
#
# 사용법:
#   bash k8s/scripts/secrets-edit.sh                       # 기본 파일
#   bash k8s/scripts/secrets-edit.sh path/to/other.enc.yaml
#
# 운영 가이드: docs/secrets.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET="${1:-$REPO_ROOT/k8s/secrets/app-secret.enc.yaml}"

if ! command -v sops >/dev/null 2>&1; then
  echo "ERROR: sops 미설치. 'brew install sops age' 후 재시도하세요." >&2
  exit 1
fi

if [ ! -f "$TARGET" ]; then
  echo "ERROR: $TARGET 없음. 먼저 secrets-bootstrap.sh 를 실행하세요." >&2
  exit 1
fi

exec sops "$TARGET"
