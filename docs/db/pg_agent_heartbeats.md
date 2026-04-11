> 정책: 항상 200줄 이내를 유지한다.

# agent_heartbeats

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `agent_heartbeats` |
| 역할 | 에이전트 생존 신호 기록. 7일 롤링으로 유지. |
| 사용 여부 | ✅ 활성 — 모든 에이전트가 주기적 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| agent_id | VARCHAR(30) | 에이전트 ID |
| status | VARCHAR(10) | healthy / degraded / error / dead |
| last_action | TEXT | 마지막 수행 작업 |
| metrics | JSONB | 에이전트 메트릭 |
| recorded_at | TIMESTAMPTZ | 기록 시각 |

## 테이블 관계

- → `agent_registry(agent_id)` 논리적 참조

## 비고

- 7일 이상 오래된 레코드는 수동 VACUUM으로 정리
