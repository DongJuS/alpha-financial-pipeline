> 정책: 항상 200줄 이내를 유지한다.

# model_role_configs

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `model_role_configs` |
| 역할 | LLM 역할 설정. Strategy A 5명 predictor + Strategy B 4명 (proposer/challenger×2/synthesizer). |
| 사용 여부 | ✅ 활성 — 시드 9건, API에서 CRUD |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| config_key | VARCHAR(60) UNIQUE | 설정 키 (strategy_a_predictor_1 등) |
| strategy_code | CHAR(1) | A / B |
| role | VARCHAR(30) | predictor / proposer / challenger / synthesizer |
| agent_id | VARCHAR(50) | 에이전트 ID |
| llm_model | VARCHAR(80) | LLM 모델명 |
| persona | TEXT | 페르소나 설명 |
| execution_order | INTEGER | 실행 순서 |
| is_enabled | BOOLEAN | 활성 여부 |

## 테이블 관계

- → `predictions(agent_id)` — 동일 에이전트 ID로 연결
- 독립 설정 테이블 (FK 없음)
