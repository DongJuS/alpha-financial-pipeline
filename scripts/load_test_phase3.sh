#!/bin/bash
# Phase 3: 지속 부하 테스트 — 5 DAGs x 3분 간격 x 30분
# 목적: 메모리 누수, Pod 누적, Scheduler 안정성 검증

NAMESPACE_AF="airflow"
NAMESPACE_AT="alpha-trading"
DAGS="pre_market_collection post_market_retrain data_quality_check backfill_pipeline full_cycle"
INTERVAL=180       # 3분 간격
DURATION=1800      # 30분 (10 라운드)
OUTDIR="/tmp/phase3_results"
mkdir -p "$OUTDIR"

LOG="$OUTDIR/phase3.log"
RESOURCE_LOG="$OUTDIR/resources.csv"
POD_LOG="$OUTDIR/pods.csv"
RESULT_LOG="$OUTDIR/dag_results.csv"

echo "========================================" | tee "$LOG"
echo "  Phase 3: 지속 부하 테스트 시작" | tee -a "$LOG"
echo "  시작: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "  간격: ${INTERVAL}초, 총: ${DURATION}초" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

# CSV 헤더
echo "timestamp,cpu_cores,cpu_pct,mem_bytes,mem_pct" > "$RESOURCE_LOG"
echo "timestamp,namespace,total_pods,running,pending,error,worker_pods" > "$POD_LOG"
echo "timestamp,round,dag,state" > "$RESULT_LOG"

# 시작 전 리소스
echo "" | tee -a "$LOG"
echo "--- 시작 전 리소스 ---" | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"

# Scheduler 재시작 횟수 기록
SCHED_RESTARTS_START=$(kubectl get pod -n "$NAMESPACE_AF" -l component=scheduler -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)
echo "Scheduler 시작 시 재시작 횟수: $SCHED_RESTARTS_START" | tee -a "$LOG"

START_TIME=$(date +%s)
ROUND=0

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TIME))
    if [ "$ELAPSED" -ge "$DURATION" ]; then
        echo "" | tee -a "$LOG"
        echo "=== ${DURATION}초 경과 — 테스트 종료 ===" | tee -a "$LOG"
        break
    fi

    ROUND=$((ROUND + 1))
    TS=$(date '+%H:%M:%S')
    echo "" | tee -a "$LOG"
    echo "--- Round $ROUND (${ELAPSED}s/${DURATION}s) $TS ---" | tee -a "$LOG"

    # 5 DAGs 동시 트리거
    for dag in $DAGS; do
        kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
            airflow dags trigger "$dag" --run-id "phase3_r${ROUND}_$(date +%s)" 2>/dev/null &
    done
    wait
    echo "  5 DAGs 트리거 완료" | tee -a "$LOG"

    # 30초 대기 후 리소스 측정 (DAG 실행 중간)
    sleep 30

    # 리소스 측정
    RESOURCE=$(kubectl top node 2>/dev/null | tail -1)
    CPU_CORES=$(echo "$RESOURCE" | awk '{print $2}')
    CPU_PCT=$(echo "$RESOURCE" | awk '{print $3}' | tr -d '%')
    MEM_BYTES=$(echo "$RESOURCE" | awk '{print $4}')
    MEM_PCT=$(echo "$RESOURCE" | awk '{print $5}' | tr -d '%')
    echo "$TS,$CPU_CORES,$CPU_PCT,$MEM_BYTES,$MEM_PCT" >> "$RESOURCE_LOG"
    echo "  리소스: CPU=${CPU_CORES}(${CPU_PCT}%) MEM=${MEM_BYTES}(${MEM_PCT}%)" | tee -a "$LOG"

    # Pod 수 측정
    AF_PODS=$(kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null)
    AF_TOTAL=$(echo "$AF_PODS" | wc -l | tr -d ' ')
    AF_RUNNING=$(echo "$AF_PODS" | grep -c Running || echo 0)
    AF_PENDING=$(echo "$AF_PODS" | grep -c Pending || echo 0)
    AF_ERROR=$(echo "$AF_PODS" | grep -cE 'Error|CrashLoop|OOMKill' || echo 0)
    WORKERS=$(echo "$AF_PODS" | grep -c "^airflow-worker\|phase3" || echo 0)
    echo "$TS,airflow,$AF_TOTAL,$AF_RUNNING,$AF_PENDING,$AF_ERROR,$WORKERS" >> "$POD_LOG"
    echo "  Airflow Pods: total=$AF_TOTAL running=$AF_RUNNING pending=$AF_PENDING error=$AF_ERROR workers=$WORKERS" | tee -a "$LOG"

    # DAG 상태 확인 (최근 run)
    for dag in $DAGS; do
        STATE=$(kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
            airflow dags list-runs -d "$dag" --no-backfill -o plain 2>/dev/null | head -3 | tail -1 | awk '{print $3}')
        echo "$TS,$ROUND,$dag,$STATE" >> "$RESULT_LOG"
    done

    # Scheduler 재시작 횟수
    SCHED_RESTARTS=$(kubectl get pod -n "$NAMESPACE_AF" -l component=scheduler -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)
    echo "  Scheduler 재시작: $SCHED_RESTARTS (시작 대비 +$((SCHED_RESTARTS - SCHED_RESTARTS_START)))" | tee -a "$LOG"

    # 남은 시간 대기 (interval - 이미 경과한 시간)
    STEP_ELAPSED=$(($(date +%s) - NOW))
    SLEEP_TIME=$((INTERVAL - STEP_ELAPSED))
    if [ "$SLEEP_TIME" -gt 0 ] && [ "$ELAPSED" -lt "$((DURATION - INTERVAL))" ]; then
        echo "  다음 라운드까지 ${SLEEP_TIME}초 대기..." | tee -a "$LOG"
        sleep "$SLEEP_TIME"
    fi
done

# 최종 리소스
echo "" | tee -a "$LOG"
echo "--- 최종 리소스 ---" | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"

# Scheduler 최종 재시작 횟수
SCHED_RESTARTS_END=$(kubectl get pod -n "$NAMESPACE_AF" -l component=scheduler -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)

# 잔여 Worker Pod 확인 (Pod 누적 여부)
echo "" | tee -a "$LOG"
echo "--- 잔여 Pod 확인 ---" | tee -a "$LOG"
kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | tee -a "$LOG"

# 요약
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Phase 3 요약" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  총 라운드: $ROUND" | tee -a "$LOG"
echo "  Scheduler 재시작: $SCHED_RESTARTS_START → $SCHED_RESTARTS_END (+$((SCHED_RESTARTS_END - SCHED_RESTARTS_START)))" | tee -a "$LOG"
echo "  종료 시각: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"

# 리소스 추이 요약
echo "" | tee -a "$LOG"
echo "--- 리소스 추이 ---" | tee -a "$LOG"
echo "CPU(%):" | tee -a "$LOG"
awk -F',' 'NR>1{print "  " $1 ": " $3 "%"}' "$RESOURCE_LOG" | tee -a "$LOG"
echo "MEM(%):" | tee -a "$LOG"
awk -F',' 'NR>1{print "  " $1 ": " $5 "%"}' "$RESOURCE_LOG" | tee -a "$LOG"

# DAG 성공/실패 집계
echo "" | tee -a "$LOG"
echo "--- DAG 결과 집계 ---" | tee -a "$LOG"
for dag in $DAGS; do
    SUCCESS=$(grep ",$dag,success" "$RESULT_LOG" | wc -l | tr -d ' ')
    FAILED=$(grep ",$dag,failed" "$RESULT_LOG" | wc -l | tr -d ' ')
    RUNNING=$(grep ",$dag,running" "$RESULT_LOG" | wc -l | tr -d ' ')
    QUEUED=$(grep ",$dag,queued" "$RESULT_LOG" | wc -l | tr -d ' ')
    echo "  $dag: success=$SUCCESS failed=$FAILED running=$RUNNING queued=$QUEUED" | tee -a "$LOG"
done

echo "" | tee -a "$LOG"
echo "=== Phase 3 완료 ===" | tee -a "$LOG"
echo "결과 파일: $OUTDIR/" | tee -a "$LOG"
