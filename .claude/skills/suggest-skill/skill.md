---
name: suggest-skill
description: >
  현재 git/프로젝트 상태를 분석하여 지금 이 순간에 실행하면 좋을 skill을 추천한다.
  사용자의 평소 워크플로우 패턴을 기반으로 판단한다.
argument-hint: ""
---

# suggest-skill — 지금 쓸 skill 추천

현재 상태를 빠르게 파악하고, 사용자의 워크플로우 패턴에 맞는 skill을 추천한다.

---

## Step 1: 현재 상태 수집

아래를 **병렬로** 실행한다:

1. `git status` — 변경/미커밋 파일
2. `git branch` — 현재 브랜치
3. `git log --oneline -3` — 최근 커밋
4. `ls .agent/discussions/` — 열린 논의 문서
5. `progress.md` 첫 50줄 — 완료/진행 항목

---

## Step 2: 패턴 매칭

아래 조건을 **위에서 아래로** 순서대로 평가한다. 먼저 매칭되는 것이 우선순위가 높다.

### 조건표

| 우선순위 | 조건 | 추천 skill | 이유 |
|---------|------|-----------|------|
| 1 | 커밋 안 된 변경사항이 있다 | `/git-commit-merge` | 변경사항 정리가 최우선 |
| 2 | main이 아닌 브랜치에 커밋이 있고 PR이 없다 | `/git-commit-merge` | 브랜치 작업을 PR로 마무리 |
| 3 | progress.md에 ✅ 완료 항목이 5개 이상 쌓여 있다 | `/cleaning` | 문서 정리 시점 |
| 4 | .agent/discussions/에 status: open 문서가 있고 결론이 확정됨 | `/post-discussion` + `/discussion --archive` | 확정된 논의를 포스팅하고 아카이브 |
| 5 | 다음 작업이 큰 단위이고 분할이 필요해 보인다 | `/partition` → `/4agents` | 병렬 작업으로 효율화 |
| 6 | 기술적 결정이 필요한 미해결 이슈가 있다 | `/team-discuss-invest` | 팀 토론으로 의사결정 |
| 7 | 위 조건에 해당하는 것이 없다 | `/suggest-next` | 다음 작업 탐색 |

### 복합 추천

조건이 여러 개 매칭되면, 실행 순서를 포함하여 추천한다.
예: "변경사항 커밋 후 cleaning 하시면 됩니다" → `/git-commit-merge` → `/cleaning`

---

## Step 3: 추천 출력

간결하게 출력한다:

```
💡 지금 추천: /git-commit-merge
   └ 이유: test/ 파일 10개 변경, 커밋 안 됨

   다음: /cleaning
   └ 이유: progress.md 완료 항목 7개 정리 필요
```

- 추천은 **최대 3개**까지
- 각 추천마다 **판단 근거를 1줄**로
- 해당 없으면: "특별히 추천할 skill이 없습니다. `/suggest-next`로 다음 작업을 찾아보세요."
