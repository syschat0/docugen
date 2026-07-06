from app.schemas.artifacts import ArtifactRead
from app.schemas.projects import ProjectRead
from app.services.view_seo import (
    build_description,
    build_document_title,
    markdown_excerpt,
    render_seo_head,
)


def _project() -> ProjectRead:
    return ProjectRead(
        id="p1",
        title="테스트 보고서",
        initial_request="인공지능 문서 자동화에 대한 개요를 작성합니다.",
        status="completed",
        current_phase="draft",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
    )


def _draft() -> ArtifactRead:
    return ArtifactRead(
        id="a1",
        project_id="p1",
        node_id=None,
        type="draft",
        title="Generated draft",
        content={"markdown": "# 서론\n\n본문 내용입니다."},
        file_path=None,
        version=2,
        created_at="2026-01-02T00:00:00Z",
        updated_at="2026-01-02T01:00:00Z",
    )


def test_build_description_uses_markdown_excerpt():
    description = build_description(_project(), _draft(), language="ko")
    assert "테스트 보고서" in description
    assert "서론" in description or "본문" in description


def test_render_seo_head_includes_canonical_and_json_ld():
    html = render_seo_head(
        title=build_document_title(_project(), language="ko"),
        description="요약",
        page_url="http://127.0.0.1:8000/view?project=p1",
        language="ko",
        robots="index, follow",
        json_ld={"@context": "https://schema.org", "@type": "Article"},
    )
    assert 'rel="canonical"' in html
    assert 'property="og:title"' in html
    assert "application/ld+json" in html


def test_markdown_excerpt_strips_heading_markers():
    excerpt = markdown_excerpt("# 제목\n\n본문 텍스트")
    assert "#" not in excerpt
    assert "제목" in excerpt
    assert "본문 텍스트" in excerpt
