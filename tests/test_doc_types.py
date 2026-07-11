from types import SimpleNamespace

import pytest

from app.db import repositories
from app.schemas.projects import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import llm
from app.services.doc_types import (
    DEFAULT_DOC_TYPE,
    DOC_TYPES,
    doc_type_choices,
    get_doc_type_profile,
    is_valid_doc_type,
)

REQUIRED_FIELDS = (
    "label_en",
    "label_ko",
    "research_default",
    "citations_enabled",
    "intake_priorities",
    "memory_schema",
    "generation_params",
    "numbered_headings",
    "default_section_length",
    "classify_hint",
    "style_hint",
    "brief_guidance",
    "outline_guidance",
    "section_guidance",
    "rubric",
)


def _project(document_type=None) -> ProjectRead:
    return ProjectRead(
        id="p1",
        title="t",
        initial_request="r",
        document_type=document_type,
        status="created",
        current_phase="intake",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


class TestRegistry:
    def test_every_profile_declares_all_fields(self):
        for key, profile in DOC_TYPES.items():
            for field in REQUIRED_FIELDS:
                assert field in profile, f"{key} missing {field}"

    def test_default_type_is_registered(self):
        assert is_valid_doc_type(DEFAULT_DOC_TYPE)

    def test_profile_fallback_for_unknown_or_none(self):
        assert get_doc_type_profile(None)["key"] == DEFAULT_DOC_TYPE
        assert get_doc_type_profile("nonsense")["key"] == DEFAULT_DOC_TYPE
        assert get_doc_type_profile("essay")["key"] == "essay"

    def test_choices_cover_registry(self):
        choices = doc_type_choices()
        assert [choice["key"] for choice in choices] == list(DOC_TYPES)
        assert all(choice["label_ko"] and choice["label_en"] for choice in choices)

    def test_intake_priorities_are_short_ordered_checklists(self):
        for key, profile in DOC_TYPES.items():
            priorities = profile["intake_priorities"]
            assert 3 <= len(priorities) <= 5, key
            assert all(isinstance(item, str) and item.strip() for item in priorities)

    def test_memory_schema_has_compact_distinct_fields(self):
        for key, profile in DOC_TYPES.items():
            schema = profile["memory_schema"]
            assert 2 <= len(schema) <= 4, key
            assert all(name and description for name, description in schema.items())
        assert "narrative_progress" in DOC_TYPES["essay"]["memory_schema"]
        assert "evidence_chain" in DOC_TYPES["academic_paper"]["memory_schema"]

    def test_generation_params_cover_pipeline_stages(self):
        expected = {
            "intake",
            "brief",
            "outline",
            "section_plan",
            "section_writing",
            "summary",
            "review",
            "revision",
        }
        for key, profile in DOC_TYPES.items():
            params = profile["generation_params"]
            assert set(params) == expected, key
            assert all(0 <= item["temperature"] <= 1.5 for item in params.values())
            assert all(256 <= item["max_tokens"] <= 12000 for item in params.values())
        assert (
            DOC_TYPES["essay"]["generation_params"]["section_writing"]["temperature"]
            > DOC_TYPES["tech_doc"]["generation_params"]["section_writing"]["temperature"]
        )


class TestSchemas:
    def test_create_normalizes_auto_to_none(self):
        for value in (None, "", "auto"):
            payload = ProjectCreate(title="t", initial_request="r", document_type=value)
            assert payload.document_type is None

    def test_create_rejects_unknown_type(self):
        with pytest.raises(ValueError):
            ProjectCreate(title="t", initial_request="r", document_type="poem")

    def test_update_keeps_auto_and_rejects_unknown(self):
        assert ProjectUpdate(document_type="auto").document_type == "auto"
        assert ProjectUpdate(document_type="essay").document_type == "essay"
        assert ProjectUpdate().document_type is None
        with pytest.raises(ValueError):
            ProjectUpdate(document_type="poem")


class TestProfileDefaults:
    def test_essay_disables_search_by_default(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        monkeypatch.setattr(repositories, "get_project", lambda pid: _project("essay"))
        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(search_enabled=True)
        )
        assert repositories.effective_search_enabled("p1") is False

    def test_explicit_override_beats_profile(self, monkeypatch):
        monkeypatch.setattr(
            repositories, "get_project_settings", lambda pid: {"search_enabled": True}
        )
        monkeypatch.setattr(repositories, "get_project", lambda pid: _project("essay"))
        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(search_enabled=True)
        )
        assert repositories.effective_search_enabled("p1") is True

    def test_profile_cannot_reenable_globally_disabled_search(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        monkeypatch.setattr(repositories, "get_project", lambda pid: _project("report"))
        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(search_enabled=False)
        )
        assert repositories.effective_search_enabled("p1") is False

    def test_explicit_override_cannot_bypass_global_search_gate(self, monkeypatch):
        monkeypatch.setattr(
            repositories, "get_project_settings", lambda pid: {"search_enabled": True}
        )
        monkeypatch.setattr(repositories, "get_project", lambda pid: _project("report"))
        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(search_enabled=False)
        )
        assert repositories.effective_search_enabled("p1") is False


class TestProfileStageGating:
    def test_disabled_research_skips_web_and_preserves_reference_pool(
        self, monkeypatch
    ):
        runs = []
        monkeypatch.setattr(
            repositories, "effective_search_enabled", lambda project_id: False
        )
        monkeypatch.setattr(
            repositories,
            "_complete_reuse_run",
            lambda *args, **kwargs: runs.append((args[2], args[3])),
        )
        reference = SimpleNamespace(
            kind="url",
            status="ready",
            content_text="User supplied evidence.",
            source="https://example.com/reference",
            title="Provided reference",
        )
        monkeypatch.setattr(
            repositories, "list_project_references", lambda pid: [reference]
        )
        monkeypatch.setattr(
            repositories,
            "_latest_artifact",
            lambda *args: pytest.fail("disabled research must not read artifacts"),
        )

        result = repositories._run_research_stage(
            "p1", _project("essay"), [], "writer", "2026-01-01T00:00:00Z"
        )

        assert result.research["enabled"] is False
        assert result.research["results"][0]["url"] == reference.source
        assert (
            result.source_summaries["sources"][0]["url"] == reference.source
        )
        assert result.artifact_ids == []
        assert [stage for stage, _payload in runs] == ["research", "source_summary"]

    def test_disabled_chapter_research_skips_artifacts(self, monkeypatch):
        runs = []
        monkeypatch.setattr(
            repositories, "effective_search_enabled", lambda project_id: False
        )
        monkeypatch.setattr(
            repositories,
            "_complete_reuse_run",
            lambda *args, **kwargs: runs.append((args[2], args[3])),
        )
        monkeypatch.setattr(
            repositories,
            "_latest_artifact",
            lambda *args: pytest.fail("disabled chapter research must not read artifacts"),
        )

        result = repositories._run_chapter_research_stage(
            "p1",
            _project("essay"),
            {"outline_tree": []},
            "writer",
            "2026-01-01T00:00:00Z",
        )

        assert result.chapter_sources == {"enabled": False, "chapters": []}
        assert result.artifact_ids == []
        assert runs[0][0] == "chapter_research"


class TestHeadingNumbering:
    def test_numbered_inserts_section_id(self):
        result = repositories._ensure_markdown_heading_number(
            "### Title\n\nBody.", {"id": "1.2", "title": "Title"}
        )
        assert result.startswith("### 1.2 Title")

    def test_unnumbered_keeps_plain_heading(self):
        result = repositories._ensure_markdown_heading_number(
            "### Title\n\nBody.", {"id": "1.2", "title": "Title"}, numbered=False
        )
        assert result.startswith("### Title")

    def test_unnumbered_strips_id_the_model_added(self):
        result = repositories._ensure_markdown_heading_number(
            "### 1.2 Title\n\nBody.", {"id": "1.2", "title": "Title"}, numbered=False
        )
        assert result.startswith("### Title")

    def test_unnumbered_adds_missing_heading_without_id(self):
        result = repositories._ensure_markdown_heading_number(
            "Body only.", {"id": "1.2", "title": "Title", "depth": 3}, numbered=False
        )
        assert result.startswith("### Title")


class TestLocalMergeProfiles:
    def test_citations_disabled_skips_sources_section(self):
        drafts = [
            {"section": {"id": "1.1", "title": "S"}, "markdown": "### S\n\nBody."}
        ]
        used = [{"title": "A", "url": "https://a.example.com"}]
        merged = repositories._local_merge(
            _project("essay"),
            drafts,
            {"results": used},
            None,
            used,
            profile=get_doc_type_profile("essay"),
        )
        assert "## Sources" not in merged

    def test_script_merge_has_no_heading_numbers(self):
        plan = {
            "outline_tree": [
                {"id": "1", "title": "Opening", "children": [
                    {"id": "1.1", "title": "Greeting", "children": []},
                ]},
            ]
        }
        drafts = [
            {"section": {"id": "1.1", "title": "Greeting"}, "markdown": "### Greeting\n\nHello."}
        ]
        merged = repositories._local_merge(
            _project("presentation_script"),
            drafts,
            None,
            plan,
            [],
            profile=get_doc_type_profile("presentation_script"),
        )
        assert "## Opening" in merged
        assert "## 1 Opening" not in merged
        assert "### Greeting" in merged


class TestClassifier:
    def test_returns_valid_key(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_json_chat", lambda s, u: ({"document_type": "essay"}, None)
        )
        key, _usage = llm.classify_document_type(_project())
        assert key == "essay"

    def test_unknown_key_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_json_chat", lambda s, u: ({"document_type": "poem"}, None)
        )
        key, _usage = llm.classify_document_type(_project())
        assert key == DEFAULT_DOC_TYPE
