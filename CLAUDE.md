# 🚀 CLAUDE.md — 에이전트 행동 강령

> **에이전트는 반드시 이 파일을 가장 먼저 읽어야 합니다.**

---

## 📌 프로젝트 개요

- **프로젝트명:** agents-investing
- **목표:** 한국 KOSPI/KOSDAQ 시장 대상 멀티 에이전트 자동 투자 시스템을 운영하고, 기존 Strategy A/B 구조를 유지한 채 RL Trading과 Search/Scraping pipeline을 구조적으로 확장한다.
- **기술 스택:** Python 3.11+, FastAPI, LangGraph, PostgreSQL, Redis, React 18 + TypeScript + Vite, KIS Developers API, FinanceDataReader, Claude/OpenAI/Gemini

---

## 🔐 Git Push 인증 절차

GitHub 관련 지침은 `.github/README.md`부터 읽는다.
`git push` 절차는 `.github/GIT_PUSH.md`를 따른다.

---

## 🧭 에이전트 행동 규칙

1. **작업 시작 전** `progress.md`를 읽고 현재 상태를 파악한다.
2. **상세 규칙**은 `.agent/README.md`부터 읽는다.
   - 기술 스택 제약: `.agent/tech_stack.md`
   - 코드 컨벤션: `.agent/conventions.md`
   - 재사용 프롬프트: `.agent/prompts.md`
   - 전체 로드맵: `.agent/roadmap.md`
3. **구조 설명**은 `architecture.md`를 참고한다.
4. **문서 맵**은 `docs/README.md`를 참고한다.
5. **장기 기억**이 필요하면 루트의 `MEMORY.md`(활성 규칙)를 읽는다. 과거 결정 이력이 필요하면 `MEMORY-archive.md`를 참조한다.
6. **모든 작업 완료 후** 반드시 `progress.md`를 업데이트한다.
7. **새로운 기술적 결정이나 문제 해결 경험**은 `MEMORY.md`에 기록한다.
8. 멋대로 새 패키지를 설치하지 않는다. `.agent/tech_stack.md`에 명시된 것만 사용한다.
9. **새 논의 문서**는 반드시 `.agent/templates/discussion.md`를 기반으로 생성한다.
10. 논의 문서 파일명은 `YYYYMMDD-topic-slug.md` 규칙을 따른다.
11. 논의 작업은 `.agent/discussions/` 폴더에 기록한다.
12. 논의 문서는 결론 확정 후 필요한 영구 문서에 반영하고, 블로그에 포스팅(`/post-discussion`)한 뒤 삭제한다.
13. **테스트에서 시스템 바이너리 경로를 하드코딩하지 않는다.** `/usr/bin/echo` 대신 `echo` 또는 `shutil.which("echo")`를 사용한다.
14. **파일 경로는 `__file__` 기준 상대 경로를 사용한다.** 절대 경로 하드코딩 금지. 예: `Path(__file__).parent / "fixtures" / "sample.json"`
15. **테스트는 `pip install -r requirements.txt` 후 `pytest`로 실행한다.** Docker 환경이 없는 경우에도 동일하게 패키지를 설치한 뒤 직접 테스트를 돌린다.

---

## 📏 문서 정리 기준

### 삭제 가능
- git diff/log로 **"무엇을 했는지"** 복원 가능한 항목
- 예: "collector.py에 S3 저장 로직 추가", "테스트 88개 통과"

### 삭제 불가
- **"왜 그렇게 했는지"**, **"뭐 때문에 깨졌는지"** 같은 인과관계·의사결정 맥락
- 예: "runner 등록 추가 후 portfolio readiness가 깨짐 → risk_summary가 dict→dataclass로 바뀌면서 .get() 실패"

### AI 필독 문서 줄 수 기준
- progress.md, architecture.md, MEMORY.md 등 매 세션 읽는 문서는 **200줄 이내** 유지
- 초과 시 위 삭제 기준에 따라 정리하고, 인과관계가 있는 항목만 보존

---

## 🔧 트러블슈팅 관리

1. **트러블슈팅 발생 시** `troubleshooting/{이슈명}.md` 파일을 생성하고 진행 상황을 기록한다.
2. **트러블슈팅 해결 시** 해결 요약(원인, 해결법, 영향 범위)을 `troubleshooting/MEMORY.md`에 기록한다.
3. **git push 시** 커밋 메시지에 해결된 트러블슈팅 내용을 포함한다.
4. push 완료 후 해당 `troubleshooting/{이슈명}.md` 파일을 **삭제**한다.

*Last updated: 2026-03-28*

---

## 🧪 E2E 테스트 기준

> 매 작업 완료 시 아래 e2e 검증을 반드시 수행한다.

### 기동 검증 (docker compose)
1. `docker compose down -v && docker compose up -d --build` → 전체 서비스 healthy
2. `docker compose exec api python scripts/smoke_test.py --skip-telegram` → 전체 통과
3. `docker compose exec api python scripts/health_check.py` → DB/Redis 정상

### 데이터 흐름 검증
1. **gen 모드 (주말/장외)**: `GEN_API_URL` 설정 시 gen 서버가 랜덤 시세 생성 → gen-collector가 수집 → DB + S3 저장. 주말에도 스킵하지 않고 1사이클 완주해야 한다.
2. **FDR 모드 (기본)**: `FinanceDataReader`로 과거 데이터 수집 → DB 저장. `scripts/rl_bootstrap.py --tickers 005930 --train-only`로 학습 파이프라인 검증.
3. **실시간 모드 (장중)**: KIS WebSocket으로 틱 데이터 수집 → Redis pub/sub → DB + S3 저장. 장중에만 가능.

### 모드 판별 기준
- `GEN_API_URL` 환경변수가 설정되면 gen 모드 (주말/장외 시뮬레이션)
- 미설정이면 FDR + KIS 모드 (실제 시장 데이터)
- 주말에 gen 모드가 아니면 Orchestrator 사이클을 스킵하는 것이 **정상 동작**

### 테스트 스위트
- `python3.11 -m pytest test/ --ignore=test/test_search_pipeline.py` → 512+ passed
- 독립 실행 시 전체 통과 확인 (전체 실행 시 event loop 오염으로 일부 실패는 알려진 이슈)

---

## 🔗 빠른 참조

- 개발 명령어: `docs/DEV_COMMANDS.md`
- Swagger / OpenAPI: `docs/SWAGGER.md`
- 환경 변수 템플릿: `.env.example`
- 트러블슈팅 이력: `troubleshooting/MEMORY.md`

---

*Last updated: 2026-03-28*
