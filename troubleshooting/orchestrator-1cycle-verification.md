# Collector → Orchestrator 1사이클 재현 검증 (2026-03-29)

> docker compose up 상태에서 worker 서비스의 Orchestrator 사이클 재현 확인.
> 상태: **재현 성공** — 파이프라인 전체 동작, LLM 미설정으로 예측 0건은 예상된 동작.

---

## 환경

```
docker compose ps → 8 서비스 (api, worker, postgres, redis, minio, gen, gen-collector, ui)
API health: {"status":"healthy","scheduler":{"running":true,"job_count":9}}
```

---

## 1사이클 흐름 (13:47:21 ~ 13:47:37, 약 16초)

```
1. Strategy A 토너먼트 시작 (3종목: 005930, 000660, 259960)
2. Strategy B 토론 시작 (3종목)
3. RL Runner: 0/3 티커에서 0 신호 (활성 정책 없음)
4. Predictor 5개 인스턴스 × 3종목 = 15회 LLM 호출 시도
   → 전부 실패 (Claude CLI 없음 + Gemini OAuth 미설정 + GPT key 없음)
5. Strategy A 우승자: predictor_1 (predictions=0)
6. Strategy B 토론 완료 (0신호)
7. Orchestrator blend mode: 3 전략 중 A만 활성
   → 블렌딩 fallback: B/RL 빈 시그널 → 1전략 블렌딩으로 전환
8. N-way blending: 3건 시그널 생성 (HOLD/0.0)
9. PortfolioManager: 장외 주문 스킵 (market_status=closed) — 정상
10. S3 블렌딩 저장: s3://alpha-lake/blend_results/date=2026-03-29/blend_results_134737.parquet (3건)
11. Orchestrator cycle 완료
```

---

## 검증 결과

| 항목 | 상태 | 비고 |
|------|------|------|
| Collector 수집 | ✅ | 24건 수집 완료 |
| Strategy A (Tournament) | ✅ | 토너먼트 실행, 우승자 선정 (예측 0건은 LLM 미설정 때문) |
| Strategy B (Consensus) | ✅ | 토론 시도, LLM 없어서 0신호 — graceful degradation |
| Strategy RL | ✅ | 활성 정책 없어서 0신호 — 정상 (부트스트랩 미실행 상태) |
| N-way 블렌딩 | ✅ | fallback 정상 동작 (B/RL 빈 → A 1전략) |
| PortfolioManager | ✅ | 장외시간 주문 스킵 정상 |
| S3 Parquet 저장 | ✅ | blend_results Hive-style 저장 성공 |
| 스케줄러 | ✅ | 9개 잡 running |
| 120초 인터벌 반복 | ✅ | 13:47 → 13:49 사이클 재실행 확인 |

---

## 발견된 이슈 (기존 known issue)

### LLM Docker 인증 미설정

```
Claude CLI 명령을 찾을 수 없어 SDK 모드로 폴백: claude
Docker/K8s 환경에서 ANTHROPIC_API_KEY가 미설정.
Gemini OAuth credentials unavailable: Your default credentials were not found.
```

**원인:** docker-compose.yml에 `${HOME}/.claude:/root/.claude:ro`와 `${HOME}/.config/gcloud:/root/.config/gcloud:ro` bind mount가 설정되어 있지만, 현재 Docker 환경(Colima)에서 호스트 경로 마운트가 안 됨.

**해결 방향:** PR #25에서 bind mount 구조는 완료됨. `.env`에 `ANTHROPIC_API_KEY` 직접 설정하면 SDK 모드로 동작. Gemini는 `gcloud auth application-default login` 후 재시작.

**영향:** LLM 예측만 안 됨. 파이프라인 자체는 graceful degradation으로 정상 동작.

---

*작성: 2026-03-29*
