#!/bin/bash
# Phase 2 재실행: Scheduler 리소스 상향 후 5/5 SUCCESS 달성 시도
# 목적: 이전 Phase 2 (4/5) 대비 개선 확인

NAMESPACE_AF="airflow"
DAGS="pre_market_collection post_market_retrain data_quality_check backfill_pipeline full_cycle"
OUTDIR="/tmp/phase2_rerun_results"
mkdir -p "$OUTDIR"
LOG="$OUTDIR/phase2_rerun.log"

echo "=============================================" | tee "$LOG"
echo "  Phase 2 재실행: 5 DAGs 동시 (리소스 상향)" | tee -a "$LOG"
echo "  시작: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "=============================================" | tee -a "$LOG"

# 시작 전 리소스
echo "" | tee -a "$LOG"
echo "--- 실행 전 ---" | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"
kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | tee -a "$LOG"

# Scheduler 리소스 확인
echo "" | tee -a "$LOG"
echo "--- Scheduler 리소스 설정 ---" | tee -a "$LOG"
kubectl get pod -n "$NAMESPACE_AF" -l component=scheduler -o jsonpath='{.items[0].spec.containers[0].resources}' 2>/dev/null | python3 -m json.tool 2>/dev/null | tee -a "$LOG"

# DAG unpause 확인
for dag in $DAGS; do
    kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- airflow dags unpause "$dag" 2>/dev/null
done

# 5 DAGs 동시 트리거
echo "" | tee -a "$LOG"
echo "--- 5 DAGs 동시 트리거 ---" | tee -a "$LOG"
TRIGGER_TIME=$(date '+%H:%M:%S')
TRIGGER_EPOCH=$(date +%s)

for dag in $DAGS; do
    kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
        airflow dags trigger "$dag" --run-id "phase2r_$(date +%s)_${dag}" 2>/dev/null &
done
wait
echo "  5 DAGs 트리거 완료: $TRIGGER_TIME" | tee -a "$LOG"

# 10초 간격 관찰 (최대 300초 = 5분)
echo "" | tee -a "$LOG"
echo "--- 실시간 관찰 ---" | tee -a "$LOG"

ALL_DONE=false
for i in $(seq 1 30); do
    sleep 10
    ELAPSED=$((i * 10))

    # Worker Pod 수
    AF_PODS=$(kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null)
    WORKERS=$(echo "$AF_PODS" | grep -v scheduler | grep -v webserver | grep -v Completed | wc -l | tr -d ' ')

    # 리소스
    RESOURCE=$(kubectl top node 2>/dev/null | tail -1)
    CPU_PCT=$(echo "$RESOURCE" | awk '{print $3}')
    MEM_PCT=$(echo "$RESOURCE" | awk '{print $5}')

    # 각 DAG 상태
    STATES=""
    SUCCESS_COUNT=0
    FAILED_COUNT=0
    RUNNING_COUNT=0
    for dag in $DAGS; do
        STATE=$(kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
            airflow dags list-runs -d "$dag" --no-backfill -o plain 2>/dev/null | grep "phase2r" | head -1 | awk '{print $3}')
        STATES="$STATES ${dag}=${STATE:-queued}"
        [ "$STATE" = "success" ] && SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        [ "$STATE" = "failed" ] && FAILED_COUNT=$((FAILED_COUNT + 1))
        [ "$STATE" = "running" ] && RUNNING_COUNT=$((RUNNING_COUNT + 1))
    done

    echo "  ${ELAPSED}s: workers=$WORKERS CPU=$CPU_PCT MEM=$MEM_PCT |$STATES" | tee -a "$LOG"

    # 모든 DAG 완료 확인
    TOTAL_DONE=$((SUCCESS_COUNT + FAILED_COUNT))
    if [ "$TOTAL_DONE" -ge 5 ]; then
        echo "" | tee -a "$LOG"
        echo "  ✅ 전체 완료: SUCCESS=$SUCCESS_COUNT FAILED=$FAILED_COUNT" | tee -a "$LOG"
        ALL_DONE=true
        break
    fi
done

TOTAL_TIME=$(( $(date +%s) - TRIGGER_EPOCH ))

# 최종 리소스
echo "" | tee -a "$LOG"
echo "--- 최종 리소스 ---" | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"

# 각 DAG 최종 상태 상세
echo "" | tee -a "$LOG"
echo "--- DAG별 최종 상태 ---" | tee -a "$LOG"
for dag in $DAGS; do
    echo "[$dag]" | tee -a "$LOG"
    kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
        airflow dags list-runs -d "$dag" --no-backfill -o plain 2>/dev/null | grep "phase2r" | head -3 | tee -a "$LOG"
    echo "" | tee -a "$LOG"
done

# 최종 Pod 상태
echo "--- 최종 Pod 상태 ---" | tee -a "$LOG"
kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | tee -a "$LOG"

# 요약
echo "" | tee -a "$LOG"
echo "=============================================" | tee -a "$LOG"
echo "  Phase 2 재실행 결과" | tee -a "$LOG"
echo "=============================================" | tee -a "$LOG"
echo "  총 소요: ${TOTAL_TIME}초" | tee -a "$LOG"

SUCCESS_FINAL=0
FAILED_FINAL=0
for dag in $DAGS; do
    STATE=$(kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
        airflow dags list-runs -d "$dag" --no-backfill -o plain 2>/dev/null | grep "phase2r" | head -1 | awk '{print $3}')
    echo "  $dag: $STATE" | tee -a "$LOG"
    [ "$STATE" = "success" ] && SUCCESS_FINAL=$((SUCCESS_FINAL + 1))
    [ "$STATE" = "failed" ] && FAILED_FINAL=$((FAILED_FINAL + 1))
done
echo "" | tee -a "$LOG"
echo "  결과: ${SUCCESS_FINAL}/5 SUCCESS, ${FAILED_FINAL}/5 FAILED" | tee -a "$LOG"
echo "  종료: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "=== Phase 2 재실행 완료 ===" | tee -a "$LOG"
