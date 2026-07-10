from types import SimpleNamespace

import pytest

from app.db import repositories, session
from app.schemas.artifacts import ArtifactCreate
from app.schemas.projects import ProjectCreate


def _stored_quality():
    return {
        "status": "review_needed",
        "high_stakes": False,
        "source_quality": {"strong_source_count": 0, "low_quality_count": 0},
        "citations": {},
        "evidence": {},
        "writing_quality": {
            "duplicate_pair_count": 1,
            "possible_contradiction_count": 0,
            "unsupported_overclaim_count": 0,
            "issue_count": 1,
            "issues": [
                {
                    "type": "duplicate",
                    "section_ids": ["1.1", "2.1"],
                    "excerpts": ["The same sentence appears twice."],
                }
            ],
        },
        "structure_quality": {
            "long_sentence_count": 0,
            "long_paragraph_count": 0,
            "list_heavy_section_count": 0,
            "heading_issue_count": 0,
            "missing_introduction": False,
            "missing_conclusion": False,
            "issue_count": 0,
            "issues": [],
        },
        "review": {"issue_count": 0, "revision_targets": []},
        "warnings": ["duplicate_content"],
    }


@pytest.fixture
def quality_project(tmp_path, monkeypatch):
    monkeypatch.setattr(
        session, "settings", SimpleNamespace(database_path=tmp_path / "quality.sqlite3")
    )
    session.init_db()
    project = repositories.create_project(
        ProjectCreate(title="Quality decisions", initial_request="Test the quality UI")
    )
    repositories.set_project_status(project.id, "review_needed", "final_merge")
    draft = repositories.create_artifact(
        project.id,
        ArtifactCreate(
            type="draft",
            title="Draft",
            content={"format": "markdown", "markdown": "# Draft", "quality": _stored_quality()},
        ),
    )
    return project.id, draft.id


def test_acknowledge_keeps_issue_active_and_waive_suppresses_it(quality_project):
    project_id, draft_id = quality_project
    initial = repositories.get_project_quality_summary(project_id)
    issue = initial["writing_quality"]["issues"][0]
    assert initial["draft_id"] == draft_id
    assert initial["writing_quality"]["active_issue_count"] == 1

    acknowledged = repositories.set_quality_issue_decision(
        project_id, issue["issue_key"], "acknowledged", "Checked against the draft"
    )
    assert acknowledged["status"] == "review_needed"
    assert acknowledged["writing_quality"]["active_issue_count"] == 1
    assert acknowledged["writing_quality"]["issues"][0]["decision"]["decision"] == "acknowledged"

    waived = repositories.set_quality_issue_decision(
        project_id, issue["issue_key"], "waived", "Intentional repetition"
    )
    assert waived["status"] == "ready"
    assert waived["writing_quality"]["active_issue_count"] == 0
    assert "duplicate_content" not in waived["warnings"]
    assert repositories.get_project(project_id).status == "completed"

    restored = repositories.delete_quality_issue_decision(project_id, issue["issue_key"])
    assert restored["status"] == "review_needed"
    assert restored["writing_quality"]["active_issue_count"] == 1
    assert repositories.get_project(project_id).status == "review_needed"


def test_decision_does_not_carry_to_a_new_draft_version(quality_project):
    project_id, draft_id = quality_project
    initial = repositories.get_project_quality_summary(project_id)
    issue_key = initial["writing_quality"]["issues"][0]["issue_key"]
    repositories.set_quality_issue_decision(
        project_id, issue_key, "waived", "Accepted only for this version"
    )

    new_draft = repositories.restore_draft_version(project_id, draft_id)
    current = repositories.get_project_quality_summary(project_id)
    assert current["draft_id"] == new_draft.id
    assert current["writing_quality"]["active_issue_count"] == 1
    assert "decision" not in current["writing_quality"]["issues"][0]


def test_unknown_issue_key_is_rejected(quality_project):
    project_id, _draft_id = quality_project
    with pytest.raises(repositories.UnknownQualityIssueError):
        repositories.set_quality_issue_decision(
            project_id, "not-a-current-issue", "waived", "Invalid"
        )
