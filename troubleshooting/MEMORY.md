# 🔧 트러블슈팅 이력

> 해결된 트러블슈팅의 요약을 기록합니다.
> 각 항목은 **원인 → 해결법 → 영향 범위**를 포함합니다.
> 개별 트러블슈팅 파일(`{이슈명}.md`)은 해결 후 git push 시 삭제합니다.

---

## 기록 형식

```
### {날짜} — {이슈 제목}
- **증상:** 무엇이 깨졌는가
- **원인:** 왜 깨졌는가 (인과관계)
- **해결:** 어떻게 고쳤는가
- **영향:** 어떤 파일/기능에 영향을 줬는가
```

---

### 2026-03-29 — 테스트 스위트 47건 실패 → 0건 (PR #44/#45/#50)
- **증상:** 전체 테스트 실행 시 47건 실패 (event loop 오염 32건, Python 3.9 문법 8건, 인터페이스 불일치 17건 등)
- **원인:** (1) conftest.py의 session-scoped `event_loop` fixture가 pytest-asyncio 0.26에서 deprecated → `IsolatedAsyncioTestCase`와 충돌하여 cascade 실패. (2) `asyncio.run()` 직접 호출이 event loop를 파괴. (3) SearchAgent 리팩토링 후 테스트 미업데이트.
- **해결:** (1) deprecated `event_loop` fixture 제거. (2) `asyncio.run()` → `IsolatedAsyncioTestCase` + `await` 전환. (3) test_search_pipeline.py 현재 인터페이스에 맞게 재작성. (4) DB 의존 테스트 `@pytest.mark.integration` 마킹.
- **영향:** conftest.py, test_blend_nway.py, test_aggregate_risk.py, test_strategy_promotion.py, test_data_pipeline.py, test_rl_bootstrap.py, test_search_pipeline.py, test_portfolio_manager.py, test_risk_validation.py
- **결과:** 462 passed → **557 passed, 0 failed**

### 2026-03-29 — README 빠른 시작 minio 서비스 누락
- **증상:** README 명령대로 `docker compose up` 실행 시 api/worker가 시작 불가
- **원인:** docker-compose.yml에서 api/worker가 minio에 `service_healthy` 의존하나 README 명령에 minio 누락
- **해결:** README.md 두 곳에 `minio` 서비스 추가 (PR #53)
- **영향:** README.md만 수정, 런타임 코드 변경 없음
