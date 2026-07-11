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


# Snapshot of the invalidation graph derived from each stage's declared primary
# artifact type. Pins the derivation so a stage-order edit that shifts the tail
# is caught here instead of silently changing what a forced rerun clears.
_EXPECTED_INVALIDATION: dict[str, tuple[tuple[str, ...], bool]] = {
    "intake": (
        ("research_sources", "source_summaries", "brief", "outline", "outline_review",
         "section_plan", "section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "draft"),
        True,
    ),
    "style_card": (
        ("style_card", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "draft"),
        True,
    ),
    "research": (
        ("research_sources", "source_summaries", "brief", "outline", "outline_review",
         "section_plan", "section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "draft"),
        True,
    ),
    "source_summary": (
        ("source_summaries", "brief", "outline", "outline_review",
         "section_plan", "section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "draft"),
        True,
    ),
    "brief": (
        ("brief", "outline", "outline_review", "section_plan", "section_plan_review",
         "chapter_sources", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "draft"),
        True,
    ),
    "outline": (
        ("outline", "outline_review", "section_plan", "section_plan_review",
         "chapter_sources", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "draft"),
        True,
    ),
    "outline_review": (
        ("outline_review", "section_plan", "section_plan_review",
         "chapter_sources", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "draft"),
        True,
    ),
    "section_plan": (
        ("section_plan", "section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "draft"),
        True,
    ),
    "section_plan_review": (
        ("section_plan_review", "chapter_sources", "section_draft",
         "continuity_review", "rubric_review", "targeted_revision", "draft"),
        True,
    ),
    "chapter_research": (
        ("chapter_sources", "section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "draft"),
        True,
    ),
    "section_writing": (
        ("section_draft", "continuity_review", "rubric_review",
         "targeted_revision", "draft"),
        True,
    ),
    "section_summary": (
        ("continuity_review", "rubric_review", "targeted_revision", "draft"),
        True,
    ),
    "feedback_revision": (
        ("continuity_review", "rubric_review", "targeted_revision", "draft"),
        False,
    ),
    "continuity_review": (
        ("continuity_review", "rubric_review", "targeted_revision", "draft"),
        False,
    ),
    "rubric_review": (
        ("rubric_review", "targeted_revision", "draft"),
        False,
    ),
    "targeted_revision": (
        ("targeted_revision", "draft"),
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
