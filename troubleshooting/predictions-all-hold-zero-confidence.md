# Predictions 전부 HOLD / confidence 0.000

> 생성일: 2026-03-29
> 상태: 미해결 (환경 제약)

---

## 증상

DB의 predictions 테이블에 315건이 있지만, 전부 `signal=HOLD`, `confidence=0.000`, `strategy=A`.

```sql
SELECT ticker, signal, confidence, strategy FROM predictions ORDER BY trading_date DESC LIMIT 5;
-- 005930 | HOLD | 0.000 | A
-- 000660 | HOLD | 0.000 | A
-- 259960 | HOLD | 0.000 | A
```

## 원인

1. **Docker 내 LLM API 키 미설정**: Claude CLI 미설치 + `ANTHROPIC_API_KEY` 미설정 + Gemini OAuth 미인증
2. PredictorAgent가 3종 LLM 전부 호출 실패 → 시그널 생성 불가 → 기본 HOLD(0.0) 반환
3. Strategy A(Tournament)는 predictor 5개가 모두 HOLD(0.0) → 토너먼트 우승자도 HOLD(0.0)

```
worker: predictor_1 전체 실패: 3종목 전부 예측 불가 — LLM 프로바이더 설정을 확인하세요
worker: predictor_2 전체 실패: 3종목 전부 예측 불가
...
```

## 영향

- **블렌딩은 정상**: HOLD 시그널도 블렌딩에 참여하며, N-way 결과가 S3에 저장됨
- **주문 없음**: 장외(주말) + HOLD 시그널 → PortfolioManager가 주문 스킵 (정상 동작)
- **대시보드**: predictions 목록에 HOLD만 표시됨

## 해결 방법

`.env`에 최소 1개 LLM API 키 추가:

```bash
# 옵션 1: Anthropic API 키
ANTHROPIC_API_KEY=sk-ant-...

# 옵션 2: OpenAI API 키
OPENAI_API_KEY=sk-...

# 옵션 3: Gemini (gcloud ADC)
# 호스트에서: gcloud auth application-default login
```

docker-compose.yml에서 `api`와 `worker` 서비스에 `.env`가 `env_file`로 마운트되어 있으므로, `.env` 수정 후 `docker compose restart worker`만 하면 됨.

## 관련

- `troubleshooting/llm-provider-docker-missing.md` — 동일 근본 원인

---

*작성: 2026-03-29*
