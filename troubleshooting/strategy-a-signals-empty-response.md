# Strategy A signals API 빈 응답

> 생성일: 2026-03-29
> 상태: 미해결 (확인 필요)

---

## 증상

`GET /api/v1/strategy/a/signals` 호출 시 HTTP 200이지만 응답 바디가 비어있음 (JSON 파싱 실패).

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/strategy/a/signals
# → 빈 응답 (content-length: 0 또는 빈 문자열)
```

Strategy B는 `{"date":"today","signals":[]}` 정상 반환.

## 원인 추정

1. Strategy A 라우터가 응답 직렬화에서 에러 → 빈 바디 반환
2. 또는 Strategy A가 토너먼트 결과를 DB에서 조회할 때 쿼리 실패 (predictor_tournament_scores 테이블은 있지만 데이터가 없을 수 있음)

## 검증 방법

```bash
# 1. 토너먼트 점수 테이블 확인
docker compose exec postgres psql -U alpha_user -d alpha_db -c "SELECT count(*) FROM predictor_tournament_scores;"

# 2. API 로그에서 에러 확인
docker compose logs api --tail 50 | grep -i "strategy.*a\|error\|500"

# 3. 라우터 코드 확인
# src/api/routers/strategy.py 에서 /a/signals 핸들러 디버그
```

## 영향도

낮음 — 대시보드에서 Strategy A 시그널이 안 보일 수 있지만, 블렌딩/주문 파이프라인에는 영향 없음 (orchestrator가 직접 predictor를 호출하므로)

---

*작성: 2026-03-29*
