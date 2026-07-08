import html
import json
import re
from typing import Any

from app.schemas.artifacts import ArtifactRead
from app.schemas.projects import ProjectRead

_SITE_NAME = "LLM Document Agent"
_DESCRIPTION_LIMIT = 160


def _strip_markdown(text: str) -> str:
    cleaned = text.replace("\r\n", "\n")
    cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    # Citation links ([[3]](url) or [(site, n.d.)](url)) are noise in a
    # description, so drop them entirely; normal links keep their text.
    cleaned = re.sub(r"\[\[\d+\]\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[\([^()\n]{1,120}\)\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^>\s?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[-*]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\|", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def build_description(
    project: ProjectRead,
    draft: ArtifactRead | None = None,
    *,
    language: str = "ko",
) -> str:
    source = ""
    if draft and isinstance(draft.content, dict):
        markdown = draft.content.get("markdown")
        if isinstance(markdown, str) and markdown.strip():
            source = _strip_markdown(markdown)
    if not source:
        source = _strip_markdown(project.initial_request)

    prefix = project.title.strip()
    if source.lower().startswith(prefix.lower()):
        excerpt = source
    else:
        joiner = " — " if language == "en" else " — "
        excerpt = f"{prefix}{joiner}{source}" if source else prefix

    if len(excerpt) <= _DESCRIPTION_LIMIT:
        return excerpt
    cut = excerpt[: _DESCRIPTION_LIMIT - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return f"{cut}…"


def build_document_title(project: ProjectRead, *, language: str = "ko") -> str:
    suffix = "양식 보기" if language == "ko" else "Document View"
    return f"{project.title.strip()} · {suffix}"


def build_json_ld(
    project: ProjectRead,
    page_url: str,
    draft: ArtifactRead | None = None,
    *,
    description: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": project.title,
        "description": description,
        "url": page_url,
        "datePublished": project.created_at,
        "dateModified": (draft.updated_at if draft else project.updated_at),
        "isPartOf": {
            "@type": "WebSite",
            "name": _SITE_NAME,
            "url": page_url.rsplit("/view", 1)[0] + "/ui/",
        },
        "publisher": {
            "@type": "Organization",
            "name": _SITE_NAME,
        },
    }
    if draft is not None:
        payload["version"] = str(draft.version)
    return payload


def render_seo_head(
    *,
    title: str,
    description: str,
    page_url: str,
    language: str,
    robots: str,
    json_ld: dict[str, Any] | None = None,
) -> str:
    locale = "ko_KR" if language == "ko" else "en_US"
    tags = [
        f'<title>{html.escape(title)}</title>',
        f'<meta name="description" content="{html.escape(description, quote=True)}" />',
        f'<meta name="robots" content="{html.escape(robots, quote=True)}" />',
        f'<link rel="canonical" href="{html.escape(page_url, quote=True)}" />',
        f'<meta property="og:type" content="article" />',
        f'<meta property="og:site_name" content="{html.escape(_SITE_NAME, quote=True)}" />',
        f'<meta property="og:title" content="{html.escape(title, quote=True)}" />',
        f'<meta property="og:description" content="{html.escape(description, quote=True)}" />',
        f'<meta property="og:url" content="{html.escape(page_url, quote=True)}" />',
        f'<meta property="og:locale" content="{locale}" />',
        f'<meta name="twitter:card" content="summary" />',
        f'<meta name="twitter:title" content="{html.escape(title, quote=True)}" />',
        f'<meta name="twitter:description" content="{html.escape(description, quote=True)}" />',
    ]
    if json_ld is not None:
        tags.append(
            '<script type="application/ld+json" data-seo="document">'
            f"{json.dumps(json_ld, ensure_ascii=False)}"
            "</script>"
        )
    return "\n    ".join(tags)


def markdown_excerpt(markdown: str, limit: int = 600) -> str:
    text = _strip_markdown(markdown)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return f"{cut}…"


def render_noscript_article(
    project: ProjectRead,
    description: str,
    body_excerpt: str,
) -> str:
    excerpt = html.escape(body_excerpt or description)
    title = html.escape(project.title)
    return (
        f'<article class="noscript-article"><h1>{title}</h1>'
        f"<p>{excerpt}</p></article>"
    )
