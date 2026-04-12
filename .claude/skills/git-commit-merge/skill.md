---
name: git-commit-merge
description: >
  현재 변경사항을 자세한 커밋 메시지로 commit하고, PR 생성 후 merge까지 일괄 진행한다.
  브랜치 상태를 검증하고, 의도대로 진행되었는지 각 단계마다 확인한다.
argument-hint: "<PR 제목 또는 작업 설명 (선택)>"
---

# git-commit-merge — Commit + PR + Merge 일괄 진행

---

## Step 1: 브랜치 상태 파악

아래 명령을 **병렬로** 실행하여 현재 상태를 파악한다:

1. `git branch` — 현재 브랜치 확인
2. `git status` — 변경/추가/삭제 파일 확인
3. `git diff --stat` — 변경 규모 확인
4. `git log --oneline -5` — 최근 커밋 스타일 확인
5. `git log --oneline main..HEAD` — main 대비 커밋 수 확인

### 검증 정책

- **main 브랜치에 있으면**: 새 브랜치를 생성해야 한다. 작업 내용에 맞는 브랜치명을 자동 생성한다.
  - 예: `fix/risk-validation-db-mock`, `test/qa-round2-agent3`, `feat/scheduler-retry`
- **변경사항이 없으면**: 커밋할 것이 없다고 알리고 중단한다.
- **src/ 와 test/ 가 섞여 있으면**: 의도된 것인지 변경 내용을 요약하여 사용자에게 확인한다.

---

## Step 2: 변경 내용 분석 + 커밋 메시지 작성

`git diff` (staged + unstaged)를 읽고 변경 내용을 분석한다.

### 커밋 메시지 규칙

- **Conventional Commits** 형식 사용: `type: 한글 제목`
  - `feat:` 새 기능, `fix:` 버그 수정, `test:` 테스트, `refactor:` 리팩토링, `docs:` 문서, `chore:` 기타
- **제목**: 1줄, 무엇을 왜 했는지
- **본문**: 변경 파일/함수 단위로 상세 설명
  - 어떤 파일이 어떻게 바뀌었는지
  - 핵심 기술적 결정이 있으면 이유 포함
  - 테스트 결과 (passed/failed 수)
- **꼬리말**: `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
- HEREDOC 형식으로 커밋 메시지를 전달한다

### 제외 정책

- `.env`, `credentials.json`, `*.pem` 등 secret 파일은 **절대 stage하지 않는다**
- 발견 시 사용자에게 경고하고 해당 파일을 제외한다

---

## Step 3: Commit

1. 변경 파일을 **개별 지정**하여 stage한다 (`git add -A` 금지)
2. 커밋을 실행한다
3. 커밋 후 `git status`로 깨끗한 상태인지 확인한다

### 검증 정책

- 커밋이 실패하면 (pre-commit hook 등) 원인을 파악하고 수정 후 **새 커밋**을 생성한다 (`--amend` 금지)
- 커밋 후 `git log --oneline -1`로 커밋 메시지가 의도대로 작성되었는지 확인한다

---

## Step 4: Push + PR 생성

1. `git push -u origin <branch>` 로 원격에 푸시한다
2. `gh pr create`로 PR을 생성한다

### PR 본문 규칙

```
## Summary
<변경 내용 요약 — 3~5줄 불릿 포인트>

## 변경 파일
<파일별 변경 내용 요약>

## Test plan
<테스트 결과 또는 검증 방법>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### 검증 정책

- push 실패 시 (권한, 충돌 등) 원인을 파악하고 사용자에게 보고한다
- PR 생성 후 URL을 반드시 출력한다

---

## Step 5: Merge

1. `gh pr merge <number> --merge`로 merge한다
2. `git checkout main && git pull`로 main을 최신 상태로 만든다

### 검증 정책

- merge 실패 시 (충돌, CI 실패 등) 원인을 파악하고 사용자에게 보고한다
- merge 후 `git log --oneline -3`으로 merge 커밋이 main에 반영되었는지 확인한다

---

## Step 6: 결과 보고

최종 결과를 간결하게 보고한다:

```
✅ 완료
- Branch: <브랜치명>
- Commit: <커밋 해시> <제목>
- PR: #<번호> → merged
- 변경: <N개 파일>, +<추가>/-<삭제>줄
```

---

## 전체 정책 요약

1. **매 단계마다 검증한다** — 명령 실행 후 결과를 확인하고, 의도대로 되었는지 판단한 뒤 다음 단계로 진행
2. **main 직접 커밋 금지** — 항상 브랜치에서 작업 후 PR로 merge
3. **secret 파일 커밋 금지** — .env, 키 파일 등 자동 감지 및 제외
4. **amend 금지** — 실패 시 새 커밋 생성
5. **강제 push 금지** — `--force` 사용하지 않음
6. **사용자 확인 없이 진행** — 명백한 문제가 없으면 전 과정을 자동으로 완료
7. **문제 발생 시 즉시 보고** — 충돌, 권한 오류, hook 실패 등은 진행을 멈추고 사용자에게 알림
