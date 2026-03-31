"""
src/utils/discussion_renderer.py — 논의 문서 → 블로그 HTML 변환

.agent/discussions/ 폴더의 마크다운 논의 문서를 읽어
프로젝트 컨텍스트를 포함한 블로그용 HTML로 변환합니다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import markdown

from src.utils.blog_client import BlogPost

# 프로젝트 컨텍스트 (고정)
PROJECT_NAME = "alpha-financial-pipeline"
PROJECT_DESCRIPTION = (
    "한국 KOSPI/KOSDAQ 시장 대상 멀티 에이전트 자동 투자 시스템. "
    "Strategy A(Tournament) / B(Consensus) / RL / S(Search) 4-way 블렌딩."
)

# 마크다운 변환 확장
MD_EXTENSIONS = ["tables", "fenced_code", "codehilite", "toc", "nl2br"]


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """논의 문서 프론트매터를 파싱합니다.

    프론트매터는 첫 번째 `## ` 헤딩 이전의 `key: value` 줄들입니다.
    YAML 펜스(---)가 아닌 bare key-value 형식입니다.

    Returns:
        (frontmatter_dict, body_markdown)
    """
    lines = content.split("\n")
    meta: dict[str, Any] = {}
    body_start = 0
    related_files: list[str] = []
    in_related = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 헤딩 시작 → 본문 시작
        if stripped.startswith("## "):
            body_start = i
            break

        # 제목 줄 (# Discussion Topic Template 등) 스킵
        if stripped.startswith("# ") and not stripped.startswith("## "):
            continue

        # related_files 리스트 항목
        if in_related and stripped.startswith("- "):
            related_files.append(stripped[2:].strip())
            continue
        elif in_related and not stripped.startswith("- "):
            in_related = False

        # key: value 파싱
        match = re.match(r"^(\w[\w_-]*)\s*:\s*(.*)$", stripped)
        if match:
            key, value = match.group(1), match.group(2).strip()
            if key == "related_files":
                in_related = True
                continue
            meta[key] = value

    if related_files:
        meta["related_files"] = related_files

    body = "\n".join(lines[body_start:])
    return meta, body


def _build_context_header(meta: dict[str, Any]) -> str:
    """프로젝트 컨텍스트 HTML 헤더를 생성합니다."""
    status = meta.get("status", "unknown")
    created = meta.get("created_at", "")
    slug = meta.get("topic_slug", "")

    status_color = {
        "open": "#e67e22",
        "closed": "#3498db",
        "complete": "#27ae60",
    }.get(status, "#95a5a6")

    related = meta.get("related_files", [])
    related_html = ""
    if related:
        items = "".join(f"<li><code>{f}</code></li>" for f in related[:10])
        related_html = f"<h4>Related Files</h4><ul>{items}</ul>"

    return f"""
<div style="background:#f8f9fa;border-left:4px solid #3498db;padding:16px;margin-bottom:24px;border-radius:4px;">
  <h3 style="margin:0 0 8px 0;">{PROJECT_NAME}</h3>
  <p style="margin:0 0 8px 0;color:#555;">{PROJECT_DESCRIPTION}</p>
  <p style="margin:0;">
    <span style="background:{status_color};color:white;padding:2px 8px;border-radius:3px;font-size:0.85em;">{status}</span>
    {f'<span style="margin-left:8px;color:#777;">{created}</span>' if created else ''}
    {f'<span style="margin-left:8px;color:#777;">#{slug}</span>' if slug else ''}
  </p>
  {related_html}
</div>
"""


def _generate_labels(meta: dict[str, Any]) -> list[str]:
    """블로그 라벨(태그)을 생성합니다."""
    labels = [PROJECT_NAME]
    if slug := meta.get("topic_slug"):
        labels.append(slug)
    if status := meta.get("status"):
        labels.append(status)
    return labels


def _generate_title(meta: dict[str, Any], file_path: Path) -> str:
    """블로그 글 제목을 생성합니다."""
    slug = meta.get("topic_slug", "")
    created = meta.get("created_at", "")

    if slug:
        # kebab-case → Title Case
        title_part = slug.replace("-", " ").title()
    else:
        # 파일명에서 추출
        title_part = file_path.stem
        # YYYYMMDD- 접두사 제거
        title_part = re.sub(r"^\d{8}-", "", title_part)
        title_part = title_part.replace("-", " ").title()

    prefix = f"[{PROJECT_NAME}]"
    date_part = f" ({created})" if created else ""
    return f"{prefix} {title_part}{date_part}"


def render_discussion_to_blog_post(
    discussion_path: Path,
    *,
    is_draft: bool = False,
) -> BlogPost:
    """논의 문서를 BlogPost 객체로 변환합니다.

    Args:
        discussion_path: 논의 문서 경로 (.agent/discussions/*.md)
        is_draft: True이면 Blogger 임시글로 발행

    Returns:
        BlogPost 인스턴스
    """
    content = discussion_path.read_text(encoding="utf-8")

    # 프론트매터 파싱
    meta, body_md = _parse_frontmatter(content)

    # 마크다운 → HTML 변환
    md_converter = markdown.Markdown(extensions=MD_EXTENSIONS)
    body_html = md_converter.convert(body_md)

    # 컨텍스트 헤더 + 본문 합체
    context_header = _build_context_header(meta)
    full_html = context_header + body_html

    # 제목 및 라벨 생성
    title = _generate_title(meta, discussion_path)
    labels = _generate_labels(meta)

    return BlogPost(
        title=title,
        content_html=full_html,
        labels=labels,
        is_draft=is_draft,
    )
