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
  ttlSecondsAfterFinished: 600
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

# ── 보고서 회수 (로그에서 JSON 추출) ──────────────────────────────
REPORT_FILE="$REPORT_DIR/benchmark_${TIMESTAMP}.json"
LOGS=$(kubectl logs "job/$JOB_NAME" -n "$NAMESPACE" 2>/dev/null || echo "")

# 로그에서 Summary 이후 JSON 블록 추출
echo "$LOGS" | python3 -c "
import sys, json
lines = sys.stdin.read()
# 'Report saved' 직전의 JSON 출력을 찾아 전체 report 재구성
# Summary 블록 추출
try:
    start = lines.index('{', lines.index('Summary'))
    depth = 0
    end = start
    for i, c in enumerate(lines[start:], start):
        if c == '{': depth += 1
        elif c == '}': depth -= 1
        if depth == 0:
            end = i + 1
            break
    summary = json.loads(lines[start:end])
    # 전체 로그를 파싱하여 보고서 생성
    report = {'timestamp': '$TIMESTAMP', 'summary': summary, 'raw_log_length': len(lines)}
    with open('$REPORT_FILE', 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f'📊 보고서: $REPORT_FILE')
except Exception as e:
    print(f'⚠️ JSON 추출 실패: {e}')
    # 로그 전체를 텍스트로 저장
    with open('${REPORT_FILE%.json}.log', 'w') as f:
        f.write(lines)
    print(f'📝 로그 저장: ${REPORT_FILE%.json}.log')
" 2>/dev/null || echo "⚠️ 보고서 생성 실패"

# ── 정리 (보고서 회수 후 삭제) ────────────────────────────────────
kubectl delete job "$JOB_NAME" -n "$NAMESPACE" --wait=false 2>/dev/null || true
kubectl delete configmap bench-script -n "$NAMESPACE" 2>/dev/null || true

echo ""
echo "✅ 벤치마크 완료 + Pod 정리 완료"
