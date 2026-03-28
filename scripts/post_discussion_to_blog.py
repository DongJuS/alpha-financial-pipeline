#!/usr/bin/env python3
"""
scripts/post_discussion_to_blog.py — 논의 문서 블로그 포스팅 CLI

사용법:
    python scripts/post_discussion_to_blog.py [filename] [--draft] [--dry-run]

예시:
    python scripts/post_discussion_to_blog.py 20260314-searxng-pipeline.md
    python scripts/post_discussion_to_blog.py 20260314-searxng-pipeline.md --draft
    python scripts/post_discussion_to_blog.py 20260314-searxng-pipeline.md --dry-run
    python scripts/post_discussion_to_blog.py  # 목록에서 선택
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.utils.blog_client import get_blog_client  # noqa: E402
from src.utils.discussion_renderer import render_discussion_to_blog_post  # noqa: E402

DISCUSSIONS_DIR = ROOT / ".agent" / "discussions"


def _list_discussions() -> list[Path]:
    """논의 문서 목록을 반환합니다."""
    if not DISCUSSIONS_DIR.exists():
        return []
    return sorted(DISCUSSIONS_DIR.glob("*.md"))


def _select_discussion() -> Path | None:
    """사용자에게 논의 문서를 선택하게 합니다."""
    files = _list_discussions()
    if not files:
        print("논의 문서가 없습니다: .agent/discussions/")
        return None

    print("\n논의 문서 목록:")
    print("-" * 60)
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f.name}")
    print("-" * 60)

    try:
        choice = input("포스팅할 문서 번호를 입력하세요 (q=취소): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice.lower() == "q":
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(files):
            return files[idx]
    except ValueError:
        pass

    print(f"잘못된 입력: {choice}")
    return None


async def _post(file_path: Path, *, is_draft: bool, dry_run: bool) -> None:
    """논의 문서를 블로그에 포스팅합니다."""
    print(f"\n파일: {file_path.name}")

    # 렌더링
    post = render_discussion_to_blog_post(file_path, is_draft=is_draft)
    print(f"제목: {post.title}")
    print(f"라벨: {', '.join(post.labels)}")
    print(f"모드: {'임시글(draft)' if is_draft else '공개'}")

    if dry_run:
        print(f"\n{'='*60}")
        print("[ DRY-RUN ] HTML 미리보기:")
        print(f"{'='*60}")
        print(post.content_html[:2000])
        if len(post.content_html) > 2000:
            print(f"\n... (총 {len(post.content_html)} 글자, 잘림)")
        return

    # 발행
    client = get_blog_client()
    try:
        # 중복 체크: 같은 제목의 글이 있으면 업데이트
        existing_id = await client.find_by_title(post.title)
        if existing_id:
            print(f"기존 글 발견 (ID: {existing_id}) → 업데이트합니다.")
            result = await client.update(existing_id, post)
        else:
            result = await client.publish(post)

        print(f"\n발행 완료!")
        print(f"  Post ID: {result.post_id}")
        print(f"  URL: {result.url}")
        print(f"  발행 시각: {result.published_at}")
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="논의 문서를 Google Blogger에 포스팅")
    parser.add_argument("filename", nargs="?", help="논의 문서 파일명 (.agent/discussions/ 기준)")
    parser.add_argument("--draft", action="store_true", help="임시글로 저장")
    parser.add_argument("--dry-run", action="store_true", help="HTML만 출력하고 발행하지 않음")
    args = parser.parse_args()

    if args.filename:
        file_path = DISCUSSIONS_DIR / args.filename
        if not file_path.exists():
            # 절대 경로나 상대 경로도 시도
            file_path = Path(args.filename)
        if not file_path.exists():
            print(f"파일을 찾을 수 없습니다: {args.filename}")
            sys.exit(1)
    else:
        file_path = _select_discussion()
        if file_path is None:
            sys.exit(0)

    asyncio.run(_post(file_path, is_draft=args.draft, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
