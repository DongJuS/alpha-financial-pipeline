# Claude CLI 버전 불일치로 "Not logged in"

> 발생일: 2026-03-30
> 상태: 해결 완료

---

## 증상

호스트 `~/.claude/`를 bind mount했으나 컨테이너 안에서:
```
Not logged in
```

## 원인

Claude Code의 OAuth 세션 토큰이 **호스트 바이너리(2.1.84)와 컨테이너 바이너리(2.1.87) 간에 호환되지 않음**.

세션 파일 형식이 버전별로 다르거나, 호스트 머신에 바인딩된 토큰으로 추정.

## 해결

1. bind mount를 `ro` → `rw`로 변경 (컨테이너에서 토큰 쓰기 가능)
2. 컨테이너 안에서 `docker compose exec -it worker claude /login` 실행
3. 브라우저에서 OAuth 인증 완료 → 토큰이 `/root/.claude/`에 저장
4. `rw` 마운트를 통해 호스트 `~/.claude/`에도 반영

## 주의

- `docker compose down` 후 재시작해도 호스트 디렉토리에 토큰이 저장되어 있으므로 로그인 유지
- Claude Code 업데이트 시 재인증이 필요할 수 있음

---

*이 파일은 push 후 MEMORY.md에 요약 기록 후 삭제합니다.*
