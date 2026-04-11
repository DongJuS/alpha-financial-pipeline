> 정책: 항상 200줄 이내를 유지한다.

# predictor_tournament_scores

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `predictor_tournament_scores` |
| 역할 | Strategy A 토너먼트 점수. 5일 rolling accuracy 기반 승자 선정. |
| 사용 여부 | ✅ 활성 — strategy_a, orchestrator에서 사용 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| agent_id | VARCHAR(30) | 예측 에이전트 ID |
| llm_model | VARCHAR(50) | LLM 모델 |
| persona | TEXT | 페르소나 (가치투자형, 기술적분석형 등) |
| trading_date | DATE | 매매일 |
| correct / total | INTEGER | 정답수 / 전체수 |
| rolling_accuracy | NUMERIC(5,4) | 5일 이동 정확도 |
| is_current_winner | BOOLEAN | 현재 승자 여부 |

## 테이블 관계

- → `predictions` — 동일 agent_id/trading_date로 정확도 산출
- UNIQUE: (agent_id, trading_date)
