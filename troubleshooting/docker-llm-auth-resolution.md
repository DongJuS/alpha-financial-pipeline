# Docker LLM 인증 전체 해결 기록

> 발생일: 2026-03-29~30
> 상태: 해결 완료

---

## 문제 1: Permission Denied (Dockerfile target)

**증상:** Worker 컨테이너에서 `/root/.claude/`, `/root/.config/gcloud/` 접근 불가.
**원인:** multi-stage Dockerfile에서 `target` 미지정 → prod 스테이지(USER alpha, uid 999)가 빌드됨 → `/root/` 경로 읽기 불가.
**해결:** docker-compose.yml의 5개 앱 서비스에 `target: dev` 명시.

## 문제 2: Gemini OAuth + API Key 충돌

**증상:** `client_options.api_key and credentials are mutually exclusive`
**원인:** `.env`에 `GEMINI_API_KEY=AIza...`가 남아 있으면서 동시에 `~/.config/gcloud/` OAuth ADC도 마운트됨. google-generativeai SDK가 둘을 동시에 받으면 거부.
**해결:**
- `.env`에서 `GEMINI_API_KEY` 변수 자체 삭제
- `.env.example`, `docker-compose.test.yml`, `security_audit.py`에서도 제거
- OAuth(ADC)만 단독 사용

## 문제 3: Claude CLI "Not logged in"

**증상:** 호스트 `~/.claude/`를 bind mount했으나 컨테이너 안에서 `Not logged in`.
**원인:** Claude Code의 OAuth 세션 토큰이 호스트 바이너리(2.1.84)와 컨테이너 바이너리(2.1.87) 간에 호환되지 않음. 세션 파일 형식이 버전별로 다르거나, 호스트 머신에 바인딩된 토큰.
**해결:**
1. bind mount를 `ro` → `rw`로 변경 (컨테이너에서 토큰 쓰기 가능)
2. 컨테이너 안에서 `docker compose exec -it worker claude /login` 실행
3. 브라우저에서 OAuth 인증 완료 → 토큰이 `/root/.claude/`에 저장
4. 이후 `rw` 마운트를 통해 호스트 `~/.claude/`에도 반영

**주의:** `docker compose down` 후 재시작하면 컨테이너가 재생성되므로 로그인 유지됨 (호스트 디렉토리에 토큰 저장).

## 문제 4: LLM 일일 사용 한도 30회 도달

**증상:** 인증 성공 후에도 `RuntimeError: Claude 일일 사용 한도(30회)에 도달했습니다.`
**원인:** `src/services/llm_usage_limiter.py`에서 provider별 일일 호출 횟수를 Redis로 카운팅. 한도 30회/일 설정. 이전 사이클에서 인증 실패 시에도 카운트가 올라갔거나, 디버깅 중 수동 호출로 소진.
**영향:** 인증은 성공이므로 자정 리셋 후 정상 동작.
**확인 방법:**
```bash
# Redis에서 현재 카운트 확인
docker compose exec redis redis-cli KEYS "*llm_usage*"
docker compose exec redis redis-cli GET "llm_usage:claude:2026-03-30"

# 수동 리셋 (긴급 시)
docker compose exec redis redis-cli DEL "llm_usage:claude:2026-03-30"
docker compose exec redis redis-cli DEL "llm_usage:gemini:2026-03-30"
```

---

## 최종 상태

| Provider | 인증 | 호출 | 비고 |
|---|---|---|---|
| Claude | ✅ CLI 로그인 완료 | ⚠️ 일일 한도 도달 (자정 리셋) | `claude -p "say ok"` → 정상 응답 확인 |
| Gemini | ✅ OAuth ADC 정상 | ⚠️ 일일 한도 도달 (자정 리셋) | `configured: True`, API key 충돌 해결 |
| GPT | ⬜ 미사용 | — | 의도적 비활성화 |

---

## 진단 타임라인

| 시각 | 발견 | 행동 |
|---|---|---|
| 22:30 | Worker에서 3 provider 전부 실패 | 로그 분류 시작 |
| 22:32 | `whoami` → `alpha` (non-root) | Dockerfile target 문제 특정 |
| 22:36 | `target: dev` 추가 | 5개 서비스 수정 |
| 22:50 | 리빌드 후 root 확인 | 마운트 접근 가능 |
| 23:10 | Gemini `api_key and credentials mutually exclusive` | `.env`에서 GEMINI_API_KEY 제거 |
| 23:20 | Claude `Not logged in` | bind mount `ro` → `rw` 변경 |
| 23:25 | 컨테이너 안에서 `claude /login` | 브라우저 OAuth 인증 |
| 23:30 | Claude/Gemini 모두 `configured: True` | 인증 완료 확인 |
| 23:35 | `일일 사용 한도 30회 도달` | 자정 리셋 대기 |

---

*이 파일은 push 후 MEMORY.md에 요약 기록 후 삭제합니다.*
