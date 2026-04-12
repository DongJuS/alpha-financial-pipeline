# Git Push Instructions

> **모든 AI 세션에서 `git push`를 수행하기 전에 반드시 아래 절차를 따른다.**

1. `.env` 파일에서 `GITHUB_TOKEN` 값을 읽는다.
2. 아래 Python 스크립트로 remote URL에 토큰을 주입한다:

```python
import subprocess, re
token = None
with open(".env") as f:
    for line in f:
        m = re.match(r"GITHUB_TOKEN=(.+)", line.strip())
        if m:
            token = m.group(1).strip()
if token:
    url = f"https://{token}@github.com/DongJuS/alpha-financial-pipeline.git"
    subprocess.run(["git", "remote", "set-url", "origin", url])
    print("remote URL updated with token")
```

3. push가 완료된 뒤에는 **토큰을 URL에서 제거**하여 `.git/config`에 토큰이 평문으로 남지 않도록 한다:

```python
import subprocess
subprocess.run(["git", "remote", "set-url", "origin",
                "https://github.com/DongJuS/alpha-financial-pipeline.git"])
print("remote URL cleaned")
```

> ⚠️ `GITHUB_TOKEN`은 `.env`에만 보관하고, `.git/config`나 코드에 직접 하드코딩하지 않는다.
> `.env`는 `.gitignore`에 등록되어 있으므로 커밋되지 않는다.

---

## 브랜치 보호 정책

> main 브랜치는 현재 GitHub 레벨 보호가 설정되어 있지 않다. 아래 규칙을 반드시 준수한다.

### 금지 사항

1. **`git push --force origin main` 금지** — main 히스토리가 파괴되면 복구 불가
2. **`git push origin --delete main` 금지** — main 브랜치 삭제 시 전체 파이프라인 중단
3. **main에 직접 push 금지** — 반드시 브랜치 → PR → merge 경로를 사용

### 허용 경로

```
feature 브랜치에서 작업 → git push -u origin <branch> → gh pr create → gh pr merge
```

### 주의가 필요한 명령어

| 명령어 | 위험도 | 설명 |
|--------|--------|------|
| `git push --force` | 🔴 | 원격 히스토리 덮어쓰기. main에 절대 사용 금지 |
| `git push origin --delete <branch>` | 🟡 | 브랜치 삭제. main/develop 대상 금지 |
| `git reset --hard` | 🟡 | 로컬 변경 소실. push 전에만 사용 |
| `git rebase` + force push | 🔴 | 이미 push된 커밋 rebase 후 force push 금지 |

---
