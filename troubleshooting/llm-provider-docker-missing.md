# LLM 프로바이더 Docker 내 미설정 (Strategy A/B 시그널 0건)

> 생성일: 2026-03-29
> 상태: 미해결 (환경 제약)
> 관련: e2e 검증

---

## 증상

worker 1사이클 실행 시 Strategy A/B가 0건 시그널 생성:
```
predictor_1 전체 실패: 3종목 전부 예측 불가 — LLM 프로바이더 설정을 확인하세요
Claude CLI 명령을 찾을 수 없어 SDK 모드로 폴백: claude
Docker/K8s 환경에서 ANTHROPIC_API_KEY가 미설정
Gemini OAuth credentials unavailable
```

## 원인

1. **Claude CLI**: Docker 이미지에 설치 실패 + `ANTHROPIC_API_KEY` 환경변수 미설정
2. **Gemini OAuth**: gcloud ADC 마운트(`~/.config/gcloud`)가 Docker 내에서 인증 실패
3. **OpenAI**: `OPENAI_API_KEY` 미설정

3종 LLM 모두 사용 불가 → predictor가 전부 실패 → Strategy A/B 시그널 0건.

## 현재 동작

- **블렌딩 fallback 정상**: B/RL 빈 시그널 → A 1전략 블렌딩으로 전환
- **Orchestrator 사이클 완주**: 시그널 0건이어도 사이클 자체는 정상 종료
- **S3 저장**: blend_results Parquet 저장 완료

## 해결 방안

### 단기 (API 키 주입)
```bash
# .env에 최소 1개 LLM API 키 추가
ANTHROPIC_API_KEY=sk-ant-...
# 또는
OPENAI_API_KEY=sk-...
```

### 중기 (Docker 내 인증 개선)
- Claude CLI: Docker 이미지에서 SDK 모드만 사용 (API 키 기반)
- Gemini: Service Account JSON을 Secret으로 마운트

### 영향도
- LLM 없이도 시스템은 **구조적으로 정상 동작** (graceful degradation)
- 실제 투자 시그널을 생성하려면 최소 1개 LLM API 키 필요

---

*작성: 2026-03-29*
