# 🚀 CLAUDE.md — 에이전트 행동 강령

> **에이전트는 반드시 이 파일을 가장 먼저 읽어야 합니다.**

---

## 📌 프로젝트 개요

- **프로젝트명:** agents-investing
- **목표:** 한국 KOSPI/KOSDAQ 시장 대상 멀티 에이전트 자동 투자 시스템을 운영하고, 기존 Strategy A/B 구조를 유지한 채 RL Trading과 Search/Scraping pipeline을 구조적으로 확장한다.
- **기술 스택:** Python 3.11+, FastAPI, LangGraph, PostgreSQL, Redis, React 18 + TypeScript + Vite, KIS Developers API, FinanceDataReader, Claude/OpenAI/Gemini

---

## ⚡ 자주 쓰는 명령어

```bash
# 개발 서버 실행
npm run dev

# 테스트 실행
npm run test

# 빌드
npm run build

# 린트
npm run lint
```

---

## 🧭 에이전트 행동 규칙

1. **작업 시작 전** `progress.md`를 읽고 현재 상태를 파악한다.
2. **상세 규칙**은 `.agent/` 폴더를 참조한다.
   - 기술 스택 제약: `.agent/tech_stack.md`
   - 코드 컨벤션: `.agent/conventions.md`
   - 재사용 프롬프트: `.agent/prompts.md`
   - 전체 로드맵: `.agent/roadmap.md`
3. **장기 기억**이 필요하면 루트의 `MEMORY.md`를 읽는다.
4. **모든 작업 완료 후** 반드시 `progress.md`를 업데이트한다.
5. **새로운 기술적 결정이나 문제 해결 경험**은 `MEMORY.md`에 기록한다.
6. 멋대로 새 패키지를 설치하지 않는다. `.agent/tech_stack.md`에 명시된 것만 사용한다.
7. **새 논의 문서**는 반드시 `.agent/templates/discussion.md`를 기반으로 생성한다.
8. 논의 문서 파일명은 `YYYYMMDD-topic-slug.md` 규칙을 따른다.
9. 논의 작업은 `.agent/discussions/` 폴더에 기록한다.
10. 논의 문서는 결론 확정 후 필요한 영구 문서에 반영하고, 반영이 끝나면 삭제한다.
11. **테스트에서 시스템 바이너리 경로를 하드코딩하지 않는다.** `/usr/bin/echo` 대신 `echo` 또는 `shutil.which("echo")`를 사용한다.
12. **파일 경로는 `__file__` 기준 상대 경로를 사용한다.** 절대 경로 하드코딩 금지. 예: `Path(__file__).parent / "fixtures" / "sample.json"`
13. **테스트는 `pip install -r requirements.txt` 후 `pytest`로 실행한다.** Docker 환경이 없는 경우에도 동일하게 패키지를 설치한 뒤 직접 테스트를 돌린다.
---

## 📂 프로젝트 구조 요약

```
# /agents-investing (Root)

├── CLAUDE.md             # 🚀 [Entry] 에이전트 행동 강령 (최우선 진입점)
├── MEMORY.md             # 🧠 [Memory] 기술적 결정 및 문제 해결의 누적 기록
├── progress.md           # 📝 [State] 현재 세션의 할 일 목록 및 진척도
├── README.md             # 프로젝트 소개 문서
├── architecture.md       # 전체 아키텍처 설계 문서
│
├── .agent/               # 📂 [Knowledge] 에이전트 전용 상세 지침서
│   ├── roadmap.md        # 프로젝트 전체 마일스톤 (Long-term Goal)
│   ├── tech_stack.md     # 허용된 라이브러리, 버전, API 제약 (Skills)
│   ├── conventions.md    # 코드 스타일, 테스트 규칙, 배포 규격
│   ├── templates/        # 문서 템플릿 원본
│   ├── discussions/      # 에이전트 논의 작업 문서
│   └── prompts.md        # 특정 작업(Refactoring, UI)을 위한 재사용 프롬프트
│
├── .mcp/                 # 🔌 [Interface] 에이전트 도구 연결 설정
│   └── config.json       # GitHub, DB, 외부 서비스 연동 설정
│
├── docs/                 # 📄 [Reference] 기획서, DB 스키마, 비즈니스 로직
│   ├── AGENTS.md         # 에이전트 종류·역할 분담 정의 (멀티 에이전트 구조)
│   ├── BOOTSTRAP.md      # 시스템/에이전트 최초 부팅 절차 및 초기화 지침
│   ├── HEARTBEAT.md      # 에이전트 생존 신호·상태 모니터링 규격
│   ├── IDENTITY.md       # 에이전트 페르소나·정체성 정의 (이름, 역할, 말투)
│   ├── MEMORY.md         # 메모리 시스템 설계 문서 (루트 MEMORY.md는 실제 기록, 이건 구조 설계)
│   ├── SOUL.md           # 에이전트 핵심 가치관·원칙·행동 철학
│   ├── TOOLS.md          # 에이전트가 사용 가능한 도구 목록 및 사용법
│   ├── USER.md           # 사용자 페르소나·선호도·컨텍스트 정의
│   └── api_spec.md       # API 엔드포인트 상세 설계
│
├── apps/                 # 개별 애플리케이션 (모노레포)
├── extensions/           # 확장 모듈
├── packages/             # 공유 패키지
├── scripts/              # 빌드/배포 스크립트
├── skills/               # 에이전트 스킬 정의
│   └── skills.md
├── src/                  # 💻 [Code] 실제 소스 코드
├── test/                 # 🧪 [Verification] 에이전트가 돌려야 할 테스트 코드
├── ui/                   # UI 관련 코드
└── .env.example          # 🔑 환경 변수 템플릿
```

---

## 🔑 환경 변수

환경 변수는 `.env.example`을 복사하여 `.env`로 사용한다.

---

*Last updated: 2026-03-14*

---

## 확장 구조 메모

- 기존 Strategy A/B와 포트폴리오 실행 구조는 유지합니다.
- 강화학습 트레이딩은 기존 시스템을 대체하는 것이 아니라 구조에 추가되는 기능입니다.
- 검색 파이프라인도 동일하게 추가 기능이며, 방향은 `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI 구조화 -> Claude CLI 추론` 입니다.
- README에는 현재 상태를 `통합 테스트 진행 중`으로 표기하고, 운영 반영이 완료되면 이후 문구를 바꿉니다.
