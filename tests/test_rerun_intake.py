"""Rerunning the pipeline from the intake phase must re-collect questions.

Regression tests for two bugs: _invalidate_from_phase had no "intake"
entry (the force rerun silently did nothing), and question planning was
gated on "no decisions yet", so a project with saved answers could never
reach the question step again.
"""

from types import SimpleNamespace

import pytest

from app.db import repositories, session
from app.schemas.artifacts import ArtifactCreate
from app.schemas.projects import ProjectCreate
from app.schemas.questions import PendingQuestionCreate, QuestionAnswerCreate


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        session, "settings", SimpleNamespace(database_path=tmp_path / "test.sqlite3")
    )
    session.init_db()


def _project():
    return repositories.create_project(
        ProjectCreate(title="한글 프로젝트", initial_request="소논문을 한국어로 써줘")
    )


def _answered_question(project_id: str) -> None:
    question = repositories.create_pending_question(
        project_id,
        PendingQuestionCreate(phase="intake", question={"question": "Which audience?"}),
    )
    repositories.answer_pending_question(
        project_id, question.id, QuestionAnswerCreate(answer="고등학생")
    )


class TestInvalidateFromIntake:
    def test_drops_pending_questions_and_artifacts(self, temp_db):
        project = _project()
        _answered_question(project.id)
        repositories.create_pending_question(
            project.id,
            PendingQuestionCreate(phase="intake", question={"question": "Unanswered?"}),
        )
        repositories.create_artifact(
            project.id,
            ArtifactCreate(type="brief", title="Brief", content={"topic": "t"}),
        )

        repositories._invalidate_from_phase(project.id, "intake")

        assert repositories.list_pending_questions(project.id, status="pending") == []
        # Answered questions and their decisions survive as planner input.
        answered = repositories.list_pending_questions(project.id, status="answered")
        assert len(answered) == 1
        assert len(repositories.list_user_decisions(project.id)) == 1
        assert repositories._latest_artifact(project.id, "brief") is None


class TestPipelineStageRegistry:
    def test_registry_keys_are_unique_and_drive_workflow_order(self):
        keys = [stage.key for stage in repositories.PIPELINE_STAGES]
        assert len(keys) == len(set(keys))
        assert repositories.WORKFLOW_STEPS == [
            (stage.key, stage.label) for stage in repositories.PIPELINE_STAGES
        ]
        assert keys.index("feedback_revision") < keys.index("continuity_review")

    def test_feedback_rerun_keeps_drafts_but_clears_downstream_runs(self, temp_db):
        project = _project()
        draft = repositories.create_artifact(
            project.id,
            ArtifactCreate(type="section_draft", title="Section", content={}),
        )
        for phase in ("intake", "feedback_revision", "continuity_review", "final_merge"):
            repositories._start_agent_run(project.id, "test", phase, {})

        repositories._invalidate_from_phase(project.id, "feedback_revision")

        assert repositories.get_artifact(project.id, draft.id) is not None
        with session.get_connection() as conn:
            phases = [
                row["phase"]
                for row in conn.execute(
                    "SELECT phase FROM agent_runs WHERE project_id = ? ORDER BY created_at",
                    (project.id,),
                ).fetchall()
            ]
        assert phases == ["intake"]


class TestForcedIntakeRerun:
    def test_replans_questions_despite_existing_answers(self, temp_db, monkeypatch):
        project = _project()
        _answered_question(project.id)

        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(llm_enabled=True)
        )
        monkeypatch.setattr(
            repositories, "classify_document_type", lambda p: ("report", None)
        )
        captured = {}

        def fake_plan(proj, decisions, profile=None):
            captured["decision_count"] = len(decisions)
            return (
                [
                    {
                        "phase": "intake",
                        "question": "대상 독자는 누구인가요?",
                        "reason": "",
                        "priority": "high",
                    }
                ],
                None,
            )

        monkeypatch.setattr(repositories, "plan_user_questions", fake_plan)

        result = repositories.run_document_generation(project.id, force_from="intake")

        assert result.status == "waiting_for_user"
        # The planner saw the saved answer so it can avoid re-asking it.
        assert captured["decision_count"] == 1
        pending = repositories.list_pending_questions(project.id, status="pending")
        assert [q.question["question"] for q in pending] == ["대상 독자는 누구인가요?"]

    def test_unforced_rerun_still_skips_planning_with_answers(self, temp_db, monkeypatch):
        project = _project()
        _answered_question(project.id)

        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(llm_enabled=True)
        )
        monkeypatch.setattr(
            repositories, "classify_document_type", lambda p: ("report", None)
        )

        def fail_plan(*args, **kwargs):
            raise AssertionError("question planning must not run")

        monkeypatch.setattr(repositories, "plan_user_questions", fail_plan)
        # Stop the run right after the intake gate: the style-card stage is
        # the next thing that touches references.
        monkeypatch.setattr(
            repositories,
            "list_project_references",
            lambda pid: (_ for _ in ()).throw(RuntimeError("stop here")),
        )

        with pytest.raises(RuntimeError, match="stop here"):
            repositories.run_document_generation(project.id)
