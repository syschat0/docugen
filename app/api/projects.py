from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi import Response

from app.core.config import settings
from app.db.repositories import (
    add_project_references,
    create_project,
    delete_project,
    delete_quality_issue_decision,
    delete_project_reference,
    get_project,
    get_project_quality_summary,
    get_project_settings,
    list_project_references,
    list_projects,
    mark_project_inputs_changed,
    set_quality_issue_decision,
    set_project_settings,
    UnknownQualityIssueError,
    update_project,
)
from app.schemas.projects import (
    ProjectCreate,
    ProjectRead,
    ProjectQualityRead,
    QualityIssueDecisionUpsert,
    ProjectReferenceRead,
    ProjectSettingsRead,
    ProjectSettingsUpdate,
    ProjectUpdate,
    ReferenceUrlsCreate,
)
from app.services.doc_types import get_doc_type_profile
from app.services.search_options import default_search_options
from app.services.references import (
    MAX_FILE_BYTES,
    MAX_REFERENCE_COUNT,
    extract_file_reference,
    fetch_url_reference,
    normalize_reference_urls,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=201)
def create_project_endpoint(payload: ProjectCreate) -> ProjectRead:
    return create_project(payload)


@router.get("", response_model=List[ProjectRead])
def list_projects_endpoint() -> List[ProjectRead]:
    return list_projects()


@router.get("/{project_id}", response_model=ProjectRead)
def get_project_endpoint(project_id: str) -> ProjectRead:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/quality", response_model=ProjectQualityRead)
def get_project_quality_endpoint(project_id: str) -> ProjectQualityRead:
    summary = get_project_quality_summary(project_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectQualityRead(**summary)


@router.put(
    "/{project_id}/quality/issues/{issue_key}", response_model=ProjectQualityRead
)
def set_quality_issue_decision_endpoint(
    project_id: str, issue_key: str, payload: QualityIssueDecisionUpsert
) -> ProjectQualityRead:
    try:
        summary = set_quality_issue_decision(
            project_id, issue_key, payload.decision, payload.reason
        )
    except UnknownQualityIssueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectQualityRead(**summary)


@router.delete(
    "/{project_id}/quality/issues/{issue_key}", response_model=ProjectQualityRead
)
def delete_quality_issue_decision_endpoint(
    project_id: str, issue_key: str
) -> ProjectQualityRead:
    summary = delete_quality_issue_decision(project_id, issue_key)
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectQualityRead(**summary)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project_endpoint(project_id: str, payload: ProjectUpdate) -> ProjectRead:
    if (
        payload.title is None
        and payload.initial_request is None
        and payload.document_type is None
    ):
        raise HTTPException(status_code=422, detail="No fields to update")
    project = update_project(
        project_id, payload.title, payload.initial_request, payload.document_type
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/settings", response_model=ProjectSettingsRead)
def get_project_settings_endpoint(project_id: str) -> ProjectSettingsRead:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    profile = get_doc_type_profile(project.document_type)
    stored = get_project_settings(project_id)
    return ProjectSettingsRead(
        search_enabled=stored.get("search_enabled"),
        section_search_enabled=stored.get("section_search_enabled"),
        citation_style=stored.get("citation_style"),
        target_length=stored.get("target_length"),
        search_engines=stored.get("search_engines"),
        search_headless=stored.get("search_headless"),
        search_stealth=stored.get("search_stealth"),
        search_locale=stored.get("search_locale"),
        search_query_language=stored.get("search_query_language"),
        defaults={
            # "Use default" resolves through the document-type profile, so
            # the UI shows what this project would actually do.
            "search_enabled": settings.search_enabled
            and bool(profile.get("research_default", True)),
            "section_search_enabled": settings.section_search_enabled,
            "citation_style": settings.citation_style,
            "search_engines": list(default_search_options().engines),
            "search_headless": settings.search_headless,
            "search_stealth": settings.search_stealth,
            "search_locale": settings.search_locale,
            "search_query_language": settings.search_query_language,
        },
    )


@router.put("/{project_id}/settings", response_model=ProjectSettingsRead)
def update_project_settings_endpoint(
    project_id: str, payload: ProjectSettingsUpdate
) -> ProjectSettingsRead:
    _require_project(project_id)
    stored = get_project_settings(project_id)
    updated = {
        **stored,
        "search_enabled": payload.search_enabled,
        "section_search_enabled": payload.section_search_enabled,
        "citation_style": payload.citation_style,
        "target_length": payload.target_length,
        "search_engines": payload.search_engines,
        "search_headless": payload.search_headless,
        "search_stealth": payload.search_stealth,
        "search_locale": payload.search_locale,
        "search_query_language": payload.search_query_language,
    }
    # A run-affecting setting changed, so invalidate stale artifacts on next run.
    # citation_style is deliberately excluded: it only changes how the final
    # merge renders citations, so cached section drafts stay valid and a style
    # change just re-merges on the next run. The search knobs change which
    # sources a run finds, so they DO invalidate.
    changed = (
        stored.get("search_enabled") != payload.search_enabled
        or stored.get("section_search_enabled") != payload.section_search_enabled
        or stored.get("target_length") != payload.target_length
        or stored.get("search_engines") != payload.search_engines
        or stored.get("search_headless") != payload.search_headless
        or stored.get("search_stealth") != payload.search_stealth
        or stored.get("search_locale") != payload.search_locale
        or stored.get("search_query_language") != payload.search_query_language
    )
    set_project_settings(project_id, updated)
    if changed:
        mark_project_inputs_changed(project_id)
    return get_project_settings_endpoint(project_id)


@router.delete("/{project_id}", status_code=204)
def delete_project_endpoint(project_id: str) -> Response:
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return Response(status_code=204)


def _require_project(project_id: str) -> None:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


def _require_reference_capacity(project_id: str, incoming: int) -> None:
    existing = len(list_project_references(project_id))
    if existing + incoming > MAX_REFERENCE_COUNT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Reference limit is {MAX_REFERENCE_COUNT} per project "
                f"({existing} already added)"
            ),
        )


@router.get("/{project_id}/references", response_model=List[ProjectReferenceRead])
def list_references_endpoint(project_id: str) -> List[ProjectReferenceRead]:
    _require_project(project_id)
    return list_project_references(project_id)


@router.post(
    "/{project_id}/references/urls",
    response_model=List[ProjectReferenceRead],
    status_code=201,
)
def add_url_references_endpoint(
    project_id: str, payload: ReferenceUrlsCreate
) -> List[ProjectReferenceRead]:
    _require_project(project_id)
    urls = normalize_reference_urls(payload.urls)
    if not urls:
        raise HTTPException(status_code=422, detail="No usable URLs provided")
    _require_reference_capacity(project_id, len(urls))
    entries = [fetch_url_reference(url) for url in urls]
    created = add_project_references(project_id, entries)
    mark_project_inputs_changed(project_id)
    return created


@router.post(
    "/{project_id}/references/files",
    response_model=List[ProjectReferenceRead],
    status_code=201,
)
async def add_file_references_endpoint(
    project_id: str, files: List[UploadFile] = File(...), kind: str = "file"
) -> List[ProjectReferenceRead]:
    _require_project(project_id)
    if kind not in {"file", "style"}:
        raise HTTPException(status_code=422, detail="kind must be 'file' or 'style'")
    _require_reference_capacity(project_id, len(files))
    entries = []
    for upload in files:
        data = await upload.read(MAX_FILE_BYTES + 1)
        entries.append(
            extract_file_reference(upload.filename or "unnamed", data, kind=kind)
        )
    created = add_project_references(project_id, entries)
    mark_project_inputs_changed(project_id)
    return created


@router.delete("/{project_id}/references/{reference_id}", status_code=204)
def delete_reference_endpoint(project_id: str, reference_id: str) -> Response:
    if not delete_project_reference(project_id, reference_id):
        raise HTTPException(status_code=404, detail="Reference not found")
    mark_project_inputs_changed(project_id)
    return Response(status_code=204)
