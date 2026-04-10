# 💓 HEARTBEAT.md — 에이전트 생존 신호·상태 모니터링 규격

> 모든 에이전트는 이 규격에 따라 헬스비트를 발신해야 합니다.

---

## 📡 헬스비트 프로토콜

### 발신 규칙
- **주기:** 30초마다 Redis에 헬스비트 키 갱신
- **키:** `heartbeat:{agent_id}` (Redis Hash)
- **TTL:** 90초 (3회 주기 미발신 시 자동 만료 = 장애 감지)

### 헬스비트 필드 (Redis Hash)

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `status` | string | 에이전트 상태 | `ok`, `degraded`, `error` |
| `updated_at` | int | Unix timestamp (초) | `1712700000` |
| `mode` | string | 동작 모드 (선택) | `websocket`, `fdr`, `idle` |
| `last_data_at` | int | 마지막 데이터 수신 시각 (선택) | `1712699990` |
| `error_count` | int | 최근 에러 횟수 (선택) | `2` |

**기본 호출 (모든 에이전트):**
```python
await set_heartbeat(agent_id)  # status="ok", updated_at 자동
```

**확장 호출 (Collector 등):**
```python
await set_heartbeat(agent_id, status="degraded", mode="fdr", error_count=2)
```

---

## 🟢🟡🔴 상태 정의

| 상태 | 색상 | 의미 | 조건 |
|------|------|------|------|
| `ok` | 🟢 초록 | 정상 운영 중 | 핵심 기능 정상 동작 |
| `degraded` | 🟡 노랑 | 기능은 하지만 성능/모드 저하 | WebSocket→FDR 폴백, 재연결 시도 중 |
| `error` | 🔴 빨강 | 주요 기능 불가 | 재연결 한도 초과, 핵심 작업 수행 불가 |
| (TTL 만료) | ⚫ 검정 | 프로세스 사망 | 90초간 heartbeat 미수신 |

---

## 🏥 Docker / K8s 헬스체크

### Docker Compose

`scripts/docker_healthcheck.py`가 worker 서비스의 healthcheck를 담당한다.

```yaml
healthcheck:
  test: ["CMD", "python", "scripts/docker_healthcheck.py", "--service", "worker"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

**체크 항목:**
1. Redis PING 응답
2. 에이전트 heartbeat 키 존재 (하나 이상)
3. status ≠ error

### K8s Probe

| Probe | 역할 | 실패 시 |
|-------|------|---------|
| `livenessProbe` | 프로세스 생존 확인 | Pod 재시작 |
| `readinessProbe` | 기능 정상 확인 | 트래픽 차단 |

두 probe 모두 `docker_healthcheck.py`를 사용한다.

---

## 👀 Orchestrator 모니터링

**점검 시점:** 매 사이클 완료 후 (`run_cycle` 내부)

Orchestrator는 사이클 성공 후 `_check_agent_health()`를 호출하여
collector_agent, portfolio_manager_agent, notifier_agent의 heartbeat를 점검한다.

| 조건 | 행동 |
|------|------|
| heartbeat 키 없음 (TTL 만료) | `offline` → Telegram 알림 (⚫) |
| `error` 상태 감지 | Telegram 알림 (🔴) + mode/error_count 포함 |
| `degraded` 상태 감지 | Telegram 알림 (⚠️) + mode/error_count 포함 |
| `ok` 상태 | 정상 — 별도 조치 없음 |

**알림 메서드:** `NotifierAgent.send_agent_health_alert(agent_id, status, mode, error_count)`
**재시작은 Docker/K8s 인프라에 위임.** Orchestrator는 감지 + 알림만 담당.

---

## 🏥 에이전트별 복구 절차

### CollectorAgent 장애
1. 데이터 갭 발생 구간 `collector_errors` 테이블에 기록
2. 재시작 후 `fdr.DataReader()`로 누락 구간 백필
3. WebSocket 재연결 시도 (최대 3회)
4. 3회 초과 시 FDR 스냅샷 폴백 (status=degraded, mode=fdr)
5. Docker/K8s healthcheck가 error 감지 시 컨테이너 재시작

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
[ CollectorAgent ]    🟢 ok         모드: websocket   마지막 데이터: 10:32:15
[ PredictorAgent-1 ]  🟢 ok
[ PortfolioManager ]  🟢 ok
[ NotifierAgent ]     🟢 ok
[ Orchestrator ]      🟢 ok
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

*Last updated: 2026-04-10*
