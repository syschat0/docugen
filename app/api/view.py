from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.db.repositories import get_latest_artifact, get_project
from app.services.view_seo import (
    build_description,
    build_document_title,
    build_json_ld,
    markdown_excerpt,
    render_noscript_article,
    render_seo_head,
)

router = APIRouter(tags=["view"])

_VIEW_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "static" / "view" / "index.html"
)


def _view_page_url(request: Request, project_id: str | None) -> str:
    base = str(request.base_url).rstrip("/")
    if not project_id:
        return f"{base}/view"
    return f"{base}/view?project={project_id}"


@router.get("/view", response_class=HTMLResponse, name="view_page")
def view_page_endpoint(
    request: Request,
    project: str | None = Query(default=None, alias="project"),
    lang: str | None = Query(default=None),
) -> HTMLResponse:
    language = "ko" if (lang or "").lower().startswith("ko") else "en"
    template = _VIEW_TEMPLATE.read_text(encoding="utf-8")
    project_id = (project or "").strip() or None

    if project_id is None:
        title = "양식 보기" if language == "ko" else "Document View"
        description = (
            "프로젝트 초안을 A4 양식으로 확인합니다."
            if language == "ko"
            else "Read project drafts in an A4 document layout."
        )
        seo_head = render_seo_head(
            title=title,
            description=description,
            page_url=_view_page_url(request, None),
            language=language,
            robots="noindex, nofollow",
        )
        html = template.replace("<!-- seo-head -->", seo_head)
        html = html.replace("<!-- seo-noscript -->", "")
        html = html.replace('lang="en"', f'lang="{language}"', 1)
        return HTMLResponse(html)

    record = get_project(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")

    draft = get_latest_artifact(project_id, "draft")
    page_url = _view_page_url(request, project_id)
    description = build_description(record, draft, language=language)
    title = build_document_title(record, language=language)
    json_ld = build_json_ld(
        record,
        page_url,
        draft,
        description=description,
    )
    seo_head = render_seo_head(
        title=title,
        description=description,
        page_url=page_url,
        language=language,
        robots="index, follow" if draft else "noindex, nofollow",
        json_ld=json_ld,
    )
    noscript = ""
    if draft and isinstance(draft.content, dict) and draft.content.get("markdown"):
        noscript = render_noscript_article(
            record,
            description,
            markdown_excerpt(str(draft.content.get("markdown", ""))),
        )

    html = template.replace("<!-- seo-head -->", seo_head)
    html = html.replace("<!-- seo-noscript -->", noscript)
    html = html.replace('lang="en"', f'lang="{language}"', 1)
    return HTMLResponse(html)
