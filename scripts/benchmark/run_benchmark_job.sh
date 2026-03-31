#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run_benchmark_job.sh — K8s Job으로 벤치마크 → 보고서 → Pod 자동 정리
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

NAMESPACE="${K8S_NAMESPACE:-alpha-trading}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
JOB_NAME="bench-${TIMESTAMP}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DIR="$SCRIPT_DIR/reports"
IMAGE=$(kubectl get deployment worker -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "alpha-trading:latest")

mkdir -p "$REPORT_DIR"

echo "╔══════════════════════════════════════════╗"
echo "║   Alpha Benchmark — K8s Job Runner       ║"
echo "║  Job:       $JOB_NAME"
echo "║  Image:     $IMAGE"
echo "╚══════════════════════════════════════════╝"

# ── 스크립트를 ConfigMap으로 주입 ─────────────────────────────────
kubectl create configmap bench-script -n "$NAMESPACE" \
    --from-file=benchmark_runner.py="$SCRIPT_DIR/benchmark_runner.py" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null 2>&1

# ── Job 생성 ─────────────────────────────────────────────────────
kubectl apply -f - <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB_NAME
  namespace: $NAMESPACE
spec:
  ttlSecondsAfterFinished: 120
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      volumes:
        - name: bench-script
          configMap:
            name: bench-script
      containers:
        - name: bench
          image: $IMAGE
          imagePullPolicy: Never
          volumeMounts:
            - name: bench-script
              mountPath: /bench
          env:
            - { name: DB_HOST, value: alpha-pg-postgresql }
            - { name: DB_PORT, value: "5432" }
            - { name: DB_NAME, value: alpha_db }
            - { name: DB_USER, value: alpha_user }
            - { name: DB_PASS, value: alpha_pass }
            - { name: S3_ENDPOINT_URL, value: "http://minio:9000" }
            - { name: S3_ACCESS_KEY, value: minioadmin }
            - { name: S3_SECRET_KEY, value: minioadmin }
            - { name: S3_BUCKET_NAME, value: alpha-lake }
            - { name: BENCHMARK_TIMESTAMP, value: "$TIMESTAMP" }
            - { name: REPORT_PATH, value: /tmp/benchmark_report.json }
          command: ["python3", "/bench/benchmark_runner.py"]
          resources:
            limits: { cpu: "2", memory: 2Gi }
            requests: { cpu: 500m, memory: 512Mi }
YAML

echo ""
echo "⏳ Job 실행 중... (최대 10분)"

# ── 완료 대기 ────────────────────────────────────────────────────
kubectl wait --for=condition=complete "job/$JOB_NAME" -n "$NAMESPACE" --timeout=600s 2>/dev/null || true

# ── 로그 ─────────────────────────────────────────────────────────
echo ""
kubectl logs "job/$JOB_NAME" -n "$NAMESPACE" 2>/dev/null || echo "(로그 없음)"

# ── 보고서 회수 ──────────────────────────────────────────────────
POD=$(kubectl get pods -n "$NAMESPACE" -l "job-name=$JOB_NAME" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
REPORT_FILE="$REPORT_DIR/benchmark_${TIMESTAMP}.json"

if [ -n "$POD" ]; then
    kubectl cp "$NAMESPACE/$POD:/tmp/benchmark_report.json" "$REPORT_FILE" 2>/dev/null && \
        echo "" && echo "📊 보고서: $REPORT_FILE" || \
        echo "⚠️ 보고서 회수 실패"
fi

# ── 정리 ─────────────────────────────────────────────────────────
kubectl delete job "$JOB_NAME" -n "$NAMESPACE" 2>/dev/null || true
kubectl delete configmap bench-script -n "$NAMESPACE" 2>/dev/null || true

echo ""
echo "✅ 벤치마크 완료 + Pod 정리 완료"
