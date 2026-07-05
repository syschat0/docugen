import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.db.session import get_connection
from app.core.config import settings
from app.schemas.artifacts import ArtifactCreate, ArtifactRead
from app.schemas.exports import ExportRead
from app.schemas.projects import ProjectCreate, ProjectRead
from app.schemas.questions import (
    PendingQuestionCreate,
    PendingQuestionRead,
    QuestionAnswerCreate,
    UserDecisionRead,
)
from app.schemas.workflow import WorkflowProgressRead, WorkflowRunRead, WorkflowStepRead
from app.services.llm import (
    LLMError,
    apply_section_revisions,
    collect_leaf_titles,
    expand_chapter_subtree,
    generate_brief,
    generate_outline,
    generate_section_plan,
    merge_sections,
    plan_user_questions,
    review_continuity,
    review_outline,
    review_section_plan,
    revise_targeted_sections,
    select_relevant_sources,
    write_section_with_summary,
)
from app.services.search import research_chapters, search_web, summarize_search_sources


class QuestionAlreadyAnsweredError(Exception):
    pass


class WorkflowRunFailedError(Exception):
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
                "artifact_id": draft.id,
                "updated_at": draft.updated_at,
            }
        )
    return reusable


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
    research: Dict[str, Any] | None,
) -> str:
    handoff = previous_summary.get("next_section_handoff") if previous_summary else ""
    source = ""
    results = research.get("results", []) if research else []
    if results:
        source = f"\n\nReference note: see [{1}] {results[0].get('title', 'source')}."
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


def _local_merge(
    project: ProjectRead,
    section_drafts: list[Dict[str, Any]],
    research: Dict[str, Any] | None,
    section_plan: Dict[str, Any] | None = None,
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

    sources = research.get("results", []) if research else []
    source_lines = "\n".join(
        f"{index}. [{source.get('title', 'Source')}]({source.get('url', '')})"
        for index, source in enumerate(sources, start=1)
    )
    sources_section = f"\n\n## Sources\n\n{source_lines}\n" if source_lines else ""
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
    candidates: list[Dict[str, Any]] = []
    for chapter in (chapter_sources or {}).get("chapters") or []:
        if isinstance(chapter, dict) and str(chapter.get("chapter_id")) == chapter_id:
            candidates.extend(chapter.get("sources") or [])
    global_summaries = ((research or {}).get("source_summaries") or {}).get("sources") or []
    candidates.extend(source for source in global_summaries if isinstance(source, dict))
    if not candidates:
        candidates = [
            result
            for result in (research or {}).get("results") or []
            if isinstance(result, dict)
        ]
    return select_relevant_sources(section, candidates, limit=2)


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


def run_document_generation(
    project_id: str, force_from: str | None = None
) -> Optional[WorkflowRunRead]:
    project = get_project(project_id)
    if project is None:
        return None

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
    # they must not feed prompts or invalidate cached artifacts.
    decisions = [
        decision
        for decision in list_user_decisions(project_id)
        if decision.phase != "outline_approval"
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
            all_section_titles = [
                f"{item.get('id', '')} {item.get('title', '')}".strip()
                for item in sections
            ]
            for section in sections:
                if settings.llm_enabled:
                    markdown, summary, usage = write_section_with_summary(
                        project,
                        brief,
                        section,
                        previous_summary,
                        _sources_for_section(section, chapter_sources, research),
                        all_section_titles,
                    )
                else:
                    markdown, usage = _local_section_draft(
                        project, section, previous_summary, research
                    ), None
                    summary = _local_section_summary(section, markdown)
                if usage is not None:
                    writing_usage.append(usage)
                markdown = _ensure_markdown_heading_number(markdown, section)
                draft_content = {"section": section, "markdown": markdown}
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
                        "artifact_id": artifact_ids[-1],
                        "updated_at": draft_artifact.updated_at if draft_artifact else utc_now_iso(),
                    }
                )
                summaries.append(summary)
                previous_summary = summary
            _complete_agent_run(
                run_id,
                {
                    "section_artifact_ids": artifact_ids[-len(section_drafts) :],
                    "summary_ids": summary_ids,
                    "summary_mode": "combined_with_writing",
                },
                token_usage={"section_calls": writing_usage} if writing_usage else None,
            )

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
                continuity, usage = review_continuity(
                    project, brief, section_drafts, summaries
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

        draft_artifact = _latest_artifact(project_id, "draft")
        if draft_artifact is not None and _is_fresh(draft_artifact.updated_at, revision_time):
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
                        "llm" if settings.llm_enabled and settings.llm_merge_enabled else "local"
                    ),
                },
            )
            merge_inputs = [
                {"section": draft["section"], "markdown": draft["markdown"]}
                for draft in section_drafts
            ]
            if settings.llm_enabled and settings.llm_merge_enabled:
                final_markdown, usage = merge_sections(
                    project, brief, outline, merge_inputs, summaries, research
                )
                merge_mode = "llm"
            else:
                final_markdown, usage = _local_merge(
                    project, merge_inputs, research, section_plan
                ), None
                merge_mode = "local"
            final_content = {"format": "markdown", "markdown": final_markdown}
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
                {"artifact_id": artifact_ids[-1], "merge_mode": merge_mode},
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
        details["chapters"] = [
            {
                "id": chapter.get("chapter_id"),
                "title": chapter.get("title"),
                "query": chapter.get("query"),
                "source_count": len(chapter.get("sources") or []),
                "error": chapter.get("error"),
            }
            for chapter in chapters
            if isinstance(chapter, dict)
        ]
    elif phase == "section_writing":
        drafts = artifacts_by_type.get("section_draft") or []
        details["section_draft_count"] = len(drafts)
        details["section_drafts"] = [
            {
                "title": draft.get("title"),
                "preview": _short_text((draft.get("content") or {}).get("markdown", ""), 220),
            }
            for draft in drafts[:8]
        ]
    elif phase == "section_summary":
        parsed_summaries = []
        for summary in summaries[:8]:
            content = _json_loads(summary.get("summary_json")) or {}
            parsed_summaries.append(
                {
                    "section_id": content.get("section_id") or summary.get("node_id"),
                    "summary": _short_text(content.get("summary", ""), 220),
                }
            )
        details["summary_count"] = len(summaries)
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
        if markdown:
            details["draft_preview"] = _short_text(markdown, 500)
            details["character_count"] = len(markdown)

    return details


def get_workflow_progress(project_id: str) -> Optional[WorkflowProgressRead]:
    project = get_project(project_id)
    if project is None:
        return None

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
        steps.append(
            WorkflowStepRead(
                phase=phase,
                label=label,
                status=status,
                created_at=row["created_at"] if row is not None else inferred_time,
                completed_at=row["completed_at"] if row is not None else inferred_time,
                error=row["error"] if row is not None else None,
                details=details,
            )
        )

    percent = int((completed_count / len(WORKFLOW_STEPS)) * 100)
    if project.status == "completed":
        percent = 100

    return WorkflowProgressRead(
        project=project,
        steps=steps,
        percent=percent,
        current_phase=project.current_phase,
        status=project.status,
    )
