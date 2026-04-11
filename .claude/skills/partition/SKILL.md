---
name: partition
description: >
  roadmap/progress를 분석하여 작업을 3~4명의 AI 에이전트에게 충돌 없이 분담하고,
  파티셔닝 문서를 .agent/partition/에 생성한다.
argument-hint: "[roadmap | progress | <topic>] [--agents N]"
---

# Partition Skill

roadmap/progress를 분석하여 수행할 작업을 식별하고, 여러 AI 에이전트가 **git 충돌 없이** 병렬 작업할 수 있도록 업무를 분담한다.

## 입력

- `$ARGUMENTS`로 범위를 지정한다:
  - `roadmap` — `.agent/roadmap.md`에서 미완료 작업을 찾아 분담
  - `progress` — `progress.md`에서 진행 중/다음 작업을 찾아 분담
  - `<topic>` — 특정 주제에 대한 작업을 분담
  - `--agents N` — 에이전트 수 지정 (기본: 3)

## 핵심 원칙: 충돌 방지

파티셔닝의 최우선 목표는 **git merge 시 충돌을 최소화**하는 것이다.

### 파일 소유권 규칙

1. **하나의 파일은 하나의 에이전트만 수정한다** — 같은 파일을 두 에이전트가 동시에 수정하면 충돌이 발생한다
2. **새 파일 생성은 자유** — 신규 파일은 충돌이 없으므로 각 에이전트가 자유롭게 생성 가능
3. **공유 파일(config, __init__.py 등) 수정은 한 에이전트에게만 배정** — 여러 에이전트가 import를 추가해야 하면, 마지막 에이전트에게 모아서 배정
4. **테스트 파일도 소유권을 분리** — `test_xxx.py`를 새로 만들되, 기존 테스트 파일 수정은 한 에이전트만

### 분담 전략

- **수직 분할 (기본)**: 기능/모듈 단위로 분할. 예) Agent1=수집기, Agent2=API, Agent3=프론트
- **수평 분할 (필요 시)**: 레이어 단위로 분할. 예) Agent1=DB스키마, Agent2=서비스로직, Agent3=테스트
- 의존성이 있는 작업은 **순서를 명시**한다 (Agent1 완료 후 Agent2 시작)

---

## Step 1: 현황 파악

아래 파일을 읽는다:

- `progress.md` — 현재 상태, 진행 중/다음 작업
- `.agent/roadmap.md` — 전체 로드맵, 미완료 마일스톤
- `architecture.md` — 시스템 구조 (모듈 의존성 파악)

`$ARGUMENTS`에 따라 대상 작업 목록을 추출한다.

## Step 2: 작업 식별 및 분류

대상 작업을 아래 기준으로 분류한다:

| 분류 | 설명 |
|------|------|
| 독립 작업 | 다른 작업과 파일 의존성 없음 → 병렬 가능 |
| 순차 작업 | 선행 작업의 결과물이 필요 → 순서 지정 |
| 공유 작업 | 공통 파일 수정 필요 → 한 에이전트에 집중 |

각 작업에 대해 **수정 대상 파일 목록**을 구체적으로 나열한다.

## Step 3: 에이전트 배정

작업을 에이전트에게 배정한다. 각 에이전트별로 아래 정보를 명시한다:

```
### Agent {N}: {역할 이름}

**담당 작업:**
- 작업 1: {설명}
- 작업 2: {설명}

**수정 대상 파일:**
- `src/xxx/yyy.py` (수정)
- `src/xxx/zzz.py` (신규)
- `test/test_xxx.py` (신규)

**절대 수정 금지 파일:**
- `src/aaa/bbb.py` (Agent M 담당)

**완료 기준:**
- [ ] 기준 1
- [ ] 기준 2

**예상 브랜치명:** `feat/partition-agentN-{slug}`
```

## Step 4: 충돌 검증 매트릭스

모든 에이전트의 수정 대상 파일을 교차 검증한다:

```
| 파일 | Agent1 | Agent2 | Agent3 |
|------|--------|--------|--------|
| src/a.py | ✏️ | ❌ | ❌ |
| src/b.py | ❌ | ✏️ | ❌ |
| src/c.py | ❌ | ❌ | ✏️ |
```

**같은 파일에 ✏️가 2개 이상이면 재배정**한다.

## Step 5: 사용자 확인

파티셔닝 결과를 요약하여 사용자에게 보여주고 확인을 받는다:

```
📋 파티셔닝 결과 ({N}개 에이전트):

Agent 1: {역할} — {작업 수}개 작업, {파일 수}개 파일
Agent 2: {역할} — {작업 수}개 작업, {파일 수}개 파일
Agent 3: {역할} — {작업 수}개 작업, {파일 수}개 파일

⚠️ 순차 의존성: Agent 1 → Agent 2 (xxx 때문)
✅ 파일 충돌 없음

수정할 내용이 있으면 알려주세요.
```

## Step 6: 파티셔닝 문서 생성

사용자 확인 후 `.agent/partition/YYYYMMDD-{topic}-partition.md`를 생성한다.

문서 구조:

```markdown
# {주제} — 에이전트 파티셔닝

status: open
created_at: YYYY-MM-DD
topic_slug: {topic}-partition

## 배경

파티셔닝 대상 작업과 이유.

## 파티셔닝 요약

| Agent | 역할 | 작업 수 | 핵심 파일 |
|-------|------|---------|----------|
| 1 | ... | N | ... |

## Agent 1: {역할}

### 담당 작업
...

### 수정 대상 파일
...

### 절대 수정 금지 파일
...

### 완료 기준
...

### 브랜치명
`feat/partition-agent1-{slug}`

## Agent 2: {역할}
(동일 구조)

## Agent 3: {역할}
(동일 구조)

## 충돌 검증 매트릭스

| 파일 | Agent1 | Agent2 | Agent3 |
|------|--------|--------|--------|
...

## 순차 의존성

- Agent 1 완료 후 Agent 2 시작 (사유: ...)
- Agent 2, 3은 병렬 가능

## 병합 순서

1. Agent 1 PR 먼저 병합
2. Agent 2, 3 순서 무관
```

## Step 7: 사용 안내

문서 생성 후 사용 방법을 안내한다:

```
✅ 파티셔닝 문서 생성 완료: .agent/partition/YYYYMMDD-{topic}-partition.md

각 에이전트에게 아래와 같이 작업을 지시하세요:
  Session 1: ".agent/partition/YYYYMMDD-{topic}-partition.md 의 Agent 1 작업을 진행해줘"
  Session 2: ".agent/partition/YYYYMMDD-{topic}-partition.md 의 Agent 2 작업을 진행해줘"
  Session 3: ".agent/partition/YYYYMMDD-{topic}-partition.md 의 Agent 3 작업을 진행해줘"
```

---

## 문서 작성 정책

- **발언자/역할 표시 금지** — 결정+근거만 기록
- `.agent/templates/discussion.md` 기반이되, 파티셔닝 전용 구조 사용
- 파일명은 `YYYYMMDD-{topic}-partition.md` 규칙
