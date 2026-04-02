# Gemini API Key와 OAuth ADC 충돌

> 발생일: 2026-03-30
> 상태: 해결 완료 (PR #67)

---

## 증상

Docker 컨테이너에서 Gemini 호출 시:
```
client_options.api_key and credentials are mutually exclusive
```

## 원인

`.env`에 `GEMINI_API_KEY=AIza...`가 남아 있으면서, 동시에 `~/.config/gcloud/application_default_credentials.json`도 bind mount됨.

google-generativeai SDK는 API Key와 OAuth ADC를 동시에 받으면 **상호배타로 거부**.

## 해결

1. `.env`에서 `GEMINI_API_KEY` 변수 자체 삭제
2. `.env.example`에서도 제거 (신규 설치 시 혼동 방지)
3. `security_audit.py`에서도 제거
4. OAuth(ADC)만 단독 사용

## 재발 방지

- `.env.example`에 해당 변수가 아예 없으므로 신규 설치 시 상호배타 상황 발생 불가
- LLM 인증은 CLI/OAuth 단일 경로로 통일

---

*이 파일은 push 후 MEMORY.md에 요약 기록 후 삭제합니다.*
