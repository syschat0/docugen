import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.db.session import get_connection
from app.core.config import settings
from app.schemas.artifacts import ArtifactCreate, ArtifactRead
from app.schemas.exports import ExportRead
from app.schemas.projects import ProjectCreate, ProjectRead, ProjectReferenceRead
from app.schemas.questions import (
    PendingQuestionCreate,
    PendingQuestionRead,
    QuestionAnswerCreate,
    SectionFeedbackRead,
    UserDecisionRead,
)
from app.schemas.workflow import WorkflowProgressRead, WorkflowRunRead, WorkflowStepRead
from app.services.citations import (
    CITATION_STYLES,
    format_sources_section,
    render_citations,
)
from app.services.llm import (
    LLMError,
    apply_section_revisions,
    collect_leaf_titles,
    expand_chapter_subtree,
    generate_brief,
    generate_outline,
    generate_section_plan,
    best_overlap_score,
    plan_user_questions,
    review_continuity_staged,
    review_outline,
    review_section_plan,
    revise_section_with_feedback,
    revise_targeted_sections,
    select_section_sources,
    smooth_chapter_seams,
    summarize_chapter,
    write_section_with_summary,
)
from app.services.search import (
    build_section_query,
    research_chapters,
    search_section_sources,
    search_web,
    summarize_search_sources,
)
from app.services.run_control import (
    clear_cancel,
    clear_stage_progress,
    get_stage_progress,
    is_cancel_requested,
    set_stage_progress,
)


class QuestionAlreadyAnsweredError(Exception):
    pass


class WorkflowRunFailedError(Exception):
    pass


class WorkflowCancelledError(Exception):
    """Raised inside a run when the user requested cancellation."""
    pass


WORKFLOW_STEPS: list[tuple[str, str]] = [
    ("intake", "Intake questions"),
    ("research", "Web research"),
    ("source_summary", "Source summaries"),
    ("brief", "Brief"),
    ("outline", "Outline"),
    ("outline_review", "Outline review"),
    ("section_plan", "Section plan"),
    ("section_plan_review", "Section plan review"),
    ("chapter_research", "Chapter research"),
    ("section_writing", "Section writing"),
    ("section_summary", "Section summaries"),
    ("feedback_revision", "Feedback revision"),
    ("continuity_review", "Continuity review"),
    ("targeted_revision", "Targeted revision"),
    ("final_merge", "Final merge"),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None) -> Dict[str, Any] | None:
    if value is None:
        return None
    return json.loads(value)


def get_app_setting(key: str) -> Dict[str, Any] | None:
    """Read a JSON-valued app setting, or None if unset."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    return _json_loads(row["value"])


def set_app_setting(key: str, value: Dict[str, Any]) -> None:
    """Upsert a JSON-valued app setting."""
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, _json_dumps(value), now),
        )


# Per-project overrides for run-affecting flags. A value of None means "use the
# global env default"; only keys the user explicitly set are stored.
PROJECT_SETTING_KEYS = ("search_enabled", "section_search_enabled", "citation_style")


def get_project_settings(project_id: str) -> Dict[str, Any]:
    """Stored per-project overrides (empty dict when nothing is set)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM project_settings WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    if row is None:
        return {}
    return _json_loads(row["value"]) or {}


def set_project_settings(project_id: str, value: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert the per-project settings blob and return the stored value."""
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO project_settings (project_id, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET value = excluded.value,
                                                  updated_at = excluded.updated_at
            """,
            (project_id, _json_dumps(value), now),
        )
    return value


def mark_project_inputs_changed(project_id: str) -> None:
    """Bump the input cutoff so the next run regenerates downstream artifacts.

    Editing the request, references, or run settings changes the document's
    inputs. Recording the change time here (and folding it into
    ``_decision_cutoff``) invalidates stale cached artifacts the same way a new
    intake answer does — without deleting anything, so old versions survive.
    """
    current = get_project_settings(project_id)
    current["inputs_changed_at"] = utc_now_iso()
    set_project_settings(project_id, current)


def _override_or_default(project_id: str, key: str, default: bool) -> bool:
    value = get_project_settings(project_id).get(key)
    return default if value is None else bool(value)


def effective_search_enabled(project_id: str) -> bool:
    return _override_or_default(project_id, "search_enabled", settings.search_enabled)


def effective_section_search_enabled(project_id: str) -> bool:
    return _override_or_default(
        project_id, "section_search_enabled", settings.section_search_enabled
    )


def effective_citation_style(project_id: str) -> str:
    """Resolved citation style; unknown stored/env values fall back to numeric."""
    value = get_project_settings(project_id).get("citation_style")
    if value is None:
        value = settings.citation_style
    return value if value in CITATION_STYLES else "numeric"


def _question_text(question_json: str) -> str:
    question = json.loads(question_json)
    if isinstance(question, dict) and isinstance(question.get("question"), str):
        return question["question"]
    return json.dumps(question, ensure_ascii=False)


def create_project(payload: ProjectCreate) -> ProjectRead:
    now = utc_now_iso()
    project_id = str(uuid4())

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO projects (
                id, title, initial_request, status, current_phase, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                payload.title,
                payload.initial_request,
                "created",
                "intake",
                now,
                now,
            ),
        )

    project = get_project(project_id)
    if project is None:
        raise RuntimeError("Project was not persisted")
    return project


def get_project(project_id: str) -> Optional[ProjectRead]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, title, initial_request, status, current_phase, created_at, updated_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()

    if row is None:
        return None
    return ProjectRead(**dict(row))


def update_project(
    project_id: str, title: str | None = None, initial_request: str | None = None
) -> Optional[ProjectRead]:
    """Edit the project's title and/or initial request.

    An edited request changes the document inputs, so the input cutoff is bumped
    to regenerate downstream artifacts on the next run (old versions are kept).
    """
    if get_project(project_id) is None:
        return None

    fields: list[str] = []
    params: list[str] = []
    if title is not None:
        fields.append("title = ?")
        params.append(title)
    request_changed = initial_request is not None
    if request_changed:
        fields.append("initial_request = ?")
        params.append(initial_request)

    now = utc_now_iso()
    if fields:
        fields.append("updated_at = ?")
        params.append(now)
        params.append(project_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(fields)} WHERE id = ?",
                params,
            )
    if request_changed:
        mark_project_inputs_changed(project_id)
    return get_project(project_id)


def list_projects() -> List[ProjectRead]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, initial_request, status, current_phase, created_at, updated_at
            FROM projects
            ORDER BY created_at DESC
            """
        ).fetchall()

    return [ProjectRead(**dict(row)) for row in rows]


def delete_project(project_id: str) -> bool:
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if exists is None:
            return False

        for table in (
            "project_references",
            "project_settings",
            "workflow_threads",
            "pending_questions",
            "user_decisions",
            "artifacts",
            "summaries",
            "agent_runs",
        ):
            conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    return True


def set_project_status(project_id: str, status: str, phase: str | None = None) -> None:
    now = utc_now_iso()
    with get_connection() as conn:
        if phase is None:
            conn.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, project_id),
            )
        else:
            conn.execute(
                "UPDATE projects SET status = ?, current_phase = ?, updated_at = ? WHERE id = ?",
                (status, phase, now, project_id),
            )


def fail_stale_running_projects() -> int:
    # Background runs do not survive a server restart, so any project still
    # marked "running" at startup is stale.
    now = utc_now_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE status = ?",
            ("failed", now, "running"),
        )
        return cursor.rowcount


def create_pending_question(
    project_id: str, payload: PendingQuestionCreate
) -> PendingQuestionRead:
    now = utc_now_iso()
    question_id = str(uuid4())

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pending_questions (
                id, project_id, phase, question_json, status, created_at, answered_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question_id,
                project_id,
                payload.phase,
                _json_dumps(payload.question),
                "pending",
                now,
                None,
            ),
        )

    question = get_pending_question(project_id, question_id)
    if question is None:
        raise RuntimeError("Question was not persisted")
    return question


def _pending_question_from_row(row) -> PendingQuestionRead:
    data = dict(row)
    data["question"] = _json_loads(data.pop("question_json")) or {}
    if "applies_to_json" in data:
        data["applies_to"] = _json_loads(data.pop("applies_to_json"))
    return PendingQuestionRead(**data)


def get_pending_question(
    project_id: str, question_id: str
) -> Optional[PendingQuestionRead]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT pq.id, pq.project_id, pq.phase, pq.question_json, pq.status,
                   pq.created_at, pq.answered_at, ud.answer, ud.applies_to_json
            FROM pending_questions pq
            LEFT JOIN user_decisions ud
              ON ud.project_id = pq.project_id AND ud.question_id = pq.id
            WHERE pq.project_id = ? AND pq.id = ?
            """,
            (project_id, question_id),
        ).fetchone()

    if row is None:
        return None
    return _pending_question_from_row(row)


def list_pending_questions(
    project_id: str, status: str | None = None
) -> List[PendingQuestionRead]:
    params: list[str] = [project_id]
    status_clause = ""
    if status is not None:
        status_clause = "AND pq.status = ?"
        params.append(status)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT pq.id, pq.project_id, pq.phase, pq.question_json, pq.status,
                   pq.created_at, pq.answered_at, ud.answer, ud.applies_to_json
            FROM pending_questions pq
            LEFT JOIN user_decisions ud
              ON ud.project_id = pq.project_id AND ud.question_id = pq.id
            WHERE pq.project_id = ?
            {status_clause}
            ORDER BY pq.created_at DESC
            """,
            params,
        ).fetchall()

    return [_pending_question_from_row(row) for row in rows]


def answer_pending_question(
    project_id: str, question_id: str, payload: QuestionAnswerCreate
) -> Optional[UserDecisionRead]:
    now = utc_now_iso()
    decision_id = str(uuid4())

    with get_connection() as conn:
        question_row = conn.execute(
            """
            SELECT id, project_id, phase, question_json, status
            FROM pending_questions
            WHERE project_id = ? AND id = ?
            """,
            (project_id, question_id),
        ).fetchone()
        if question_row is None:
            return None
        if question_row["status"] != "pending":
            raise QuestionAlreadyAnsweredError()

        conn.execute(
            """
            INSERT INTO user_decisions (
                id, project_id, phase, question_id, question, answer, applies_to_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                project_id,
                question_row["phase"],
                question_id,
                _question_text(question_row["question_json"]),
                payload.answer,
                _json_dumps(payload.applies_to),
                now,
            ),
        )
        conn.execute(
            """
            UPDATE pending_questions
            SET status = ?, answered_at = ?
            WHERE project_id = ? AND id = ?
            """,
            ("answered", now, project_id, question_id),
        )

    decision = get_user_decision(project_id, decision_id)
    if decision is None:
        raise RuntimeError("Decision was not persisted")
    return decision


def get_user_decision(project_id: str, decision_id: str) -> Optional[UserDecisionRead]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, phase, question_id, question, answer, applies_to_json, created_at
            FROM user_decisions
            WHERE project_id = ? AND id = ?
            """,
            (project_id, decision_id),
        ).fetchone()

    if row is None:
        return None
    data = dict(row)
    data["applies_to"] = _json_loads(data.pop("applies_to_json"))
    return UserDecisionRead(**data)


def get_user_decision_by_question(
    project_id: str, question_id: str
) -> Optional[UserDecisionRead]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, phase, question_id, question, answer, applies_to_json, created_at
            FROM user_decisions
            WHERE project_id = ? AND question_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, question_id),
        ).fetchone()

    if row is None:
        return None
    data = dict(row)
    data["applies_to"] = _json_loads(data.pop("applies_to_json"))
    return UserDecisionRead(**data)


def update_question_answer(
    project_id: str, question_id: str, payload: QuestionAnswerCreate
) -> Optional[UserDecisionRead]:
    now = utc_now_iso()
    decision = get_user_decision_by_question(project_id, question_id)
    if decision is None:
        return None

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE user_decisions
            SET answer = ?, applies_to_json = ?, created_at = ?
            WHERE project_id = ? AND question_id = ?
            """,
            (
                payload.answer,
                _json_dumps(payload.applies_to),
                now,
                project_id,
                question_id,
            ),
        )
        conn.execute(
            """
            UPDATE pending_questions
            SET status = ?, answered_at = ?
            WHERE project_id = ? AND id = ?
            """,
            ("answered", now, project_id, question_id),
        )
        conn.execute(
            """
            UPDATE projects
            SET status = ?, current_phase = ?, updated_at = ?
            WHERE id = ?
            """,
            ("created", "intake", now, project_id),
        )

    return get_user_decision_by_question(project_id, question_id)


def delete_question_answer(project_id: str, question_id: str) -> bool:
    now = utc_now_iso()
    decision = get_user_decision_by_question(project_id, question_id)
    if decision is None:
        return False

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM user_decisions
            WHERE project_id = ? AND question_id = ?
            """,
            (project_id, question_id),
        )
        conn.execute(
            """
            UPDATE pending_questions
            SET status = ?, answered_at = ?
            WHERE project_id = ? AND id = ?
            """,
            ("pending", None, project_id, question_id),
        )
        conn.execute(
            """
            UPDATE projects
            SET status = ?, current_phase = ?, updated_at = ?
            WHERE id = ?
            """,
            ("waiting_for_user", "intake", now, project_id),
        )

    return True


def list_user_decisions(project_id: str) -> List[UserDecisionRead]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, phase, question_id, question, answer, applies_to_json, created_at
            FROM user_decisions
            WHERE project_id = ?
            ORDER BY created_at ASC
            """,
            (project_id,),
        ).fetchall()

    decisions: list[UserDecisionRead] = []
    for row in rows:
        data = dict(row)
        data["applies_to"] = _json_loads(data.pop("applies_to_json"))
        decisions.append(UserDecisionRead(**data))
    return decisions


class UnknownSectionError(Exception):
    pass


def add_section_feedback(
    project_id: str, section_id: str, comment: str
) -> Optional[UserDecisionRead]:
    """Store a per-section improvement comment as a section_feedback decision.

    These decisions are excluded from the global input cutoff, so they only
    trigger a rewrite of their target section on the next run instead of
    regenerating the whole document.
    """
    if get_project(project_id) is None:
        return None

    known_ids = {
        str(((draft.content or {}).get("section") or {}).get("id", ""))
        for draft in _latest_artifacts(project_id, "section_draft")
    }
    if section_id not in known_ids:
        raise UnknownSectionError(
            f"No section draft found for section id: {section_id}"
        )

    decision_id = str(uuid4())
    now = utc_now_iso()
    question = f"Improve section {section_id}"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_decisions (
                id, project_id, phase, question_id, question, answer, applies_to_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                project_id,
                "section_feedback",
                None,
                question,
                comment,
                json.dumps({"section_id": section_id}, ensure_ascii=False),
                now,
            ),
        )
    return UserDecisionRead(
        id=decision_id,
        project_id=project_id,
        phase="section_feedback",
        question_id=None,
        question=question,
        answer=comment,
        applies_to={"section_id": section_id},
        created_at=now,
    )


def list_section_feedback(
    project_id: str, section_id: str
) -> Optional[list[SectionFeedbackRead]]:
    """All feedback for one section, oldest first, with its applied state.

    A comment counts as applied once the section's latest draft is newer than
    the comment (the same rule the feedback_revision stage uses).
    """
    if get_project(project_id) is None:
        return None

    draft_time = ""
    for draft in _latest_artifacts(project_id, "section_draft"):
        section = (draft.content or {}).get("section") or {}
        if str(section.get("id", "")) == str(section_id):
            draft_time = draft.updated_at

    return [
        SectionFeedbackRead(
            **decision.model_dump(),
            applied=bool(draft_time and decision.created_at <= draft_time),
        )
        for decision in list_user_decisions(project_id)
        if decision.phase == "section_feedback"
        and str((decision.applies_to or {}).get("section_id", "")) == str(section_id)
    ]


def create_artifact(project_id: str, payload: ArtifactCreate) -> ArtifactRead:
    now = utc_now_iso()
    artifact_id = str(uuid4())

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO artifacts (
                id, project_id, node_id, type, title, content_json,
                file_path, version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                project_id,
                payload.node_id,
                payload.type,
                payload.title,
                _json_dumps(payload.content),
                payload.file_path,
                1,
                now,
                now,
            ),
        )

    artifact = get_artifact(project_id, artifact_id)
    if artifact is None:
        raise RuntimeError("Artifact was not persisted")
    return artifact


def _artifact_from_row(row) -> ArtifactRead:
    data = dict(row)
    data["content"] = _json_loads(data.pop("content_json"))
    return ArtifactRead(**data)


def get_artifact(project_id: str, artifact_id: str) -> Optional[ArtifactRead]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, node_id, type, title, content_json,
                   file_path, version, created_at, updated_at
            FROM artifacts
            WHERE project_id = ? AND id = ?
            """,
            (project_id, artifact_id),
        ).fetchone()

    if row is None:
        return None
    return _artifact_from_row(row)


def list_artifacts(project_id: str) -> List[ArtifactRead]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, node_id, type, title, content_json,
                   file_path, version, created_at, updated_at
            FROM artifacts
            WHERE project_id = ?
            ORDER BY created_at DESC
            """,
            (project_id,),
        ).fetchall()

    return [_artifact_from_row(row) for row in rows]


def _next_artifact_version(conn, project_id: str, artifact_type: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(version), 0) + 1
        FROM artifacts
        WHERE project_id = ? AND type = ?
        """,
        (project_id, artifact_type),
    ).fetchone()
    return int(row[0])


def _insert_artifact(
    conn,
    project_id: str,
    artifact_type: str,
    title: str,
    content: Dict[str, Any],
    now: str,
    node_id: str | None = None,
) -> str:
    artifact_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO artifacts (
            id, project_id, node_id, type, title, content_json,
            file_path, version, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            project_id,
            node_id,
            artifact_type,
            title,
            _json_dumps(content),
            None,
            _next_artifact_version(conn, project_id, artifact_type),
            now,
            now,
        ),
    )
    return artifact_id


_REFERENCE_COLUMNS = (
    "id, project_id, kind, source, title, content_text, status, error, created_at"
)


def add_project_references(
    project_id: str, entries: List[Dict[str, str]]
) -> List[ProjectReferenceRead]:
    now = utc_now_iso()
    created: List[ProjectReferenceRead] = []
    with get_connection() as conn:
        for entry in entries:
            reference_id = str(uuid4())
            conn.execute(
                f"""
                INSERT INTO project_references ({_REFERENCE_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference_id,
                    project_id,
                    entry["kind"],
                    entry["source"],
                    entry.get("title") or None,
                    entry.get("content_text") or None,
                    entry.get("status") or "ready",
                    entry.get("error") or None,
                    now,
                ),
            )
            created.append(
                ProjectReferenceRead(
                    id=reference_id,
                    project_id=project_id,
                    kind=entry["kind"],
                    source=entry["source"],
                    title=entry.get("title") or None,
                    content_text=entry.get("content_text") or None,
                    status=entry.get("status") or "ready",
                    error=entry.get("error") or None,
                    created_at=now,
                )
            )
    return created


def list_project_references(project_id: str) -> List[ProjectReferenceRead]:
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {_REFERENCE_COLUMNS}
            FROM project_references
            WHERE project_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
    return [ProjectReferenceRead(**dict(row)) for row in rows]


def delete_project_reference(project_id: str, reference_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM project_references WHERE id = ? AND project_id = ?",
            (reference_id, project_id),
        )
    return cursor.rowcount > 0


def _reference_url(reference: ProjectReferenceRead) -> str:
    if reference.kind == "url":
        return reference.source
    return f"file://{reference.source}"


def _merge_reference_sources(
    references: List[ProjectReferenceRead],
    research: Dict[str, Any],
    source_summaries: Dict[str, Any],
) -> None:
    """Prepend user-provided references to the research source pool.

    User references outrank web search results, so they lead both the result
    list (brief prompt) and the source summaries (section source selection).
    """
    ready = [
        ref for ref in references
        if ref.status == "ready" and (ref.content_text or "").strip()
    ]
    if not ready:
        return

    results = [item for item in research.get("results") or [] if isinstance(item, dict)]
    summaries = [
        item for item in source_summaries.get("sources") or [] if isinstance(item, dict)
    ]
    result_urls = {item.get("url") for item in results}
    summary_urls = {item.get("url") for item in summaries}

    new_results: List[Dict[str, str]] = []
    new_summaries: List[Dict[str, str]] = []
    for reference in ready:
        url = _reference_url(reference)
        title = (reference.title or "").strip() or reference.source
        content = " ".join((reference.content_text or "").split())
        if url not in result_urls:
            new_results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": content[:300],
                    "query": "user-provided reference",
                }
            )
        if url not in summary_urls:
            new_summaries.append(
                {"title": title, "url": url, "summary": content[:1200], "error": ""}
            )

    research["results"] = new_results + results
    source_summaries["sources"] = new_summaries + summaries


def _insert_pending_question(
    conn,
    project_id: str,
    phase: str,
    question: Dict[str, Any],
    now: str,
) -> str:
    question_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO pending_questions (
            id, project_id, phase, question_json, status, created_at, answered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_id,
            project_id,
            phase,
            _json_dumps(question),
            "pending",
            now,
            None,
        ),
    )
    return question_id


def _make_document_artifacts(project: ProjectRead) -> list[tuple[str, str, Dict[str, Any]]]:
    request = project.initial_request.strip()
    brief = {
        "topic": project.title,
        "goal": request,
        "audience": "general reader",
        "tone": "clear and practical",
        "format": "markdown document",
        "success_criteria": [
            "Cover the user's request directly.",
            "Use a readable structure.",
            "Leave clear places for later revision.",
        ],
    }
    outline = {
        "chapters": [
            {
                "id": "1",
                "title": "Introduction",
                "purpose": "Set context and explain the document goal.",
                "expected_sections": ["Background", "Scope"],
            },
            {
                "id": "2",
                "title": "Main Discussion",
                "purpose": "Develop the core points requested by the user.",
                "expected_sections": ["Key points", "Details", "Examples"],
            },
            {
                "id": "3",
                "title": "Conclusion",
                "purpose": "Summarize the document and suggest next steps.",
                "expected_sections": ["Summary", "Next steps"],
            },
        ]
    }
    markdown = (
        f"# {project.title}\n\n"
        "## Introduction\n\n"
        f"This draft is based on the initial request: {request}\n\n"
        "The goal of this document is to turn that request into a structured, "
        "reviewable first draft. It starts with the main context, then develops "
        "the core discussion, and closes with a concise summary.\n\n"
        "## Main Discussion\n\n"
        "### Key Points\n\n"
        "- Identify the main topic and expected reader.\n"
        "- Organize the content into sections that can be expanded later.\n"
        "- Keep decisions and assumptions visible so the draft can improve over time.\n\n"
        "### Details\n\n"
        "This section is the first generated body draft. It should be treated as a "
        "starting point rather than a final document. Add source material, examples, "
        "and domain-specific details here as the project collects more context.\n\n"
        "### Examples\n\n"
        "Use this area for concrete cases, comparisons, or supporting notes that make "
        "the document easier to understand.\n\n"
        "## Conclusion\n\n"
        "This first draft gives the project a working structure. The next useful step "
        "is to revise the outline, expand each section, and replace assumptions with "
        "confirmed user decisions or source material.\n"
    )
    draft = {
        "format": "markdown",
        "markdown": markdown,
    }

    return [
        ("brief", "Generated brief", brief),
        ("outline", "Generated outline", outline),
        ("draft", "Generated draft", draft),
    ]


def _insert_summary(
    conn,
    project_id: str,
    node_id: str,
    scope: str,
    summary: Dict[str, Any],
    now: str,
) -> str:
    summary_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO summaries (
            id, project_id, node_id, scope, summary_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            summary_id,
            project_id,
            node_id,
            scope,
            _json_dumps(summary),
            now,
            now,
        ),
    )
    return summary_id


def _start_agent_run(
    project_id: str,
    agent_name: str,
    phase: str,
    input_data: Dict[str, Any],
) -> str:
    # Every stage (and every reuse run) starts here, so this is the single
    # choke point where a cancel request aborts the run at a stage boundary.
    if is_cancel_requested(project_id):
        raise WorkflowCancelledError()
    now = utc_now_iso()
    run_id = str(uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO agent_runs (
                id, project_id, agent_name, phase, input_json, output_json,
                status, token_usage_json, error, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                agent_name,
                phase,
                _json_dumps(input_data),
                None,
                "running",
                None,
                None,
                now,
                None,
            ),
        )
        conn.execute(
            """
            UPDATE projects
            SET status = ?, current_phase = ?, updated_at = ?
            WHERE id = ?
            """,
            ("running", phase, now, project_id),
        )
    return run_id


def _complete_agent_run(
    run_id: str,
    output_data: Dict[str, Any],
    status: str = "completed",
    token_usage: Dict[str, Any] | None = None,
) -> None:
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET output_json = ?, status = ?, token_usage_json = ?, completed_at = ?
            WHERE id = ?
            """,
            (_json_dumps(output_data), status, _json_dumps(token_usage), now, run_id),
        )


def _complete_reuse_run(
    project_id: str,
    agent_name: str,
    phase: str,
    output_data: Dict[str, Any],
) -> None:
    run_id = _start_agent_run(
        project_id,
        agent_name,
        phase,
        {"reuse": True},
    )
    _complete_agent_run(run_id, {"reused": True, **output_data})


def _fail_agent_run(run_id: str, error: str) -> None:
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, error = ?, completed_at = ?
            WHERE id = ?
            """,
            ("failed", error, now, run_id),
        )


def _latest_artifact(project_id: str, artifact_type: str) -> Optional[ArtifactRead]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, node_id, type, title, content_json,
                   file_path, version, created_at, updated_at
            FROM artifacts
            WHERE project_id = ? AND type = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, artifact_type),
        ).fetchone()

    if row is None:
        return None
    return _artifact_from_row(row)


def get_latest_artifact(project_id: str, artifact_type: str) -> Optional[ArtifactRead]:
    return _latest_artifact(project_id, artifact_type)


def export_project_markdown(project_id: str) -> Optional[ExportRead]:
    draft = _latest_artifact(project_id, "draft")
    if draft is None or not draft.content:
        return None

    markdown = draft.content.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        return None

    export_path = settings.database_path.parent / "projects" / project_id / "exports" / "final.md"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(markdown, encoding="utf-8")
    return ExportRead(format="markdown", file_path=str(export_path))


def _latest_artifacts(project_id: str, artifact_type: str) -> List[ArtifactRead]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, node_id, type, title, content_json,
                   file_path, version, created_at, updated_at
            FROM artifacts
            WHERE project_id = ? AND type = ?
            ORDER BY created_at ASC
            """,
            (project_id, artifact_type),
        ).fetchall()

    return [_artifact_from_row(row) for row in rows]


def _invalidate_from_phase(project_id: str, phase: str) -> None:
    artifact_types_by_phase = {
        "research": [
            "research_sources",
            "source_summaries",
            "brief",
            "outline",
            "outline_review",
            "section_plan",
            "section_plan_review",
            "chapter_sources",
            "section_draft",
            "draft",
        ],
        "source_summary": [
            "source_summaries",
            "brief",
            "outline",
            "outline_review",
            "section_plan",
            "section_plan_review",
            "chapter_sources",
            "section_draft",
            "draft",
        ],
        "brief": [
            "brief",
            "outline",
            "outline_review",
            "section_plan",
            "section_plan_review",
            "chapter_sources",
            "section_draft",
            "draft",
        ],
        "outline": [
            "outline",
            "outline_review",
            "section_plan",
            "section_plan_review",
            "chapter_sources",
            "section_draft",
            "draft",
        ],
        "outline_review": [
            "outline_review",
            "section_plan",
            "section_plan_review",
            "chapter_sources",
            "section_draft",
            "draft",
        ],
        "section_plan": [
            "section_plan",
            "section_plan_review",
            "chapter_sources",
            "section_draft",
            "draft",
        ],
        "section_plan_review": [
            "section_plan_review",
            "chapter_sources",
            "section_draft",
            "draft",
        ],
        "chapter_research": [
            "chapter_sources",
            "section_draft",
            "draft",
        ],
        "section_writing": ["section_draft", "draft"],
        "section_summary": ["draft"],
        "continuity_review": ["draft"],
        "targeted_revision": ["draft"],
        "final_merge": ["draft"],
    }
    artifact_types = artifact_types_by_phase.get(phase)
    if artifact_types is None:
        return

    # Preserve every prior final draft as version history: a forced rerun only
    # clears intermediate artifacts and then writes a new draft version, so the
    # old one stays browsable in the version list.
    artifact_types = [artifact_type for artifact_type in artifact_types if artifact_type != "draft"]

    run_phases = [item[0] for item in WORKFLOW_STEPS]
    if phase in run_phases:
        run_phases = run_phases[run_phases.index(phase) :]

    with get_connection() as conn:
        placeholders = ",".join("?" for _ in artifact_types)
        conn.execute(
            f"DELETE FROM artifacts WHERE project_id = ? AND type IN ({placeholders})",
            (project_id, *artifact_types),
        )
        if phase in {"section_writing", "section_summary", "continuity_review", "targeted_revision", "final_merge", "section_plan", "section_plan_review"}:
            conn.execute("DELETE FROM summaries WHERE project_id = ?", (project_id,))
        run_placeholders = ",".join("?" for _ in run_phases)
        conn.execute(
            f"DELETE FROM agent_runs WHERE project_id = ? AND phase IN ({run_placeholders})",
            (project_id, *run_phases),
        )


def _reset_agent_runs(project_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM agent_runs WHERE project_id = ?", (project_id,))


def _list_section_summaries(project_id: str) -> list[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT node_id, summary_json
            FROM summaries
            WHERE project_id = ? AND scope = ?
            ORDER BY created_at ASC
            """,
            (project_id, "section"),
        ).fetchall()

    return [_json_loads(row["summary_json"]) or {"section_id": row["node_id"]} for row in rows]


def _list_chapter_digests(project_id: str) -> list[Dict[str, Any]]:
    """Latest chapter digest per chapter, in first-written (chapter) order."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT node_id, summary_json
            FROM summaries
            WHERE project_id = ? AND scope = ?
            ORDER BY created_at ASC
            """,
            (project_id, "chapter"),
        ).fetchall()

    latest_by_chapter: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        digest = _json_loads(row["summary_json"])
        if digest:
            latest_by_chapter[row["node_id"]] = digest
    return list(latest_by_chapter.values())


def _reusable_section_drafts(
    project_id: str,
    sections: list[Dict[str, Any]],
    cutoff: str,
) -> Optional[list[Dict[str, Any]]]:
    drafts = _latest_artifacts(project_id, "section_draft")
    latest_by_section: dict[str, ArtifactRead] = {}
    for draft in drafts:
        content = draft.content or {}
        section = content.get("section") or {}
        section_id = str(section.get("id", ""))
        if not section_id or not _is_fresh(draft.updated_at, cutoff):
            continue
        latest_by_section[section_id] = draft

    reusable: list[Dict[str, Any]] = []
    for section in sections:
        section_id = str(section.get("id", ""))
        draft = latest_by_section.get(section_id)
        if draft is None:
            return None
        content = draft.content or {}
        markdown = content.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            return None
        reusable.append(
            {
                "section": content.get("section") or section,
                "markdown": markdown,
                "sources": content.get("sources") or [],
                "artifact_id": draft.id,
                "updated_at": draft.updated_at,
            }
        )
    return reusable


def _section_feedback_comments(
    feedback_decisions: list[UserDecisionRead], section_id: str
) -> list[str]:
    return [
        decision.answer
        for decision in sorted(feedback_decisions, key=lambda item: item.created_at)
        if str((decision.applies_to or {}).get("section_id", "")) == str(section_id)
    ]


def _pending_section_feedback(
    feedback_decisions: list[UserDecisionRead],
    section_drafts: list[Dict[str, Any]],
) -> Dict[str, list[UserDecisionRead]]:
    """Group feedback newer than the current draft of its target section.

    A feedback decision counts as applied once its section draft was written
    after the feedback arrived (fresh writes receive the comments in their
    prompt; feedback rewrites store a newer draft artifact), so timestamps are
    the only state needed.
    """
    draft_times = {
        str((draft.get("section") or {}).get("id", "")): str(draft.get("updated_at") or "")
        for draft in section_drafts
    }
    pending: Dict[str, list[UserDecisionRead]] = {}
    for decision in feedback_decisions:
        section_id = str((decision.applies_to or {}).get("section_id", ""))
        draft_time = draft_times.get(section_id)
        if draft_time is None or decision.created_at <= draft_time:
            continue
        pending.setdefault(section_id, []).append(decision)
    for items in pending.values():
        items.sort(key=lambda decision: decision.created_at)
    return pending


def _reusable_section_summaries(
    project_id: str,
    sections: list[Dict[str, Any]],
) -> Optional[list[Dict[str, Any]]]:
    summaries = _list_section_summaries(project_id)
    latest_by_section: dict[str, Dict[str, Any]] = {}
    for summary in summaries:
        section_id = str(summary.get("section_id", ""))
        if section_id:
            latest_by_section[section_id] = summary

    reusable: list[Dict[str, Any]] = []
    for section in sections:
        section_id = str(section.get("id", ""))
        summary = latest_by_section.get(section_id)
        if summary is None:
            return None
        reusable.append(summary)
    return reusable


def _is_fresh(updated_at: str, cutoff: str) -> bool:
    return updated_at >= cutoff


def _decision_cutoff(project: ProjectRead, decisions: list[UserDecisionRead]) -> str:
    values = [project.created_at]
    values.extend(decision.created_at for decision in decisions)
    # Editing the request/references/settings records an inputs_changed_at that
    # must also invalidate stale artifacts, just like a new decision does.
    changed_at = get_project_settings(project.id).get("inputs_changed_at")
    if isinstance(changed_at, str) and changed_at:
        values.append(changed_at)
    return max(values)


def _local_brief(
    project: ProjectRead,
    decisions: list[UserDecisionRead],
    research: Dict[str, Any] | None,
) -> Dict[str, Any]:
    decision_text = "; ".join(f"{d.question}: {d.answer}" for d in decisions)
    sources = research.get("results", []) if research else []
    return {
        "topic": project.title,
        "goal": project.initial_request,
        "audience": "general reader",
        "tone": "clear and practical",
        "format": "markdown document",
        "must_include": [decision_text] if decision_text else [],
        "must_avoid": [],
        "source_notes": [
            f"{source.get('title', 'Source')}: {source.get('url', '')}"
            for source in sources
        ],
        "success_criteria": [
            "Use a readable outline.",
            "Write section by section.",
            "Merge sections into a coherent final draft.",
        ],
    }


def _local_outline(project: ProjectRead, brief: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "chapters": [
            {
                "id": "1",
                "title": "Introduction",
                "purpose": "Set context and scope.",
                "expected_sections": ["Background", "Document goal"],
            },
            {
                "id": "2",
                "title": "Main Discussion",
                "purpose": "Develop the core ideas.",
                "expected_sections": ["Key points", "Details"],
            },
            {
                "id": "3",
                "title": "Conclusion",
                "purpose": "Summarize and identify next steps.",
                "expected_sections": ["Summary", "Next steps"],
            },
        ]
    }


def _local_section_plan(outline: Dict[str, Any]) -> Dict[str, Any]:
    outline_tree: list[Dict[str, Any]] = []
    sections: list[Dict[str, Any]] = []
    for chapter in outline.get("chapters", []):
        chapter_id = str(chapter.get("id", len(sections) + 1))
        expected = chapter.get("expected_sections") or [chapter.get("title", "Section")]
        children: list[Dict[str, Any]] = []
        for index, title in enumerate(expected[:2], start=1):
            section = {
                "id": f"{chapter_id}.{index}",
                "parent_id": chapter_id,
                "title": str(title),
                "path": [str(chapter.get("title", f"Chapter {chapter_id}")), str(title)],
                "depth": 3,
                "purpose": str(chapter.get("purpose", "")),
                "key_points": [str(title)],
                "target_length": 400,
                "children": [],
            }
            children.append(section)
            sections.append({key: value for key, value in section.items() if key != "children"})
        outline_tree.append(
            {
                "id": chapter_id,
                "title": str(chapter.get("title", f"Chapter {chapter_id}")),
                "purpose": str(chapter.get("purpose", "")),
                "key_points": [],
                "children": children,
            }
        )
    return {"outline_tree": outline_tree, "sections": sections}


def _section_path_text(section: Dict[str, Any]) -> str:
    path = section.get("path")
    if isinstance(path, list) and path:
        return " > ".join(str(item) for item in path if str(item).strip())
    return str(section.get("title", "Section"))


def _numbered_title(item: Dict[str, Any]) -> str:
    item_id = str(item.get("id") or "").strip()
    title = str(item.get("title") or "Section").strip()
    if item_id and not title.startswith(f"{item_id} "):
        return f"{item_id} {title}"
    return title


def _ensure_markdown_heading_number(markdown: str, section: Dict[str, Any]) -> str:
    section_id = str(section.get("id") or "").strip()
    if not section_id:
        return markdown

    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            marker, _, title = stripped.partition(" ")
            if not title.startswith(f"{section_id} "):
                lines[index] = f"{marker} {section_id} {title}".rstrip()
            return "\n".join(lines)

        depth = min(max(_int_or_default(section.get("depth"), 2), 2), 6)
        heading = f"{'#' * depth} {_numbered_title(section)}"
        return "\n".join([heading, "", markdown])
    return markdown


def _flatten_outline_tree(
    nodes: list[Dict[str, Any]],
    path: list[str] | None = None,
    depth: int = 1,
) -> list[Dict[str, Any]]:
    flattened: list[Dict[str, Any]] = []
    for index, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or index)
        title = str(node.get("title") or f"Section {node_id}")
        current_path = [*(path or []), title]
        children = node.get("children")
        if isinstance(children, list) and children:
            flattened.extend(_flatten_outline_tree(children, current_path, depth + 1))
        else:
            flattened.append(
                {
                    "id": node_id,
                    "parent_id": node.get("parent_id"),
                    "title": title,
                    "path": current_path,
                    "depth": depth + 1,
                    "purpose": str(node.get("purpose", "")),
                    "key_points": node.get("key_points") if isinstance(node.get("key_points"), list) else [],
                    "target_length": node.get("target_length", 500),
                }
            )
    return flattened


def _tree_from_sections(sections: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    root: list[Dict[str, Any]] = []
    node_by_path: dict[str, Dict[str, Any]] = {}
    for section in sections:
        path = section.get("path")
        parts = [str(item) for item in path if str(item).strip()] if isinstance(path, list) else []
        if not parts:
            parts = [str(section.get("title") or section.get("id") or "Section")]
        parent_children = root
        path_key_parts: list[str] = []
        for depth, title in enumerate(parts, start=1):
            path_key_parts.append(title)
            path_key = "\u001f".join(path_key_parts)
            node = node_by_path.get(path_key)
            if node is None:
                is_leaf = depth == len(parts)
                node = {
                    "id": str(section.get("id")) if is_leaf else ".".join(path_key_parts),
                    "title": title,
                    "purpose": str(section.get("purpose", "")) if is_leaf else "",
                    "key_points": section.get("key_points", []) if is_leaf else [],
                    "children": [],
                }
                node_by_path[path_key] = node
                parent_children.append(node)
            parent_children = node.setdefault("children", [])
    return root


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_section_plan(section_plan: Dict[str, Any]) -> Dict[str, Any]:
    outline_tree = section_plan.get("outline_tree")
    sections = section_plan.get("sections")

    if isinstance(outline_tree, dict):
        outline_tree = [outline_tree]
    if not isinstance(outline_tree, list):
        outline_tree = []
    if not isinstance(sections, list):
        sections = []

    if outline_tree and not sections:
        sections = _flatten_outline_tree(outline_tree)
    elif sections and not outline_tree:
        outline_tree = _tree_from_sections(sections)

    normalized_sections: list[Dict[str, Any]] = []
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or index)
        title = str(section.get("title") or f"Section {section_id}")
        path = section.get("path")
        if not isinstance(path, list) or not path:
            path = [title]
        normalized_sections.append(
            {
                "id": section_id,
                "parent_id": section.get("parent_id"),
                "title": title,
                "path": [str(item) for item in path],
                "depth": _int_or_default(section.get("depth"), (len(path) or 1) + 1),
                "purpose": str(section.get("purpose", "")),
                "key_points": section.get("key_points") if isinstance(section.get("key_points"), list) else [],
                "target_length": _int_or_default(section.get("target_length"), 500),
            }
        )

    return {**section_plan, "outline_tree": outline_tree, "sections": normalized_sections}


def _local_section_draft(
    project: ProjectRead,
    section: Dict[str, Any],
    previous_summary: Dict[str, Any] | None,
    sources: list[Dict[str, Any]],
    feedback: list[str] | None = None,
) -> str:
    handoff = previous_summary.get("next_section_handoff") if previous_summary else ""
    source = ""
    if sources:
        source = f"\n\nReference note: see [{1}] {sources[0].get('title', 'source')}."
    feedback_note = ""
    if feedback:
        feedback_lines = "\n".join(f"- {comment}" for comment in feedback)
        feedback_note = f"\n\nUser feedback applied:\n{feedback_lines}"
    depth = min(max(_int_or_default(section.get("depth"), 2), 2), 6)
    heading = "#" * depth
    path = _section_path_text(section)
    return (
        f"{heading} {_numbered_title(section)}\n\n"
        f"Outline path: {path}.\n\n"
        f"This section develops **{section.get('purpose', project.initial_request)}** "
        f"for the document `{project.title}`.\n\n"
        f"Key points: {', '.join(section.get('key_points', []))}.\n\n"
        + (f"Context from the previous section: {handoff}\n" if handoff else "")
        + source
        + feedback_note
    )


def _local_section_summary(section: Dict[str, Any], markdown: str) -> Dict[str, Any]:
    return {
        "section_id": section.get("id", ""),
        "summary": markdown.split("\n\n", 1)[-1][:280],
        "claims": [],
        "terms": [],
        "open_threads": [],
        "next_section_handoff": f"Continue after {section.get('title', 'this section')}.",
    }


def _chapter_titles_from_plan(section_plan: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(chapter.get("id", "")): str(chapter.get("title", ""))
        for chapter in section_plan.get("outline_tree") or []
        if isinstance(chapter, dict)
    }


def _section_title_context(
    section: Dict[str, Any],
    sections: list[Dict[str, Any]],
    chapter_titles: Dict[str, str],
) -> list[str]:
    """Sibling sections in full, other chapters compressed to one title each.

    Distant sections rarely collide with this one, and a long "do not cover"
    list dilutes small-model attention; the hierarchy keeps it short.
    """
    section_id = str(section.get("id", ""))
    chapter_id = section_id.split(".")[0]
    titles: list[str] = []
    listed_chapters: set[str] = set()
    for item in sections:
        item_id = str(item.get("id", ""))
        item_chapter = item_id.split(".")[0]
        if item_chapter == chapter_id:
            if item_id != section_id:
                titles.append(f"{item_id} {item.get('title', '')}".strip())
        elif item_chapter not in listed_chapters:
            listed_chapters.add(item_chapter)
            chapter_title = chapter_titles.get(item_chapter, "")
            titles.append(f"{item_chapter} {chapter_title} (entire chapter)".strip())
    return titles


def _local_chapter_digest(
    chapter_id: str, chapter_title: str, chapter_summaries: list[Dict[str, Any]]
) -> Dict[str, Any]:
    text = " ".join(
        str(summary.get("summary", "")).strip()
        for summary in chapter_summaries
        if str(summary.get("summary", "")).strip()
    )
    return {
        "chapter_id": chapter_id,
        "title": chapter_title,
        "digest": text[:400],
        "claims": [
            claim
            for summary in chapter_summaries
            for claim in (summary.get("claims") or [])
        ][:5],
        "terms": [
            term
            for summary in chapter_summaries
            for term in (summary.get("terms") or [])
        ][:8],
    }


def _build_chapter_digest(
    project: ProjectRead,
    chapter_id: str,
    chapter_title: str,
    chapter_summaries: list[Dict[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    if settings.llm_enabled:
        try:
            return summarize_chapter(
                project, {"id": chapter_id, "title": chapter_title}, chapter_summaries
            )
        except LLMError:
            pass  # the digest is an enhancement; a local concat must not fail the run
    return _local_chapter_digest(chapter_id, chapter_title, chapter_summaries), None


def _local_merge(
    project: ProjectRead,
    section_drafts: list[Dict[str, Any]],
    research: Dict[str, Any] | None,
    section_plan: Dict[str, Any] | None = None,
    used_sources: list[Dict[str, Any]] | None = None,
    citation_style: str = "numeric",
    accessed_at: str | None = None,
) -> str:
    draft_by_id = {
        str((item.get("section") or {}).get("id", "")): _ensure_markdown_heading_number(
            str(item.get("markdown", "")).strip(),
            item.get("section") or {},
        )
        for item in section_drafts
        if str(item.get("markdown", "")).strip()
    }

    def render_node(node: Dict[str, Any], depth: int = 2) -> list[str]:
        node_id = str(node.get("id", ""))
        children = node.get("children") if isinstance(node.get("children"), list) else []
        if node_id in draft_by_id:
            return [draft_by_id[node_id]]
        heading_level = min(max(depth, 2), 6)
        parts = [f"{'#' * heading_level} {_numbered_title(node)}"]
        for child in children:
            if isinstance(child, dict):
                parts.extend(render_node(child, depth + 1))
        return parts

    outline_tree = (section_plan or {}).get("outline_tree")
    if isinstance(outline_tree, list) and outline_tree:
        body_parts: list[str] = []
        for node in outline_tree:
            if isinstance(node, dict):
                body_parts.extend(render_node(node))
        body = "\n\n".join(part for part in body_parts if part.strip())
    else:
        body = "\n\n".join(draft_by_id.values())

    # Number the source list from the sources actually cited inline so [n]
    # markers and the "Sources" entries always agree; fall back to the raw
    # research results only when nothing was cited.
    sources = used_sources or (research.get("results", []) if research else [])
    sources_section = format_sources_section(
        sources, style=citation_style, accessed_at=accessed_at
    )
    return f"# {project.title}\n\n{body}{sources_section}"


def _latest_decision_for_phase(
    project_id: str, phase: str
) -> Optional[UserDecisionRead]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, phase, question_id, question, answer, applies_to_json, created_at
            FROM user_decisions
            WHERE project_id = ? AND phase = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, phase),
        ).fetchone()

    if row is None:
        return None
    data = dict(row)
    data["applies_to"] = _json_loads(data.pop("applies_to_json"))
    return UserDecisionRead(**data)


def _sources_for_section(
    section: Dict[str, Any],
    chapter_sources: Dict[str, Any] | None,
    research: Dict[str, Any] | None,
) -> list[Dict[str, Any]]:
    chapter_id = str(section.get("id", "")).split(".")[0]
    chapter_candidates: list[Dict[str, Any]] = []
    for chapter in (chapter_sources or {}).get("chapters") or []:
        if isinstance(chapter, dict) and str(chapter.get("chapter_id")) == chapter_id:
            chapter_candidates.extend(chapter.get("sources") or [])
    global_summaries = ((research or {}).get("source_summaries") or {}).get("sources") or []
    global_candidates = [source for source in global_summaries if isinstance(source, dict)]
    if not chapter_candidates and not global_candidates:
        global_candidates = [
            result
            for result in (research or {}).get("results") or []
            if isinstance(result, dict)
        ]
    return select_section_sources(section, chapter_candidates, global_candidates, limit=2)


def _reexpand_section_plan(
    project: ProjectRead,
    brief: Dict[str, Any],
    section_plan: Dict[str, Any],
    review: Dict[str, Any],
    nodes_to_expand: list,
) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    outline_tree = section_plan.get("outline_tree") or []
    chapter_ids = {
        str(node).split(".")[0].strip() for node in nodes_to_expand if str(node).strip()
    }
    if not chapter_ids:
        return None, None

    feedback = {
        "issues": review.get("issues", []),
        "recommended_changes": review.get("recommended_changes", []),
    }
    new_tree: list[Dict[str, Any]] = []
    usages: list[Dict[str, Any]] = []
    changed = False
    for chapter in outline_tree:
        if not isinstance(chapter, dict):
            continue
        chapter_id = str(chapter.get("id", ""))
        if chapter_id in chapter_ids:
            other_titles = collect_leaf_titles(
                [c for c in outline_tree if isinstance(c, dict) and str(c.get("id")) != chapter_id]
            )
            try:
                children, usage = expand_chapter_subtree(
                    project, brief, chapter, other_titles, feedback=feedback
                )
            except LLMError:
                # Applying the review is best-effort; keep the original chapter.
                new_tree.append(chapter)
                continue
            chapter = {**chapter, "children": children}
            changed = True
            if usage is not None:
                usages.append({"chapter_id": chapter_id, **usage})
        new_tree.append(chapter)

    if not changed:
        return None, None
    return {"outline_tree": new_tree}, {"chapter_calls": usages} if usages else None


def _draft_conditions(project_id: str) -> Dict[str, Any]:
    """Snapshot the generation conditions recorded on each draft version.

    Stored on the draft so the version history can show what changed between
    runs (search on/off, how many references, which model)."""
    references = list_project_references(project_id)
    try:
        from app.services.llm_settings import get_active_llm_config

        model = get_active_llm_config().get("model") or settings.llm_model
    except Exception:
        model = settings.llm_model
    return {
        "search_enabled": effective_search_enabled(project_id),
        "section_search_enabled": effective_section_search_enabled(project_id),
        "citation_style": effective_citation_style(project_id),
        "reference_count": len(references),
        "reference_titles": [(ref.title or ref.source) for ref in references[:8]],
        "model": model,
    }


def restore_draft_version(project_id: str, artifact_id: str) -> Optional[ArtifactRead]:
    """Clone an older draft into a new (latest) draft version, non-destructively.

    The chosen version's content is copied into a fresh draft artifact so it
    becomes the current document while every other version stays intact.
    """
    source = get_artifact(project_id, artifact_id)
    if source is None or source.type != "draft":
        return None
    content = dict(source.content or {})
    content["restored_from"] = source.version
    now = utc_now_iso()
    with get_connection() as conn:
        new_id = _insert_artifact(
            conn,
            project_id,
            "draft",
            source.title or "Restored draft",
            content,
            now,
            source.node_id,
        )
    return get_artifact(project_id, new_id)


def run_document_generation(
    project_id: str, force_from: str | None = None
) -> Optional[WorkflowRunRead]:
    project = get_project(project_id)
    if project is None:
        return None

    # Drop any stale control state from a previous aborted attempt so this run
    # is not cancelled before it starts.
    clear_cancel(project_id)
    clear_stage_progress(project_id)

    if force_from:
        _invalidate_from_phase(project_id, force_from)
        project = get_project(project_id)
        if project is None:
            return None
    else:
        _reset_agent_runs(project_id)

    existing_pending = list_pending_questions(project_id, status="pending")
    if existing_pending:
        waiting_at = utc_now_iso()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE projects
                SET status = ?, current_phase = ?, updated_at = ?
                WHERE id = ?
                """,
                ("waiting_for_user", existing_pending[0].phase, waiting_at, project_id),
            )
        updated_project = get_project(project_id)
        if updated_project is None:
            raise RuntimeError("Project disappeared while waiting for user")
        return WorkflowRunRead(
            project=updated_project,
            artifacts=[],
            pending_questions=existing_pending,
            status="waiting_for_user",
            message="Answer the pending questions, then start writing again.",
        )

    agent_name = "llm_pipeline_writer" if settings.llm_enabled else "local_pipeline_writer"
    # Outline-approval answers are process control, not document content:
    # they must not feed prompts or invalidate cached artifacts. Section
    # feedback is applied per-section in the feedback_revision stage, so it
    # must not invalidate the whole pipeline either.
    all_decisions = list_user_decisions(project_id)
    decisions = [
        decision
        for decision in all_decisions
        if decision.phase not in {"outline_approval", "section_feedback"}
    ]
    feedback_decisions = [
        decision for decision in all_decisions if decision.phase == "section_feedback"
    ]
    input_cutoff = _decision_cutoff(project, decisions)
    artifact_ids: list[str] = []

    def fail(run_id: str, phase: str, exc: Exception) -> None:
        failed_at = utc_now_iso()
        _fail_agent_run(run_id, str(exc))
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE projects
                SET status = ?, current_phase = ?, updated_at = ?
                WHERE id = ?
                """,
                ("failed", phase, failed_at, project_id),
            )

    if settings.llm_enabled and not decisions:
        run_id = _start_agent_run(
            project_id,
            agent_name,
            "intake",
            {"title": project.title, "initial_request": project.initial_request},
        )
        try:
            planned_questions, question_usage = plan_user_questions(project, decisions)
        except LLMError as exc:
            fail(run_id, "intake", exc)
            raise WorkflowRunFailedError(str(exc)) from exc

        if planned_questions:
            question_ids: list[str] = []
            waiting_at = utc_now_iso()
            with get_connection() as conn:
                for planned in planned_questions:
                    question_payload = {
                        "question": planned["question"],
                        "reason": planned.get("reason", ""),
                        "priority": planned.get("priority", "medium"),
                    }
                    question_ids.append(
                        _insert_pending_question(
                            conn,
                            project_id,
                            planned.get("phase", "intake"),
                            question_payload,
                            waiting_at,
                        )
                    )
                conn.execute(
                    """
                    UPDATE projects
                    SET status = ?, current_phase = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        "waiting_for_user",
                        planned_questions[0].get("phase", "intake"),
                        waiting_at,
                        project_id,
                    ),
                )
            _complete_agent_run(
                run_id,
                {
                    "pending_question_ids": question_ids,
                    "pending_questions": planned_questions,
                },
                status="waiting_for_user",
                token_usage=question_usage,
            )
            updated_project = get_project(project_id)
            if updated_project is None:
                raise RuntimeError("Project disappeared while creating questions")
            return WorkflowRunRead(
                project=updated_project,
                artifacts=[],
                pending_questions=list_pending_questions(project_id, status="pending"),
                status="waiting_for_user",
                message="The writer needs a few answers before drafting.",
            )

        _complete_agent_run(
            run_id,
            {"pending_questions": []},
            status="completed",
            token_usage=question_usage,
        )
    else:
        run_id = _start_agent_run(
            project_id,
            agent_name,
            "intake",
            {"decision_count": len(decisions), "llm_enabled": settings.llm_enabled},
        )
        _complete_agent_run(run_id, {"skipped_question_planning": True})

    try:
        research_artifact = _latest_artifact(project_id, "research_sources")
        if research_artifact is not None and _is_fresh(
            research_artifact.updated_at, input_cutoff
        ):
            research = research_artifact.content or {}
            artifact_ids.append(research_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "research",
                {
                    "artifact_id": research_artifact.id,
                    "source_count": len(research.get("results", [])),
                },
            )
            research_cutoff = research_artifact.updated_at
        else:
            run_id = _start_agent_run(project_id, agent_name, "research", {})
            research = search_web(project, decisions)
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "research_sources",
                        "Web research sources",
                        research,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            research_artifact = get_artifact(project_id, artifact_ids[-1])
            research_cutoff = research_artifact.updated_at if research_artifact else utc_now_iso()
            _complete_agent_run(
                run_id,
                {
                    "artifact_id": artifact_ids[-1],
                    "source_count": len(research.get("results", [])),
                    "error": research.get("error"),
                },
            )

        source_summary_artifact = _latest_artifact(project_id, "source_summaries")
        if source_summary_artifact is not None and _is_fresh(
            source_summary_artifact.updated_at, research_cutoff
        ):
            source_summaries = source_summary_artifact.content or {}
            artifact_ids.append(source_summary_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "source_summary",
                {
                    "artifact_id": source_summary_artifact.id,
                    "source_count": len(source_summaries.get("sources", [])),
                },
            )
            source_summary_time = source_summary_artifact.updated_at
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "source_summary",
                {"source_count": len(research.get("results", []))},
            )
            source_summaries = summarize_search_sources(research)
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "source_summaries",
                        "Source summaries",
                        source_summaries,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            source_summary_artifact = get_artifact(project_id, artifact_ids[-1])
            source_summary_time = (
                source_summary_artifact.updated_at
                if source_summary_artifact
                else utc_now_iso()
            )
            _complete_agent_run(
                run_id,
                {
                    "artifact_id": artifact_ids[-1],
                    "source_count": len(source_summaries.get("sources", [])),
                },
            )
        _merge_reference_sources(
            list_project_references(project_id), research, source_summaries
        )
        research["source_summaries"] = source_summaries

        brief_artifact = _latest_artifact(project_id, "brief")
        brief_cutoff = max(input_cutoff, research_cutoff, source_summary_time)
        if brief_artifact is not None and _is_fresh(brief_artifact.updated_at, brief_cutoff):
            brief = brief_artifact.content or {}
            artifact_ids.append(brief_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "brief",
                {"artifact_id": brief_artifact.id},
            )
            brief_time = brief_artifact.updated_at
        else:
            run_id = _start_agent_run(project_id, agent_name, "brief", {})
            if settings.llm_enabled:
                brief, usage = generate_brief(project, decisions, research)
            else:
                brief, usage = _local_brief(project, decisions, research), None
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn, project_id, "brief", "Generated brief", brief, utc_now_iso(), agent_name
                    )
                )
            brief_artifact = get_artifact(project_id, artifact_ids[-1])
            brief_time = brief_artifact.updated_at if brief_artifact else utc_now_iso()
            _complete_agent_run(run_id, {"artifact_id": artifact_ids[-1]}, token_usage=usage)

        outline_artifact = _latest_artifact(project_id, "outline")
        if outline_artifact is not None and _is_fresh(
            outline_artifact.updated_at, brief_time
        ):
            outline = outline_artifact.content or {}
            artifact_ids.append(outline_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "outline",
                {"artifact_id": outline_artifact.id},
            )
            outline_time = outline_artifact.updated_at
        else:
            run_id = _start_agent_run(project_id, agent_name, "outline", {"brief": brief})
            if settings.llm_enabled:
                outline, usage = generate_outline(project, brief)
            else:
                outline, usage = _local_outline(project, brief), None
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "outline",
                        "Generated outline",
                        outline,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            outline_artifact = get_artifact(project_id, artifact_ids[-1])
            outline_time = outline_artifact.updated_at if outline_artifact else utc_now_iso()
            _complete_agent_run(run_id, {"artifact_id": artifact_ids[-1]}, token_usage=usage)

        outline_review_artifact = _latest_artifact(project_id, "outline_review")
        if outline_review_artifact is not None and _is_fresh(
            outline_review_artifact.updated_at, outline_time
        ):
            outline_review = outline_review_artifact.content or {}
            artifact_ids.append(outline_review_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "outline_review",
                {"artifact_id": outline_review_artifact.id},
            )
            outline_review_time = outline_review_artifact.updated_at
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "outline_review",
                {"outline": outline},
            )
            if settings.llm_enabled:
                outline_review, usage = review_outline(project, brief, outline)
            else:
                outline_review, usage = {
                    "verdict": "pass",
                    "issues": [],
                    "recommended_changes": [],
                    "notes": "Local fallback review passed.",
                }, None

            # Apply the reviewer's corrected outline so the review actually
            # shapes the document instead of only being recorded.
            revised_outline = outline_review.get("revised_outline")
            revision_applied = False
            if (
                settings.llm_enabled
                and isinstance(revised_outline, dict)
                and isinstance(revised_outline.get("chapters"), list)
                and revised_outline["chapters"]
            ):
                outline = revised_outline
                revision_applied = True
                with get_connection() as conn:
                    artifact_ids.append(
                        _insert_artifact(
                            conn,
                            project_id,
                            "outline",
                            "Revised outline",
                            outline,
                            utc_now_iso(),
                            agent_name,
                        )
                    )
            review_record = {
                key: value
                for key, value in outline_review.items()
                if key != "revised_outline"
            }
            review_record["revision_applied"] = revision_applied
            # Inserted after any revised outline so freshness ordering holds.
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "outline_review",
                        "Outline review",
                        review_record,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            outline_review_artifact = get_artifact(project_id, artifact_ids[-1])
            outline_review_time = (
                outline_review_artifact.updated_at
                if outline_review_artifact
                else utc_now_iso()
            )
            _complete_agent_run(
                run_id,
                {
                    "artifact_id": artifact_ids[-1],
                    "verdict": outline_review.get("verdict"),
                    "revision_applied": revision_applied,
                },
                token_usage=usage,
            )

        if settings.require_outline_approval:
            approval = _latest_decision_for_phase(project_id, "outline_approval")
            if approval is None or approval.created_at < outline_review_time:
                waiting_at = utc_now_iso()
                chapter_lines = "\n".join(
                    f"{chapter.get('id', '')}. {chapter.get('title', '')}"
                    for chapter in outline.get("chapters", [])
                    if isinstance(chapter, dict)
                )
                question_payload = {
                    "question": (
                        "생성된 목차를 검토해 주세요. 이대로 작성을 진행하려면 답변을 남긴 뒤 "
                        "다시 '작성 시작'을 눌러 주세요. (Review the outline below and answer "
                        "to approve, then start writing again.)\n" + chapter_lines
                    ),
                    "reason": "Outline approval gate before section writing.",
                    "priority": "high",
                }
                with get_connection() as conn:
                    _insert_pending_question(
                        conn, project_id, "outline_approval", question_payload, waiting_at
                    )
                    conn.execute(
                        """
                        UPDATE projects
                        SET status = ?, current_phase = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        ("waiting_for_user", "outline", waiting_at, project_id),
                    )
                updated_project = get_project(project_id)
                if updated_project is None:
                    raise RuntimeError("Project disappeared while waiting for outline approval")
                return WorkflowRunRead(
                    project=updated_project,
                    artifacts=[],
                    pending_questions=list_pending_questions(project_id, status="pending"),
                    status="waiting_for_user",
                    message="Review and approve the outline, then start writing again.",
                )

        section_plan_artifact = _latest_artifact(project_id, "section_plan")
        if section_plan_artifact is not None and _is_fresh(
            section_plan_artifact.updated_at, outline_review_time
        ):
            section_plan = section_plan_artifact.content or {}
            section_plan = _normalize_section_plan(section_plan)
            sections = section_plan.get("sections", [])
            artifact_ids.append(section_plan_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "section_plan",
                {
                    "artifact_id": section_plan_artifact.id,
                    "section_count": len(sections),
                },
            )
            section_plan_time = section_plan_artifact.updated_at
        else:
            run_id = _start_agent_run(
                project_id, agent_name, "section_plan", {"outline": outline}
            )
            if settings.llm_enabled:
                section_plan, usage = generate_section_plan(
                    project, brief, outline, research
                )
            else:
                section_plan, usage = _local_section_plan(outline), None
            section_plan = _normalize_section_plan(section_plan)
            sections = section_plan["sections"]
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "section_plan",
                        "Generated section plan",
                        section_plan,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            section_plan_artifact = get_artifact(project_id, artifact_ids[-1])
            section_plan_time = section_plan_artifact.updated_at if section_plan_artifact else utc_now_iso()
            _complete_agent_run(
                run_id,
                {"artifact_id": artifact_ids[-1], "section_count": len(sections)},
                token_usage=usage,
            )

        section_plan_review_artifact = _latest_artifact(project_id, "section_plan_review")
        if section_plan_review_artifact is not None and _is_fresh(
            section_plan_review_artifact.updated_at, section_plan_time
        ):
            section_plan_review = section_plan_review_artifact.content or {}
            artifact_ids.append(section_plan_review_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "section_plan_review",
                {"artifact_id": section_plan_review_artifact.id},
            )
            section_plan_review_time = section_plan_review_artifact.updated_at
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "section_plan_review",
                {"section_count": len(sections)},
            )
            if settings.llm_enabled:
                section_plan_review, usage = review_section_plan(
                    project, brief, section_plan
                )
            else:
                section_plan_review, usage = {
                    "verdict": "pass",
                    "issues": [],
                    "recommended_changes": [],
                    "notes": "Local fallback review passed.",
                }, None

            # Re-expand chapters the reviewer flagged so the review is applied.
            revision_applied = False
            nodes_to_expand = section_plan_review.get("nodes_to_expand")
            if settings.llm_enabled and isinstance(nodes_to_expand, list) and nodes_to_expand:
                revised_plan, revise_usage = _reexpand_section_plan(
                    project, brief, section_plan, section_plan_review, nodes_to_expand
                )
                if revised_plan is not None:
                    section_plan = _normalize_section_plan(revised_plan)
                    sections = section_plan["sections"]
                    revision_applied = True
                    if revise_usage and usage:
                        usage = {"review": usage, "reexpand": revise_usage}
                    elif revise_usage:
                        usage = {"reexpand": revise_usage}
                    with get_connection() as conn:
                        artifact_ids.append(
                            _insert_artifact(
                                conn,
                                project_id,
                                "section_plan",
                                "Revised section plan",
                                section_plan,
                                utc_now_iso(),
                                agent_name,
                            )
                        )
            section_plan_review = {**section_plan_review, "revision_applied": revision_applied}
            # Inserted after any revised plan so freshness ordering holds.
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "section_plan_review",
                        "Section plan review",
                        section_plan_review,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            section_plan_review_artifact = get_artifact(project_id, artifact_ids[-1])
            section_plan_review_time = (
                section_plan_review_artifact.updated_at
                if section_plan_review_artifact
                else utc_now_iso()
            )
            _complete_agent_run(
                run_id,
                {
                    "artifact_id": artifact_ids[-1],
                    "verdict": section_plan_review.get("verdict"),
                    "revision_applied": revision_applied,
                },
                token_usage=usage,
            )

        chapter_sources_artifact = _latest_artifact(project_id, "chapter_sources")
        if chapter_sources_artifact is not None and _is_fresh(
            chapter_sources_artifact.updated_at, section_plan_review_time
        ):
            chapter_sources = chapter_sources_artifact.content or {}
            artifact_ids.append(chapter_sources_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "chapter_research",
                {
                    "artifact_id": chapter_sources_artifact.id,
                    "chapter_count": len(chapter_sources.get("chapters", [])),
                },
            )
            chapter_research_time = chapter_sources_artifact.updated_at
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "chapter_research",
                {"chapter_count": len(section_plan.get("outline_tree") or [])},
            )
            chapter_sources = research_chapters(project, section_plan)
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "chapter_sources",
                        "Chapter research sources",
                        chapter_sources,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            chapter_sources_artifact = get_artifact(project_id, artifact_ids[-1])
            chapter_research_time = (
                chapter_sources_artifact.updated_at
                if chapter_sources_artifact
                else utc_now_iso()
            )
            _complete_agent_run(
                run_id,
                {
                    "artifact_id": artifact_ids[-1],
                    "chapter_count": len(chapter_sources.get("chapters", [])),
                    "source_count": sum(
                        len(chapter.get("sources") or [])
                        for chapter in chapter_sources.get("chapters", [])
                    ),
                    "error": chapter_sources.get("error"),
                },
            )

        section_drafts: list[Dict[str, Any]] = []
        summaries: list[Dict[str, Any]] = []
        summary_ids: list[str] = []
        previous_summary: Dict[str, Any] | None = None
        writing_usage: list[Dict[str, Any]] = []
        reusable_drafts = _reusable_section_drafts(
            project_id,
            sections,
            chapter_research_time,
        )
        reusable_summaries = _reusable_section_summaries(project_id, sections)
        if reusable_drafts is not None and reusable_summaries is not None:
            section_drafts = reusable_drafts
            summaries = reusable_summaries
            section_draft_ids = [
                draft["artifact_id"] for draft in reusable_drafts if draft.get("artifact_id")
            ]
            artifact_ids.extend(section_draft_ids)
            _complete_reuse_run(
                project_id,
                agent_name,
                "section_writing",
                {
                    "section_artifact_ids": section_draft_ids,
                    "summary_mode": "combined_with_writing",
                },
            )
            _complete_reuse_run(
                project_id,
                agent_name,
                "section_summary",
                {
                    "summary_count": len(summaries),
                    "summary_mode": "combined_with_writing",
                },
            )
            section_work_time = max(
                [draft["updated_at"] for draft in reusable_drafts if draft.get("updated_at")]
                or [section_plan_time]
            )
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "section_writing",
                {"section_count": len(sections)},
            )
            chapter_titles = _chapter_titles_from_plan(section_plan)
            topup_info: list[Dict[str, Any]] = []
            chapter_digests: list[Dict[str, Any]] = []
            digest_usage: list[Dict[str, Any]] = []
            glossary_counts: dict[str, int] = {}
            current_chapter_id: str | None = None
            chapter_summaries: list[Dict[str, Any]] = []
            sections_done = 0
            set_stage_progress(project_id, "section_writing", 0, len(sections))
            for section in sections:
                # Section writing is the longest phase; check cancel and publish
                # "n of N" sub-progress on every section, not just at boundaries.
                if is_cancel_requested(project_id):
                    raise WorkflowCancelledError()
                set_stage_progress(project_id, "section_writing", sections_done, len(sections))
                section_chapter = str(section.get("id", "")).split(".")[0]
                if (
                    current_chapter_id is not None
                    and section_chapter != current_chapter_id
                    and chapter_summaries
                ):
                    # Chapter boundary: compress the finished chapter into a
                    # digest so later sections remember it without carrying
                    # the full summary chain.
                    digest, usage = _build_chapter_digest(
                        project,
                        current_chapter_id,
                        chapter_titles.get(current_chapter_id, ""),
                        chapter_summaries,
                    )
                    chapter_digests.append(digest)
                    if usage is not None:
                        digest_usage.append({"chapter_id": current_chapter_id, **usage})
                    with get_connection() as conn:
                        _insert_summary(
                            conn,
                            project_id,
                            current_chapter_id,
                            "chapter",
                            digest,
                            utc_now_iso(),
                        )
                    chapter_summaries = []
                current_chapter_id = section_chapter
                section_sources = _sources_for_section(section, chapter_sources, research)
                # Top-up search: when nothing in the research pool matches this
                # section, one extra targeted search beats writing sourceless.
                if (
                    effective_section_search_enabled(project_id)
                    and effective_search_enabled(project_id)
                    and len(topup_info) < settings.section_search_topup_limit
                    and best_overlap_score(section, section_sources) == 0
                ):
                    extra_sources, topup_error = search_section_sources(
                        section, settings.chapter_search_results
                    )
                    topup_info.append(
                        {
                            "section_id": str(section.get("id", "")),
                            "query": build_section_query(section),
                            "source_count": len(extra_sources),
                            "error": topup_error,
                        }
                    )
                    if extra_sources:
                        section_sources = extra_sources
                section_feedback = _section_feedback_comments(
                    feedback_decisions, str(section.get("id", ""))
                )
                glossary = [
                    term
                    for term, _count in sorted(
                        glossary_counts.items(), key=lambda item: -item[1]
                    )[:15]
                ]
                if settings.llm_enabled:
                    markdown, summary, usage = write_section_with_summary(
                        project,
                        brief,
                        section,
                        previous_summary,
                        section_sources,
                        _section_title_context(section, sections, chapter_titles),
                        feedback=section_feedback,
                        chapter_digests=chapter_digests,
                        glossary=glossary,
                    )
                else:
                    markdown, usage = _local_section_draft(
                        project, section, previous_summary, section_sources, section_feedback
                    ), None
                    summary = _local_section_summary(section, markdown)
                if usage is not None:
                    writing_usage.append(usage)
                markdown = _ensure_markdown_heading_number(markdown, section)
                draft_content = {
                    "section": section,
                    "markdown": markdown,
                    "sources": section_sources,
                }
                with get_connection() as conn:
                    artifact_ids.append(
                        _insert_artifact(
                            conn,
                            project_id,
                            "section_draft",
                            f"Section {section.get('id', '')}: {section.get('title', '')}",
                            draft_content,
                            utc_now_iso(),
                            agent_name,
                        )
                    )
                    summary_ids.append(
                        _insert_summary(
                            conn,
                            project_id,
                            str(section.get("id", "")),
                            "section",
                            summary,
                            utc_now_iso(),
                        )
                    )
                draft_artifact = get_artifact(project_id, artifact_ids[-1])
                section_drafts.append(
                    {
                        "section": section,
                        "markdown": markdown,
                        "sources": section_sources,
                        "artifact_id": artifact_ids[-1],
                        "updated_at": draft_artifact.updated_at if draft_artifact else utc_now_iso(),
                    }
                )
                summaries.append(summary)
                previous_summary = summary
                chapter_summaries.append(summary)
                for term in summary.get("terms") or []:
                    term_text = str(term).strip()
                    if term_text:
                        glossary_counts[term_text] = glossary_counts.get(term_text, 0) + 1
                sections_done += 1
                set_stage_progress(project_id, "section_writing", sections_done, len(sections))
            if current_chapter_id is not None and chapter_summaries:
                digest, usage = _build_chapter_digest(
                    project,
                    current_chapter_id,
                    chapter_titles.get(current_chapter_id, ""),
                    chapter_summaries,
                )
                chapter_digests.append(digest)
                if usage is not None:
                    digest_usage.append({"chapter_id": current_chapter_id, **usage})
                with get_connection() as conn:
                    _insert_summary(
                        conn,
                        project_id,
                        current_chapter_id,
                        "chapter",
                        digest,
                        utc_now_iso(),
                    )
            token_usage: Dict[str, Any] = {}
            if writing_usage:
                token_usage["section_calls"] = writing_usage
            if digest_usage:
                token_usage["digest_calls"] = digest_usage
            _complete_agent_run(
                run_id,
                {
                    "section_artifact_ids": artifact_ids[-len(section_drafts) :],
                    "summary_ids": summary_ids,
                    "summary_mode": "combined_with_writing",
                    "chapter_digest_count": len(chapter_digests),
                    "glossary_terms": [
                        term
                        for term, _count in sorted(
                            glossary_counts.items(), key=lambda item: -item[1]
                        )[:15]
                    ],
                    **({"topup_searches": topup_info} if topup_info else {}),
                },
                token_usage=token_usage or None,
            )
            clear_stage_progress(project_id)

            run_id = _start_agent_run(
                project_id,
                agent_name,
                "section_summary",
                {"section_count": len(section_drafts)},
            )
            _complete_agent_run(
                run_id,
                {
                    "summary_ids": summary_ids,
                    "summary_count": len(summaries),
                    "summary_mode": "combined_with_writing",
                },
            )
            section_work_time = max(
                [draft["updated_at"] for draft in section_drafts if draft.get("updated_at")]
                or [utc_now_iso()]
            )

        # Apply per-section user feedback that arrived after the current draft
        # of its target section. Fresh writes above already receive feedback in
        # their prompt, so only reused drafts show up here.
        pending_feedback = _pending_section_feedback(feedback_decisions, section_drafts)
        if not pending_feedback:
            _complete_reuse_run(
                project_id,
                agent_name,
                "feedback_revision",
                {"applied_sections": [], "comment_count": 0},
            )
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "feedback_revision",
                {
                    "section_ids": sorted(pending_feedback),
                    "comment_count": sum(len(items) for items in pending_feedback.values()),
                },
            )
            feedback_usage: list[Dict[str, Any]] = []
            applied_sections: list[str] = []
            for draft in section_drafts:
                section = draft.get("section") or {}
                section_id = str(section.get("id", ""))
                decisions_for_section = pending_feedback.get(section_id)
                if not decisions_for_section:
                    continue
                comments = [decision.answer for decision in decisions_for_section]
                if settings.llm_enabled:
                    markdown, usage = revise_section_with_feedback(
                        project, brief, draft, comments
                    )
                else:
                    notes = "\n".join(f"- {comment}" for comment in comments)
                    markdown, usage = (
                        f"{draft.get('markdown', '')}\n\nUser feedback applied:\n{notes}",
                        None,
                    )
                markdown = _ensure_markdown_heading_number(markdown, section)
                draft_content = {
                    "section": section,
                    "markdown": markdown,
                    "sources": draft.get("sources") or [],
                }
                with get_connection() as conn:
                    artifact_ids.append(
                        _insert_artifact(
                            conn,
                            project_id,
                            "section_draft",
                            f"Section {section_id}: feedback applied",
                            draft_content,
                            utc_now_iso(),
                            agent_name,
                        )
                    )
                revised_artifact = get_artifact(project_id, artifact_ids[-1])
                draft["markdown"] = markdown
                draft["artifact_id"] = artifact_ids[-1]
                draft["updated_at"] = (
                    revised_artifact.updated_at if revised_artifact else utc_now_iso()
                )
                applied_sections.append(section_id)
                if usage is not None:
                    feedback_usage.append({"section_id": section_id, **usage})
            section_work_time = max(
                [section_work_time]
                + [draft["updated_at"] for draft in section_drafts if draft.get("updated_at")]
            )
            _complete_agent_run(
                run_id,
                {
                    "applied_sections": applied_sections,
                    "comment_count": sum(len(items) for items in pending_feedback.values()),
                },
                token_usage={"section_calls": feedback_usage} if feedback_usage else None,
            )

        continuity_artifact = _latest_artifact(project_id, "continuity_review")
        if continuity_artifact is not None and _is_fresh(
            continuity_artifact.updated_at, section_work_time
        ):
            continuity = continuity_artifact.content or {}
            artifact_ids.append(continuity_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "continuity_review",
                {"artifact_id": continuity_artifact.id},
            )
            continuity_time = continuity_artifact.updated_at
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "continuity_review",
                {"section_count": len(section_drafts)},
            )
            if settings.llm_enabled:
                continuity, usage = review_continuity_staged(
                    project,
                    brief,
                    section_drafts,
                    summaries,
                    _list_chapter_digests(project_id),
                )
            else:
                continuity, usage = {
                    "verdict": "pass",
                    "issues": [],
                    "revision_targets": [],
                    "notes": "Local fallback continuity review passed.",
                }, None
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "continuity_review",
                        "Continuity review",
                        continuity,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            continuity_artifact = get_artifact(project_id, artifact_ids[-1])
            continuity_time = continuity_artifact.updated_at if continuity_artifact else utc_now_iso()
            _complete_agent_run(
                run_id,
                {"artifact_id": artifact_ids[-1], "verdict": continuity.get("verdict")},
                token_usage=usage,
            )

        revision_artifact = _latest_artifact(project_id, "targeted_revision")
        if revision_artifact is not None and _is_fresh(
            revision_artifact.updated_at, continuity_time
        ):
            revision = revision_artifact.content or {}
            revised_sections = revision.get("sections")
            if isinstance(revised_sections, list) and revised_sections:
                section_drafts = apply_section_revisions(section_drafts, revised_sections)
            artifact_ids.append(revision_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "targeted_revision",
                {"artifact_id": revision_artifact.id},
            )
            revision_time = revision_artifact.updated_at
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "targeted_revision",
                {"continuity_verdict": continuity.get("verdict")},
            )
            if settings.llm_enabled:
                revised_sections, usage = revise_targeted_sections(
                    project, brief, section_drafts, continuity
                )
            else:
                revised_sections, usage = section_drafts, None
            merged_sections = apply_section_revisions(section_drafts, revised_sections)
            revision = {
                "sections": merged_sections,
                "changed": merged_sections != section_drafts,
                "continuity_verdict": continuity.get("verdict"),
            }
            section_drafts = merged_sections
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "targeted_revision",
                        "Targeted revision",
                        revision,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            revision_artifact = get_artifact(project_id, artifact_ids[-1])
            revision_time = revision_artifact.updated_at if revision_artifact else utc_now_iso()
            _complete_agent_run(
                run_id,
                {"artifact_id": artifact_ids[-1], "changed": revision["changed"]},
                token_usage=usage,
            )

        citation_style = effective_citation_style(project_id)
        draft_artifact = _latest_artifact(project_id, "draft")
        # A citation-style change re-renders only this stage: section drafts
        # stay cached, but a draft merged under another style is stale.
        draft_style = ((draft_artifact.content or {}).get("conditions") or {}).get(
            "citation_style"
        ) if draft_artifact is not None else None
        if (
            draft_artifact is not None
            and _is_fresh(draft_artifact.updated_at, revision_time)
            and draft_style == citation_style
        ):
            artifact_ids.append(draft_artifact.id)
            _complete_reuse_run(
                project_id,
                agent_name,
                "final_merge",
                {"artifact_id": draft_artifact.id},
            )
        else:
            run_id = _start_agent_run(
                project_id,
                agent_name,
                "final_merge",
                {
                    "section_count": len(section_drafts),
                    "merge_mode": (
                        "llm_seam"
                        if settings.llm_enabled and settings.llm_merge_enabled
                        else "local"
                    ),
                },
            )
            # Each section cites [1]/[2] against its own small source list, so
            # remap those local markers onto one global numbering (and real
            # links) before merging. Drafts revived from revision artifacts may
            # lack the stored source list; recompute it the same way section
            # writing did.
            renumbered_drafts, used_sources = render_citations(
                [
                    {
                        "section": draft["section"],
                        "markdown": draft["markdown"],
                        "sources": draft.get("sources")
                        or _sources_for_section(
                            draft.get("section") or {}, chapter_sources, research
                        ),
                    }
                    for draft in section_drafts
                ],
                citation_style,
            )
            seam_ids: list[str] = []
            usage = None
            if settings.llm_enabled and settings.llm_merge_enabled:
                # Seam smoothing: one small call per chapter boundary instead
                # of the old whole-document merge call. The document itself is
                # always assembled deterministically below, so headings,
                # citations, and the Sources section can never be lost.
                renumbered_drafts, usage, seam_ids = smooth_chapter_seams(
                    project, brief, renumbered_drafts
                )
                merge_mode = "llm_seam"
            else:
                merge_mode = "local"
            merge_inputs = [
                {"section": draft["section"], "markdown": draft["markdown"]}
                for draft in renumbered_drafts
            ]
            final_markdown = _local_merge(
                project,
                merge_inputs,
                research,
                section_plan,
                used_sources,
                citation_style,
                accessed_at=research_cutoff,
            )
            final_content = {
                "format": "markdown",
                "markdown": final_markdown,
                "conditions": _draft_conditions(project_id),
            }
            with get_connection() as conn:
                artifact_ids.append(
                    _insert_artifact(
                        conn,
                        project_id,
                        "draft",
                        "Final merged draft",
                        final_content,
                        utc_now_iso(),
                        agent_name,
                    )
                )
            _complete_agent_run(
                run_id,
                {
                    "artifact_id": artifact_ids[-1],
                    "merge_mode": merge_mode,
                    "smoothed_seams": seam_ids,
                },
                token_usage=usage,
            )

        with get_connection() as conn:
            completed_at = utc_now_iso()
            conn.execute(
                """
                UPDATE projects
                SET status = ?, current_phase = ?, updated_at = ?
                WHERE id = ?
                """,
                ("completed", "final_merge", completed_at, project_id),
            )
    except LLMError as exc:
        fail(run_id, get_project(project_id).current_phase if get_project(project_id) else "unknown", exc)
        raise WorkflowRunFailedError(str(exc)) from exc

    updated_project = get_project(project_id)
    if updated_project is None:
        raise RuntimeError("Project disappeared after workflow run")

    artifacts = [
        artifact
        for artifact_id in artifact_ids
        if (artifact := get_artifact(project_id, artifact_id)) is not None
    ]
    return WorkflowRunRead(
        project=updated_project,
        artifacts=artifacts,
        pending_questions=[],
        status="completed",
        message="Staged writing pipeline completed.",
    )


def _short_text(value: Any, limit: int = 500) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _run_output(row: dict[str, Any] | None) -> Dict[str, Any]:
    if row is None or not row.get("output_json"):
        return {}
    output = _json_loads(row["output_json"])
    return output or {}


def _workflow_step_details(
    phase: str,
    row: dict[str, Any] | None,
    artifacts_by_type: dict[str, list[dict[str, Any]]],
    summaries: list[dict[str, Any]],
) -> Dict[str, Any]:
    output = _run_output(row)
    details: Dict[str, Any] = {}
    if output:
        details["output"] = output

    if phase == "research":
        research = (artifacts_by_type.get("research_sources") or [{}])[-1]
        content = research.get("content") or {}
        results = content.get("results") or []
        details.update(
            {
                "query": content.get("query"),
                "source_count": len(results),
                "sources": [
                    {
                        "title": source.get("title"),
                        "url": source.get("url"),
                    }
                    for source in results[:5]
                    if isinstance(source, dict)
                ],
                "error": content.get("error"),
            }
        )
    elif phase == "source_summary":
        source_summary = (artifacts_by_type.get("source_summaries") or [{}])[-1]
        content = source_summary.get("content") or {}
        sources = content.get("sources") or []
        details["source_summary_count"] = len(sources)
        details["source_summaries"] = [
            {
                "title": source.get("title"),
                "url": source.get("url"),
                "summary": _short_text(source.get("summary", ""), 220),
                "error": source.get("error"),
            }
            for source in sources[:5]
            if isinstance(source, dict)
        ]
    elif phase == "brief":
        brief = (artifacts_by_type.get("brief") or [{}])[-1].get("content")
        if brief:
            details["brief"] = brief
    elif phase == "outline":
        outline = (artifacts_by_type.get("outline") or [{}])[-1].get("content") or {}
        chapters = outline.get("chapters") or []
        details["chapter_count"] = len(chapters)
        details["chapters"] = [
            chapter.get("title") for chapter in chapters if isinstance(chapter, dict)
        ]
    elif phase in {"outline_review", "section_plan_review", "continuity_review"}:
        review = (artifacts_by_type.get(phase) or [{}])[-1].get("content") or {}
        details["verdict"] = review.get("verdict")
        details["issues"] = review.get("issues") or []
        details["notes"] = review.get("notes")
    elif phase == "section_plan":
        plan = (artifacts_by_type.get("section_plan") or [{}])[-1].get("content") or {}
        plan = _normalize_section_plan(plan) if plan else {}
        sections = plan.get("sections") or []
        outline_tree = plan.get("outline_tree") or []
        details["section_count"] = len(sections)
        details["tree_root_count"] = len(outline_tree)
        details["sections"] = [
            {
                "id": section.get("id"),
                "title": section.get("title"),
                "path": " > ".join(section.get("path") or []),
                "depth": section.get("depth"),
            }
            for section in sections
            if isinstance(section, dict)
        ]
    elif phase == "chapter_research":
        chapter_sources = (artifacts_by_type.get("chapter_sources") or [{}])[-1]
        content = chapter_sources.get("content") or {}
        chapters = content.get("chapters") or []
        details["chapter_count"] = len(chapters)
        details["source_count"] = sum(
            len(chapter.get("sources") or [])
            for chapter in chapters
            if isinstance(chapter, dict)
        )
        details["error"] = content.get("error")
        details["chapters"] = [
            {
                "id": chapter.get("chapter_id"),
                "title": chapter.get("title"),
                "query": chapter.get("query"),
                "source_count": len(chapter.get("sources") or []),
                "error": chapter.get("error"),
                "sources": [
                    {
                        "title": source.get("title"),
                        "url": source.get("url"),
                        "summary": _short_text(
                            source.get("summary") or source.get("snippet") or "", 200
                        ),
                    }
                    for source in (chapter.get("sources") or [])[:5]
                    if isinstance(source, dict)
                ],
            }
            for chapter in chapters
            if isinstance(chapter, dict)
        ]
    elif phase == "section_writing":
        chapter_content = (
            (artifacts_by_type.get("chapter_sources") or [{}])[-1].get("content") or {}
        )
        chapter_urls = {
            source.get("url")
            for chapter in chapter_content.get("chapters") or []
            if isinstance(chapter, dict)
            for source in chapter.get("sources") or []
            if isinstance(source, dict) and source.get("url")
        }
        drafts = artifacts_by_type.get("section_draft") or []
        details["section_draft_count"] = len(drafts)
        details["section_drafts"] = [
            {
                "title": draft.get("title"),
                "preview": _short_text((draft.get("content") or {}).get("markdown", ""), 220),
                "sources": [
                    {
                        "title": source.get("title"),
                        "url": source.get("url"),
                        "from_chapter_research": source.get("url") in chapter_urls,
                    }
                    for source in (draft.get("content") or {}).get("sources") or []
                    if isinstance(source, dict) and source.get("url")
                ],
            }
            for draft in drafts[:8]
        ]
        if output.get("topup_searches"):
            details["topup_searches"] = output["topup_searches"]
        if output.get("chapter_digest_count") is not None:
            details["chapter_digest_count"] = output["chapter_digest_count"]
        if output.get("glossary_terms"):
            details["glossary_terms"] = output["glossary_terms"]
    elif phase == "section_summary":
        section_rows = [row for row in summaries if row.get("scope") == "section"]
        parsed_summaries = []
        for summary in section_rows[:8]:
            content = _json_loads(summary.get("summary_json")) or {}
            parsed_summaries.append(
                {
                    "section_id": content.get("section_id") or summary.get("node_id"),
                    "summary": _short_text(content.get("summary", ""), 220),
                }
            )
        details["summary_count"] = len(section_rows)
        details["summaries"] = parsed_summaries
        if output.get("summary_mode"):
            details["summary_mode"] = output["summary_mode"]
    elif phase == "targeted_revision":
        revision = (artifacts_by_type.get("targeted_revision") or [{}])[-1].get("content") or {}
        details["changed"] = revision.get("changed")
        details["section_count"] = len(revision.get("sections") or [])
    elif phase == "final_merge":
        draft = (artifacts_by_type.get("draft") or [{}])[-1].get("content") or {}
        markdown = draft.get("markdown", "")
        if output.get("merge_mode"):
            details["merge_mode"] = output["merge_mode"]
        if output.get("smoothed_seams"):
            details["smoothed_seams"] = len(output["smoothed_seams"])
        if markdown:
            details["draft_preview"] = _short_text(markdown, 500)
            details["character_count"] = len(markdown)

    return details


def get_workflow_progress(project_id: str) -> Optional[WorkflowProgressRead]:
    project = get_project(project_id)
    if project is None:
        return None

    stage_progress = get_stage_progress(project_id) if project.status == "running" else None

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT phase, status, input_json, output_json, token_usage_json,
                   created_at, completed_at, error
            FROM agent_runs
            WHERE project_id = ?
            ORDER BY created_at ASC
            """,
            (project_id,),
        ).fetchall()
        artifact_rows = conn.execute(
            """
            SELECT id, type, title, content_json, created_at, updated_at
            FROM artifacts
            WHERE project_id = ?
            ORDER BY created_at ASC
            """,
            (project_id,),
        ).fetchall()
        summary_rows = conn.execute(
            """
            SELECT id, node_id, scope, summary_json, created_at, updated_at
            FROM summaries
            WHERE project_id = ?
            ORDER BY created_at ASC
            """,
            (project_id,),
        ).fetchall()

    latest_by_phase: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest_by_phase[row["phase"]] = dict(row)

    artifact_times: dict[str, str] = {}
    artifacts_by_type: dict[str, list[dict[str, Any]]] = {}
    for row in artifact_rows:
        artifact_times[row["type"]] = row["updated_at"] or row["created_at"]
        data = dict(row)
        data["content"] = _json_loads(data.pop("content_json"))
        artifacts_by_type.setdefault(row["type"], []).append(data)
    has_final_draft = "draft" in artifact_times
    legacy_completed = project.status == "completed" and has_final_draft
    infer_from_artifacts = project.status == "completed" or (
        not rows and project.status == "created"
    )

    inferred_phase_times = {
        "research": artifact_times.get("research_sources"),
        "source_summary": artifact_times.get("source_summaries"),
        "brief": artifact_times.get("brief"),
        "outline": artifact_times.get("outline"),
        "outline_review": artifact_times.get("outline_review"),
        "section_plan": artifact_times.get("section_plan"),
        "section_plan_review": artifact_times.get("section_plan_review"),
        "chapter_research": artifact_times.get("chapter_sources"),
        "section_writing": artifact_times.get("section_draft"),
        "section_summary": (
            (summary_rows[-1]["updated_at"] or summary_rows[-1]["created_at"])
            if summary_rows
            else None
        ),
        "continuity_review": artifact_times.get("continuity_review"),
        "targeted_revision": artifact_times.get("targeted_revision"),
        "final_merge": artifact_times.get("draft"),
    }

    steps: list[WorkflowStepRead] = []
    completed_count = 0
    for phase, label in WORKFLOW_STEPS:
        row = latest_by_phase.get(phase)
        status = row["status"] if row is not None else "pending"
        inferred_time = inferred_phase_times.get(phase)
        if row is None:
            if phase == "intake" and (rows or artifact_rows or project.status != "created"):
                status = "completed"
                inferred_time = inferred_time or project.updated_at
            elif infer_from_artifacts and inferred_time is not None:
                status = "completed"
            elif legacy_completed:
                status = "completed"
                inferred_time = project.updated_at
        if status in {"completed", "waiting_for_user"}:
            completed_count += 1
        details = _workflow_step_details(
            phase,
            row,
            artifacts_by_type,
            [dict(summary) for summary in summary_rows],
        )
        step_progress = None
        if (
            status == "running"
            and stage_progress
            and stage_progress.get("phase") == phase
        ):
            step_progress = {
                "done": int(stage_progress["done"]),
                "total": int(stage_progress["total"]),
            }
        steps.append(
            WorkflowStepRead(
                phase=phase,
                label=label,
                status=status,
                created_at=row["created_at"] if row is not None else inferred_time,
                completed_at=row["completed_at"] if row is not None else inferred_time,
                error=row["error"] if row is not None else None,
                details=details,
                progress=step_progress,
            )
        )

    # A running stage that reports "done of total" contributes a fraction of one
    # step so the overall bar advances within a long phase, not just between them.
    running_fraction = 0.0
    for step in steps:
        if step.status == "running" and step.progress and step.progress.get("total"):
            running_fraction = step.progress["done"] / step.progress["total"]
            break
    percent = int(((completed_count + running_fraction) / len(WORKFLOW_STEPS)) * 100)
    if project.status == "completed":
        percent = 100

    return WorkflowProgressRead(
        project=project,
        steps=steps,
        percent=percent,
        current_phase=project.current_phase,
        status=project.status,
    )
