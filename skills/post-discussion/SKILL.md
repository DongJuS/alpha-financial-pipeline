---
description: 논의 문서(.agent/discussions/*.md)를 Google Blogger에 포스팅합니다
user_invocable: true
---

# /post-discussion

`.agent/discussions/` 폴더의 논의 문서를 프로젝트 컨텍스트와 함께 Google Blogger에 포스팅합니다.

## 사용법

```
/post-discussion [filename] [--draft] [--dry-run]
```

## 동작

1. `filename`이 주어지면 해당 파일을 사용합니다.
2. 주어지지 않으면 `.agent/discussions/` 폴더의 파일 목록을 보여주고 사용자에게 선택을 요청합니다.
3. 선택된 논의 문서를 프로젝트 컨텍스트(프로젝트명, 설명, 상태, 관련 파일)와 함께 HTML로 변환합니다.
4. Google Blogger API를 통해 포스팅합니다.
5. 동일 제목의 글이 이미 있으면 업데이트합니다.

## 실행 명령

파일명이 주어진 경우:
```bash
python scripts/post_discussion_to_blog.py "$1" $([[ "$*" == *--draft* ]] && echo "--draft") $([[ "$*" == *--dry-run* ]] && echo "--dry-run")
```

파일명이 없는 경우, 사용자에게 `.agent/discussions/` 목록을 보여주고 선택받은 뒤:
```bash
python scripts/post_discussion_to_blog.py "<selected_filename>"
```

## 옵션

- `--draft`: 임시글(비공개)로 저장
- `--dry-run`: HTML만 출력하고 발행하지 않음

## 예시

```
/post-discussion 20260314-searxng-pipeline.md
/post-discussion 20260314-searxng-pipeline.md --draft
/post-discussion --dry-run
/post-discussion
```

## 사전 조건

`.env`에 아래 변수가 설정되어 있어야 합니다:
- `BLOGGER_BLOG_ID`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REFRESH_TOKEN`

초기 설정은 `python scripts/setup_blogger_oauth.py`로 수행합니다.
