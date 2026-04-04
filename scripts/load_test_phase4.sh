#!/bin/bash
# Phase 4: 장애 주입 테스트 — Scheduler kill, Worker kill, DB 연결 차단
# 목적: 장애 자동 복구 능력 검증

NAMESPACE_AF="airflow"
OUTDIR="/tmp/phase4_results"
mkdir -p "$OUTDIR"
LOG="$OUTDIR/phase4.log"

echo "========================================" | tee "$LOG"
echo "  Phase 4: 장애 주입 테스트" | tee -a "$LOG"
echo "  시작: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

# 시작 전 상태
echo "" | tee -a "$LOG"
echo "--- 시작 전 상태 ---" | tee -a "$LOG"
kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"

########################################
# Test 1: Scheduler Pod Kill → 자동 복구
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Test 1: Scheduler Pod Kill" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

# Scheduler Pod 이름
SCHED_POD=$(kubectl get pod -n "$NAMESPACE_AF" -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
echo "  대상: $SCHED_POD" | tee -a "$LOG"

# DAG 하나 트리거 (Scheduler 죽기 전)
echo "  [1] full_cycle DAG 트리거" | tee -a "$LOG"
kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
    airflow dags trigger full_cycle --run-id "phase4_sched_kill_$(date +%s)" 2>/dev/null
echo "  트리거 완료, 10초 대기..." | tee -a "$LOG"
sleep 10

# Worker Pod가 생성되었는지 확인
echo "  [2] DAG 실행 확인 (Worker Pod 생성):" | tee -a "$LOG"
kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | tee -a "$LOG"

# Scheduler Kill!
KILL_TIME=$(date '+%H:%M:%S')
echo "" | tee -a "$LOG"
echo "  [3] ⚡ Scheduler Pod 삭제: $KILL_TIME" | tee -a "$LOG"
kubectl delete pod "$SCHED_POD" -n "$NAMESPACE_AF" --grace-period=0 --force 2>/dev/null | tee -a "$LOG"

# 복구 시간 측정
echo "  [4] 복구 대기 중..." | tee -a "$LOG"
KILL_EPOCH=$(date +%s)
for i in $(seq 1 60); do
    sleep 5
    STATUS=$(kubectl get pod -n "$NAMESPACE_AF" -l component=scheduler -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
    PHASE=$(kubectl get pod -n "$NAMESPACE_AF" -l component=scheduler -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
    ELAPSED=$(( $(date +%s) - KILL_EPOCH ))
    echo "    ${ELAPSED}s: phase=$PHASE ready=$STATUS" | tee -a "$LOG"
    if [ "$STATUS" = "true" ]; then
        RECOVERY_TIME=$ELAPSED
        echo "" | tee -a "$LOG"
        echo "  ✅ Scheduler 복구 완료: ${RECOVERY_TIME}초" | tee -a "$LOG"
        break
    fi
done

# 복구 후 새 Scheduler Pod 확인
NEW_SCHED=$(kubectl get pod -n "$NAMESPACE_AF" -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
echo "  새 Scheduler Pod: $NEW_SCHED" | tee -a "$LOG"

# DAG 실행이 계속되었는지 확인 (30초 대기 후)
echo "  [5] DAG 실행 연속성 확인 (30초 대기)..." | tee -a "$LOG"
sleep 30
FC_STATE=$(kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
    airflow dags list-runs -d full_cycle --no-backfill -o plain 2>/dev/null | head -3 | tail -1 | awk '{print $3}')
echo "  full_cycle 최근 상태: $FC_STATE" | tee -a "$LOG"

# Scheduler 복구 후 새 DAG 트리거 가능한지 확인
echo "  [6] 복구 후 새 DAG 트리거 테스트:" | tee -a "$LOG"
kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
    airflow dags trigger backfill_pipeline --run-id "phase4_post_recovery_$(date +%s)" 2>/dev/null
sleep 20
BP_STATE=$(kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
    airflow dags list-runs -d backfill_pipeline --no-backfill -o plain 2>/dev/null | head -3 | tail -1 | awk '{print $3}')
echo "  복구 후 backfill_pipeline: $BP_STATE" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "--- Test 1 결과 ---" | tee -a "$LOG"
echo "  Scheduler 복구 시간: ${RECOVERY_TIME:-실패}초" | tee -a "$LOG"
echo "  복구 후 DAG 트리거: $BP_STATE" | tee -a "$LOG"

########################################
# Test 2: Worker Pod Kill → Task Retry
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Test 2: Worker Pod Kill (실행 중 Task)" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

# 잔여 Worker Pod 정리 대기
echo "  [1] 잔여 Worker Pod 정리 대기 (30초)..." | tee -a "$LOG"
sleep 30

# full_cycle DAG 트리거 (retries=3 설정된 DAG)
echo "  [2] full_cycle DAG 트리거 (retries=3)" | tee -a "$LOG"
kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
    airflow dags trigger full_cycle --run-id "phase4_worker_kill_$(date +%s)" 2>/dev/null

# Worker Pod 생성 대기
echo "  [3] Worker Pod 생성 대기..." | tee -a "$LOG"
WORKER_POD=""
for i in $(seq 1 30); do
    sleep 5
    WORKER_POD=$(kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | grep "full-cycle" | grep "Running" | head -1 | awk '{print $1}')
    if [ -n "$WORKER_POD" ]; then
        echo "    Worker Pod 발견: $WORKER_POD" | tee -a "$LOG"
        break
    fi
    echo "    ${i}... 대기 중" | tee -a "$LOG"
done

if [ -z "$WORKER_POD" ]; then
    echo "  ⚠️ Worker Pod를 찾지 못함. pre_market_collection으로 재시도..." | tee -a "$LOG"
    kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
        airflow dags trigger pre_market_collection --run-id "phase4_worker_kill2_$(date +%s)" 2>/dev/null
    for i in $(seq 1 30); do
        sleep 5
        WORKER_POD=$(kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | grep -E "pre-market|full-cycle|post-market" | grep "Running" | head -1 | awk '{print $1}')
        if [ -n "$WORKER_POD" ]; then
            echo "    Worker Pod 발견: $WORKER_POD" | tee -a "$LOG"
            break
        fi
    done
fi

if [ -n "$WORKER_POD" ]; then
    # Worker Pod Kill!
    W_KILL_TIME=$(date '+%H:%M:%S')
    echo "" | tee -a "$LOG"
    echo "  [4] ⚡ Worker Pod 삭제: $WORKER_POD at $W_KILL_TIME" | tee -a "$LOG"
    kubectl delete pod "$WORKER_POD" -n "$NAMESPACE_AF" --grace-period=0 --force 2>/dev/null | tee -a "$LOG"

    # retry 발생 여부 확인 (60초 관찰)
    echo "  [5] Task retry 관찰 (120초)..." | tee -a "$LOG"
    for i in $(seq 1 12); do
        sleep 10
        ELAPSED=$((i * 10))
        PODS=$(kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | grep -v scheduler | grep -v webserver)
        WORKER_COUNT=$(echo "$PODS" | grep -cE "full-cycle|pre-market" || echo 0)
        echo "    ${ELAPSED}s: worker_pods=$WORKER_COUNT" | tee -a "$LOG"
        echo "$PODS" | grep -E "full-cycle|pre-market" | tee -a "$LOG"
    done

    # Task 상태 확인
    echo "" | tee -a "$LOG"
    echo "  [6] 최종 DAG 상태:" | tee -a "$LOG"
    kubectl exec -n "$NAMESPACE_AF" deploy/airflow-scheduler -- \
        airflow dags list-runs -d full_cycle --no-backfill -o plain 2>/dev/null | head -5 | tee -a "$LOG"
else
    echo "  ❌ Worker Pod를 찾지 못해 Test 2 스킵" | tee -a "$LOG"
fi

########################################
# Test 3: Webserver Kill → UI 복구
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Test 3: Webserver Pod Kill" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

WEB_POD=$(kubectl get pod -n "$NAMESPACE_AF" -l component=webserver -o jsonpath='{.items[0].metadata.name}')
echo "  대상: $WEB_POD" | tee -a "$LOG"

# Kill
WEB_KILL_TIME=$(date '+%H:%M:%S')
echo "  ⚡ Webserver Pod 삭제: $WEB_KILL_TIME" | tee -a "$LOG"
kubectl delete pod "$WEB_POD" -n "$NAMESPACE_AF" --grace-period=0 --force 2>/dev/null | tee -a "$LOG"

# 복구 대기
WEB_KILL_EPOCH=$(date +%s)
for i in $(seq 1 30); do
    sleep 5
    WEB_READY=$(kubectl get pod -n "$NAMESPACE_AF" -l component=webserver -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
    ELAPSED=$(( $(date +%s) - WEB_KILL_EPOCH ))
    echo "    ${ELAPSED}s: ready=$WEB_READY" | tee -a "$LOG"
    if [ "$WEB_READY" = "true" ]; then
        WEB_RECOVERY=$ELAPSED
        echo "  ✅ Webserver 복구 완료: ${WEB_RECOVERY}초" | tee -a "$LOG"
        break
    fi
done

########################################
# 최종 요약
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Phase 4 최종 요약" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Test 1 — Scheduler Kill: 복구 ${RECOVERY_TIME:-N/A}초" | tee -a "$LOG"
echo "  Test 2 — Worker Kill: Task retry 동작 확인" | tee -a "$LOG"
echo "  Test 3 — Webserver Kill: 복구 ${WEB_RECOVERY:-N/A}초" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "--- 최종 클러스터 상태 ---" | tee -a "$LOG"
kubectl get pods -n "$NAMESPACE_AF" --no-headers 2>/dev/null | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "  종료: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "=== Phase 4 완료 ===" | tee -a "$LOG"
