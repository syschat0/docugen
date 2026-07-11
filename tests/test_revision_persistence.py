"""Targeted revision must persist revised sections as new section_draft
versions (and re-validate their evidence) instead of stashing them only in
the targeted_revision artifact.

Persisting lets the next continuity/rubric review evaluate the revised text
and clears the permanent "stale" evidence downgrade that the old runtime
re-application path left behind.
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


def _drafts():
    return [
        {"section": {"id": "1.1", "title": "Intro"}, "markdown": "original 1.1", "sources": [], "evidence": []},
        {"section": {"id": "2.1", "title": "Body"}, "markdown": "original 2.1", "sources": [], "evidence": []},
    ]


def _enable_llm(monkeypatch):
    monkeypatch.setattr(
        repositories,
        "settings",
        SimpleNamespace(llm_enabled=True, sentence_quality_repair_enabled=False),
    )


class TestTargetedRevisionPersistence:
    def test_revised_section_is_persisted_and_revalidated(self, temp_db, monkeypatch):
        project = _project()
        drafts = _drafts()
        _enable_llm(monkeypatch)

        def fake_revise(project, brief, section_drafts, combined_review):
            revised = {**section_drafts[0], "markdown": "revised 1.1"}
            return [revised], None

        monkeypatch.setattr(repositories, "revise_targeted_sections", fake_revise)

        result = repositories._run_targeted_revision_stage(
            project.id,
            project,
            {},
            drafts,
            {"verdict": "revise"},
            {"verdict": "revise"},
            {"revision_targets": ["1.1"]},
            "2000-01-01T00:00:00Z",
            "tester",
        )

        # (a) a new section_draft version exists for the revised section.
        persisted = repositories._latest_artifact(project.id, "section_draft")
        assert persisted is not None
        assert persisted.content["markdown"] == "revised 1.1"
        # (b) evidence was re-validated, not permanently marked stale.
        assert persisted.content["evidence_validation"]["status"] != "stale"
        # (c) the revision artifact reports ids and drops the inline sections blob.
        revision = repositories._latest_artifact(project.id, "targeted_revision").content
        assert revision["revised_section_ids"] == ["1.1"]
        assert "sections" not in revision
        # (d) the returned drafts carry the revised markdown.
        assert result.section_drafts[0]["markdown"] == "revised 1.1"
        assert result.section_drafts[1]["markdown"] == "original 2.1"

    def test_no_change_does_not_persist(self, temp_db, monkeypatch):
        project = _project()
        drafts = _drafts()
        _enable_llm(monkeypatch)

        def fake_revise(project, brief, section_drafts, combined_review):
            return section_drafts, None

        monkeypatch.setattr(repositories, "revise_targeted_sections", fake_revise)

        result = repositories._run_targeted_revision_stage(
            project.id,
            project,
            {},
            drafts,
            {"verdict": "pass"},
            {"verdict": "pass"},
            {"revision_targets": []},
            "2000-01-01T00:00:00Z",
            "tester",
        )

        assert repositories._latest_artifact(project.id, "section_draft") is None
        assert result.revision["changed"] is False
        assert result.revision["revised_section_ids"] == []

    def test_legacy_sections_artifact_is_reapplied(self, temp_db, monkeypatch):
        project = _project()
        drafts = _drafts()
        # A pre-persistence artifact stored the revision only inline. It must be
        # fresh relative to rubric_time so the reuse path is taken.
        repositories.create_artifact(
            project.id,
            ArtifactCreate(
                type="targeted_revision",
                title="Targeted revision",
                content={
                    "changed": True,
                    "sections": [
                        {"section": {"id": "1.1", "title": "Intro"}, "markdown": "legacy revised 1.1"},
                    ],
                },
            ),
        )

        result = repositories._run_targeted_revision_stage(
            project.id,
            project,
            {},
            drafts,
            {"verdict": "revise"},
            {"verdict": "revise"},
            {"revision_targets": ["1.1"]},
            "2000-01-01T00:00:00Z",
            "tester",
        )

        assert result.section_drafts[0]["markdown"] == "legacy revised 1.1"
        assert result.section_drafts[1]["markdown"] == "original 2.1"
