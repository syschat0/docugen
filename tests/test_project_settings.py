from types import SimpleNamespace

from app.db import repositories
from app.schemas.projects import ProjectRead


def _project(created_at="2026-01-01T00:00:00+00:00") -> ProjectRead:
    return ProjectRead(
        id="p1",
        title="t",
        initial_request="r",
        status="created",
        current_phase="intake",
        created_at=created_at,
        updated_at=created_at,
    )


class TestEffectiveSettings:
    def test_override_takes_precedence_over_global(self, monkeypatch):
        monkeypatch.setattr(
            repositories, "get_project_settings", lambda pid: {"search_enabled": False}
        )
        monkeypatch.setattr(
            repositories,
            "settings",
            SimpleNamespace(search_enabled=True, section_search_enabled=False),
        )
        assert repositories.effective_search_enabled("p1") is False

    def test_none_falls_back_to_global_default(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        monkeypatch.setattr(
            repositories,
            "settings",
            SimpleNamespace(search_enabled=True, section_search_enabled=False),
        )
        assert repositories.effective_search_enabled("p1") is True
        assert repositories.effective_section_search_enabled("p1") is False

    def test_section_search_override(self, monkeypatch):
        monkeypatch.setattr(
            repositories,
            "get_project_settings",
            lambda pid: {"section_search_enabled": True},
        )
        monkeypatch.setattr(
            repositories,
            "settings",
            SimpleNamespace(search_enabled=True, section_search_enabled=False),
        )
        assert repositories.effective_section_search_enabled("p1") is True


class TestDecisionCutoff:
    def test_inputs_changed_at_extends_cutoff(self, monkeypatch):
        monkeypatch.setattr(
            repositories,
            "get_project_settings",
            lambda pid: {"inputs_changed_at": "2030-01-01T00:00:00+00:00"},
        )
        cutoff = repositories._decision_cutoff(_project(), [])
        assert cutoff == "2030-01-01T00:00:00+00:00"

    def test_no_input_change_uses_created_at(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        cutoff = repositories._decision_cutoff(_project("2026-05-05T00:00:00+00:00"), [])
        assert cutoff == "2026-05-05T00:00:00+00:00"


class TestDraftConditions:
    def test_snapshots_effective_flags_and_references(self, monkeypatch):
        monkeypatch.setattr(repositories, "list_project_references", lambda pid: [])
        monkeypatch.setattr(repositories, "effective_search_enabled", lambda pid: False)
        monkeypatch.setattr(repositories, "effective_section_search_enabled", lambda pid: True)
        monkeypatch.setattr(
            repositories,
            "settings",
            SimpleNamespace(llm_model="fallback-model"),
        )
        conditions = repositories._draft_conditions("p1")
        assert conditions["search_enabled"] is False
        assert conditions["section_search_enabled"] is True
        assert conditions["reference_count"] == 0
        assert conditions["reference_titles"] == []
        # Model comes from the active LLM config, or the env fallback on error.
        assert isinstance(conditions["model"], str) and conditions["model"]

    def test_counts_and_titles_references(self, monkeypatch):
        refs = [
            SimpleNamespace(title="Doc A", source="http://a"),
            SimpleNamespace(title=None, source="http://b"),
        ]
        monkeypatch.setattr(repositories, "list_project_references", lambda pid: refs)
        monkeypatch.setattr(repositories, "effective_search_enabled", lambda pid: True)
        monkeypatch.setattr(repositories, "effective_section_search_enabled", lambda pid: False)
        conditions = repositories._draft_conditions("p1")
        assert conditions["reference_count"] == 2
        assert conditions["reference_titles"] == ["Doc A", "http://b"]
