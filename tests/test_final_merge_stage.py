from types import SimpleNamespace

from app.db import repositories
from app.schemas.projects import ProjectRead
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
