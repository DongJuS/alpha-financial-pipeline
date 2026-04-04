#!/bin/bash
# Alpha Phase 3 재실행 — 30분 지속 부하
NS="alpha-trading"
API="deploy/api"
BASE="http://localhost:8000"
OUTDIR="/tmp/alpha_load_results"
mkdir -p "$OUTDIR"
LOG="$OUTDIR/alpha_phase3.log"
CSV="$OUTDIR/alpha_phase3_resources.csv"

INTERVAL=180  # 3분
DURATION=1800 # 30분

echo "========================================" | tee "$LOG"
echo "  Alpha Phase 3: 지속 부하 (30분)" | tee -a "$LOG"
echo "  시작: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

echo "--- 시작 전 ---" | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"

API_RESTARTS_START=$(kubectl get pod -n "$NS" -l app=api -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)
WORKER_RESTARTS_START=$(kubectl get pod -n "$NS" -l app=worker -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)

echo "timestamp,round,cpu_pct,mem_pct,health_status,collect_status,dual_status,feedback_status,readiness_status,datalake_status,api_restart,worker_restart" > "$CSV"

START=$(date +%s)
ROUND=0

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    [ "$ELAPSED" -ge "$DURATION" ] && break

    ROUND=$((ROUND + 1))
    TS=$(date '+%H:%M:%S')

    echo "" | tee -a "$LOG"
    echo "--- Round $ROUND (${ELAPSED}s/${DURATION}s) $TS ---" | tee -a "$LOG"

    # 5개 API 동시 호출 (백그라운드 + 상태 코드 캡처)
    kubectl exec -n "$NS" "$API" -- curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/api/v1/market/collect" 2>/dev/null > "$OUTDIR/r${ROUND}_collect.txt" &
    kubectl exec -n "$NS" "$API" -- curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/api/v1/agents/dual-execution/run" 2>/dev/null > "$OUTDIR/r${ROUND}_dual.txt" &
    kubectl exec -n "$NS" "$API" -- curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/api/v1/feedback/cycle" 2>/dev/null > "$OUTDIR/r${ROUND}_feedback.txt" &
    kubectl exec -n "$NS" "$API" -- curl -s -o /dev/null -w "%{http_code}" "${BASE}/api/v1/portfolio/readiness" 2>/dev/null > "$OUTDIR/r${ROUND}_readiness.txt" &
    kubectl exec -n "$NS" "$API" -- curl -s -o /dev/null -w "%{http_code}" "${BASE}/api/v1/datalake/overview" 2>/dev/null > "$OUTDIR/r${ROUND}_datalake.txt" &
    wait

    # 결과 읽기
    COLLECT_S=$(cat "$OUTDIR/r${ROUND}_collect.txt" 2>/dev/null || echo "ERR")
    DUAL_S=$(cat "$OUTDIR/r${ROUND}_dual.txt" 2>/dev/null || echo "ERR")
    FEEDBACK_S=$(cat "$OUTDIR/r${ROUND}_feedback.txt" 2>/dev/null || echo "ERR")
    READINESS_S=$(cat "$OUTDIR/r${ROUND}_readiness.txt" 2>/dev/null || echo "ERR")
    DATALAKE_S=$(cat "$OUTDIR/r${ROUND}_datalake.txt" 2>/dev/null || echo "ERR")

    echo "  API 응답: collect=$COLLECT_S dual=$DUAL_S feedback=$FEEDBACK_S readiness=$READINESS_S datalake=$DATALAKE_S" | tee -a "$LOG"

    # 30초 대기 후 리소스 측정
    sleep 30
    RESOURCE=$(kubectl top node 2>/dev/null | tail -1)
    CPU_PCT=$(echo "$RESOURCE" | awk '{print $3}' | tr -d '%')
    MEM_PCT=$(echo "$RESOURCE" | awk '{print $5}' | tr -d '%')

    # health 체크
    HEALTH=$(kubectl exec -n "$NS" "$API" -- curl -s -o /dev/null -w "%{http_code}" "${BASE}/health" 2>/dev/null)

    # Pod 재시작 횟수
    API_R=$(kubectl get pod -n "$NS" -l app=api -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)
    WORKER_R=$(kubectl get pod -n "$NS" -l app=worker -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)

    echo "  리소스: CPU=${CPU_PCT}% MEM=${MEM_PCT}% health=${HEALTH}" | tee -a "$LOG"
    echo "  재시작: API=$API_R(+$((API_R - API_RESTARTS_START))) Worker=$WORKER_R(+$((WORKER_R - WORKER_RESTARTS_START)))" | tee -a "$LOG"

    echo "$TS,$ROUND,$CPU_PCT,$MEM_PCT,$HEALTH,$COLLECT_S,$DUAL_S,$FEEDBACK_S,$READINESS_S,$DATALAKE_S,$API_R,$WORKER_R" >> "$CSV"

    # 다음 라운드까지 대기
    STEP_ELAPSED=$(($(date +%s) - NOW))
    SLEEP_TIME=$((INTERVAL - STEP_ELAPSED))
    if [ "$SLEEP_TIME" -gt 0 ] && [ "$ELAPSED" -lt "$((DURATION - INTERVAL))" ]; then
        echo "  다음 라운드까지 ${SLEEP_TIME}초 대기..." | tee -a "$LOG"
        sleep "$SLEEP_TIME"
    fi
done

echo "" | tee -a "$LOG"
echo "--- 최종 리소스 ---" | tee -a "$LOG"
kubectl top node 2>/dev/null | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "--- Phase 3 리소스 추이 ---" | tee -a "$LOG"
awk -F',' 'NR>1{printf "  R%s %s: CPU=%s%% MEM=%s%% health=%s collect=%s dual=%s feedback=%s\n", $2,$1,$3,$4,$5,$6,$7,$8}' "$CSV" | tee -a "$LOG"

# API 성공률 집계
echo "" | tee -a "$LOG"
echo "--- API 성공률 ---" | tee -a "$LOG"
TOTAL_CALLS=$((ROUND * 5))
SUCCESS_CALLS=$(awk -F',' 'NR>1{for(i=6;i<=10;i++) if($i=="200") c++} END{print c+0}' "$CSV")
FAIL_CALLS=$((TOTAL_CALLS - SUCCESS_CALLS))
echo "  총 호출: $TOTAL_CALLS, 성공: $SUCCESS_CALLS, 실패: $FAIL_CALLS" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "  Phase 3 완료: ${ROUND}라운드" | tee -a "$LOG"
echo "  종료: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
echo "=== Alpha Phase 3 완료 ===" | tee -a "$LOG"
