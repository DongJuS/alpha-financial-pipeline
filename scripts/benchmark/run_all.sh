#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run_all.sh — 전체 벤치마크 1커맨드 실행
# ─────────────────────────────────────────────────────────────────────
# 사용법:
#   ./scripts/benchmark/run_all.sh              # 전체 실행
#   ./scripts/benchmark/run_all.sh --skip-fio   # fio 제외
#   ./scripts/benchmark/run_all.sh --skip-k6    # k6 제외
#   ./scripts/benchmark/run_all.sh --db-only    # DB 벤치마크만
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULT_DIR="$SCRIPT_DIR/results"
NAMESPACE="${K8S_NAMESPACE:-alpha-trading}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

export RESULT_DIR
export DB_HOST="${DB_HOST:-localhost}"
export DB_PORT="${DB_PORT:-5432}"
export DB_NAME="${DB_NAME:-alpha_db}"
export DB_USER="${DB_USER:-alpha_user}"
export DB_PASS="${DB_PASS:-alpha_pass}"

# ── 인자 파싱 ────────────────────────────────────────────────────
SKIP_FIO=false
SKIP_K6=false
DB_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --skip-fio) SKIP_FIO=true ;;
        --skip-k6)  SKIP_K6=true ;;
        --db-only)  DB_ONLY=true; SKIP_FIO=true; SKIP_K6=true ;;
        --help|-h)
            echo "사용법: $0 [--skip-fio] [--skip-k6] [--db-only]"
            exit 0
            ;;
    esac
done

# ── 사전 요구사항 확인 ────────────────────────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "  [MISSING] $1 — brew install $2"
        return 1
    else
        echo "  [OK]      $1"
        return 0
    fi
}

echo "================================================================"
echo "  벤치마크 사전 요구사항 확인"
echo "================================================================"
echo ""

MISSING=0
check_cmd psql     "libpq"       || MISSING=$((MISSING + 1))
check_cmd pgbench  "libpq"       || MISSING=$((MISSING + 1))
check_cmd python3  "python@3.11" || MISSING=$((MISSING + 1))

if [ "$SKIP_FIO" = false ]; then
    check_cmd fio  "fio"         || MISSING=$((MISSING + 1))
fi
if [ "$SKIP_K6" = false ]; then
    check_cmd k6   "k6"          || MISSING=$((MISSING + 1))
fi

check_cmd kubectl  "kubectl"     || MISSING=$((MISSING + 1))

if [ "$MISSING" -gt 0 ]; then
    echo ""
    echo "  $MISSING 개 도구가 누락되었습니다. 위 안내에 따라 설치하세요."
    exit 1
fi

# asyncpg 설치 확인
if ! python3 -c "import asyncpg" 2>/dev/null; then
    echo "  [MISSING] asyncpg — pip install asyncpg"
    MISSING=$((MISSING + 1))
fi

echo ""

# ── 결과 디렉토리 생성 ────────────────────────────────────────────
mkdir -p "$RESULT_DIR"

# ── port-forward 설정 ────────────────────────────────────────────
PF_PIDS=()

cleanup() {
    echo ""
    echo "  port-forward 프로세스 정리 중..."
    for pid in "${PF_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    echo "  정리 완료."
}
trap cleanup EXIT

start_port_forward() {
    local svc="$1" local_port="$2" remote_port="$3"

    # 이미 해당 포트가 사용 중인지 확인
    if lsof -i ":$local_port" -sTCP:LISTEN &>/dev/null; then
        echo "  [SKIP] $svc — 포트 $local_port 이미 사용 중"
        return 0
    fi

    echo "  [START] kubectl port-forward svc/$svc $local_port:$remote_port -n $NAMESPACE"
    kubectl port-forward "svc/$svc" "$local_port:$remote_port" -n "$NAMESPACE" &>/dev/null &
    PF_PIDS+=($!)
    sleep 2

    # 연결 확인
    if ! lsof -i ":$local_port" -sTCP:LISTEN &>/dev/null; then
        echo "  [WARN] $svc port-forward가 시작되지 않았습니다."
        echo "         수동으로 실행: kubectl port-forward svc/$svc $local_port:$remote_port -n $NAMESPACE"
        return 1
    fi
    echo "  [OK]    $svc → localhost:$local_port"
    return 0
}

echo "================================================================"
echo "  K8s Port-Forward 설정"
echo "================================================================"
echo ""

start_port_forward "alpha-pg-postgresql" 5432 5432 || true

if [ "$SKIP_K6" = false ]; then
    start_port_forward "api" 18000 8000 || true
fi

echo ""

# ── DB 연결 확인 ──────────────────────────────────────────────────
echo "================================================================"
echo "  DB 연결 확인"
echo "================================================================"
echo ""

export PGPASSWORD="$DB_PASS"
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" &>/dev/null; then
    echo "  [OK] PostgreSQL 연결 성공"
    ROW_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
        "SELECT to_char(count(*), 'FM999,999,999') FROM ohlcv_daily;")
    echo "  [OK] ohlcv_daily: $ROW_COUNT rows"
else
    echo "  [FAIL] PostgreSQL 연결 실패"
    echo "  확인: kubectl port-forward svc/alpha-pg-postgresql 5432:5432 -n $NAMESPACE"
    exit 1
fi

echo ""

# ── 벤치마크 실행 ────────────────────────────────────────────────
LOG_FILE="$RESULT_DIR/run_all_${TIMESTAMP}.log"

run_bench() {
    local name="$1" cmd="$2"
    echo "================================================================"
    echo "  [$name] 시작 — $(date '+%H:%M:%S')"
    echo "================================================================"
    echo ""

    if eval "$cmd" 2>&1 | tee -a "$LOG_FILE"; then
        echo ""
        echo "  [$name] 완료"
    else
        echo ""
        echo "  [$name] 실패 (종료 코드: $?)"
    fi
    echo ""
}

echo "" > "$LOG_FILE"

# 1. pgbench
run_bench "pgbench" "bash $SCRIPT_DIR/pgbench_ohlcv.sh"

# 2. 파티셔닝 분석
run_bench "partition" "bash $SCRIPT_DIR/sysbench_partition.sh"

# 3. Python INSERT
run_bench "python_insert" "python3 $SCRIPT_DIR/python_insert.py"

# 4. Python Query
run_bench "python_query" "python3 $SCRIPT_DIR/python_query.py"

# 5. fio
if [ "$SKIP_FIO" = false ]; then
    run_bench "fio" "bash $SCRIPT_DIR/fio_disk.sh"
fi

# 6. k6
if [ "$SKIP_K6" = false ]; then
    run_bench "k6" "k6 run --out json=$RESULT_DIR/k6_result_${TIMESTAMP}.json $SCRIPT_DIR/k6_api_load.js"
fi

# ── 최종 요약 ────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              벤치마크 전체 완료 — 결과 요약                    ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                            ║"
echo "║  실행 시각 : $(date '+%Y-%m-%d %H:%M:%S')                       ║"
echo "║  결과 위치 : $RESULT_DIR/"
echo "║  전체 로그 : $LOG_FILE"
echo "║                                                            ║"
echo "║  결과 파일 목록:                                             ║"

for f in "$RESULT_DIR"/*; do
    if [ -f "$f" ]; then
        size=$(ls -lh "$f" | awk '{print $5}')
        name=$(basename "$f")
        printf "║    %-45s %6s   ║\n" "$name" "$size"
    fi
done

echo "║                                                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
