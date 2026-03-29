---
name: LLM은 API 키가 아니라 CLI/OAuth 모드
description: Claude는 CLI 모드(~/.claude 마운트), Gemini는 OAuth/ADC 모드(~/.config/gcloud 마운트). API 키를 언급하지 말 것.
type: feedback
---

이 프로젝트의 LLM 호출은 API 키를 사용하지 않는다. Claude는 CLI 모드, Gemini는 OAuth(ADC) 모드.
Docker에서는 호스트의 `~/.claude`와 `~/.config/gcloud`를 읽기 전용 마운트.

**Why:** 사용자가 여러 번 강조했으며 매우 화남. API 키 미설정을 이슈로 보고하면 안 됨.

**How to apply:** LLM 관련 이슈를 볼 때 "API 키 없음"이 아니라 "CLI/OAuth 인증 경로가 컨테이너에서 인식되지 않음"으로 진단할 것.
