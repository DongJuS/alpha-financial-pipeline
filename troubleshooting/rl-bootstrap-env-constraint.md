# RL 부트스트랩 테스트 환경 제약

> 생성일: 2026-03-29
> 상태: 미해결 (환경 제약)
> 관련 PR: #32

---

## 증상

`test/test_rl_bootstrap.py` 실행 시 `DATABASE_URL`, `JWT_SECRET` 환경변수가 없으면 Settings Pydantic 모델 validation 에러로 전체 테스트 실패.

## 원인

- `scripts/rl_bootstrap.py`가 `src.db.queries.fetch_recent_market_data`를 모듈 레벨에서 import
- 이 import 체인이 `src.utils.config.Settings`를 로드하며, Settings는 `DATABASE_URL`과 `JWT_SECRET`을 필수 필드로 요구
- `.env` 파일이 worktree에 복사되지 않음 (.gitignore 대상)

## 현재 대응

테스트 실행 시 더미 환경변수를 주입:
```bash
DATABASE_URL="postgresql://test:test@localhost/test" JWT_SECRET="test" python3 -m pytest test/test_rl_bootstrap.py
```

## 남은 리스크

1. **CI 환경에서도 동일 이슈 발생** — CI workflow에서 `DATABASE_URL`/`JWT_SECRET` 환경변수 설정 필요
2. **실제 DB 없이는 e2e 부트스트랩 불가** — 현재 테스트는 mock 기반이므로 FDR→DB→학습→활성화 실제 흐름은 미검증
3. **FDR(FinanceDataReader) 네트워크 의존** — 실제 시딩은 외부 API 호출이므로 오프라인 환경에서 실패

## 기존 테스트 실패 (PR #32와 무관)

e2e 테스트 중 기존 7개 실패 확인:
- `test_rl_trading.py` 2개: `use_rl` 파라미터가 이미 제거된 오래된 테스트 (TypeError)
- `test_blend_nway.py` 5개: Python 3.9 event loop 호환성 이슈 (`asyncio.get_event_loop()` → RuntimeError)

이 실패들은 PR #32 이전부터 존재하며 수정이 필요하지만 별도 이슈로 처리해야 함.
