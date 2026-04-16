#!/usr/bin/env bash
#
# scripts/db/backup.sh — alpha_db PostgreSQL dump 헬퍼
#
# 용도: 로컬 K3s/Compose → 클라우드 서버 이전 시 cold migration용 전체 덤프.
# 형식: pg_dump custom format (-Fc) — 병렬 복원 + 선택적 객체 복원 가능.
#
# 사용:
#   bash scripts/db/backup.sh --output /tmp/alpha_db.dump
#   bash scripts/db/backup.sh --dry-run               # 명령만 출력 (password 마스킹)
#
# 환경변수:
#   DATABASE_URL  postgres://user:pass@host:port/db (필수)
#                 미설정 시 .env에서 읽음.
#
# 보안: password는 PGPASSWORD env로만 전달. command line에 안 나옴.
#
set -euo pipefail

OUTPUT="${OUTPUT:-/tmp/alpha_db.dump}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output) OUTPUT="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -25
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "${DATABASE_URL:-}" ]]; then
    if [[ -f .env ]]; then
        DATABASE_URL=$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)
    fi
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "ERROR: DATABASE_URL 미설정. 환경변수 또는 .env 필요." >&2
    exit 3
fi

# DATABASE_URL 파싱 (postgres://user:pass@host:port/db)
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

CMD=(pg_dump --format=custom --compress=9 --no-owner --no-acl --file="$OUTPUT" -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB")

if [[ $DRY_RUN -eq 1 ]]; then
    echo "[DRY-RUN] PGPASSWORD=*** ${CMD[*]}"
    exit 0
fi

echo "[$(date)] Dumping → $OUTPUT (host=$PG_HOST db=$PG_DB)"
PGPASSWORD="$PG_PASS" "${CMD[@]}"
SIZE=$(du -h "$OUTPUT" | cut -f1)
echo "[$(date)] 완료. 파일: $OUTPUT ($SIZE)"
