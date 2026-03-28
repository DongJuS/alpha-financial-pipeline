#!/bin/bash
# .claude/hooks/post-discussion-to-blog.sh
#
# PostToolUse hook: Write/Edit로 .agent/discussions/*.md 수정 시
# 자동으로 Blogger에 임시글(draft)로 포스팅합니다.
#
# stdin으로 JSON 데이터를 받습니다:
#   { "tool_input": { "file_path": "..." }, "tool_name": "Write|Edit" }

set -euo pipefail

# jq가 없으면 무시
if ! command -v jq &>/dev/null; then
  exit 0
fi

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# file_path가 비어있으면 무시
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# .agent/discussions/*.md 패턴만 처리
if [[ ! "$FILE_PATH" =~ \.agent/discussions/[^/]+\.md$ ]]; then
  exit 0
fi

# 파일이 실제로 존재하는지 확인
if [[ ! -f "$FILE_PATH" ]]; then
  exit 0
fi

FILENAME=$(basename "$FILE_PATH")
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

# 백그라운드로 draft 포스팅 (블로킹 방지)
(
  cd "$PROJECT_DIR"
  python scripts/post_discussion_to_blog.py "$FILENAME" --draft 2>&1 | \
    while IFS= read -r line; do
      echo "[blog-hook] $line" >&2
    done
) &

echo "[blog-hook] Discussion 자동 포스팅 시작 (draft): $FILENAME" >&2
exit 0
