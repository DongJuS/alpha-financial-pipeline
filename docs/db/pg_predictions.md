> 정책: 항상 200줄 이내를 유지한다.

# predictions

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `predictions` |
| 역할 | 에이전트 예측 시그널 저장. Strategy A/B/R(RL)/S/L 구분. |
| 사용 여부 | ✅ 활성 — predictor, orchestrator 핵심 출력 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| agent_id | VARCHAR(30) | 예측 에이전트 ID |
| llm_model | VARCHAR(50) | 사용 LLM 모델 |
| strategy | CHAR(1) | A / B / R / S / L |
| ticker | VARCHAR(10) | 종목코드 |
| signal | VARCHAR(10) | BUY / SELL / HOLD |
| confidence | NUMERIC(4,3) | 신뢰도 (0~1) |
| target_price / stop_loss | INTEGER | 목표가 / 손절가 |
| reasoning_summary | TEXT | 추론 요약 (lz4 압축) |
| is_shadow | BOOLEAN | 미승인 전략 shadow 로깅 여부 |
| trading_date | DATE | 매매일 |

## 테이블 관계

- → `debate_transcripts(id)` via debate_transcript_id (논리적)
- ← `predictor_tournament_scores` — 동일 agent_id 기준 정확도 추적
