# 💓 HEARTBEAT.md — 에이전트 생존 신호·상태 모니터링 규격

> 모든 에이전트는 이 규격에 따라 헬스비트를 발신해야 합니다.
> OrchestratorAgent는 이 규격에 따라 에이전트 건강 상태를 모니터링합니다.

---

## 📡 헬스비트 프로토콜

### 발신 규칙
- **주기:** 30초마다 Redis에 헬스비트 키 갱신
- **키:** `heartbeat:{agent_id}`
- **TTL:** 90초 (3회 주기 미발신 시 자동 만료 = 장애 감지)

### 헬스비트 페이로드
```json
{
  "agent_id": "collector_agent",
  "agent_type": "collector",
  "status": "healthy",
  "last_action": "KOSPI200 틱 데이터 수집 완료 (10:32:15 KST)",
  "metrics": {
    "messages_processed_last_min": 42,
    "error_count_last_hour": 0,
    "api_latency_ms": 120
  },
  "timestamp_utc": "2026-03-12T01:32:15Z"
}
```

---

## 🟢🟡🔴 상태 정의

| 상태 | 색상 | 의미 | 조건 |
|------|------|------|------|
| `healthy` | 🟢 초록 | 정상 운영 중 | 최근 5분 에러율 <5%, API 응답 <2s |
| `degraded` | 🟡 노랑 | 기능은 하지만 성능 저하 | 에러율 ≥5% 또는 API 응답 ≥2s |
| `error` | 🔴 빨강 | 주요 기능 불가 | 예외 발생으로 핵심 작업 수행 불가 |
| `offline` | ⚫ 검정 | 프로세스 사망 | TTL 90초 만료, 헬스비트 미수신 |

---

## 👀 OrchestratorAgent 모니터링 로직

**폴링 주기:** 60초

| 조건 | 행동 |
|------|------|
| 1회 헬스비트 미수신 | WARNING 로그 기록 |
| 연속 3회 미수신 (90초) | NotifierAgent 경보 발송 + 프로세스 재시작 시도 |
| `degraded` 상태 30분 지속 | NotifierAgent 경보 발송 |
| `error` 상태 감지 즉시 | NotifierAgent 긴급 경보 + 재시작 시도 |

**Strategy A 토너먼트 중 장애:**
- Predictor 인스턴스 장애 시: 해당 인스턴스를 토너먼트에서 제외, N-1개로 진행
- 모든 인스턴스 장애 시: Strategy A HOLD, Strategy B 단독으로 진행

**PortfolioManager 장애 시:**
- 진행 중인 모든 주문 취소
- 포지션은 현상 유지 (강제 청산 없음)
- 복구 후 수동 확인 필요

---

## 🏥 에이전트별 복구 절차

### CollectorAgent 장애
1. 데이터 갭 발생 구간 `collector_errors` 테이블에 기록
2. 재시작 후 `fdr.DataReader()`로 누락 구간 백필
3. WebSocket 재연결 시도 (최대 3회)
4. 성공 후 `data_ready` 이벤트 재발행

### PredictorAgent 장애 (Strategy A)
1. 해당 인스턴스 토너먼트 당일 제외
2. 재시작 성공 시 다음 거래일부터 복귀
3. 토너먼트 점수 갭은 0으로 처리

### PortfolioManagerAgent 장애
1. 진행 중인 주문 즉시 취소 (KIS API)
2. 현재 포지션 snapshot을 Redis에서 PostgreSQL로 즉시 동기화
3. 재시작 후 상태 일관성 검증 (`kis_get_balance` vs `portfolio_positions` 비교)
4. 불일치 발견 시 KIS API 기준으로 동기화

### OrchestratorAgent 장애
1. 모든 에이전트가 안전 상태로 전환 (신규 거래 중단)
2. systemd/supervisor 자동 재시작
3. LangGraph 체크포인트에서 마지막 상태 복원
4. NotifierAgent에 복구 완료 알림

---

## 📊 헬스비트 대시보드 표시

프론트엔드 대시보드의 에이전트 상태 패널에서:

```
[ CollectorAgent ]    🟢 healthy    마지막 동작: 15:30 KOSPI 장 마감 수집
[ PredictorAgent-1 ]  🟢 healthy    마지막 동작: 08:55 Strategy B Proposer 완료
[ PredictorAgent-2 ]  🟡 degraded   마지막 동작: 08:50 GPT-4o 응답 지연 (3.2s)
[ PortfolioManager ]  🟢 healthy    마지막 동작: 09:01 삼성전자 100주 매수
[ NotifierAgent ]     🟢 healthy    마지막 동작: 08:30 아침 브리핑 발송
[ Orchestrator ]      🟢 healthy    마지막 동작: 15:35 토너먼트 스코어링 완료
```

---

## 🗄️ 헬스비트 로그 테이블

```sql
-- agent_heartbeats 테이블 (7일 롤링 보관)
SELECT agent_id, status, last_action, recorded_at
FROM agent_heartbeats
WHERE agent_id = 'collector_agent'
  AND recorded_at > NOW() - INTERVAL '1 hour'
ORDER BY recorded_at DESC;
```

---

*Last updated: 2026-03-12*
