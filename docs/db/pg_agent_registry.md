> 정책: 항상 200줄 이내를 유지한다.

# agent_registry

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `agent_registry` |
| 역할 | 에이전트 중앙 등록부. ID, 타입, 설명, 활성 상태 관리. 시드 11개. |
| 사용 여부 | ✅ 활성 — API agents 엔드포인트, heartbeat 참조 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| agent_id | VARCHAR(30) PK | 에이전트 ID |
| display_name | TEXT | 표시 이름 |
| agent_type | VARCHAR(20) | orchestrator/predictor/collector/portfolio_manager/notifier/execution/rl/research/gen |
| description | TEXT | 설명 |
| is_active | BOOLEAN | 활성 여부 |
| is_on_demand | BOOLEAN | 온디맨드 여부 |
| default_config | JSONB | 기본 설정 |

## 테이블 관계

- ← `agent_heartbeats(agent_id)` — 생존 신호 기록
- ← `predictions(agent_id)` — 예측 출력
