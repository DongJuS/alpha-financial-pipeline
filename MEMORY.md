# 🧠 MEMORY.md — 활성 운영 규칙 및 미해결 이슈

> **작성일**: 2026-03-15 | **최종 갱신**: 2026-03-28
> 완료된 결정의 상세 이력은 `MEMORY-archive.md`를 참조하세요.

---

## 📌 활성 운영 규칙

### 데이터 수집/저장 일관성
1. 새 수집 경로 추가 시 **PG+Redis+S3 3중 저장** 일관성을 반드시 맞출 것. `collect_daily_bars()`를 참조 구현으로 삼을 것.
2. SearchAgent stub 해소 전까지 Strategy S 가중치를 0으로 설정하거나, SearXNG 클라이언트를 직접 연결할 것.
3. Orchestrator CLI 엔트리포인트에 기본 Runner 4종(A/B/RL/S) 자동 등록 코드를 추가할 것.

### 에이전트 레지스트리
1. **새 에이전트 추가 시 반드시 `agent_registry` 테이블에 INSERT할 것.** 코드에만 추가하면 모니터링 누락.
2. **agent_id는 `agent_registry.agent_id`와 정확히 일치해야 한다.** 불일치 시 하트비트/상태 매칭 실패.
3. **비활성화는 soft delete (`is_active=FALSE`)**로 처리. 하드 삭제 금지.

### LLM 프로바이더 정책
1. **LLM API 키를 추가하거나 요구하지 말 것.** CLI/OAuth가 유일한 인증 방식.
2. Claude: `ANTHROPIC_CLI_COMMAND` 환경변수 또는 `/usr/bin/claude` 바이너리에 의존.
3. Gemini: `~/.config/gcloud/application_default_credentials.json` ADC 파일에 의존.
4. GPT: 사용 안 함 (API key 없음이 정상).

### DB 배치 처리
1. **새로운 bulk upsert 함수를 만들 때 반드시 `executemany()`를 사용할 것.** `for + await execute()` 패턴 금지.
2. **5,000건 이상 배치는 자동 청크 분할됨.** `executemany()` 호출 시 별도 처리 불필요.
3. **실시간 스트리밍 데이터(틱 등)는 반드시 버퍼링 후 배치 INSERT.** 단건 INSERT 금지.
4. **ON CONFLICT (upsert) 멱등성은 항상 유지할 것.**

### Sentiment → Signal 매핑
- bullish=BUY, bearish=SELL, neutral/mixed=HOLD
- confidence < 0.3 → HOLD fallback, sources=0 → confidence ≤ 0.3
- 리서치 실패 시 항상 HOLD 신호로 fallback

### 블로그 자동 포스팅 (2026-03-28 추가)
1. `.agent/discussions/*.md` 파일 Write/Edit 시 PostToolUse 훅이 자동으로 Blogger에 **draft** 포스팅.
2. `/post-discussion` 슬래시 커맨드 또는 `scripts/post_discussion_to_blog.py`로 수동 포스팅 가능.
3. 동일 제목의 글이 이미 있으면 업데이트 (중복 방지).
4. Blogger 자격 증명은 `.env`의 `BLOGGER_*` 변수에 저장.

---

## 🔍 미해결 이슈

### LLM 프로바이더 Docker 내 실패
- **상태**: 미해결
- Predictor 1~5 전체 실패. Claude CLI / Gemini OAuth가 Docker 내에서 동작하지 않음.
- `docker compose logs worker` 확인 필요.

### SearchAgent 모델 호환성
- **상태**: 미해결
- 일부 LLM 모델에서 지원 안 될 수 있음. `model_used` 필드로 추적 중.

---

## 📚 현재 아키텍처 요약

```
Orchestrator
├─ Strategy A (Tournament) → signal_a  [0.30]
├─ Strategy B (Consensus)  → signal_b  [0.30]
├─ Strategy RL (Q-learning) → signal_rl [0.20]
└─ Strategy S (Search)     → signal_s  [0.20]
        │
        └─ blend_signals() → final_signal
```

- 주문 권한: PortfolioManagerAgent만 보유
- 승격 경로: virtual → paper → real (각 단계별 게이트 조건)
- 데이터 저장: PG + Redis + S3(MinIO) 3중 구조

---

## 📋 다음 작업 체크리스트

- [ ] SearXNG 로컬 검색 엔진 통합 (API 제한 극복)
- [ ] SearchAgent 모델 호환성 테스트
- [ ] 프로덕션 환경 배포 및 모니터링
- [ ] 성능 튜닝 (블렌딩 가중치 최적화)
- [ ] QA 잔여 이슈 처리 (C3, H1~H4, M1~M4)
- [ ] LLM 프로바이더 Docker 내 실패 해결

---

*Last updated: 2026-03-28*
