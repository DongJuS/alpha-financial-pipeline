---
name: cleaning
description: >
  progress.md와 roadmap.md의 완료 항목을 감지하여 아카이브 파일로 이동하고 원본에서 삭제한다.
  discussions 미아카이브 건도 안내한다.
argument-hint: "[--dry-run]"
---

# Cleaning Skill

완료 항목을 감지 → 사용자 확인 → 아카이브 → 원본 삭제.

## 옵션

- `--dry-run`: 감지 결과만 표시하고 실제 변경하지 않음

---

## Step 1: 파일 읽기

아래 파일을 읽는다:

- `progress.md`
- `.agent/roadmap.md`
- `progress-archive.md`
- `.agent/roadmap-archive.md` (없으면 Step 4에서 자동 생성)

## Step 2: 완료 항목 감지

에이전트 판단으로 완료 항목을 식별한다.

### progress.md 감지 기준

- `✅ 최근 완료` 섹션 아래의 모든 항목
- `진행 현황` 표에서 `100% ✅` 표시된 항목 (표 자체는 유지, 개별 행만 대상)
- **제외:** `다음 작업`, `보류 항목`, 프로젝트 소개 섹션

### roadmap.md 감지 기준

- `완료된 마일스톤` 섹션(`---` 구분자 포함) 아래의 모든 `### Step ...` 블록
- **제외:** `진행 중 마일스톤`, `설계 원칙`, `장기 로드맵`, 프로젝트 소개 섹션

## Step 3: 사용자 확인

감지된 항목을 목록으로 보여준다:

```
📋 아카이브 대상:

[progress.md]
  1. ✅ Step 8b: 틱 데이터 전용 저장소
  2. ✅ Step 9 Phase 2: LLMRouter
  ...

[roadmap.md]
  3. ✅ Step 3 — RL 강화학습 + 3전략 블렌딩
  4. ✅ Step 4 — K3s 프로덕션 배포
  ...

제외할 항목 번호가 있으면 알려주세요. 없으면 Enter.
```

`--dry-run` 이면 여기서 종료한다.

사용자가 제외할 번호를 지정하면 해당 항목을 제외하고 진행한다.

## Step 4: 아카이브 + 삭제

### progress-archive.md

기존 포맷을 따라 파일 끝에 추가한다:

```markdown
---

## {항목 제목} ({날짜})

{내용 요약 — CLAUDE.md "삭제 불가" 기준의 인과관계·의사결정만 보존}
```

CLAUDE.md 문서 정리 기준을 적용한다:
- **삭제 가능** (아카이브에 넣지 않음): git diff/log로 복원 가능한 항목 (예: "테스트 88개 통과")
- **삭제 불가** (아카이브에 보존): 인과관계·의사결정 맥락 (예: "왜 TimescaleDB를 기각했는지")

아카이브 후 `progress.md`에서 해당 항목을 삭제한다.
`진행 현황` 표의 완료 행도 삭제한다.

### roadmap-archive.md

`.agent/roadmap-archive.md`가 없으면 아래 헤더로 생성한다:

```markdown
# roadmap-archive.md — 완료된 마일스톤 이력

> 이 파일은 roadmap.md에서 분리된 아카이브입니다.
> 활성 마일스톤과 진행 중 항목은 `.agent/roadmap.md`를 참조하세요.
```

roadmap.md의 완료 마일스톤 블록을 그대로 이동한다:

```markdown
---

### {Step 이름} — {설명} ✅

{마일스톤 본문 그대로 이동}
```

아카이브 후 `roadmap.md`의 `완료된 마일스톤` 섹션에서 해당 블록을 삭제한다.
`완료된 마일스톤` 섹션 헤더 자체는 유지한다 (향후 완료 항목이 다시 쌓일 수 있으므로).

## Step 5: discussions 미아카이브 확인

`.agent/discussions/` 폴더에 파일이 남아 있는지 확인한다.
`status: open`인 파일이 있으면 안내한다:

```
💡 미아카이브 논의 문서가 있습니다:
  - 20260411-cleaning-skill-design.md
  완료된 논의는 `/discussion --archive <파일>` 로 정리하세요.
```

## Step 6: 결과 보고

```
✅ Cleaning 완료:
  - progress.md: {N}개 항목 아카이브 ({before}줄 → {after}줄)
  - roadmap.md: {N}개 마일스톤 아카이브 ({before}줄 → {after}줄)

{200줄 초과 시}
⚠️ {파일명}이 {N}줄입니다. 200줄 이내로 추가 정리가 필요합니다.
```
