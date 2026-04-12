#!/usr/bin/env bash
# Run instruments v2 migration against K3s PostgreSQL
# Usage: bash k8s/scripts/run_db_migration.sh
#
# This script port-forwards to the K3s PostgreSQL pod,
# sets DATABASE_URL for the local Python scripts, and
# runs the 3-step migration sequence.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
NAMESPACE="alpha-trading"
PG_SERVICE="alpha-pg-postgresql"
LOCAL_PORT=15432
PG_PORT=5432

# PID file for port-forward cleanup
PF_PID=""

cleanup() {
  if [ -n "$PF_PID" ] && kill -0 "$PF_PID" 2>/dev/null; then
    echo "  Cleaning up port-forward (PID $PF_PID)..."
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$REPO_ROOT"

# ── 1. Resolve DATABASE_URL credentials from SOPS secret ──
echo "=== [0/3] Resolving DATABASE_URL from SOPS secrets ==="
AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
if ! command -v sops >/dev/null 2>&1; then
  echo "ERROR: sops not installed. Run 'brew install sops age' first." >&2
  exit 1
fi
if [ ! -f "$AGE_KEY_FILE" ]; then
  echo "ERROR: age key not found at $AGE_KEY_FILE." >&2
  echo "       Run k8s/scripts/secrets-bootstrap.sh first." >&2
  exit 1
fi
export SOPS_AGE_KEY_FILE="$AGE_KEY_FILE"

# Extract DATABASE_URL and rewrite host:port to point to local port-forward
ORIG_DB_URL=$(sops --decrypt k8s/secrets/app-secret.enc.yaml | grep 'DATABASE_URL:' | sed 's/.*DATABASE_URL: *//' | tr -d '"' | tr -d "'")
if [ -z "$ORIG_DB_URL" ]; then
  echo "ERROR: Could not extract DATABASE_URL from SOPS secret." >&2
  exit 1
fi

# Rewrite the host:port portion to localhost:LOCAL_PORT
# postgresql://user:pass@host:port/db → postgresql://user:pass@localhost:LOCAL_PORT/db
DATABASE_URL=$(echo "$ORIG_DB_URL" | sed -E "s|@[^/]+/|@localhost:${LOCAL_PORT}/|")
export DATABASE_URL
echo "  DATABASE_URL resolved (host rewritten to localhost:${LOCAL_PORT})"

# ── 2. Port-forward to K3s PostgreSQL ──
echo "=== [1/3] Port-forwarding to $PG_SERVICE ==="
kubectl port-forward "svc/$PG_SERVICE" "${LOCAL_PORT}:${PG_PORT}" -n "$NAMESPACE" &
PF_PID=$!

# Wait for port-forward to become ready
for i in $(seq 1 15); do
  if nc -z localhost "$LOCAL_PORT" 2>/dev/null; then
    echo "  Port-forward ready on localhost:${LOCAL_PORT}"
    break
  fi
  if [ "$i" -eq 15 ]; then
    echo "ERROR: Port-forward did not become ready in 15 seconds." >&2
    exit 1
  fi
  sleep 1
done

# ── 3. Run migration scripts ──
echo "=== [1/3] Running schema migration ==="
python scripts/db/migrate_to_v2_instruments.py
echo "  Schema migration complete."

echo "=== [2/3] Seeding instruments registry ==="
python scripts/db/seed_all_instruments.py --market KR --instruments-only
echo "  Instruments seeded."

echo "=== [3/3] Seeding trading universe ==="
python scripts/db/seed_trading_universe.py
echo "  Trading universe seeded."

echo ""
echo "=== Migration complete ==="
