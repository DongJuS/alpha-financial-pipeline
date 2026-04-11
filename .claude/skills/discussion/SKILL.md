---
name: discussion
description: >
  팀 토론으로 기술 결정 문서화 + 아카이브. /discussion <topic> 은 에이전트 토론 후 결정 문서 생성,
  /discussion --archive <파일>은 완료 논의를 200자 이내 요약으로 아카이브.
argument-hint: <topic-slug> | --archive <파일경로>
---

# Discussion Skill

`$ARGUMENTS` 를 파싱하여 아래 두 모드 중 하나를 실행한다.

## Mode 판별

- `--archive` 포함 → **Archive 모드** (`--archive` 뒤의 인자가 파일 경로)
- 그 외 → **Create 모드** (인자 전체가 topic-slug)

---

## Create 모드

### Step 1: 배경 파악

토론 전 반드시 읽을 문서:
- `progress.md` — 현재 진행 상황
- `.agent/roadmap.md` — 장기 방향
- `architecture.md` — 시스템 구조
- `MEMORY.md` — 활성 규칙

주제와 관련된 소스 코드를 탐색하고, 현재 상태와 제약 조건을 정리한다.
**읽은 모든 파일의 경로와 참고 이유를 기록해 둔다** (문서 작성 시 참조 섹션에 사용).

### Step 2: 팀 에이전트 토론

역할: **CTO, DE (Data Engineer), Backend, DevOps**
라운드: **3** (기본)

| 라운드 | 목표 |
|--------|------|
| 1 | 문제 정의, 후보 방식 나열, 각 관점 장단점 |
| 2 | 수치/근거 기반 비교, 반론과 재반론 |
| 3 | 최종 합의, 채택/기각 결정, 실행 전략 |

토론 중에는 각 역할의 발언을 구분하여 사용자에게 보여준다.

### Step 3: 사용자 확인

토론 결론을 요약 제시하고, 수정/보충할 내용이 있는지 확인한다.

### Step 4: 문서 생성

`.agent/discussions/YYYYMMDD-{topic-slug}.md` 에 작성한다.
템플릿: `.agent/templates/discussion.md` 를 **반드시** 따른다.

---

## 문서 작성 정책 (필수)

아래 정책은 **모든** discussion 문서에 예외 없이 적용한다.

### 정책 1: 발언자 금지

- 참석자/역할 정보를 기재하지 않는다
- "CTO가 말했다", "DE의 의견" 같은 표현을 쓰지 않는다
- **결정 사항과 근거만** 기록한다
- 회의록이 아닌 **기술 결정 문서**로 작성한다

### 정책 2: 참조(References) 필수 기재

**섹션 7**은 아래 3가지를 반드시 모두 포함한다.

**7.1 참고 파일** — 토론/분석 과정에서 **실제로 읽은** 파일.
각 파일마다 "이 파일에서 무엇을 참고했는지" 한 줄 설명 필수.

```
- `src/agents/predictor.py:45-89` — fallback 체인 현재 구현 확인
- `architecture.md` — 전체 데이터 흐름 구조 참고
```

**7.2 참고 소스** — 외부 문서, URL, 이전 논의 문서 등.

```
- 20260410-step8b-tick-storage-design.md — 이전 틱 저장소 결정 참고
- PostgreSQL 파티션 공식 문서
```

**7.3 영향받는 파일** — 이 결정으로 변경이 필요한 파일 목록.

```
- src/llm/router.py (신규)
- src/agents/predictor.py (리팩터링)
```

### 정책 3: 결정 근거 3축 평가

기술 결정 시 아래 3축으로 평가한다 (프로젝트 실제 규모 기준, 엔터프라이즈 아님):
1. **확장성 (Scalability)** — 현실적 1~2년 성장 범위
2. **안전 (Safety)** — 보안, 데이터 무결성, blast radius
3. **관리 수월함 (Ease of management)** — 운영 부담, 복잡도, DR 용이성

### 정책 4: 문서 헤더

문서 상단에 아래 메타데이터를 반드시 포함한다:

```
status: open
created_at: YYYY-MM-DD
topic_slug: {topic-slug}
related_files:
- 변경 대상 파일 목록
```

---

## Archive 모드

`/discussion --archive <파일경로>` 실행 시 아래 절차를 따른다.

### Step 1: Closure Checklist 확인

논의 문서의 Closure Checklist 를 읽고 각 항목의 완료 여부를 확인한다.
미완료 항목이 있으면 사용자에게 경고하고 진행 여부를 묻는다.

### Step 2: Archive Migration 작성

`MEMORY-archive.md` 끝에 아래 형식으로 추가한다:

```markdown
---

## YYYY-MM-DD — {제목} ({PR 번호})

{본문: 200자 이내}
```

**Archive Migration 작성 규칙:**

| 규칙 | 설명 |
|------|------|
| 글자 수 | 본문 200자(한글 기준) 이내. 날짜 헤딩·PR 번호는 미포함 |
| 독립성 | 프로젝트 배경지식이 없어도 이해 가능해야 함 |
| 필수 내용 | "무엇을 결정했는가" + "왜 그렇게 결정했는가" |
| 기각 대안 | 핵심 사유 한 줄만 (상세 불필요) |
| 금지 | 내부 변수명, 라인 번호 등 코드 레벨 디테일 |

**예시 (좋음):**
```
LLM 호출 코드의 provider 판별·fallback 체인 중복을 LLMRouter 클래스로 통합.
기존 클라이언트 900줄은 수정 없이 유지하고 라우터만 신규 추가.
ABC/DI는 3개 provider에 과설계로 기각.
```

**예시 (나쁨 — 배경지식 전제):**
```
predictor.py의 _provider_name()과 strategy_b의 _ask_json_with_fallback()를
router.py로 옮김. model_config.py의 provider_name_for_model()도 위임.
```

### Step 3: 논의 문서 삭제

아카이브 기록 완료 후 원본 `.agent/discussions/` 파일을 삭제한다.

---

## 역할별 전문 영역

| 역할 | 전문 영역 |
|------|----------|
| CTO | 전략적 방향, 아키텍처 결정, 비즈니스 판단 |
| DE (Data Engineer) | 데이터 파이프라인, 쿼리 최적화, 데이터 처리 |
| Backend | API 설계, 서비스 로직, 성능 최적화 |
| DevOps | 인프라, 배포, 스토리지, 모니터링 |

사용자가 다른 역할을 지정하면 해당 역할의 전문 영역에 맞게 의견을 제시한다.
