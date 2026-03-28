"""test/unit/test_discussion_renderer.py — Discussion 렌더러 유닛 테스트."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.discussion_renderer import (
    _generate_labels,
    _generate_title,
    _parse_frontmatter,
    render_discussion_to_blog_post,
)

# ── 테스트용 픽스처 ─────────────────────────────────────────────────────

SAMPLE_DISCUSSION = """\
# RL Experiment Management

status: closed
created_at: 2026-03-14
topic_slug: rl-experiment-management
owner: agent
related_files:
- src/agents/rl_trading_v2.py
- src/agents/rl_experiment_manager.py

## 1. Question

RL 하이퍼파라미터를 어떻게 관리할 것인가?

## 2. Background

현재 RL 학습 설정이 코드에 하드코딩되어 있어 실험 추적이 어려움.

## 7. Final Decision

파일 기반 프로파일 시스템 도입. `artifacts/rl/profiles/` 경로에 JSON 프로파일 저장.
"""

MINIMAL_DISCUSSION = """\
## 1. Question

간단한 질문
"""


class TestParseFrontmatter:
    def test_full_frontmatter(self) -> None:
        meta, body = _parse_frontmatter(SAMPLE_DISCUSSION)
        assert meta["status"] == "closed"
        assert meta["created_at"] == "2026-03-14"
        assert meta["topic_slug"] == "rl-experiment-management"
        assert meta["owner"] == "agent"
        assert "src/agents/rl_trading_v2.py" in meta["related_files"]
        assert "src/agents/rl_experiment_manager.py" in meta["related_files"]

    def test_body_starts_at_heading(self) -> None:
        _, body = _parse_frontmatter(SAMPLE_DISCUSSION)
        assert body.startswith("## 1. Question")

    def test_minimal_no_frontmatter(self) -> None:
        meta, body = _parse_frontmatter(MINIMAL_DISCUSSION)
        assert meta == {}
        assert "간단한 질문" in body

    def test_empty_content(self) -> None:
        meta, body = _parse_frontmatter("")
        assert meta == {}


class TestGenerateLabels:
    def test_with_slug_and_status(self) -> None:
        labels = _generate_labels({"topic_slug": "my-topic", "status": "closed"})
        assert "agents-investing" in labels
        assert "my-topic" in labels
        assert "closed" in labels

    def test_minimal(self) -> None:
        labels = _generate_labels({})
        assert labels == ["agents-investing"]


class TestGenerateTitle:
    def test_with_slug(self) -> None:
        title = _generate_title(
            {"topic_slug": "rl-experiment-management", "created_at": "2026-03-14"},
            Path("20260314-rl-experiment-management.md"),
        )
        assert "[agents-investing]" in title
        assert "Rl Experiment Management" in title
        assert "(2026-03-14)" in title

    def test_without_slug_uses_filename(self) -> None:
        title = _generate_title({}, Path("20260314-my-topic.md"))
        assert "[agents-investing]" in title
        assert "My Topic" in title

    def test_no_date(self) -> None:
        title = _generate_title({"topic_slug": "test"}, Path("test.md"))
        assert "()" not in title  # 날짜 없으면 괄호도 없어야 함


class TestRenderDiscussionToBlogPost:
    def test_renders_to_blog_post(self, tmp_path: Path) -> None:
        md_file = tmp_path / "20260314-test-topic.md"
        md_file.write_text(SAMPLE_DISCUSSION, encoding="utf-8")

        post = render_discussion_to_blog_post(md_file)
        assert "[agents-investing]" in post.title
        assert "agents-investing" in post.labels
        assert post.is_draft is False

        # HTML 내용 확인
        assert "agents-investing" in post.content_html
        assert "closed" in post.content_html  # status badge
        assert "RL 하이퍼파라미터" in post.content_html

    def test_renders_as_draft(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.write_text(MINIMAL_DISCUSSION, encoding="utf-8")

        post = render_discussion_to_blog_post(md_file, is_draft=True)
        assert post.is_draft is True

    def test_project_context_header(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.write_text(SAMPLE_DISCUSSION, encoding="utf-8")

        post = render_discussion_to_blog_post(md_file)
        # 프로젝트 설명이 포함되어야 함
        assert "KOSPI" in post.content_html or "멀티 에이전트" in post.content_html

    def test_related_files_in_context(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.write_text(SAMPLE_DISCUSSION, encoding="utf-8")

        post = render_discussion_to_blog_post(md_file)
        assert "rl_trading_v2.py" in post.content_html

    def test_code_blocks_preserved(self, tmp_path: Path) -> None:
        content = """\
## 1. Code Example

```python
def hello():
    return "world"
```
"""
        md_file = tmp_path / "test.md"
        md_file.write_text(content, encoding="utf-8")

        post = render_discussion_to_blog_post(md_file)
        assert "<code" in post.content_html or "codehilite" in post.content_html
