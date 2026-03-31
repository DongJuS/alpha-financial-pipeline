#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run_k8s_benchmark.sh — K3s DB/S3에 port-forward 후 로컬에서 벤치마크 실행
#
# 기존 pod에 영향 없음 (읽기 전용 + 트랜잭션 롤백).
# 결과는 scripts/benchmark/results/ 에 JSON으로 저장.
#
# 사용법:
#   ./scripts/benchmark/run_k8s_benchmark.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULT_DIR="$SCRIPT_DIR/results"
NAMESPACE="${K8S_NAMESPACE:-alpha-trading}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PYTHON="${PYTHON:-python3.11}"

mkdir -p "$RESULT_DIR"

echo "=== Alpha Benchmark Runner ==="
echo "Timestamp: $TIMESTAMP"
echo ""

# ── port-forward 설정 ────────────────────────────────────────────
echo "[setup] K3s port-forward 설정 중..."
pkill -f "kubectl port-forward.*25432" 2>/dev/null || true
pkill -f "kubectl port-forward.*29000" 2>/dev/null || true
sleep 1

kubectl port-forward svc/alpha-pg-postgresql 25432:5432 -n "$NAMESPACE" &>/dev/null &
PF_DB_PID=$!
kubectl port-forward svc/minio 29000:9000 -n "$NAMESPACE" &>/dev/null &
PF_S3_PID=$!
sleep 3

trap "kill $PF_DB_PID $PF_S3_PID 2>/dev/null; echo '[cleanup] port-forward 종료'" EXIT

export DB_HOST=localhost
export DB_PORT=25432
export DB_NAME=alpha_db
export DB_USER=alpha_user
export DB_PASS=alpha_pass
export S3_ENDPOINT_URL=http://localhost:29000
export S3_ACCESS_KEY=minioadmin
export S3_SECRET_KEY=minioadmin
export S3_BUCKET_NAME=alpha-lake

echo "[setup] 완료 (DB=localhost:25432, S3=localhost:29000)"
echo ""

# ── 1. DB 쿼리 성능 ──────────────────────────────────────────────
echo "=== [1/4] DB 쿼리 성능 ==="
$PYTHON "$SCRIPT_DIR/python_query.py" 2>&1 | tee "$RESULT_DIR/query_${TIMESTAMP}.log"
echo ""

# ── 2. DB INSERT 속도 ─────────────────────────────────────────────
echo "=== [2/4] DB INSERT 속도 ==="
$PYTHON "$SCRIPT_DIR/python_insert.py" --rows 50000 2>&1 | tee "$RESULT_DIR/insert_${TIMESTAMP}.log"
echo ""

# ── 3. S3 업로드 속도 ─────────────────────────────────────────────
echo "=== [3/4] S3 업로드 속도 ==="
$PYTHON "$SCRIPT_DIR/s3_upload_speed.py" --sizes 1,10,50 2>&1 | tee "$RESULT_DIR/s3_${TIMESTAMP}.log"
echo ""

# ── 4. FDR 수집 처리량 (100종목) ──────────────────────────────────
echo "=== [4/4] FDR 수집 처리량 (100종목) ==="
$PYTHON "$SCRIPT_DIR/fdr_throughput.py" --tickers 100 2>&1 | tee "$RESULT_DIR/fdr_${TIMESTAMP}.log"
echo ""

echo "=== 벤치마크 완료 ==="
echo "결과: $RESULT_DIR/*_${TIMESTAMP}.*"
ls -la "$RESULT_DIR"/*_${TIMESTAMP}.* 2>/dev/null || echo "(결과 파일 없음)"
