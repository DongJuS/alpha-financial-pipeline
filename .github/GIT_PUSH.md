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
