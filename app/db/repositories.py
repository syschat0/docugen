import json
import hashlib
import re
from dataclasses import dataclass
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
from app.services.doc_types import get_doc_type_profile
from app.services.quality import (
    build_quality_summary,
    grade_source,
    is_high_stakes_topic,
    issue_section_ids,
    sentence_quality_stats,
    validate_evidence_ledger,
)
from app.services.llm import (
    LLMError,
    apply_section_revisions,
    classify_document_type,
    collect_leaf_titles,
    derive_style_card,
    expand_chapter_subtree,
    generate_brief,
    generate_outline,
    generate_section_plan,
    best_overlap_score,
    plan_section_illustrations,
    plan_user_questions,
    select_illustration_entries,
    select_main_illustration,
    repair_section_evidence,
    repair_sentence_quality_sections,
    review_continuity_staged,
    review_outline,
    review_rubric_staged,
    review_section_plan,
    revise_section_with_feedback,
    revise_targeted_sections,
    select_section_sources,
    smooth_chapter_seams,
    summarize_chapter,
    write_section_with_summary,
)
from app.services.search import (
    research_chapters,
    search_section_sources,
    search_web,
    summarize_search_sources,
)
from app.services.image_gen import ImageGenError, generate_section_image
from app.services.image_settings import (
    get_active_image_config,
    get_image_options,
    image_generation_enabled,
)
from app.services.source_eval import evaluate_sources, rank_sources_for_section
from app.services.run_control import (
    clear_cancel,
    clear_stage_progress,
    get_stage_progress,
    is_cancel_requested,
    set_stage_progress,
)
from app.services.search_options import (
    SearchOptions,
    default_search_options,
    reset_search_options,
    use_search_options,
)


class QuestionAlreadyAnsweredError(Exception):
    pass


class WorkflowRunFailedError(Exception):
    pass


class UnknownQualityIssueError(Exception):
    pass


class WorkflowCancelledError(Exception):
    """Raised inside a run when the user requested cancellation."""
    pass


@dataclass(frozen=True)
class PipelineStageSpec:
    key: str
    label: str
    primary: tuple[str, ...] = ()


PIPELINE_STAGES: tuple[PipelineStageSpec, ...] = (
    PipelineStageSpec("intake", "Intake questions"),
    PipelineStageSpec("style_card", "Style card", ("style_card",)),
    PipelineStageSpec("research", "Web research", ("research_sources",)),
    PipelineStageSpec("source_summary", "Source summaries", ("source_summaries",)),
    PipelineStageSpec("brief", "Brief", ("brief",)),
    PipelineStageSpec("outline", "Outline", ("outline",)),
    PipelineStageSpec("outline_review", "Outline review", ("outline_review",)),
    PipelineStageSpec("section_plan", "Section plan", ("section_plan",)),
    PipelineStageSpec("section_plan_review", "Section plan review", ("section_plan_review",)),
    PipelineStageSpec("chapter_research", "Chapter research", ("chapter_sources",)),
    PipelineStageSpec("section_writing", "Section writing", ("section_draft",)),
    PipelineStageSpec("section_summary", "Section summaries"),
    PipelineStageSpec("feedback_revision", "Feedback revision"),
    PipelineStageSpec("continuity_review", "Continuity review", ("continuity_review",)),
    PipelineStageSpec("rubric_review", "Rubric review", ("rubric_review",)),
    PipelineStageSpec("targeted_revision", "Targeted revision", ("targeted_revision",)),
    PipelineStageSpec("illustration", "Illustrations", ("illustration_plan",)),
    PipelineStageSpec("final_merge", "Final merge", ("draft",)),
)

WORKFLOW_STEPS: list[tuple[str, str]] = [
    (stage.key, stage.label) for stage in PIPELINE_STAGES
]
_PIPELINE_STAGE_BY_KEY = {stage.key: stage for stage in PIPELINE_STAGES}


# style_card hangs off the reference inputs, not the main chain: forcing it
# must not clear research artifacts, and forcing intake must not clear it.
_MAIN_CHAIN_KEYS = [s.key for s in PIPELINE_STAGES if s.key != "style_card"]


def _stage_invalidates(key: str) -> tuple[str, ...]:
    if key == "style_card":
        tail = _MAIN_CHAIN_KEYS[_MAIN_CHAIN_KEYS.index("section_writing"):]
        types = ["style_card"]
    elif key in _MAIN_CHAIN_KEYS:
        tail = _MAIN_CHAIN_KEYS[_MAIN_CHAIN_KEYS.index(key):]
        types = []
    else:
        return ()
    for stage_key in tail:
        types.extend(_PIPELINE_STAGE_BY_KEY[stage_key].primary)
    return tuple(dict.fromkeys(types))


def _stage_clears_summaries(key: str) -> bool:
    # Summaries are written during section writing, so they go whenever the
    # drafts they describe are invalidated. Forcing section_summary is the
    # explicit way to regenerate them (via a full rewrite).
    return key == "section_summary" or "section_draft" in _stage_invalidates(key)


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
PROJECT_SETTING_KEYS = (
    "search_enabled",
    "section_search_enabled",
    "citation_style",
    "target_length",
    "search_engines",
    "search_headless",
    "search_stealth",
    "search_locale",
    "search_query_language",
)


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
    """Explicit override > document-type default, gated by the global flag.

    A genre that does not want research (e.g. essays) disables it by
    default, but a profile can never re-enable globally disabled search.
    """
    value = get_project_settings(project_id).get("search_enabled")
    if value is not None:
        return settings.search_enabled and bool(value)
    project = get_project(project_id)
    profile = get_doc_type_profile(project.document_type if project else None)
    return settings.search_enabled and bool(profile.get("research_default", True))


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


def effective_search_options(project_id: str) -> SearchOptions:
    """Per-project search knobs (engine/headless/stealth/locale/query language).

    Each is an explicit override when set, else the global env default. The
    pipeline installs the result for the duration of a run so the browser and
    LLM search helpers pick up the project's choices.
    """
    stored = get_project_settings(project_id)
    defaults = default_search_options()

    def pick(key: str, default: Any) -> Any:
        value = stored.get(key)
        return default if value is None else value

    engines_override = stored.get("search_engines")
    engines = tuple(engines_override) if engines_override else defaults.engines
    return SearchOptions(
        engines=engines,
        headless=bool(pick("search_headless", defaults.headless)),
        stealth=bool(pick("search_stealth", defaults.stealth)),
        locale=pick("search_locale", defaults.locale),
        query_language=pick("search_query_language", defaults.query_language),
    )


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
                id, title, initial_request, document_type, status, current_phase,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                payload.title,
                payload.initial_request,
                payload.document_type,
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
            SELECT id, title, initial_request, document_type, status, current_phase,
                   created_at, updated_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()

    if row is None:
        return None
    return ProjectRead(**dict(row))


def update_project(
    project_id: str,
    title: str | None = None,
    initial_request: str | None = None,
    document_type: str | None = None,
) -> Optional[ProjectRead]:
    """Edit the project's title, initial request, and/or document type.

    An edited request or document type changes the document inputs, so the
    input cutoff is bumped to regenerate downstream artifacts on the next run
    (old versions are kept). document_type "auto" clears the stored type so
    the next run re-classifies it.
    """
    project = get_project(project_id)
    if project is None:
        return None

    fields: list[str] = []
    params: list[str | None] = []
    if title is not None:
        fields.append("title = ?")
        params.append(title)
    request_changed = initial_request is not None
    if request_changed:
        fields.append("initial_request = ?")
        params.append(initial_request)
    new_type = None if document_type == "auto" else document_type
    type_changed = document_type is not None and new_type != project.document_type
    if type_changed:
        fields.append("document_type = ?")
        params.append(new_type)

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
    if request_changed or type_changed:
        mark_project_inputs_changed(project_id)
    return get_project(project_id)


def list_projects() -> List[ProjectRead]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, initial_request, document_type, status, current_phase,
                   created_at, updated_at
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
            "quality_issue_decisions",
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
        # Style samples are voice exemplars, not facts: they never enter the
        # research source pool (and so are never cited).
        if ref.kind != "style"
        and ref.status == "ready"
        and (ref.content_text or "").strip()
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


def export_project_markdown(
    project_id: str, base_url: str | None = None
) -> Optional[ExportRead]:
    draft = _latest_artifact(project_id, "draft")
    if draft is None or not draft.content:
        return None

    markdown = draft.content.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        return None

    # Rewrite root-relative image links to absolute so the exported file renders
    # its illustrations outside the running server.
    if base_url:
        markdown = markdown.replace("](/media/", f"]({base_url}/media/")

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
    stage = _PIPELINE_STAGE_BY_KEY.get(phase)
    if stage is None:
        return

    # Preserve every prior final draft as version history: a forced rerun only
    # clears intermediate artifacts and then writes a new draft version, so the
    # old one stays browsable in the version list.
    artifact_types = [
        artifact_type
        for artifact_type in _stage_invalidates(phase)
        if artifact_type != "draft"
    ]

    run_phases = [item[0] for item in WORKFLOW_STEPS]
    if phase in run_phases:
        run_phases = run_phases[run_phases.index(phase) :]

    with get_connection() as conn:
        if artifact_types:
            placeholders = ",".join("?" for _ in artifact_types)
            conn.execute(
                f"DELETE FROM artifacts WHERE project_id = ? AND type IN ({placeholders})",
                (project_id, *artifact_types),
            )
        if phase == "intake":
            conn.execute(
                "DELETE FROM pending_questions WHERE project_id = ? AND status = ?",
                (project_id, "pending"),
            )
        if _stage_clears_summaries(phase):
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
                "evidence": content.get("evidence") or [],
                "evidence_validation": content.get("evidence_validation"),
                "evidence_repair": content.get("evidence_repair"),
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


def _ensure_markdown_heading_number(
    markdown: str, section: Dict[str, Any], numbered: bool = True
) -> str:
    section_id = str(section.get("id") or "").strip()
    if not section_id:
        return markdown

    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if not numbered:
                # Types without numbered headings keep the writer's heading
                # as-is, minus any id the model added anyway.
                marker, _, title = stripped.partition(" ")
                if title.startswith(f"{section_id} "):
                    lines[index] = f"{marker} {title[len(section_id) + 1 :]}".rstrip()
                return "\n".join(lines)
            marker, _, title = stripped.partition(" ")
            if not title.startswith(f"{section_id} "):
                lines[index] = f"{marker} {section_id} {title}".rstrip()
            return "\n".join(lines)

        depth = min(max(_int_or_default(section.get("depth"), 2), 2), 6)
        title = _numbered_title(section) if numbered else str(section.get("title") or "Section")
        heading = f"{'#' * depth} {title}"
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


def _document_target_length(project_id: str, brief: Dict[str, Any]) -> int | None:
    """Total body-length budget: explicit setting first, then the length the
    brief extracted from the request/answers. None means no budget."""
    value = _int_or_default(get_project_settings(project_id).get("target_length"), 0)
    if value <= 0:
        value = _int_or_default((brief or {}).get("target_length_chars"), 0)
    if value <= 0:
        return None
    return min(max(value, 500), 100_000)


def _scale_section_lengths(
    section_plan: Dict[str, Any], doc_target: int | None
) -> Dict[str, Any]:
    """Distribute the document budget proportionally across leaf sections.

    Scaling happens at run time on the in-memory plan (never stored), so a
    changed budget re-flows lengths without rewriting the plan artifact.
    Per-section lengths are clamped to a writable range."""
    sections = section_plan.get("sections") or []
    if not doc_target or not sections:
        return section_plan
    current = [max(_int_or_default(s.get("target_length"), 500), 1) for s in sections]
    total = sum(current)
    if total <= 0:
        return section_plan
    scale = doc_target / total
    for section, length in zip(sections, current):
        section["target_length"] = int(min(max(length * scale, 150), 3000))
    return section_plan


def _normalize_section_plan(
    section_plan: Dict[str, Any], default_length: int = 500
) -> Dict[str, Any]:
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
                "target_length": _int_or_default(section.get("target_length"), default_length),
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


def _empty_genre_memory(profile: Dict[str, Any] | None) -> Dict[str, list[Any]]:
    profile = profile or get_doc_type_profile(None)
    return {str(key): [] for key in (profile.get("memory_schema") or {})}


def _local_section_summary(
    section: Dict[str, Any],
    markdown: str,
    profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "section_id": section.get("id", ""),
        "summary": markdown.split("\n\n", 1)[-1][:280],
        "claims": [],
        "terms": [],
        "open_threads": [],
        "next_section_handoff": f"Continue after {section.get('title', 'this section')}.",
        "memory": _empty_genre_memory(profile),
        "evidence": [],
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
    chapter_id: str,
    chapter_title: str,
    chapter_summaries: list[Dict[str, Any]],
    profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    text = " ".join(
        str(summary.get("summary", "")).strip()
        for summary in chapter_summaries
        if str(summary.get("summary", "")).strip()
    )
    memory = _empty_genre_memory(profile)
    for key in memory:
        values: list[str] = []
        for summary in chapter_summaries:
            value = (summary.get("memory") or {}).get(key)
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                clean = str(candidate or "").strip()
                if clean and clean not in values:
                    values.append(clean[:120])
        memory[key] = values[:4]
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
        "memory": memory,
    }


def _build_chapter_digest(
    project: ProjectRead,
    chapter_id: str,
    chapter_title: str,
    chapter_summaries: list[Dict[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    profile = get_doc_type_profile(project.document_type)
    if settings.llm_enabled:
        try:
            return summarize_chapter(
                project,
                {"id": chapter_id, "title": chapter_title},
                chapter_summaries,
                profile=profile,
            )
        except LLMError:
            pass  # the digest is an enhancement; a local concat must not fail the run
    return (
        _local_chapter_digest(
            chapter_id, chapter_title, chapter_summaries, profile=profile
        ),
        None,
    )


def _local_merge(
    project: ProjectRead,
    section_drafts: list[Dict[str, Any]],
    research: Dict[str, Any] | None,
    section_plan: Dict[str, Any] | None = None,
    used_sources: list[Dict[str, Any]] | None = None,
    citation_style: str = "numeric",
    accessed_at: str | None = None,
    profile: Dict[str, Any] | None = None,
) -> str:
    profile = profile or get_doc_type_profile(None)
    numbered = bool(profile.get("numbered_headings", True))
    draft_by_id = {
        str((item.get("section") or {}).get("id", "")): _ensure_markdown_heading_number(
            str(item.get("markdown", "")).strip(),
            item.get("section") or {},
            numbered=numbered,
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
        title = _numbered_title(node) if numbered else str(node.get("title") or "Section")
        parts = [f"{'#' * heading_level} {title}"]
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
    # research results only when nothing was cited. Types without citations
    # (essays, scripts) get no Sources section at all.
    if profile.get("citations_enabled", True):
        sources = used_sources or (research.get("results", []) if research else [])
        sources_section = format_sources_section(
            sources, style=citation_style, accessed_at=accessed_at
        )
    else:
        sources_section = ""
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
    project_text: str = "",
    *,
    section_eval_info: list[Dict[str, Any]] | None = None,
    allow_section_eval: bool = False,
) -> tuple[list[Dict[str, Any]], Dict[str, Dict[str, Any]] | None]:
    """Select a section's sources, optionally reranked by a listwise LLM judge.

    Returns ``(sources, section_fit)`` where ``section_fit`` is the per-url
    relevance map used for ranking, or ``None`` when listwise evaluation did not
    run. When ``section_eval_info`` is supplied (the section-writing loop), the
    candidate pool is scored in one LLM call whose stats are appended there;
    ``allow_section_eval`` gates whether that real call may be made (run budget),
    while cache hits are always served. The final-merge caller omits both and
    keeps the pure-heuristic path.
    """
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

    section_fit: Dict[str, Dict[str, Any]] | None = None
    if section_eval_info is not None:
        section_fit, stats = rank_sources_for_section(
            section,
            chapter_candidates + global_candidates,
            allow_llm_call=allow_section_eval,
        )
        if stats["called"] or stats["cache_hit"] or stats["error"]:
            section_eval_info.append(
                {"section_id": str(section.get("id", "")), **stats}
            )

    sources = select_section_sources(
        section,
        chapter_candidates,
        global_candidates,
        limit=2,
        project_text=project_text,
        section_fit=section_fit,
    )
    return sources, section_fit


def _eval_marks_relevant(
    section_sources: list[Dict[str, Any]],
    section_fit: Dict[str, Dict[str, Any]] | None,
) -> bool:
    """True when listwise evaluation scored a selected source relevant (>= 2).

    Used to suppress the zero-overlap "no_relevant_source" top-up: if the judge
    considered a chosen source relevant, a lack of lexical overlap is not a
    reason to re-search for that section.
    """
    if not section_fit:
        return False
    for source in section_sources:
        if not isinstance(source, dict):
            continue
        entry = section_fit.get(str(source.get("url") or ""))
        if isinstance(entry, dict):
            try:
                if int(entry.get("relevance", 0)) >= 2:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _reexpand_section_plan(
    project: ProjectRead,
    brief: Dict[str, Any],
    section_plan: Dict[str, Any],
    review: Dict[str, Any],
    nodes_to_expand: list,
    profile: Dict[str, Any] | None = None,
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
                    project, brief, chapter, other_titles, feedback=feedback,
                    profile=profile,
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


def _combine_reviews(
    continuity: Dict[str, Any], rubric: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge continuity and rubric findings for one targeted-revision pass.

    Targets are deduplicated in order and capped so a harsh review cannot
    trigger a rewrite of the whole document."""
    issues = list(continuity.get("issues") or []) + list(rubric.get("issues") or [])
    targets = list(
        dict.fromkeys(
            str(target).strip()
            for source in (continuity, rubric)
            for target in (source.get("revision_targets") or [])
            if str(target).strip()
        )
    )
    # Reviewers occasionally describe exact affected sections but forget the
    # revision_targets field. Recover them so a contradictory "pass" cannot
    # silently discard actionable findings.
    targets = list(dict.fromkeys(targets + issue_section_ids(issues)))[:5]
    return {
        "verdict": "needs_revision" if targets or issues else "pass",
        "issues": issues,
        "revision_targets": targets,
    }


def _quality_issue_key(issue: Dict[str, Any]) -> str:
    identity = {
        "type": str(issue.get("type") or ""),
        "section_ids": [str(value) for value in (issue.get("section_ids") or [])],
        "excerpts": [" ".join(str(value).lower().split()) for value in (issue.get("excerpts") or [])],
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return digest[:24]


def _quality_decisions(project_id: str, draft_id: str) -> dict[str, Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT issue_key, decision, reason, created_at, updated_at
            FROM quality_issue_decisions
            WHERE project_id = ? AND draft_id = ?
            """,
            (project_id, draft_id),
        ).fetchall()
    return {str(row["issue_key"]): dict(row) for row in rows}


_QUALITY_WARNING_BY_ISSUE_TYPE = {
    "duplicate": "duplicate_content",
    "possible_contradiction": "possible_contradictions",
    "unsupported_overclaim": "unsupported_overclaims",
    "long_sentence": "long_sentences",
    "long_paragraph": "long_paragraphs",
    "list_heavy": "list_heavy_sections",
    "heading_structure": "heading_structure",
    "missing_introduction": "missing_introduction",
    "missing_conclusion": "missing_conclusion",
}


def _quality_type_totals(summary: Dict[str, Any]) -> dict[str, int]:
    writing = summary.get("writing_quality") or {}
    structure = summary.get("structure_quality") or {}
    return {
        "duplicate": int(writing.get("duplicate_pair_count") or 0),
        "possible_contradiction": int(writing.get("possible_contradiction_count") or 0),
        "unsupported_overclaim": int(writing.get("unsupported_overclaim_count") or 0),
        "long_sentence": int(structure.get("long_sentence_count") or 0),
        "long_paragraph": int(structure.get("long_paragraph_count") or 0),
        "list_heavy": int(structure.get("list_heavy_section_count") or 0),
        "heading_structure": int(structure.get("heading_issue_count") or 0),
        "missing_introduction": int(bool(structure.get("missing_introduction"))),
        "missing_conclusion": int(bool(structure.get("missing_conclusion"))),
    }


def _apply_quality_decisions(
    project_id: str, draft_id: str, raw_summary: Dict[str, Any]
) -> Dict[str, Any]:
    summary = json.loads(json.dumps(raw_summary, ensure_ascii=False))
    summary["draft_id"] = draft_id
    decisions = _quality_decisions(project_id, draft_id)
    waived_by_type: dict[str, int] = {}
    acknowledged_count = 0
    waived_count = 0

    for group_name in ("writing_quality", "structure_quality"):
        group = summary.setdefault(group_name, {})
        group_waived = 0
        group_acknowledged = 0
        for issue in group.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            issue_key = _quality_issue_key(issue)
            issue["issue_key"] = issue_key
            decision = decisions.get(issue_key)
            if not decision:
                continue
            issue["decision"] = decision
            if decision["decision"] == "waived":
                group_waived += 1
                waived_count += 1
                issue_type = str(issue.get("type") or "")
                waived_by_type[issue_type] = waived_by_type.get(issue_type, 0) + 1
            else:
                group_acknowledged += 1
                acknowledged_count += 1
        group["waived_issue_count"] = group_waived
        group["acknowledged_issue_count"] = group_acknowledged
        group["active_issue_count"] = max(
            int(group.get("issue_count") or 0) - group_waived, 0
        )

    review = summary.setdefault("review", {})
    # Older stored summaries carry only revision_targets; newer ones include
    # target_issues whose excerpt is the reviewer's note for that section.
    raw_target_issues = review.get("target_issues") or [
        {"type": "review_target", "section_ids": [str(section_id)], "excerpts": []}
        for section_id in (review.get("revision_targets") or [])
    ]
    review["target_issues"] = [
        {
            "type": "review_target",
            "section_ids": [str(value) for value in (item.get("section_ids") or [])],
            "excerpts": [str(value) for value in (item.get("excerpts") or [])],
            # Keyed without the excerpt so identity stays stable even when the
            # reviewer words the same finding differently between runs.
            "issue_key": _quality_issue_key(
                {
                    "type": "review_target",
                    "section_ids": [
                        str(value) for value in (item.get("section_ids") or [])
                    ],
                    "excerpts": [],
                }
            ),
        }
        for item in raw_target_issues
        if isinstance(item, dict)
    ]

    totals = _quality_type_totals(summary)
    removable_warnings = {
        warning
        for issue_type, warning in _QUALITY_WARNING_BY_ISSUE_TYPE.items()
        if totals.get(issue_type, 0) > 0
        and waived_by_type.get(issue_type, 0) >= totals[issue_type]
    }
    summary["warnings"] = [
        warning
        for warning in (summary.get("warnings") or [])
        if warning not in removable_warnings
    ]
    summary["status"] = "review_needed" if summary["warnings"] else "ready"
    summary["decision_summary"] = {
        "acknowledged_count": acknowledged_count,
        "waived_count": waived_count,
    }
    return summary


def _quality_actionable_keys(summary: Dict[str, Any]) -> set[str]:
    return {
        str(issue.get("issue_key"))
        for group_name in ("writing_quality", "structure_quality")
        for issue in ((summary.get(group_name) or {}).get("issues") or [])
        if isinstance(issue, dict) and issue.get("issue_key")
    }


def _sync_project_quality_status(project_id: str, summary: Dict[str, Any]) -> None:
    project = get_project(project_id)
    if (
        project is not None
        and project.current_phase == "final_merge"
        and project.status in {"completed", "review_needed"}
    ):
        set_project_status(
            project_id,
            "review_needed" if summary.get("status") == "review_needed" else "completed",
            "final_merge",
        )


def set_quality_issue_decision(
    project_id: str, issue_key: str, decision: str, reason: str
) -> Optional[Dict[str, Any]]:
    project = get_project(project_id)
    if project is None:
        return None
    if project.current_phase != "final_merge":
        raise UnknownQualityIssueError(
            "Quality decisions can only be saved for the current final draft"
        )
    summary = get_project_quality_summary(project_id)
    if summary is None:
        return None
    if issue_key not in _quality_actionable_keys(summary):
        raise UnknownQualityIssueError("Quality issue does not belong to the latest draft")
    draft_id = str(summary.get("draft_id") or "")
    if not draft_id:
        raise UnknownQualityIssueError("No current draft is available")
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO quality_issue_decisions (
                id, project_id, draft_id, issue_key, decision, reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, draft_id, issue_key) DO UPDATE SET
                decision = excluded.decision,
                reason = excluded.reason,
                updated_at = excluded.updated_at
            """,
            (str(uuid4()), project_id, draft_id, issue_key, decision, reason, now, now),
        )
    updated = get_project_quality_summary(project_id)
    if updated is not None:
        _sync_project_quality_status(project_id, updated)
    return updated


def delete_quality_issue_decision(
    project_id: str, issue_key: str
) -> Optional[Dict[str, Any]]:
    summary = get_project_quality_summary(project_id)
    if summary is None:
        return None
    draft_id = str(summary.get("draft_id") or "")
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM quality_issue_decisions
            WHERE project_id = ? AND draft_id = ? AND issue_key = ?
            """,
            (project_id, draft_id, issue_key),
        )
    updated = get_project_quality_summary(project_id)
    if updated is not None:
        _sync_project_quality_status(project_id, updated)
    return updated


def get_project_quality_summary(project_id: str) -> Optional[Dict[str, Any]]:
    """Build the latest deterministic quality summary for API and status use."""
    project = get_project(project_id)
    if project is None:
        return None

    draft_artifact = _latest_artifact(project_id, "draft")
    stored_quality = (draft_artifact.content or {}).get("quality") if draft_artifact else None
    if (
        project.current_phase == "final_merge"
        and project.status in {"completed", "review_needed"}
        and isinstance(stored_quality, dict)
        and stored_quality.get("status")
    ):
        return _apply_quality_decisions(project_id, draft_artifact.id, stored_quality)

    latest_by_section: dict[str, Dict[str, Any]] = {}
    for artifact in _latest_artifacts(project_id, "section_draft"):
        content = artifact.content or {}
        section_id = str((content.get("section") or {}).get("id") or "")
        if section_id:
            latest_by_section[section_id] = content
    section_drafts = list(latest_by_section.values())
    sources: list[Dict[str, Any]] = []
    for draft in section_drafts:
        sources.extend(source for source in (draft.get("sources") or []) if isinstance(source, dict))

    continuity_artifact = _latest_artifact(project_id, "continuity_review")
    rubric_artifact = _latest_artifact(project_id, "rubric_review")
    revision_artifact = _latest_artifact(project_id, "targeted_revision")
    profile = get_doc_type_profile(project.document_type)
    summary = build_quality_summary(
        project_text=f"{project.title}\n{project.initial_request}",
        sources=sources,
        section_drafts=section_drafts,
        continuity=continuity_artifact.content if continuity_artifact else None,
        rubric=rubric_artifact.content if rubric_artifact else None,
        citations_enabled=bool(profile.get("citations_enabled", True)),
        sentence_repair=(
            (revision_artifact.content or {}).get("sentence_quality_repair")
            if revision_artifact
            else None
        ),
        document_type=str(profile.get("key") or "report"),
    )
    if draft_artifact is not None and project.current_phase != "final_merge":
        summary["status"] = "review_needed"
        summary["warnings"] = list(
            dict.fromkeys([*(summary.get("warnings") or []), "stale_due_inputs"])
        )
    if draft_artifact is None:
        return summary
    return _apply_quality_decisions(project_id, draft_artifact.id, summary)


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
    project = get_project(project_id)
    profile = get_doc_type_profile(project.document_type if project else None)
    return {
        "document_type": project.document_type if project else None,
        "search_enabled": effective_search_enabled(project_id),
        "section_search_enabled": effective_section_search_enabled(project_id),
        "citations_enabled": bool(profile.get("citations_enabled", True)),
        "citation_style": effective_citation_style(project_id),
        "target_length": get_project_settings(project_id).get("target_length"),
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
    restored = get_artifact(project_id, new_id)
    summary = get_project_quality_summary(project_id)
    if summary is not None:
        _sync_project_quality_status(project_id, summary)
    return restored


@dataclass(frozen=True)
class FinalMergeInputs:
    project_id: str
    project: ProjectRead
    profile: Dict[str, Any]
    section_drafts: list[Dict[str, Any]]
    chapter_sources: Dict[str, Any] | None
    research: Dict[str, Any] | None
    brief: Dict[str, Any]
    section_plan: Dict[str, Any]
    research_cutoff: str | None
    continuity: Dict[str, Any]
    rubric_review: Dict[str, Any]
    revision: Dict[str, Any]
    citation_style: str


def _usable_illustration_entries(project_id: str) -> list[Dict[str, Any]]:
    """All illustration entries whose generated image exists on disk.

    Best effort: any read problem (no plan, no table) yields no entries so the
    merge always succeeds. Only successfully generated/cached files are kept.
    """
    try:
        artifact = _latest_artifact(project_id, "illustration_plan")
    except Exception:
        return []
    if artifact is None or not artifact.content:
        return []
    usable: list[Dict[str, Any]] = []
    for entry in artifact.content.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") not in {"generated", "cached"}:
            continue
        file_name = str(entry.get("file") or "")
        if not file_name or not (settings.media_dir / file_name).exists():
            continue
        usable.append(entry)
    return usable


def _usable_illustrations(project_id: str) -> Dict[str, Dict[str, Any]]:
    """Map section_id -> illustration entry for body images that exist on disk.

    Excludes the cover ("main") image; an entry with no role is treated as a
    section image for backward compatibility with pre-cover-image artifacts.
    """
    result: Dict[str, Dict[str, Any]] = {}
    for entry in _usable_illustration_entries(project_id):
        if entry.get("role") == "main":
            continue
        section_id = str(entry.get("section_id") or "")
        if section_id:
            result[section_id] = entry
    return result


def _usable_main_illustration(project_id: str) -> Dict[str, Any] | None:
    """The first usable cover ("main") illustration, or None."""
    for entry in _usable_illustration_entries(project_id):
        if entry.get("role") == "main":
            return entry
    return None


def _apply_section_illustration(
    markdown: str, entry: Dict[str, Any] | None
) -> str:
    if not entry:
        return markdown
    return _insert_illustration(markdown, entry)


def _build_final_draft_content(
    inputs: FinalMergeInputs,
) -> tuple[Dict[str, Any], str, list[str], dict[str, Any] | None]:
    """Assemble and assess a final draft without writing artifacts or runs."""
    citations_enabled = bool(inputs.profile.get("citations_enabled", True))
    renumbered_drafts, used_sources = render_citations(
        [
            {
                "section": draft["section"],
                "markdown": draft["markdown"],
                "sources": (
                    draft.get("sources")
                    or _sources_for_section(
                        draft.get("section") or {},
                        inputs.chapter_sources,
                        inputs.research,
                        project_text=(
                            f"{inputs.project.title} {inputs.project.initial_request}"
                        ),
                    )[0]
                )
                if citations_enabled
                else [],
                "evidence": draft.get("evidence") or [],
                "evidence_validation": draft.get("evidence_validation"),
                "evidence_repair": draft.get("evidence_repair"),
            }
            for draft in inputs.section_drafts
        ],
        inputs.citation_style,
    )
    seam_ids: list[str] = []
    usage = None
    if settings.llm_enabled and settings.llm_merge_enabled:
        renumbered_drafts, usage, seam_ids = smooth_chapter_seams(
            inputs.project, inputs.brief, renumbered_drafts
        )
        merge_mode = "llm_seam"
    else:
        merge_mode = "local"
    illustrations_by_section = _usable_illustrations(inputs.project_id)
    merge_inputs = [
        {
            "section": draft["section"],
            "markdown": _apply_section_illustration(
                draft["markdown"],
                illustrations_by_section.get(
                    str((draft.get("section") or {}).get("id") or "")
                ),
            ),
        }
        for draft in renumbered_drafts
    ]
    final_markdown = _local_merge(
        inputs.project,
        merge_inputs,
        inputs.research,
        inputs.section_plan,
        used_sources,
        inputs.citation_style,
        accessed_at=inputs.research_cutoff,
        profile=inputs.profile,
    )
    # The merged draft starts with "# {title}", so the cover image lands right
    # under the document title.
    main_entry = _usable_main_illustration(inputs.project_id)
    if main_entry:
        final_markdown = _insert_illustration(final_markdown, main_entry)
    quality_summary = build_quality_summary(
        project_text=f"{inputs.project.title}\n{inputs.project.initial_request}",
        sources=used_sources,
        section_drafts=renumbered_drafts,
        continuity=inputs.continuity,
        rubric=inputs.rubric_review,
        citations_enabled=citations_enabled,
        sentence_repair=inputs.revision.get("sentence_quality_repair"),
        document_type=str(inputs.profile.get("key") or "report"),
    )
    return (
        {
            "format": "markdown",
            "markdown": final_markdown,
            "conditions": _draft_conditions(inputs.project_id),
            "quality": quality_summary,
        },
        merge_mode,
        seam_ids,
        usage,
    )


@dataclass(frozen=True)
class PreparedRunContext:
    project: ProjectRead
    profile: Dict[str, Any]
    agent_name: str
    classified_type: str | None
    classify_usage: dict[str, Any] | None
    decisions: list[UserDecisionRead]
    feedback_decisions: list[UserDecisionRead]
    input_cutoff: str


@dataclass(frozen=True)
class ResearchStageResult:
    research: Dict[str, Any]
    source_summaries: Dict[str, Any]
    research_cutoff: str
    source_summary_time: str
    artifact_ids: list[str]


@dataclass(frozen=True)
class BriefStageResult:
    brief: Dict[str, Any]
    brief_time: str
    doc_target: int
    artifact_ids: list[str]


@dataclass(frozen=True)
class OutlineStageResult:
    outline: Dict[str, Any]
    outline_review_time: str
    artifact_ids: list[str]
    waiting_result: WorkflowRunRead | None = None


@dataclass(frozen=True)
class SectionPlanStageResult:
    section_plan: Dict[str, Any]
    sections: list[Dict[str, Any]]
    section_plan_time: str
    section_plan_review_time: str
    artifact_ids: list[str]


@dataclass(frozen=True)
class ChapterResearchStageResult:
    chapter_sources: Dict[str, Any]
    chapter_research_time: str
    artifact_ids: list[str]


@dataclass(frozen=True)
class SectionWritingStageResult:
    section_drafts: list[Dict[str, Any]]
    summaries: list[Dict[str, Any]]
    section_work_time: str
    artifact_ids: list[str]


@dataclass(frozen=True)
class WrittenSectionResult:
    draft_content: Dict[str, Any]
    summary: Dict[str, Any]
    usage_entries: list[Dict[str, Any]]


@dataclass(frozen=True)
class FeedbackRevisionStageResult:
    section_drafts: list[Dict[str, Any]]
    section_work_time: str
    artifact_ids: list[str]


@dataclass(frozen=True)
class DocumentReviewStageResult:
    continuity: Dict[str, Any]
    rubric_review: Dict[str, Any]
    combined_review: Dict[str, Any]
    rubric_time: str
    artifact_ids: list[str]


@dataclass(frozen=True)
class TargetedRevisionStageResult:
    section_drafts: list[Dict[str, Any]]
    revision: Dict[str, Any]
    revision_time: str
    artifact_ids: list[str]


@dataclass(frozen=True)
class IllustrationStageResult:
    illustration_time: str
    artifact_ids: list[str]


def _waiting_for_user_result(project_id: str) -> WorkflowRunRead | None:
    existing_pending = list_pending_questions(project_id, status="pending")
    if not existing_pending:
        return None
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


def _prepare_generation_run(
    project_id: str, project: ProjectRead
) -> PreparedRunContext:
    """Resolve profile and split user decisions before stage execution."""
    agent_name = "llm_pipeline_writer" if settings.llm_enabled else "local_pipeline_writer"
    classified_type: str | None = None
    classify_usage: dict[str, Any] | None = None
    if settings.llm_enabled and not project.document_type:
        try:
            classified_type, classify_usage = classify_document_type(project)
        except LLMError:
            classified_type, classify_usage = None, None
        if classified_type:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE projects SET document_type = ?, updated_at = ? WHERE id = ?",
                    (classified_type, utc_now_iso(), project_id),
                )
            project = get_project(project_id) or project
    profile = get_doc_type_profile(project.document_type)

    # Process-control and per-section feedback decisions do not belong in the
    # global document prompt or its input cutoff.
    all_decisions = list_user_decisions(project_id)
    decisions = [
        decision
        for decision in all_decisions
        if decision.phase not in {"outline_approval", "section_feedback"}
    ]
    feedback_decisions = [
        decision for decision in all_decisions if decision.phase == "section_feedback"
    ]
    return PreparedRunContext(
        project=project,
        profile=profile,
        agent_name=agent_name,
        classified_type=classified_type,
        classify_usage=classify_usage,
        decisions=decisions,
        feedback_decisions=feedback_decisions,
        input_cutoff=_decision_cutoff(project, decisions),
    )


def _fail_pipeline_stage(
    project_id: str, run_id: str, phase: str, exc: Exception
) -> None:
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


def _run_intake_stage(
    project_id: str,
    prepared: PreparedRunContext,
    *,
    force_intake: bool,
) -> WorkflowRunRead | None:
    """Plan missing intake questions and pause the workflow when needed."""
    project = prepared.project
    decisions = prepared.decisions

    # A forced intake rerun re-plans questions even when answers exist: the
    # planner sees the saved decisions, so it only asks what is still missing
    # (or nothing, letting the run continue into drafting).
    if settings.llm_enabled and (not decisions or force_intake):
        run_id = _start_agent_run(
            project_id,
            prepared.agent_name,
            "intake",
            {
                "title": project.title,
                "initial_request": project.initial_request,
                "document_type": project.document_type,
                "forced": force_intake,
            },
        )
        try:
            planned_questions, question_usage = plan_user_questions(
                project, decisions, profile=prepared.profile
            )
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "intake", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        if prepared.classify_usage is not None:
            question_usage = {
                "questions": question_usage,
                "classification": prepared.classify_usage,
            }

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
        return None

    run_id = _start_agent_run(
        project_id,
        prepared.agent_name,
        "intake",
        {
            "decision_count": len(decisions),
            "llm_enabled": settings.llm_enabled,
            "document_type": project.document_type,
        },
    )
    _complete_agent_run(
        run_id,
        {"skipped_question_planning": True},
        token_usage=(
            {"classification": prepared.classify_usage}
            if prepared.classify_usage
            else None
        ),
    )
    return None


def _run_style_card_stage(
    project_id: str,
    project: ProjectRead,
    agent_name: str,
    input_cutoff: str,
) -> tuple[Dict[str, Any] | None, list[str]]:
    """Build or reuse the optional writing-style guide."""
    style_samples = [
        ref
        for ref in list_project_references(project_id)
        if ref.kind == "style"
        and ref.status == "ready"
        and (ref.content_text or "").strip()
    ]
    style_card: Dict[str, Any] | None = None
    artifact_ids: list[str] = []
    style_card_artifact = _latest_artifact(project_id, "style_card")
    if not style_samples:
        _complete_reuse_run(
            project_id,
            agent_name,
            "style_card",
            {"skipped": True, "reason": "no style samples"},
        )
    elif style_card_artifact is not None and _is_fresh(
        style_card_artifact.updated_at, input_cutoff
    ):
        style_card = style_card_artifact.content or {}
        artifact_ids.append(style_card_artifact.id)
        _complete_reuse_run(
            project_id,
            agent_name,
            "style_card",
            {"artifact_id": style_card_artifact.id},
        )
    elif not settings.llm_enabled:
        _complete_reuse_run(
            project_id,
            agent_name,
            "style_card",
            {"skipped": True, "reason": "llm disabled"},
        )
    else:
        run_id = _start_agent_run(
            project_id,
            agent_name,
            "style_card",
            {"sample_count": len(style_samples)},
        )
        try:
            style_card, usage = derive_style_card(project, style_samples)
        except LLMError as exc:
            _complete_agent_run(run_id, {"error": str(exc)}, status="completed")
            style_card = None
        else:
            with get_connection() as conn:
                artifact_id = _insert_artifact(
                    conn,
                    project_id,
                    "style_card",
                    "Style card",
                    style_card,
                    utc_now_iso(),
                    agent_name,
                )
            artifact_ids.append(artifact_id)
            _complete_agent_run(
                run_id, {"artifact_id": artifact_id}, token_usage=usage
            )

    return style_card, artifact_ids


def _run_research_stage(
    project_id: str,
    project: ProjectRead,
    decisions: list[UserDecisionRead],
    agent_name: str,
    input_cutoff: str,
) -> ResearchStageResult:
    """Build or reuse web research and its normalized source summaries."""
    if not effective_search_enabled(project_id):
        research: Dict[str, Any] = {"enabled": False, "results": []}
        source_summaries: Dict[str, Any] = {"sources": []}
        _complete_reuse_run(
            project_id,
            agent_name,
            "research",
            {"skipped": True, "reason": "disabled_by_profile_or_settings"},
        )
        _complete_reuse_run(
            project_id,
            agent_name,
            "source_summary",
            {"skipped": True, "reason": "research_disabled"},
        )
        _merge_reference_sources(
            list_project_references(project_id), research, source_summaries
        )
        research["source_summaries"] = source_summaries
        return ResearchStageResult(
            research=research,
            source_summaries=source_summaries,
            research_cutoff=input_cutoff,
            source_summary_time=input_cutoff,
            artifact_ids=[],
        )

    artifact_ids: list[str] = []
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
        try:
            research = search_web(project, decisions)
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "research", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        with get_connection() as conn:
            artifact_id = _insert_artifact(
                conn,
                project_id,
                "research_sources",
                "Web research sources",
                research,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(artifact_id)
        research_artifact = get_artifact(project_id, artifact_id)
        research_cutoff = (
            research_artifact.updated_at if research_artifact else utc_now_iso()
        )
        _complete_agent_run(
            run_id,
            {
                "artifact_id": artifact_id,
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
        try:
            source_summaries = summarize_search_sources(research)
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "source_summary", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        # Judge the freshly built sources in place before the artifact is stored
        # so the verdicts persist with them. Isolated so a judge failure never
        # fails the stage; the pipeline still runs on the P1 heuristics.
        try:
            topic_text = f"{project.title} {project.initial_request}"
            source_summaries["evaluation"] = evaluate_sources(
                source_summaries.get("sources") or [], topic_text
            )
        except Exception as exc:  # pragma: no cover - defensive isolation
            source_summaries["evaluation"] = {"enabled": True, "error": str(exc)}
        with get_connection() as conn:
            artifact_id = _insert_artifact(
                conn,
                project_id,
                "source_summaries",
                "Source summaries",
                source_summaries,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(artifact_id)
        source_summary_artifact = get_artifact(project_id, artifact_id)
        source_summary_time = (
            source_summary_artifact.updated_at
            if source_summary_artifact
            else utc_now_iso()
        )
        _complete_agent_run(
            run_id,
            {
                "artifact_id": artifact_id,
                "source_count": len(source_summaries.get("sources", [])),
                "evaluation": source_summaries.get("evaluation"),
            },
        )

    _merge_reference_sources(
        list_project_references(project_id), research, source_summaries
    )
    research["source_summaries"] = source_summaries
    return ResearchStageResult(
        research=research,
        source_summaries=source_summaries,
        research_cutoff=research_cutoff,
        source_summary_time=source_summary_time,
        artifact_ids=artifact_ids,
    )


def _run_brief_stage(
    project_id: str,
    project: ProjectRead,
    decisions: list[UserDecisionRead],
    research: Dict[str, Any],
    profile: Dict[str, Any],
    style_card: Dict[str, Any] | None,
    agent_name: str,
    input_cutoff: str,
    research_cutoff: str,
    source_summary_time: str,
) -> BriefStageResult:
    """Build or reuse the document brief and resolve its length budget."""
    artifact_ids: list[str] = []
    brief_artifact = _latest_artifact(project_id, "brief")
    brief_cutoff = max(input_cutoff, research_cutoff, source_summary_time)
    if brief_artifact is not None and _is_fresh(
        brief_artifact.updated_at, brief_cutoff
    ):
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
        try:
            if settings.llm_enabled:
                brief, usage = generate_brief(
                    project, decisions, research, profile=profile
                )
            else:
                brief, usage = _local_brief(project, decisions, research), None
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "brief", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        with get_connection() as conn:
            artifact_id = _insert_artifact(
                conn,
                project_id,
                "brief",
                "Generated brief",
                brief,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(artifact_id)
        brief_artifact = get_artifact(project_id, artifact_id)
        brief_time = brief_artifact.updated_at if brief_artifact else utc_now_iso()
        _complete_agent_run(
            run_id, {"artifact_id": artifact_id}, token_usage=usage
        )

    # The style card is authoritative for register: downstream prompts read
    # brief["style"], while the stored artifact keeps the original register.
    if style_card and str(style_card.get("register") or "").strip():
        brief = {**brief, "style": str(style_card["register"]).strip()}

    return BriefStageResult(
        brief=brief,
        brief_time=brief_time,
        doc_target=_document_target_length(project_id, brief),
        artifact_ids=artifact_ids,
    )


def _run_outline_stage(
    project_id: str,
    project: ProjectRead,
    brief: Dict[str, Any],
    profile: Dict[str, Any],
    agent_name: str,
    brief_time: str,
    doc_target: int,
) -> OutlineStageResult:
    """Build, review, and optionally wait for approval of the outline."""
    artifact_ids: list[str] = []
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
        run_id = _start_agent_run(
            project_id, agent_name, "outline", {"brief": brief}
        )
        try:
            if settings.llm_enabled:
                outline, usage = generate_outline(
                    project, brief, profile=profile, doc_target=doc_target
                )
            else:
                outline, usage = _local_outline(project, brief), None
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "outline", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        with get_connection() as conn:
            artifact_id = _insert_artifact(
                conn,
                project_id,
                "outline",
                "Generated outline",
                outline,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(artifact_id)
        outline_artifact = get_artifact(project_id, artifact_id)
        outline_time = outline_artifact.updated_at if outline_artifact else utc_now_iso()
        _complete_agent_run(
            run_id, {"artifact_id": artifact_id}, token_usage=usage
        )

    outline_review_artifact = _latest_artifact(project_id, "outline_review")
    if outline_review_artifact is not None and _is_fresh(
        outline_review_artifact.updated_at, outline_time
    ):
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
        try:
            if settings.llm_enabled:
                outline_review, usage = review_outline(project, brief, outline)
            else:
                outline_review, usage = {
                    "verdict": "pass",
                    "issues": [],
                    "recommended_changes": [],
                    "notes": "Local fallback review passed.",
                }, None
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "outline_review", exc)
            raise WorkflowRunFailedError(str(exc)) from exc

        # Apply the reviewer's corrected outline so the review actually shapes
        # the document instead of only being recorded.
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
                revised_outline_id = _insert_artifact(
                    conn,
                    project_id,
                    "outline",
                    "Revised outline",
                    outline,
                    utc_now_iso(),
                    agent_name,
                )
            artifact_ids.append(revised_outline_id)
        review_record = {
            key: value
            for key, value in outline_review.items()
            if key != "revised_outline"
        }
        review_record["revision_applied"] = revision_applied
        # Inserted after any revised outline so freshness ordering holds.
        with get_connection() as conn:
            review_artifact_id = _insert_artifact(
                conn,
                project_id,
                "outline_review",
                "Outline review",
                review_record,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(review_artifact_id)
        outline_review_artifact = get_artifact(project_id, review_artifact_id)
        outline_review_time = (
            outline_review_artifact.updated_at
            if outline_review_artifact
            else utc_now_iso()
        )
        _complete_agent_run(
            run_id,
            {
                "artifact_id": review_artifact_id,
                "verdict": outline_review.get("verdict"),
                "revision_applied": revision_applied,
            },
            token_usage=usage,
        )

    waiting_result: WorkflowRunRead | None = None
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
                    conn,
                    project_id,
                    "outline_approval",
                    question_payload,
                    waiting_at,
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
                raise RuntimeError(
                    "Project disappeared while waiting for outline approval"
                )
            waiting_result = WorkflowRunRead(
                project=updated_project,
                artifacts=[],
                pending_questions=list_pending_questions(project_id, status="pending"),
                status="waiting_for_user",
                message="Review and approve the outline, then start writing again.",
            )

    return OutlineStageResult(
        outline=outline,
        outline_review_time=outline_review_time,
        artifact_ids=artifact_ids,
        waiting_result=waiting_result,
    )


def _run_section_plan_stage(
    project_id: str,
    project: ProjectRead,
    brief: Dict[str, Any],
    outline: Dict[str, Any],
    research: Dict[str, Any],
    profile: Dict[str, Any],
    agent_name: str,
    outline_review_time: str,
    doc_target: int,
) -> SectionPlanStageResult:
    """Build, review, and length-balance the per-section writing plan."""
    artifact_ids: list[str] = []
    default_length = int(profile.get("default_section_length", 500))
    section_plan_artifact = _latest_artifact(project_id, "section_plan")
    if section_plan_artifact is not None and _is_fresh(
        section_plan_artifact.updated_at, outline_review_time
    ):
        section_plan = _normalize_section_plan(
            section_plan_artifact.content or {}, default_length
        )
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
        try:
            if settings.llm_enabled:
                section_plan, usage = generate_section_plan(
                    project,
                    brief,
                    outline,
                    research,
                    profile=profile,
                    doc_target=doc_target,
                )
            else:
                section_plan, usage = _local_section_plan(outline), None
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "section_plan", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        section_plan = _normalize_section_plan(section_plan, default_length)
        sections = section_plan["sections"]
        with get_connection() as conn:
            artifact_id = _insert_artifact(
                conn,
                project_id,
                "section_plan",
                "Generated section plan",
                section_plan,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(artifact_id)
        section_plan_artifact = get_artifact(project_id, artifact_id)
        section_plan_time = (
            section_plan_artifact.updated_at
            if section_plan_artifact
            else utc_now_iso()
        )
        _complete_agent_run(
            run_id,
            {"artifact_id": artifact_id, "section_count": len(sections)},
            token_usage=usage,
        )

    section_plan_review_artifact = _latest_artifact(
        project_id, "section_plan_review"
    )
    if section_plan_review_artifact is not None and _is_fresh(
        section_plan_review_artifact.updated_at, section_plan_time
    ):
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
        try:
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
            if (
                settings.llm_enabled
                and isinstance(nodes_to_expand, list)
                and nodes_to_expand
            ):
                revised_plan, revise_usage = _reexpand_section_plan(
                    project,
                    brief,
                    section_plan,
                    section_plan_review,
                    nodes_to_expand,
                    profile=profile,
                )
                if revised_plan is not None:
                    section_plan = _normalize_section_plan(
                        revised_plan, default_length
                    )
                    sections = section_plan["sections"]
                    revision_applied = True
                    if revise_usage and usage:
                        usage = {"review": usage, "reexpand": revise_usage}
                    elif revise_usage:
                        usage = {"reexpand": revise_usage}
                    with get_connection() as conn:
                        revised_plan_id = _insert_artifact(
                            conn,
                            project_id,
                            "section_plan",
                            "Revised section plan",
                            section_plan,
                            utc_now_iso(),
                            agent_name,
                        )
                    artifact_ids.append(revised_plan_id)
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "section_plan_review", exc)
            raise WorkflowRunFailedError(str(exc)) from exc

        section_plan_review = {
            **section_plan_review,
            "revision_applied": revision_applied,
        }
        # Inserted after any revised plan so freshness ordering holds.
        with get_connection() as conn:
            review_artifact_id = _insert_artifact(
                conn,
                project_id,
                "section_plan_review",
                "Section plan review",
                section_plan_review,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(review_artifact_id)
        section_plan_review_artifact = get_artifact(
            project_id, review_artifact_id
        )
        section_plan_review_time = (
            section_plan_review_artifact.updated_at
            if section_plan_review_artifact
            else utc_now_iso()
        )
        _complete_agent_run(
            run_id,
            {
                "artifact_id": review_artifact_id,
                "verdict": section_plan_review.get("verdict"),
                "revision_applied": revision_applied,
            },
            token_usage=usage,
        )

    # Stored plan artifacts keep the model's original lengths; the run-time
    # budget re-flows whichever plan survived review.
    section_plan = _scale_section_lengths(section_plan, doc_target)
    sections = section_plan["sections"]
    return SectionPlanStageResult(
        section_plan=section_plan,
        sections=sections,
        section_plan_time=section_plan_time,
        section_plan_review_time=section_plan_review_time,
        artifact_ids=artifact_ids,
    )


def _run_chapter_research_stage(
    project_id: str,
    project: ProjectRead,
    section_plan: Dict[str, Any],
    agent_name: str,
    section_plan_review_time: str,
) -> ChapterResearchStageResult:
    """Build or reuse the source pool assigned to each planned chapter."""
    if not effective_search_enabled(project_id):
        _complete_reuse_run(
            project_id,
            agent_name,
            "chapter_research",
            {"skipped": True, "reason": "disabled_by_profile_or_settings"},
        )
        return ChapterResearchStageResult(
            chapter_sources={"enabled": False, "chapters": []},
            chapter_research_time=section_plan_review_time,
            artifact_ids=[],
        )

    artifact_ids: list[str] = []
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
        try:
            chapter_sources = research_chapters(project, section_plan)
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "chapter_research", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        # One shared judge budget across every chapter's sources, evaluated in
        # place before the artifact is stored. Isolated so a judge failure never
        # fails the stage.
        try:
            topic_text = f"{project.title} {project.initial_request}"
            all_sources: list[Dict[str, Any]] = []
            for chapter in chapter_sources.get("chapters") or []:
                if isinstance(chapter, dict):
                    all_sources.extend(
                        source
                        for source in (chapter.get("sources") or [])
                        if isinstance(source, dict)
                    )
            chapter_sources["evaluation"] = evaluate_sources(all_sources, topic_text)
        except Exception as exc:  # pragma: no cover - defensive isolation
            chapter_sources["evaluation"] = {"enabled": True, "error": str(exc)}
        with get_connection() as conn:
            artifact_id = _insert_artifact(
                conn,
                project_id,
                "chapter_sources",
                "Chapter research sources",
                chapter_sources,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(artifact_id)
        chapter_sources_artifact = get_artifact(project_id, artifact_id)
        chapter_research_time = (
            chapter_sources_artifact.updated_at
            if chapter_sources_artifact
            else utc_now_iso()
        )
        _complete_agent_run(
            run_id,
            {
                "artifact_id": artifact_id,
                "chapter_count": len(chapter_sources.get("chapters", [])),
                "source_count": sum(
                    len(chapter.get("sources") or [])
                    for chapter in chapter_sources.get("chapters", [])
                ),
                "error": chapter_sources.get("error"),
                "evaluation": chapter_sources.get("evaluation"),
            },
        )

    return ChapterResearchStageResult(
        chapter_sources=chapter_sources,
        chapter_research_time=chapter_research_time,
        artifact_ids=artifact_ids,
    )


def _reuse_section_writing_stage(
    project_id: str,
    sections: list[Dict[str, Any]],
    agent_name: str,
    chapter_research_time: str,
    section_plan_time: str,
) -> SectionWritingStageResult | None:
    """Return the complete cached writing result only when drafts and summaries align."""
    reusable_drafts = _reusable_section_drafts(
        project_id,
        sections,
        chapter_research_time,
    )
    reusable_summaries = _reusable_section_summaries(project_id, sections)
    if reusable_drafts is None or reusable_summaries is None:
        return None

    section_draft_ids = [
        draft["artifact_id"]
        for draft in reusable_drafts
        if draft.get("artifact_id")
    ]
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
            "summary_count": len(reusable_summaries),
            "summary_mode": "combined_with_writing",
        },
    )
    section_work_time = max(
        [
            draft["updated_at"]
            for draft in reusable_drafts
            if draft.get("updated_at")
        ]
        or [section_plan_time]
    )
    return SectionWritingStageResult(
        section_drafts=reusable_drafts,
        summaries=reusable_summaries,
        section_work_time=section_work_time,
        artifact_ids=section_draft_ids,
    )


def _write_planned_section(
    project: ProjectRead,
    brief: Dict[str, Any],
    section: Dict[str, Any],
    previous_summary: Dict[str, Any] | None,
    section_sources: list[Dict[str, Any]],
    title_context: list[str],
    feedback: list[str],
    chapter_digests: list[Dict[str, Any]],
    glossary: list[str],
    profile: Dict[str, Any],
    style_card: Dict[str, Any] | None,
) -> WrittenSectionResult:
    """Write one planned section and validate or repair its evidence ledger."""
    usage_entries: list[Dict[str, Any]] = []
    if settings.llm_enabled:
        markdown, summary, usage = write_section_with_summary(
            project,
            brief,
            section,
            previous_summary,
            section_sources,
            title_context,
            feedback=feedback,
            chapter_digests=chapter_digests,
            glossary=glossary,
            profile=profile,
            style_card=style_card,
        )
    else:
        markdown, usage = _local_section_draft(
            project, section, previous_summary, section_sources, feedback
        ), None
        summary = _local_section_summary(section, markdown, profile=profile)
    if usage is not None:
        usage_entries.append(usage)
    markdown = _ensure_markdown_heading_number(
        markdown, section, numbered=profile.get("numbered_headings", True)
    )
    evidence = summary.get("evidence") or []
    evidence_validation = validate_evidence_ledger(
        markdown=markdown,
        evidence=evidence,
        sources=section_sources,
        section=section,
    )
    evidence_repair: Dict[str, Any] = {
        "attempted": False,
        "succeeded": evidence_validation.get("status") == "valid",
    }
    if (
        profile.get("citations_enabled", True)
        and evidence_validation.get("status") == "needs_review"
    ):
        cited_ids = evidence_validation.get("cited_source_ids") or []
        if not cited_ids:
            # Invalid unused ledger rows do not require another model call.
            evidence = evidence_validation.get("valid_entries") or []
            summary["evidence"] = evidence
            evidence_validation = validate_evidence_ledger(
                markdown=markdown,
                evidence=evidence,
                sources=section_sources,
                section=section,
            )
            evidence_repair = {
                "attempted": False,
                "succeeded": evidence_validation.get("status") == "valid",
                "mode": "discarded_unused_invalid_entries",
            }
        elif settings.llm_enabled:
            evidence_repair = {"attempted": True, "succeeded": False}
            try:
                repaired_markdown, repaired_evidence, repair_usage = (
                    repair_section_evidence(
                        project,
                        brief,
                        section,
                        markdown,
                        section_sources,
                        evidence_validation,
                    )
                )
            except LLMError as exc:
                evidence_repair["error"] = str(exc)
            else:
                markdown = _ensure_markdown_heading_number(
                    repaired_markdown,
                    section,
                    numbered=profile.get("numbered_headings", True),
                )
                evidence = repaired_evidence
                summary["evidence"] = evidence
                summary["claims"] = [
                    str(item.get("claim") or "").strip()
                    for item in evidence
                    if str(item.get("claim") or "").strip()
                ][:5]
                summary["summary"] = markdown.split("\n\n", 1)[-1][:500]
                evidence_validation = validate_evidence_ledger(
                    markdown=markdown,
                    evidence=evidence,
                    sources=section_sources,
                    section=section,
                )
                evidence_repair.update(
                    {
                        "succeeded": evidence_validation.get("status") == "valid",
                        "remaining_invalid_entries": evidence_validation.get(
                            "invalid_entry_count", 0
                        ),
                        "remaining_unverified_citations": len(
                            evidence_validation.get("unverified_citation_ids") or []
                        ),
                    }
                )
                if repair_usage is not None:
                    usage_entries.append(
                        {
                            "section_id": str(section.get("id", "")),
                            "evidence_repair": repair_usage,
                        }
                    )

    return WrittenSectionResult(
        draft_content={
            "section": section,
            "markdown": markdown,
            "sources": section_sources,
            "evidence": evidence,
            "evidence_validation": evidence_validation,
            "evidence_repair": evidence_repair,
        },
        summary=summary,
        usage_entries=usage_entries,
    )


def _run_new_section_writing_stage(
    project_id: str,
    project: ProjectRead,
    brief: Dict[str, Any],
    sections: list[Dict[str, Any]],
    section_plan: Dict[str, Any],
    chapter_sources: Dict[str, Any],
    research: Dict[str, Any],
    feedback_decisions: list[UserDecisionRead],
    profile: Dict[str, Any],
    style_card: Dict[str, Any] | None,
    agent_name: str,
) -> SectionWritingStageResult:
    """Write and persist every planned section with bounded context memory."""
    section_drafts: list[Dict[str, Any]] = []
    summaries: list[Dict[str, Any]] = []
    summary_ids: list[str] = []
    artifact_ids: list[str] = []
    previous_summary: Dict[str, Any] | None = None
    writing_usage: list[Dict[str, Any]] = []
    run_id = _start_agent_run(
        project_id,
        agent_name,
        "section_writing",
        {"section_count": len(sections)},
    )
    chapter_titles = _chapter_titles_from_plan(section_plan)
    topup_info: list[Dict[str, Any]] = []
    section_eval_info: list[Dict[str, Any]] = []
    chapter_digests: list[Dict[str, Any]] = []
    digest_usage: list[Dict[str, Any]] = []
    glossary_counts: dict[str, int] = {}
    current_chapter_id: str | None = None
    chapter_summaries: list[Dict[str, Any]] = []
    sections_done = 0
    set_stage_progress(project_id, "section_writing", 0, len(sections))
    try:
        for section in sections:
            if is_cancel_requested(project_id):
                raise WorkflowCancelledError()
            set_stage_progress(
                project_id, "section_writing", sections_done, len(sections)
            )
            section_chapter = str(section.get("id", "")).split(".")[0]
            if (
                current_chapter_id is not None
                and section_chapter != current_chapter_id
                and chapter_summaries
            ):
                # At chapter boundaries, keep a compact digest instead of the
                # full prior summary chain in later small-model prompts.
                digest, usage = _build_chapter_digest(
                    project,
                    current_chapter_id,
                    chapter_titles.get(current_chapter_id, ""),
                    chapter_summaries,
                )
                chapter_digests.append(digest)
                if usage is not None:
                    digest_usage.append(
                        {"chapter_id": current_chapter_id, **usage}
                    )
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

            project_text = f"{project.title} {project.initial_request}"
            # Budget counts real LLM attempts (successes and errors alike); cache
            # hits are free, so a flaky endpoint still stops after the cap.
            allow_section_eval = (
                settings.section_eval_enabled
                and settings.llm_enabled
                and sum(
                    1
                    for info in section_eval_info
                    if info.get("called") or info.get("error")
                )
                < settings.section_eval_limit
            )
            section_sources, section_fit = _sources_for_section(
                section,
                chapter_sources,
                research,
                project_text=project_text,
                section_eval_info=section_eval_info,
                allow_section_eval=allow_section_eval,
            )
            needs_source_quality_topup = (
                is_high_stakes_topic(project_text)
                and best_overlap_score(
                    section,
                    [
                        source
                        for source in section_sources
                        if grade_source(source)["tier"]
                        in {"authoritative", "institutional"}
                    ],
                )
                == 0
            )
            # A source the listwise judge scored relevant (>= 2) is not a reason
            # to re-search just because it lacks lexical overlap, so it suppresses
            # the "no_relevant_source" top-up (the high-stakes path is unchanged).
            eval_relevant = _eval_marks_relevant(section_sources, section_fit)
            if (
                effective_section_search_enabled(project_id)
                and effective_search_enabled(project_id)
                and len(topup_info) < settings.section_search_topup_limit
                and (
                    (
                        best_overlap_score(section, section_sources) == 0
                        and not eval_relevant
                    )
                    or needs_source_quality_topup
                )
            ):
                extra_sources, topup_error, topup_query = search_section_sources(
                    section,
                    settings.chapter_search_results,
                    project_text=project_text,
                )
                topup_info.append(
                    {
                        "section_id": str(section.get("id", "")),
                        "query": topup_query,
                        "engines": _unique_engines(extra_sources),
                        "source_count": len(extra_sources),
                        "reason": (
                            "missing_strong_source"
                            if needs_source_quality_topup
                            else "no_relevant_source"
                        ),
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
            written_section = _write_planned_section(
                project,
                brief,
                section,
                previous_summary,
                section_sources,
                _section_title_context(section, sections, chapter_titles),
                section_feedback,
                chapter_digests,
                glossary,
                profile,
                style_card,
            )
            draft_content = written_section.draft_content
            summary = written_section.summary
            writing_usage.extend(written_section.usage_entries)
            with get_connection() as conn:
                artifact_id = _insert_artifact(
                    conn,
                    project_id,
                    "section_draft",
                    f"Section {section.get('id', '')}: {section.get('title', '')}",
                    draft_content,
                    utc_now_iso(),
                    agent_name,
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
            artifact_ids.append(artifact_id)
            draft_artifact = get_artifact(project_id, artifact_id)
            section_drafts.append(
                {
                    **draft_content,
                    "artifact_id": artifact_id,
                    "updated_at": (
                        draft_artifact.updated_at
                        if draft_artifact
                        else utc_now_iso()
                    ),
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
            set_stage_progress(
                project_id, "section_writing", sections_done, len(sections)
            )

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
    except LLMError as exc:
        _fail_pipeline_stage(project_id, run_id, "section_writing", exc)
        raise WorkflowRunFailedError(str(exc)) from exc

    token_usage: Dict[str, Any] = {}
    if writing_usage:
        token_usage["section_calls"] = writing_usage
    if digest_usage:
        token_usage["digest_calls"] = digest_usage
    _complete_agent_run(
        run_id,
        {
            "section_artifact_ids": artifact_ids,
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
            **(
                {"section_evaluations": section_eval_info}
                if section_eval_info
                else {}
            ),
        },
        token_usage=token_usage or None,
    )
    clear_stage_progress(project_id)

    summary_run_id = _start_agent_run(
        project_id,
        agent_name,
        "section_summary",
        {"section_count": len(section_drafts)},
    )
    _complete_agent_run(
        summary_run_id,
        {
            "summary_ids": summary_ids,
            "summary_count": len(summaries),
            "summary_mode": "combined_with_writing",
        },
    )
    section_work_time = max(
        [
            draft["updated_at"]
            for draft in section_drafts
            if draft.get("updated_at")
        ]
        or [utc_now_iso()]
    )
    return SectionWritingStageResult(
        section_drafts=section_drafts,
        summaries=summaries,
        section_work_time=section_work_time,
        artifact_ids=artifact_ids,
    )


def _persist_revised_section_draft(
    project_id: str,
    draft: Dict[str, Any],
    markdown: str,
    title: str,
    agent_name: str,
) -> str:
    """Persist a revised section as a new section_draft version.

    Re-validates the evidence ledger against the revised markdown so a
    revision does not permanently downgrade evidence status to "stale"."""
    section = draft.get("section") or {}
    sources = draft.get("sources") or []
    evidence = draft.get("evidence") or []
    evidence_validation = validate_evidence_ledger(
        markdown=markdown,
        evidence=evidence,
        sources=sources,
        section=section,
    )
    evidence_repair = {
        "attempted": False,
        "succeeded": False,
        "reason": "revalidated_after_revision",
    }
    draft_content = {
        "section": section,
        "markdown": markdown,
        "sources": sources,
        "evidence": evidence,
        "evidence_validation": evidence_validation,
        "evidence_repair": evidence_repair,
    }
    with get_connection() as conn:
        artifact_id = _insert_artifact(
            conn, project_id, "section_draft", title, draft_content,
            utc_now_iso(), agent_name,
        )
    artifact = get_artifact(project_id, artifact_id)
    draft["markdown"] = markdown
    draft["evidence_validation"] = evidence_validation
    draft["evidence_repair"] = evidence_repair
    draft["artifact_id"] = artifact_id
    draft["updated_at"] = artifact.updated_at if artifact else utc_now_iso()
    return artifact_id


def _run_feedback_revision_stage(
    project_id: str,
    project: ProjectRead,
    brief: Dict[str, Any],
    profile: Dict[str, Any],
    feedback_decisions: list[UserDecisionRead],
    section_drafts: list[Dict[str, Any]],
    section_work_time: str,
    agent_name: str,
) -> FeedbackRevisionStageResult:
    """Apply only feedback newer than each section's current draft."""
    pending_feedback = _pending_section_feedback(feedback_decisions, section_drafts)
    if not pending_feedback:
        _complete_reuse_run(
            project_id,
            agent_name,
            "feedback_revision",
            {"applied_sections": [], "comment_count": 0},
        )
        return FeedbackRevisionStageResult(
            section_drafts=section_drafts,
            section_work_time=section_work_time,
            artifact_ids=[],
        )

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
    artifact_ids: list[str] = []
    try:
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
            markdown = _ensure_markdown_heading_number(
                markdown,
                section,
                numbered=profile.get("numbered_headings", True),
            )
            artifact_id = _persist_revised_section_draft(
                project_id,
                draft,
                markdown,
                f"Section {section_id}: feedback applied",
                agent_name,
            )
            artifact_ids.append(artifact_id)
            applied_sections.append(section_id)
            if usage is not None:
                feedback_usage.append({"section_id": section_id, **usage})
    except LLMError as exc:
        _fail_pipeline_stage(project_id, run_id, "feedback_revision", exc)
        raise WorkflowRunFailedError(str(exc)) from exc

    section_work_time = max(
        [section_work_time]
        + [
            draft["updated_at"]
            for draft in section_drafts
            if draft.get("updated_at")
        ]
    )
    _complete_agent_run(
        run_id,
        {
            "applied_sections": applied_sections,
            "comment_count": sum(len(items) for items in pending_feedback.values()),
        },
        token_usage={"section_calls": feedback_usage} if feedback_usage else None,
    )
    return FeedbackRevisionStageResult(
        section_drafts=section_drafts,
        section_work_time=section_work_time,
        artifact_ids=artifact_ids,
    )


_TARGETED_REVISION_TITLE = "targeted revision"


def _review_input_time(project_id: str, section_work_time: str) -> str:
    """Newest section-draft change the reviews are required to have seen.

    Draft versions persisted by the targeted-revision stage do not count: the
    reviews that triggered that revision had already covered everything else,
    so counting them would mark the reviews stale right after their own
    revision ran and re-run the whole review chain on every later workflow
    run, whatever stage the user forced.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT MAX(COALESCE(updated_at, created_at)) AS latest
            FROM artifacts
            WHERE project_id = ? AND type = 'section_draft'
              AND title NOT LIKE ?
            """,
            (project_id, f"%{_TARGETED_REVISION_TITLE}"),
        ).fetchone()
    latest = row["latest"] if row else None
    return latest or section_work_time


def _run_document_review_stage(
    project_id: str,
    project: ProjectRead,
    brief: Dict[str, Any],
    profile: Dict[str, Any],
    section_drafts: list[Dict[str, Any]],
    summaries: list[Dict[str, Any]],
    section_work_time: str,
    agent_name: str,
) -> DocumentReviewStageResult:
    """Run or reuse continuity and document-type rubric reviews."""
    artifact_ids: list[str] = []
    continuity_artifact = _latest_artifact(project_id, "continuity_review")
    if continuity_artifact is not None and _is_fresh(
        continuity_artifact.updated_at,
        _review_input_time(project_id, section_work_time),
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
        try:
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
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "continuity_review", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        with get_connection() as conn:
            artifact_id = _insert_artifact(
                conn,
                project_id,
                "continuity_review",
                "Continuity review",
                continuity,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(artifact_id)
        continuity_artifact = get_artifact(project_id, artifact_id)
        continuity_time = (
            continuity_artifact.updated_at if continuity_artifact else utc_now_iso()
        )
        _complete_agent_run(
            run_id,
            {"artifact_id": artifact_id, "verdict": continuity.get("verdict")},
            token_usage=usage,
        )

    rubric_artifact = _latest_artifact(project_id, "rubric_review")
    if rubric_artifact is not None and _is_fresh(
        rubric_artifact.updated_at, continuity_time
    ):
        rubric_review = rubric_artifact.content or {}
        artifact_ids.append(rubric_artifact.id)
        _complete_reuse_run(
            project_id,
            agent_name,
            "rubric_review",
            {"artifact_id": rubric_artifact.id},
        )
        rubric_time = rubric_artifact.updated_at
    else:
        run_id = _start_agent_run(
            project_id,
            agent_name,
            "rubric_review",
            {
                "section_count": len(section_drafts),
                "document_type": profile.get("key"),
            },
        )
        try:
            if settings.llm_enabled:
                rubric_review, usage = review_rubric_staged(
                    project, brief, profile, section_drafts
                )
            else:
                rubric_review, usage = {
                    "verdict": "pass",
                    "criteria": [],
                    "issues": [],
                    "revision_targets": [],
                    "notes": "Local fallback rubric review passed.",
                }, None
        except LLMError as exc:
            _fail_pipeline_stage(project_id, run_id, "rubric_review", exc)
            raise WorkflowRunFailedError(str(exc)) from exc
        with get_connection() as conn:
            artifact_id = _insert_artifact(
                conn,
                project_id,
                "rubric_review",
                "Rubric review",
                rubric_review,
                utc_now_iso(),
                agent_name,
            )
        artifact_ids.append(artifact_id)
        rubric_artifact = get_artifact(project_id, artifact_id)
        rubric_time = rubric_artifact.updated_at if rubric_artifact else utc_now_iso()
        _complete_agent_run(
            run_id,
            {
                "artifact_id": artifact_id,
                "verdict": rubric_review.get("verdict"),
                "scores": {
                    str(item.get("key")): item.get("average_score")
                    for item in (rubric_review.get("criteria") or [])
                    if isinstance(item, dict)
                },
            },
            token_usage=usage,
        )

    return DocumentReviewStageResult(
        continuity=continuity,
        rubric_review=rubric_review,
        combined_review=_combine_reviews(continuity, rubric_review),
        rubric_time=rubric_time,
        artifact_ids=artifact_ids,
    )


def _run_targeted_revision_stage(
    project_id: str,
    project: ProjectRead,
    brief: Dict[str, Any],
    section_drafts: list[Dict[str, Any]],
    continuity: Dict[str, Any],
    rubric_review: Dict[str, Any],
    combined_review: Dict[str, Any],
    rubric_time: str,
    agent_name: str,
) -> TargetedRevisionStageResult:
    """Apply review targets and bounded sentence-quality repair."""
    revision_artifact = _latest_artifact(project_id, "targeted_revision")
    if revision_artifact is not None and _is_fresh(
        revision_artifact.updated_at, rubric_time
    ):
        revision = revision_artifact.content or {}
        legacy_sections = revision.get("sections")
        if isinstance(legacy_sections, list) and legacy_sections:
            # Pre-persistence artifacts carry revisions only here; keep applying them.
            section_drafts = apply_section_revisions(section_drafts, legacy_sections)
        _complete_reuse_run(
            project_id,
            agent_name,
            "targeted_revision",
            {"artifact_id": revision_artifact.id},
        )
        return TargetedRevisionStageResult(
            section_drafts=section_drafts,
            revision=revision,
            revision_time=revision_artifact.updated_at,
            artifact_ids=[revision_artifact.id],
        )

    run_id = _start_agent_run(
        project_id,
        agent_name,
        "targeted_revision",
        {
            "continuity_verdict": continuity.get("verdict"),
            "rubric_verdict": rubric_review.get("verdict"),
            "target_count": len(combined_review.get("revision_targets") or []),
        },
    )
    try:
        if settings.llm_enabled:
            revised_sections, usage = revise_targeted_sections(
                project, brief, section_drafts, combined_review
            )
        else:
            revised_sections, usage = section_drafts, None
        merged_sections = apply_section_revisions(section_drafts, revised_sections)
        sentence_repair_report: Dict[str, Any] = {
            "enabled": bool(
                settings.llm_enabled
                and getattr(settings, "sentence_quality_repair_enabled", True)
            ),
            "attempted": False,
            "initial_issue_count": 0,
            "final_issue_count": 0,
            "attempted_section_count": 0,
            "repaired_section_count": 0,
            "results": [],
            "remaining_issues": [],
        }
        sentence_repair_usage = None
        if sentence_repair_report["enabled"]:
            project_text = f"{project.title} {project.initial_request}"
            high_stakes = is_high_stakes_topic(project_text)
            initial_sentence_quality = sentence_quality_stats(
                merged_sections,
                high_stakes=high_stakes,
            )
            if initial_sentence_quality["issue_count"]:
                (
                    merged_sections,
                    sentence_repair_report,
                    sentence_repair_usage,
                ) = repair_sentence_quality_sections(
                    project,
                    brief,
                    merged_sections,
                    initial_sentence_quality,
                    high_stakes=high_stakes,
                    limit=getattr(settings, "sentence_quality_repair_limit", 3),
                )
                sentence_repair_report["enabled"] = True
    except LLMError as exc:
        _fail_pipeline_stage(project_id, run_id, "targeted_revision", exc)
        raise WorkflowRunFailedError(str(exc)) from exc

    # Persist each actually-revised section as a new section_draft version so
    # downstream reviews evaluate the revised text (and re-validate evidence)
    # instead of relying on runtime re-application from this artifact.
    revised_ids: list[str] = []
    persisted_artifact_ids: list[str] = []
    final_sections: list[Dict[str, Any]] = []
    for original, merged in zip(section_drafts, merged_sections):
        if merged is original or merged.get("markdown") == original.get("markdown"):
            final_sections.append(original)
            continue
        updated = dict(merged)
        section_id = str((updated.get("section") or {}).get("id", ""))
        persisted_artifact_ids.append(
            _persist_revised_section_draft(
                project_id, updated, str(updated.get("markdown") or ""),
                # _review_input_time matches on this title to exclude these
                # versions from review staleness; keep the two in sync.
                f"Section {section_id}: {_TARGETED_REVISION_TITLE}", agent_name,
            )
        )
        revised_ids.append(section_id)
        final_sections.append(updated)

    revision = {
        "changed": bool(revised_ids),
        "revised_section_ids": revised_ids,
        "continuity_verdict": continuity.get("verdict"),
        "rubric_verdict": rubric_review.get("verdict"),
        "sentence_quality_repair": sentence_repair_report,
    }
    section_drafts = final_sections
    with get_connection() as conn:
        artifact_id = _insert_artifact(
            conn,
            project_id,
            "targeted_revision",
            "Targeted revision",
            revision,
            utc_now_iso(),
            agent_name,
        )
    revision_artifact = get_artifact(project_id, artifact_id)
    revision_time = (
        revision_artifact.updated_at if revision_artifact else utc_now_iso()
    )
    _complete_agent_run(
        run_id,
        {
            "artifact_id": artifact_id,
            "changed": revision["changed"],
            "revised_section_ids": revised_ids,
            "sentence_quality_repair": sentence_repair_report,
        },
        token_usage=(
            {
                "reviewer_revision": usage,
                "sentence_quality_repair": sentence_repair_usage,
            }
            if usage or sentence_repair_usage
            else None
        ),
    )
    return TargetedRevisionStageResult(
        section_drafts=section_drafts,
        revision=revision,
        revision_time=revision_time,
        artifact_ids=persisted_artifact_ids + [artifact_id],
    )


def _illustration_conditions(
    config: Dict[str, str], options: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "provider": config.get("provider"),
        "model": config.get("model"),
        "size": settings.image_size,
        "max_images": options["max_images"],
        # A style change must re-plan and re-generate, not reuse a cached plan.
        "style": options["style"],
        # Toggling either image kind changes the plan, so both invalidate reuse.
        "main_image": options["main_image"],
        "section_images": options["section_images"],
        "style_suffix": settings.image_style_suffix,
    }


def _document_language(project: ProjectRead) -> str:
    """Coarse label for caption/alt language: Korean if the request has Hangul."""
    text = f"{project.title} {project.initial_request}"
    return "Korean" if re.search(r"[가-힣]", text) else "English"


def _illustration_plan_has_failures(content: Dict[str, Any] | None) -> bool:
    """True when the stored plan recorded a planner error or a failed image."""
    data = content or {}
    if data.get("error"):
        return True
    return any(
        isinstance(entry, dict) and entry.get("status") == "failed"
        for entry in data.get("entries") or []
    )


def _run_illustration_stage(
    project_id: str,
    project: ProjectRead,
    section_drafts: list[Dict[str, Any]],
    summaries: list[Dict[str, Any]],
    revision_time: str,
    force_from: str | None,
    agent_name: str,
) -> IllustrationStageResult:
    """Plan and generate section illustrations after the drafts are final.

    Disabled by default: with no image provider the stage completes as a
    "skipped" reuse run and writes no artifact, so the document is unchanged. A
    failed image never fails the run — it is recorded on its entry and skipped.
    """
    if not image_generation_enabled():
        _complete_reuse_run(
            project_id,
            agent_name,
            "illustration",
            {"skipped": True, "reason": "disabled"},
        )
        return IllustrationStageResult(illustration_time=revision_time, artifact_ids=[])

    options = get_image_options()
    section_cap = options["max_images"] if options["section_images"] else 0
    if not options["main_image"] and section_cap <= 0:
        # A provider is configured but every image kind is turned off, so there
        # is nothing to generate; complete as a skipped reuse run like disabled.
        _complete_reuse_run(
            project_id,
            agent_name,
            "illustration",
            {"skipped": True, "reason": "no_image_targets"},
        )
        return IllustrationStageResult(illustration_time=revision_time, artifact_ids=[])

    config = get_active_image_config()
    conditions = _illustration_conditions(config, options)

    existing = _latest_artifact(project_id, "illustration_plan")
    # A plan with failures is never reused: failed API calls were not billed,
    # so retrying is free when the cause was transient, and images that did
    # generate are still served from the media cache.
    if (
        existing is not None
        and _is_fresh(existing.updated_at, revision_time)
        and ((existing.content or {}).get("conditions") == conditions)
        and not _illustration_plan_has_failures(existing.content)
        and force_from != "illustration"
    ):
        _complete_reuse_run(
            project_id,
            agent_name,
            "illustration",
            {"artifact_id": existing.id},
        )
        return IllustrationStageResult(
            illustration_time=existing.updated_at, artifact_ids=[existing.id]
        )

    run_id = _start_agent_run(
        project_id,
        agent_name,
        "illustration",
        {"section_count": len(section_drafts), "provider": config.get("provider")},
    )

    summary_by_id = {
        str(item.get("section_id") or item.get("node_id") or ""): str(
            item.get("summary") or ""
        )
        for item in summaries
        if isinstance(item, dict)
    }
    planner_sections: list[Dict[str, Any]] = []
    drafts_markdown_by_section_id: Dict[str, str] = {}
    for draft in section_drafts:
        section = draft.get("section") or {}
        section_id = str(section.get("id") or "")
        if not section_id:
            continue
        drafts_markdown_by_section_id[section_id] = str(draft.get("markdown") or "")
        planner_sections.append(
            {
                "id": section_id,
                "title": str(section.get("title") or ""),
                "summary": summary_by_id.get(section_id, ""),
            }
        )

    entries: list[Dict[str, Any]] = []
    plan_error: str | None = None
    usage = None
    main_item: Dict[str, Any] | None = None
    if planner_sections and settings.llm_enabled:
        try:
            parsed, parsed_main, usage = plan_section_illustrations(
                planner_sections,
                max_images=section_cap,
                language=_document_language(project),
                style=options["style"],
                include_main=options["main_image"],
                document_title=project.title,
            )
            selected = select_illustration_entries(
                parsed,
                planner_sections,
                drafts_markdown_by_section_id,
                section_cap,
                style=options["style"],
            )
            main_item = (
                select_main_illustration(parsed_main, options["style"])
                if options["main_image"]
                else None
            )
        except LLMError as exc:
            # A failed plan must not fail the run; record it and produce no images.
            plan_error = str(exc)
            selected = []
            main_item = None
    else:
        selected = []

    # The cover image (if any) generates first, then the per-section images. Both
    # kinds share one loop; the entry's "role" tells the merge where each goes.
    targets: list[Dict[str, Any]] = []
    if main_item:
        targets.append({"section_id": "", "role": "main", **main_item})
    for item in selected:
        targets.append({"role": "section", **item})

    generated = cached = failed = 0
    for item in targets:
        if is_cancel_requested(project_id):
            raise WorkflowCancelledError()
        prompt = item["prompt"]
        path = _cache_image_path(config, prompt)
        pre_existing = path.exists()
        entry: Dict[str, Any] = {
            "section_id": item["section_id"],
            "role": item["role"],
            "prompt": prompt,
            "caption": item["caption"],
            "alt": item["alt"],
            "file": path.name,
            "url": f"/media/{path.name}",
            "status": "cached" if pre_existing else "generated",
            "error": None,
        }
        try:
            generate_section_image(prompt, config=config)
        except ImageGenError as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            failed += 1
        else:
            if pre_existing:
                cached += 1
            else:
                generated += 1
        entries.append(entry)

    content = {
        "entries": entries,
        "conditions": conditions,
        "error": plan_error,
    }
    with get_connection() as conn:
        artifact_id = _insert_artifact(
            conn,
            project_id,
            "illustration_plan",
            "Section illustrations",
            content,
            utc_now_iso(),
            agent_name,
        )
    artifact = get_artifact(project_id, artifact_id)
    illustration_time = artifact.updated_at if artifact else utc_now_iso()
    _complete_agent_run(
        run_id,
        {
            "artifact_id": artifact_id,
            "generated": generated,
            "cached": cached,
            "failed": failed,
            "error": plan_error,
        },
        token_usage=usage,
    )
    return IllustrationStageResult(
        illustration_time=illustration_time, artifact_ids=[artifact_id]
    )


def _cache_image_path(config: Dict[str, str], prompt: str):
    """Mirror image_gen's cache filename so the plan can record it before generating."""
    from app.services.image_gen import _cache_path

    return _cache_path(
        config.get("provider") or "", config.get("model") or "", settings.image_size, prompt
    )


def _insert_illustration(markdown: str, entry: dict) -> str:
    """Insert the image block after the section's first heading line.

    Places a blank line, the image, a blank line, an italic caption, and a blank
    line right after the first ``#`` heading (or at the very top when there is no
    heading). alt/caption are lightly sanitized — brackets would break the image
    syntax — without heavy escaping.
    """

    def _safe(text: Any) -> str:
        return str(text or "").replace("[", "(").replace("]", ")").strip()

    alt = _safe(entry.get("alt")) or _safe(entry.get("caption"))
    url = str(entry.get("url") or "")
    caption = str(entry.get("caption") or "").replace("*", "").strip()
    image_line = f"![{alt}]({url})"
    block = [image_line]
    if caption:
        block.append("")
        block.append(f"*{caption}*")

    lines = markdown.split("\n")
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            insert_at = index + 1
            new_lines = (
                lines[:insert_at] + ["", *block, ""] + lines[insert_at:]
            )
            return "\n".join(new_lines)
    # No heading: prepend the block.
    return "\n".join([*block, "", markdown])


def run_document_generation(
    project_id: str, force_from: str | None = None
) -> Optional[WorkflowRunRead]:
    """Install the project's effective search options for the whole run, then
    delegate. The options reach the browser/LLM search helpers via a context
    variable, so the reset must wrap every exit path."""
    token = use_search_options(effective_search_options(project_id))
    try:
        return _run_document_generation(project_id, force_from)
    finally:
        reset_search_options(token)


def _run_document_generation(
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

    waiting_result = _waiting_for_user_result(project_id)
    if waiting_result is not None:
        return waiting_result

    prepared = _prepare_generation_run(project_id, project)
    project = prepared.project
    profile = prepared.profile
    agent_name = prepared.agent_name
    decisions = prepared.decisions
    feedback_decisions = prepared.feedback_decisions
    input_cutoff = prepared.input_cutoff
    artifact_ids: list[str] = []

    intake_result = _run_intake_stage(
        project_id,
        prepared,
        force_intake=force_from == "intake",
    )
    if intake_result is not None:
        return intake_result

    try:
        # Style card: distill the user's writing samples into a voice guide.
        # Best effort - a failed derivation records the error and the run
        # continues without a card.
        style_card, style_card_artifact_ids = _run_style_card_stage(
            project_id,
            project,
            agent_name,
            input_cutoff,
        )
        artifact_ids.extend(style_card_artifact_ids)

        research_result = _run_research_stage(
            project_id,
            project,
            decisions,
            agent_name,
            input_cutoff,
        )
        research = research_result.research
        source_summaries = research_result.source_summaries
        research_cutoff = research_result.research_cutoff
        source_summary_time = research_result.source_summary_time
        artifact_ids.extend(research_result.artifact_ids)

        brief_result = _run_brief_stage(
            project_id,
            project,
            decisions,
            research,
            profile,
            style_card,
            agent_name,
            input_cutoff,
            research_cutoff,
            source_summary_time,
        )
        brief = brief_result.brief
        brief_time = brief_result.brief_time
        doc_target = brief_result.doc_target
        artifact_ids.extend(brief_result.artifact_ids)

        outline_result = _run_outline_stage(
            project_id,
            project,
            brief,
            profile,
            agent_name,
            brief_time,
            doc_target,
        )
        if outline_result.waiting_result is not None:
            return outline_result.waiting_result
        outline = outline_result.outline
        outline_review_time = outline_result.outline_review_time
        artifact_ids.extend(outline_result.artifact_ids)

        section_plan_result = _run_section_plan_stage(
            project_id,
            project,
            brief,
            outline,
            research,
            profile,
            agent_name,
            outline_review_time,
            doc_target,
        )
        section_plan = section_plan_result.section_plan
        sections = section_plan_result.sections
        section_plan_time = section_plan_result.section_plan_time
        section_plan_review_time = section_plan_result.section_plan_review_time
        artifact_ids.extend(section_plan_result.artifact_ids)

        chapter_research_result = _run_chapter_research_stage(
            project_id,
            project,
            section_plan,
            agent_name,
            section_plan_review_time,
        )
        chapter_sources = chapter_research_result.chapter_sources
        chapter_research_time = chapter_research_result.chapter_research_time
        artifact_ids.extend(chapter_research_result.artifact_ids)

        writing_result = _reuse_section_writing_stage(
            project_id,
            sections,
            agent_name,
            chapter_research_time,
            section_plan_time,
        )
        if writing_result is not None:
            section_drafts = writing_result.section_drafts
            summaries = writing_result.summaries
            section_work_time = writing_result.section_work_time
            artifact_ids.extend(writing_result.artifact_ids)
        else:
            writing_result = _run_new_section_writing_stage(
                project_id,
                project,
                brief,
                sections,
                section_plan,
                chapter_sources,
                research,
                feedback_decisions,
                profile,
                style_card,
                agent_name,
            )
            section_drafts = writing_result.section_drafts
            summaries = writing_result.summaries
            section_work_time = writing_result.section_work_time
            artifact_ids.extend(writing_result.artifact_ids)

        # Fresh writes already receive feedback in their prompt; this stage only
        # applies comments that are newer than a reused draft.
        feedback_result = _run_feedback_revision_stage(
            project_id,
            project,
            brief,
            profile,
            feedback_decisions,
            section_drafts,
            section_work_time,
            agent_name,
        )
        section_drafts = feedback_result.section_drafts
        section_work_time = feedback_result.section_work_time
        artifact_ids.extend(feedback_result.artifact_ids)

        review_result = _run_document_review_stage(
            project_id,
            project,
            brief,
            profile,
            section_drafts,
            summaries,
            section_work_time,
            agent_name,
        )
        continuity = review_result.continuity
        rubric_review = review_result.rubric_review
        combined_review = review_result.combined_review
        rubric_time = review_result.rubric_time
        artifact_ids.extend(review_result.artifact_ids)

        revision_result = _run_targeted_revision_stage(
            project_id,
            project,
            brief,
            section_drafts,
            continuity,
            rubric_review,
            combined_review,
            rubric_time,
            agent_name,
        )
        section_drafts = revision_result.section_drafts
        revision = revision_result.revision
        revision_time = revision_result.revision_time
        artifact_ids.extend(revision_result.artifact_ids)

        illustration_result = _run_illustration_stage(
            project_id,
            project,
            section_drafts,
            summaries,
            revision_time,
            force_from,
            agent_name,
        )
        artifact_ids.extend(illustration_result.artifact_ids)
        # A refreshed illustration plan must re-merge the draft, so the merge's
        # freshness is gated on whichever of the two is newer.
        merge_cutoff = max(revision_time, illustration_result.illustration_time)

        citation_style = effective_citation_style(project_id)
        draft_artifact = _latest_artifact(project_id, "draft")
        # A citation-style change re-renders only this stage: section drafts
        # stay cached, but a draft merged under another style is stale.
        draft_style = ((draft_artifact.content or {}).get("conditions") or {}).get(
            "citation_style"
        ) if draft_artifact is not None else None
        if (
            draft_artifact is not None
            and _is_fresh(draft_artifact.updated_at, merge_cutoff)
            and draft_style == citation_style
            and force_from != "final_merge"
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
            final_content, merge_mode, seam_ids, usage = _build_final_draft_content(
                FinalMergeInputs(
                    project_id=project_id,
                    project=project,
                    profile=profile,
                    section_drafts=section_drafts,
                    chapter_sources=chapter_sources,
                    research=research,
                    brief=brief,
                    section_plan=section_plan,
                    research_cutoff=research_cutoff,
                    continuity=continuity,
                    rubric_review=rubric_review,
                    revision=revision,
                    citation_style=citation_style,
                )
            )
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

        quality_summary = get_project_quality_summary(project_id) or {"status": "review_needed"}
        final_status = (
            "review_needed"
            if quality_summary.get("status") == "review_needed"
            else "completed"
        )
        with get_connection() as conn:
            completed_at = utc_now_iso()
            conn.execute(
                """
                UPDATE projects
                SET status = ?, current_phase = ?, updated_at = ?
                WHERE id = ?
                """,
                (final_status, "final_merge", completed_at, project_id),
            )
    except LLMError as exc:
        current_project = get_project(project_id)
        _fail_pipeline_stage(
            project_id,
            run_id,
            current_project.current_phase if current_project else "unknown",
            exc,
        )
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
        status=updated_project.status,
        message=(
            "Draft generated; quality review is recommended."
            if updated_project.status == "review_needed"
            else "Staged writing pipeline completed."
        ),
    )


def _short_text(value: Any, limit: int = 500) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _unique_engines(sources: list[dict[str, Any]]) -> list[str]:
    """Ordered-unique, truthy search engine names across the given sources."""
    engines: list[str] = []
    for source in sources:
        engine = source.get("engine") if isinstance(source, dict) else None
        if engine and engine not in engines:
            engines.append(engine)
    return engines


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
                "queries": content.get("queries"),
                "query_source": content.get("query_source"),
                "engines": content.get("engines") or [],
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
                "engine": chapter.get("engine"),
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
        details["section_count"] = len(
            revision.get("revised_section_ids") or revision.get("sections") or []
        )
    elif phase == "illustration":
        plan = (artifacts_by_type.get("illustration_plan") or [{}])[-1].get("content") or {}
        entries = plan.get("entries") or []
        details["image_count"] = len(entries)
        details["generated_count"] = sum(
            1 for e in entries if isinstance(e, dict) and e.get("status") == "generated"
        )
        details["cached_count"] = sum(
            1 for e in entries if isinstance(e, dict) and e.get("status") == "cached"
        )
        details["failed_count"] = sum(
            1 for e in entries if isinstance(e, dict) and e.get("status") == "failed"
        )
        details["error"] = plan.get("error")
        details["images"] = [
            {
                "section_id": e.get("section_id"),
                "caption": _short_text(e.get("caption", ""), 120),
                "status": e.get("status"),
            }
            for e in entries[:8]
            if isinstance(e, dict)
        ]
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
        "style_card": artifact_times.get("style_card"),
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
        "rubric_review": artifact_times.get("rubric_review"),
        "targeted_revision": artifact_times.get("targeted_revision"),
        "illustration": artifact_times.get("illustration_plan"),
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
