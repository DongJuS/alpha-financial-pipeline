#!/bin/bash
# Alpha K8s 부하 테스트 — Airflow 대비 동일 워크로드
# Alpha는 단일 프로세스(API Pod + Worker Pod)로 동작

NS="alpha-trading"
API="deploy/api"
BASE="http://localhost:8000"
OUTDIR="/tmp/alpha_load_results"
mkdir -p "$OUTDIR"
LOG="$OUTDIR/alpha_load.log"

# API 호출 헬퍼 (시간 측정 포함)
call_api() {
    local method=$1 path=$2 label=$3
    local start=$(date +%s%N)
    local status=$(kubectl exec -n "$NS" "$API" -- \
        curl -s -o /dev/null -w "%{http_code}" -X "$method" "${BASE}${path}" \
        -H "Content-Type: application/json" 2>/dev/null)
    local end=$(date +%s%N)
    local ms=$(( (end - start) / 1000000 ))
    echo "${label}: ${status} (${ms}ms)"
    return 0
}

# API 호출 (응답 포함)
call_api_body() {
    local method=$1 path=$2
    kubectl exec -n "$NS" "$API" -- \
        curl -s -X "$method" "${BASE}${path}" \
        -H "Content-Type: application/json" 2>/dev/null
}

# 리소스 측정
measure() {
    kubectl top node 2>/dev/null | tail -1 | awk '{printf "CPU=%s(%s) MEM=%s(%s)", $2, $3, $4, $5}'
}

echo "========================================" | tee "$LOG"
echo "  Alpha K8s 부하 테스트" | tee -a "$LOG"
echo "  시작: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

# 시작 전 리소스
echo "" | tee -a "$LOG"
echo "--- 시작 전 ---" | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"
kubectl get pods -n "$NS" --no-headers 2>/dev/null | tee -a "$LOG"

# API Pod 재시작 횟수
API_RESTARTS_START=$(kubectl get pod -n "$NS" -l app=api -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)
WORKER_RESTARTS_START=$(kubectl get pod -n "$NS" -l app=worker -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)

########################################
# Phase 1: 기준선 — 단일 사이클
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Phase 1: 기준선 — 단일 사이클" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

P1_START=$(date +%s)
P1_RES_BEFORE=$(measure)
echo "  시작 리소스: $P1_RES_BEFORE" | tee -a "$LOG"

echo "  [1/5] 시세 수집 (collect)..." | tee -a "$LOG"
R1=$(call_api POST "/api/v1/market/collect" "collect")
echo "  $R1" | tee -a "$LOG"

echo "  [2/5] 시스템 메트릭 (metrics)..." | tee -a "$LOG"
R2=$(call_api GET "/api/v1/system/metrics" "metrics")
echo "  $R2" | tee -a "$LOG"

echo "  [3/5] 데이터레이크 조회 (datalake)..." | tee -a "$LOG"
R3=$(call_api GET "/api/v1/datalake/overview" "datalake")
echo "  $R3" | tee -a "$LOG"

echo "  [4/5] 포트폴리오 준비 (readiness)..." | tee -a "$LOG"
R4=$(call_api GET "/api/v1/portfolio/readiness" "readiness")
echo "  $R4" | tee -a "$LOG"

echo "  [5/5] 듀얼 실행 (dual-execution)..." | tee -a "$LOG"
R5=$(call_api POST "/api/v1/agents/dual-execution/run" "dual-exec")
echo "  $R5" | tee -a "$LOG"

P1_END=$(date +%s)
P1_TIME=$((P1_END - P1_START))
P1_RES_AFTER=$(measure)
echo "" | tee -a "$LOG"
echo "  Phase 1 소요: ${P1_TIME}초" | tee -a "$LOG"
echo "  종료 리소스: $P1_RES_AFTER" | tee -a "$LOG"

########################################
# Phase 2: 동시 부하 — 5개 API 동시 호출
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Phase 2: 동시 부하 — 5개 API 동시" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

sleep 10  # 안정화 대기
P2_START=$(date +%s)
P2_RES_BEFORE=$(measure)
echo "  시작 리소스: $P2_RES_BEFORE" | tee -a "$LOG"

# 5개 동시 호출
echo "  5개 API 동시 트리거..." | tee -a "$LOG"
{
    call_api POST "/api/v1/market/collect" "collect" > "$OUTDIR/p2_1.txt" 2>&1
} &
{
    call_api POST "/api/v1/agents/dual-execution/run" "dual-exec" > "$OUTDIR/p2_2.txt" 2>&1
} &
{
    call_api POST "/api/v1/feedback/cycle" "feedback" > "$OUTDIR/p2_3.txt" 2>&1
} &
{
    call_api GET "/api/v1/portfolio/readiness" "readiness" > "$OUTDIR/p2_4.txt" 2>&1
} &
{
    call_api GET "/api/v1/datalake/overview" "datalake" > "$OUTDIR/p2_5.txt" 2>&1
} &
wait

# 10초 간격 리소스 측정 (동시 호출 처리 중)
for i in $(seq 1 6); do
    sleep 10
    ELAPSED=$((i * 10))
    RES=$(measure)
    echo "  ${ELAPSED}s: $RES" | tee -a "$LOG"
done

P2_END=$(date +%s)
P2_TIME=$((P2_END - P2_START))
P2_RES_AFTER=$(measure)

echo "" | tee -a "$LOG"
echo "  Phase 2 결과:" | tee -a "$LOG"
for f in "$OUTDIR"/p2_*.txt; do
    cat "$f" | tee -a "$LOG"
done
echo "  Phase 2 소요: ${P2_TIME}초" | tee -a "$LOG"
echo "  종료 리소스: $P2_RES_AFTER" | tee -a "$LOG"

########################################
# Phase 3: 지속 부하 — 30분 연속
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Phase 3: 지속 부하 — 30분 연속" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

sleep 10
P3_START=$(date +%s)
P3_INTERVAL=180  # 3분
P3_DURATION=1800 # 30분
ROUND=0
RESOURCE_CSV="$OUTDIR/alpha_resources.csv"
echo "timestamp,round,cpu_pct,mem_pct,api_status,response_ms" > "$RESOURCE_CSV"

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - P3_START))
    [ "$ELAPSED" -ge "$P3_DURATION" ] && break

    ROUND=$((ROUND + 1))
    TS=$(date '+%H:%M:%S')
    echo "" | tee -a "$LOG"
    echo "--- Round $ROUND (${ELAPSED}s/${P3_DURATION}s) $TS ---" | tee -a "$LOG"

    # 5개 API 동시 호출
    {
        call_api POST "/api/v1/market/collect" "collect" > "$OUTDIR/p3r${ROUND}_1.txt" 2>&1
    } &
    {
        call_api POST "/api/v1/agents/dual-execution/run" "dual-exec" > "$OUTDIR/p3r${ROUND}_2.txt" 2>&1
    } &
    {
        call_api POST "/api/v1/feedback/cycle" "feedback" > "$OUTDIR/p3r${ROUND}_3.txt" 2>&1
    } &
    {
        call_api GET "/api/v1/portfolio/readiness" "readiness" > "$OUTDIR/p3r${ROUND}_4.txt" 2>&1
    } &
    {
        call_api GET "/api/v1/datalake/overview" "datalake" > "$OUTDIR/p3r${ROUND}_5.txt" 2>&1
    } &
    wait

    # 30초 후 리소스 측정
    sleep 30
    RESOURCE=$(kubectl top node 2>/dev/null | tail -1)
    CPU_PCT=$(echo "$RESOURCE" | awk '{print $3}' | tr -d '%')
    MEM_PCT=$(echo "$RESOURCE" | awk '{print $5}' | tr -d '%')
    echo "  리소스: CPU=${CPU_PCT}% MEM=${MEM_PCT}%" | tee -a "$LOG"

    # API 응답 시간 측정 (health 엔드포인트)
    H_START=$(date +%s%N)
    H_STATUS=$(kubectl exec -n "$NS" "$API" -- curl -s -o /dev/null -w "%{http_code}" "${BASE}/health" 2>/dev/null)
    H_END=$(date +%s%N)
    H_MS=$(( (H_END - H_START) / 1000000 ))
    echo "  health: ${H_STATUS} (${H_MS}ms)" | tee -a "$LOG"
    echo "$TS,$ROUND,$CPU_PCT,$MEM_PCT,$H_STATUS,$H_MS" >> "$RESOURCE_CSV"

    # API/Worker Pod 재시작 확인
    API_RESTARTS=$(kubectl get pod -n "$NS" -l app=api -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)
    WORKER_RESTARTS=$(kubectl get pod -n "$NS" -l app=worker -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)
    echo "  API 재시작: $API_RESTARTS (+$((API_RESTARTS - API_RESTARTS_START))), Worker 재시작: $WORKER_RESTARTS (+$((WORKER_RESTARTS - WORKER_RESTARTS_START)))" | tee -a "$LOG"

    # 결과 요약
    for f in "$OUTDIR"/p3r${ROUND}_*.txt; do
        echo "  $(cat $f)" | tee -a "$LOG"
    done

    # 대기
    STEP_ELAPSED=$(($(date +%s) - NOW))
    SLEEP_TIME=$((P3_INTERVAL - STEP_ELAPSED))
    [ "$SLEEP_TIME" -gt 0 ] && [ "$ELAPSED" -lt "$((P3_DURATION - P3_INTERVAL))" ] && sleep "$SLEEP_TIME"
done

P3_END=$(date +%s)
echo "" | tee -a "$LOG"
echo "  Phase 3 완료: $ROUND 라운드, $((P3_END - P3_START))초" | tee -a "$LOG"

# Phase 3 리소스 추이
echo "" | tee -a "$LOG"
echo "--- Phase 3 리소스 추이 ---" | tee -a "$LOG"
awk -F',' 'NR>1{printf "  R%s: CPU=%s%% MEM=%s%% health=%sms\n", $2, $3, $4, $6}' "$RESOURCE_CSV" | tee -a "$LOG"

########################################
# Phase 4: 장애 주입
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Phase 4: 장애 주입 — Pod Kill" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

sleep 30  # Phase 3 이후 안정화

## Test 1: API Pod Kill
echo "" | tee -a "$LOG"
echo "--- Test 1: API Pod Kill ---" | tee -a "$LOG"
API_POD=$(kubectl get pod -n "$NS" -l app=api -o jsonpath='{.items[0].metadata.name}')
echo "  대상: $API_POD" | tee -a "$LOG"

# Kill 전 health 확인
PRE_HEALTH=$(kubectl exec -n "$NS" "$API" -- curl -s -o /dev/null -w "%{http_code}" "${BASE}/health" 2>/dev/null)
echo "  Kill 전 health: $PRE_HEALTH" | tee -a "$LOG"

# Kill!
API_KILL_EPOCH=$(date +%s)
echo "  ⚡ API Pod 삭제: $(date '+%H:%M:%S')" | tee -a "$LOG"
kubectl delete pod "$API_POD" -n "$NS" --grace-period=0 --force 2>/dev/null | tee -a "$LOG"

# 복구 대기
for i in $(seq 1 60); do
    sleep 5
    READY=$(kubectl get pod -n "$NS" -l app=api -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
    ELAPSED=$(( $(date +%s) - API_KILL_EPOCH ))
    echo "    ${ELAPSED}s: ready=$READY" | tee -a "$LOG"
    if [ "$READY" = "true" ]; then
        API_RECOVERY=$ELAPSED
        echo "  ✅ API Pod 복구: ${API_RECOVERY}초" | tee -a "$LOG"
        break
    fi
done

# 복구 후 health 확인
sleep 5
POST_HEALTH=$(kubectl exec -n "$NS" deploy/api -- curl -s -o /dev/null -w "%{http_code}" "${BASE}/health" 2>/dev/null)
echo "  복구 후 health: $POST_HEALTH" | tee -a "$LOG"

# 복구 후 스케줄러 상태 확인
SCHED_STATUS=$(kubectl exec -n "$NS" deploy/api -- curl -s "${BASE}/api/v1/scheduler/status" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'running={d[\"running\"]}, jobs={d[\"job_count\"]}')" 2>/dev/null)
echo "  복구 후 스케줄러: $SCHED_STATUS" | tee -a "$LOG"

## Test 2: Worker Pod Kill
echo "" | tee -a "$LOG"
echo "--- Test 2: Worker Pod Kill ---" | tee -a "$LOG"
WORKER_POD=$(kubectl get pod -n "$NS" -l app=worker -o jsonpath='{.items[0].metadata.name}')
echo "  대상: $WORKER_POD" | tee -a "$LOG"

WORKER_KILL_EPOCH=$(date +%s)
echo "  ⚡ Worker Pod 삭제: $(date '+%H:%M:%S')" | tee -a "$LOG"
kubectl delete pod "$WORKER_POD" -n "$NS" --grace-period=0 --force 2>/dev/null | tee -a "$LOG"

for i in $(seq 1 60); do
    sleep 5
    READY=$(kubectl get pod -n "$NS" -l app=worker -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
    ELAPSED=$(( $(date +%s) - WORKER_KILL_EPOCH ))
    echo "    ${ELAPSED}s: ready=$READY" | tee -a "$LOG"
    if [ "$READY" = "true" ]; then
        WORKER_RECOVERY=$ELAPSED
        echo "  ✅ Worker Pod 복구: ${WORKER_RECOVERY}초" | tee -a "$LOG"
        break
    fi
done

# Worker 복구 후 API health (Worker 의존성 확인)
sleep 5
POST_WORKER_HEALTH=$(kubectl exec -n "$NS" deploy/api -- curl -s "${BASE}/health" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'status={d[\"status\"]}, db={d[\"services\"][\"database\"]}, redis={d[\"services\"][\"redis\"]}')" 2>/dev/null)
echo "  Worker 복구 후 API health: $POST_WORKER_HEALTH" | tee -a "$LOG"

########################################
# 최종 요약
########################################
echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Alpha 부하 테스트 최종 요약" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  Phase 1 (단일 사이클): ${P1_TIME}초" | tee -a "$LOG"
echo "  Phase 2 (동시 부하): ${P2_TIME}초" | tee -a "$LOG"
echo "  Phase 3 (지속 부하): ${ROUND}라운드 / $((P3_END - P3_START))초" | tee -a "$LOG"
echo "  Phase 4-1 (API Kill): 복구 ${API_RECOVERY:-N/A}초" | tee -a "$LOG"
echo "  Phase 4-2 (Worker Kill): 복구 ${WORKER_RECOVERY:-N/A}초" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "--- 최종 클러스터 상태 ---" | tee -a "$LOG"
kubectl get pods -n "$NS" --no-headers 2>/dev/null | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "  종료: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "=== Alpha 부하 테스트 완료 ===" | tee -a "$LOG"
