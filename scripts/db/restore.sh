#!/usr/bin/env bash
#
# scripts/db/restore.sh — alpha_db PostgreSQL pg_restore 헬퍼
#
# 용도: 클라우드 서버에서 backup.sh로 만든 dump 파일을 복원.
# 사전 조건: PostgreSQL 컨테이너 기동 + 빈 alpha_db 데이터베이스 존재.
#
# 사용:
#   bash scripts/db/restore.sh --input /tmp/alpha_db.dump
#   bash scripts/db/restore.sh --input /tmp/alpha_db.dump --jobs 4
#   bash scripts/db/restore.sh --dry-run --input /tmp/alpha_db.dump
#
# 보안: password는 PGPASSWORD env로만 전달. command line에 안 나옴.
#
# 주의:
#   복원 후 반드시 마이그레이션 4단계를 순차 실행한다 (docs/cloud-migration-phases.md):
#     1. migrate_to_v2_instruments.py
#     2. migrate_ohlcv_minute.py
#     3. seed_all_instruments.py
#     4. seed_trading_universe.py
#
set -euo pipefail

INPUT=""
JOBS=2
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input) INPUT="$2"; shift 2 ;;
        --jobs) JOBS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -25
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "$INPUT" ]]; then
    echo "ERROR: --input 필수" >&2
    exit 2
fi

if [[ ! -f "$INPUT" ]]; then
    echo "ERROR: 파일 없음: $INPUT" >&2
    exit 3
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
    if [[ -f .env ]]; then
        DATABASE_URL=$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)
    fi
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "ERROR: DATABASE_URL 미설정" >&2
    exit 3
fi

parse_url() {
    python3 - "$1" <<'PY'
import sys, urllib.parse
u = urllib.parse.urlparse(sys.argv[1])
print(u.username or '')
print(u.password or '')
print(u.hostname or 'localhost')
print(u.port or 5432)
print((u.path or '/').lstrip('/'))
PY
}

{
    read -r PG_USER
    read -r PG_PASS
    read -r PG_HOST
    read -r PG_PORT
    read -r PG_DB
} < <(parse_url "$DATABASE_URL")

CMD=(pg_restore --no-owner --no-acl --jobs="$JOBS" -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" "$INPUT")

if [[ $DRY_RUN -eq 1 ]]; then
    echo "[DRY-RUN] PGPASSWORD=*** ${CMD[*]}"
    exit 0
fi

echo "[$(date)] Restoring ← $INPUT (host=$PG_HOST db=$PG_DB jobs=$JOBS)"
PGPASSWORD="$PG_PASS" "${CMD[@]}"
echo "[$(date)] 완료. 다음 단계: docs/cloud-migration-phases.md Phase 2.3 마이그레이션 4단계 실행"
