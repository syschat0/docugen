from types import SimpleNamespace

from app.db import repositories, session
from app.schemas.artifacts import ArtifactCreate
from app.schemas.projects import ProjectCreate, ProjectRead
from app.services.doc_types import get_doc_type_profile


def _project(document_type="essay"):
    return ProjectRead(
        id="p1",
        title="A small document",
        initial_request="Write a concise draft",
        document_type=document_type,
        status="running",
        current_phase="final_merge",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_final_merge_builder_is_pure_and_respects_no_citation_profile(monkeypatch):
    monkeypatch.setattr(
        repositories,
        "settings",
        SimpleNamespace(llm_enabled=False, llm_merge_enabled=False),
    )
    monkeypatch.setattr(
        repositories, "_draft_conditions", lambda project_id: {"project_id": project_id}
    )
    inputs = repositories.FinalMergeInputs(
        project_id="p1",
        project=_project(),
        profile=get_doc_type_profile("essay"),
        section_drafts=[
            {
                "section": {"id": "1.1", "title": "Opening"},
                "markdown": "### Opening\n\nA reflective opening should not keep a stray citation [1].",
                "sources": [{"title": "Unused", "url": "https://example.com"}],
            },
            {
                "section": {"id": "2.1", "title": "Closing"},
                "markdown": "### Closing\n\nThe final image returns with a different meaning.",
                "sources": [],
            },
        ],
        chapter_sources=None,
        research=None,
        brief={"style": "reflective"},
        section_plan={"sections": []},
        research_cutoff=None,
        continuity={"verdict": "pass", "issues": []},
        rubric_review={"verdict": "pass", "issues": [], "criteria": []},
        revision={},
        citation_style="numeric",
    )

    content, mode, seams, usage = repositories._build_final_draft_content(inputs)

    assert mode == "local"
    assert seams == []
    assert usage is None
    assert "[1]" not in content["markdown"]
    assert "## Sources" not in content["markdown"]
    assert content["conditions"] == {"project_id": "p1"}
    assert content["quality"]["source_quality"]["total"] == 0


def test_final_merge_inserts_cover_image_under_title(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    (media / "cover.png").write_bytes(b"COVER")
    monkeypatch.setattr(
        session, "settings", SimpleNamespace(database_path=tmp_path / "test.sqlite3")
    )
    session.init_db()
    monkeypatch.setattr(
        repositories,
        "settings",
        SimpleNamespace(llm_enabled=False, llm_merge_enabled=False, media_dir=media),
    )
    monkeypatch.setattr(
        repositories, "_draft_conditions", lambda project_id: {"project_id": project_id}
    )

    project = repositories.create_project(
        ProjectCreate(title="A small document", initial_request="Write a concise draft")
    )
    repositories.create_artifact(
        project.id,
        ArtifactCreate(
            type="illustration_plan",
            title="Section illustrations",
            content={
                "entries": [
                    {
                        "section_id": "",
                        "role": "main",
                        "status": "generated",
                        "file": "cover.png",
                        "url": "/media/cover.png",
                        "alt": "cover alt",
                        "caption": "cover caption",
                    }
                ]
            },
        ),
    )

    inputs = repositories.FinalMergeInputs(
        project_id=project.id,
        project=project,
        profile=get_doc_type_profile("essay"),
        section_drafts=[
            {
                "section": {"id": "1.1", "title": "Opening"},
                "markdown": "### Opening\n\nA reflective opening paragraph.",
                "sources": [],
            },
        ],
        chapter_sources=None,
        research=None,
        brief={"style": "reflective"},
        section_plan={"sections": []},
        research_cutoff=None,
        continuity={"verdict": "pass", "issues": []},
        rubric_review={"verdict": "pass", "issues": [], "criteria": []},
        revision={},
        citation_style="numeric",
    )

    content, mode, seams, usage = repositories._build_final_draft_content(inputs)

    markdown = content["markdown"]
    lines = markdown.split("\n")
    assert lines[0] == "# A small document"
    assert "![cover alt](/media/cover.png)" in markdown
    # The cover image sits directly under the title, before the body.
    assert markdown.index("![cover alt]") < markdown.index("Opening")
