"""Regression tests for the "Improve draft" rerun path.

The improve button forces a rerun from continuity_review. Two stage-spec
bugs made that rerun useless: continuity_review and targeted_revision did
not invalidate their own artifacts, so both stages were reused as "fresh"
and the run passed straight through; and the review/revision/merge stages
cleared the summaries table, which broke section-draft reuse and turned a
tail-only rerun into a full rewrite of every section.
"""

from types import SimpleNamespace

import pytest

from app.db import repositories, session
from app.schemas.artifacts import ArtifactCreate
from app.schemas.projects import ProjectCreate


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


def _seed_review_tail(project_id: str) -> dict[str, str]:
    ids = {}
    for artifact_type in (
        "section_draft",
        "continuity_review",
        "rubric_review",
        "targeted_revision",
        "draft",
    ):
        artifact = repositories.create_artifact(
            project_id,
            ArtifactCreate(type=artifact_type, title=artifact_type, content={}),
        )
        ids[artifact_type] = artifact.id
    with session.get_connection() as conn:
        repositories._insert_summary(
            conn,
            project_id,
            "s1",
            "section",
            {"section_id": "s1"},
            repositories.utc_now_iso(),
        )
    return ids


class TestImproveRerunInvalidation:
    def test_continuity_rerun_clears_review_tail_but_keeps_writing(self, temp_db):
        project = _project()
        ids = _seed_review_tail(project.id)

        repositories._invalidate_from_phase(project.id, "continuity_review")

        assert repositories.get_artifact(project.id, ids["section_draft"]) is not None
        # Prior final drafts stay as version history; only the review tail
        # is cleared so those stages actually re-run.
        assert repositories._latest_artifact(project.id, "draft") is not None
        for artifact_type in ("continuity_review", "rubric_review", "targeted_revision"):
            assert repositories._latest_artifact(project.id, artifact_type) is None
        # Summaries must survive or section writing loses its reuse path and
        # the improve run rewrites every section.
        assert repositories._list_section_summaries(project.id)

    def test_targeted_revision_rerun_clears_own_artifact(self, temp_db):
        project = _project()
        ids = _seed_review_tail(project.id)

        repositories._invalidate_from_phase(project.id, "targeted_revision")

        assert repositories._latest_artifact(project.id, "targeted_revision") is None
        assert repositories.get_artifact(project.id, ids["continuity_review"]) is not None
        assert repositories._list_section_summaries(project.id)

    def test_final_merge_rerun_keeps_summaries(self, temp_db):
        project = _project()
        _seed_review_tail(project.id)

        repositories._invalidate_from_phase(project.id, "final_merge")

        assert repositories._latest_artifact(project.id, "targeted_revision") is not None
        assert repositories._list_section_summaries(project.id)


def _draft_version(project_id: str, title: str, when: str) -> str:
    artifact = repositories.create_artifact(
        project_id, ArtifactCreate(type="section_draft", title=title, content={})
    )
    with session.get_connection() as conn:
        conn.execute(
            "UPDATE artifacts SET created_at = ?, updated_at = ? WHERE id = ?",
            (when, when, artifact.id),
        )
    return artifact.id


class TestReviewInputTime:
    """Reviews must not go stale from the revision they themselves triggered.

    Targeted revision persists revised drafts after the reviews run, so
    comparing review freshness against the newest draft made every later
    run re-run the whole review chain regardless of the forced stage.
    """

    def test_ignores_targeted_revision_versions(self, temp_db):
        project = _project()
        _draft_version(project.id, "Section 1.1: draft", "2026-01-01T00:00:01+00:00")
        _draft_version(
            project.id, "Section 1.1: targeted revision", "2026-01-01T00:00:03+00:00"
        )
        # A review written between the original draft and the revision it
        # triggered still counts as having seen everything it needed to.
        assert (
            repositories._review_input_time(project.id, "fallback")
            == "2026-01-01T00:00:01+00:00"
        )

    def test_counts_feedback_versions(self, temp_db):
        project = _project()
        _draft_version(project.id, "Section 1.1: draft", "2026-01-01T00:00:01+00:00")
        _draft_version(
            project.id, "Section 1.1: feedback applied", "2026-01-01T00:00:05+00:00"
        )
        assert (
            repositories._review_input_time(project.id, "fallback")
            == "2026-01-01T00:00:05+00:00"
        )

    def test_falls_back_without_drafts(self, temp_db):
        project = _project()
        assert repositories._review_input_time(project.id, "FALLBACK") == "FALLBACK"


# Snapshot of the invalidation graph derived from each stage's declared primary
# artifact type. Pins the derivation so a stage-order edit that shifts the tail
# is caught here instead of silently changing what a forced rerun clears.
_EXPECTED_INVALIDATION: dict[str, tuple[tuple[str, ...], bool]] = {
    "intake": (
        ("research_sources", "source_summaries", "brief", "outline", "outline_review",
         "section_plan", "section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "illustration_plan",
         "draft"),
        True,
    ),
    "style_card": (
        ("style_card", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "illustration_plan", "draft"),
        True,
    ),
    "research": (
        ("research_sources", "source_summaries", "brief", "outline", "outline_review",
         "section_plan", "section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "illustration_plan",
         "draft"),
        True,
    ),
    "source_summary": (
        ("source_summaries", "brief", "outline", "outline_review",
         "section_plan", "section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "illustration_plan",
         "draft"),
        True,
    ),
    "brief": (
        ("brief", "outline", "outline_review", "section_plan", "section_plan_review",
         "chapter_sources", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "illustration_plan", "draft"),
        True,
    ),
    "outline": (
        ("outline", "outline_review", "section_plan", "section_plan_review",
         "chapter_sources", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "illustration_plan", "draft"),
        True,
    ),
    "outline_review": (
        ("outline_review", "section_plan", "section_plan_review",
         "chapter_sources", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "illustration_plan", "draft"),
        True,
    ),
    "section_plan": (
        ("section_plan", "section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "illustration_plan",
         "draft"),
        True,
    ),
    "section_plan_review": (
        ("section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "illustration_plan",
         "draft"),
        True,
    ),
    "chapter_research": (
        ("chapter_sources", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "illustration_plan", "draft"),
        True,
    ),
    "section_writing": (
        ("section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "illustration_plan", "draft"),
        True,
    ),
    "section_summary": (
        ("continuity_review", "rubric_review", "targeted_revision",
         "illustration_plan", "draft"),
        True,
    ),
    "feedback_revision": (
        ("continuity_review", "rubric_review", "targeted_revision",
         "illustration_plan", "draft"),
        False,
    ),
    "continuity_review": (
        ("continuity_review", "rubric_review", "targeted_revision",
         "illustration_plan", "draft"),
        False,
    ),
    "rubric_review": (
        ("rubric_review", "targeted_revision", "illustration_plan", "draft"),
        False,
    ),
    "targeted_revision": (
        ("targeted_revision", "illustration_plan", "draft"),
        False,
    ),
    "illustration": (
        ("illustration_plan", "draft"),
        False,
    ),
    "final_merge": (
        ("draft",),
        False,
    ),
}


def test_derived_invalidation_table():
    derived = {
        stage.key: (
            repositories._stage_invalidates(stage.key),
            repositories._stage_clears_summaries(stage.key),
        )
        for stage in repositories.PIPELINE_STAGES
    }
    assert derived == _EXPECTED_INVALIDATION
