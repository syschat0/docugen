from types import SimpleNamespace

from app.db import repositories
from app.schemas.projects import ProjectRead
from app.services import search_options


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


class TestEffectiveCitationStyle:
    def test_override_takes_precedence_over_global(self, monkeypatch):
        monkeypatch.setattr(
            repositories,
            "get_project_settings",
            lambda pid: {"citation_style": "author_date"},
        )
        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(citation_style="numeric")
        )
        assert repositories.effective_citation_style("p1") == "author_date"

    def test_none_falls_back_to_global_default(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(citation_style="author_date")
        )
        assert repositories.effective_citation_style("p1") == "author_date"

    def test_unknown_values_fall_back_to_numeric(self, monkeypatch):
        monkeypatch.setattr(
            repositories,
            "get_project_settings",
            lambda pid: {"citation_style": "chicago"},
        )
        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(citation_style="numeric")
        )
        assert repositories.effective_citation_style("p1") == "numeric"

        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        monkeypatch.setattr(
            repositories, "settings", SimpleNamespace(citation_style="bogus")
        )
        assert repositories.effective_citation_style("p1") == "numeric"


class TestEffectiveSearchOptions:
    _GLOBAL = SimpleNamespace(
        search_engine="daum",
        search_headless=True,
        search_stealth=False,
        search_locale="ko-KR",
        search_query_language="native",
    )

    def test_overrides_take_precedence(self, monkeypatch):
        monkeypatch.setattr(
            repositories,
            "get_project_settings",
            lambda pid: {
                "search_engines": ["bing", "daum"],
                "search_headless": False,
                "search_stealth": True,
                "search_locale": "en-US",
                "search_query_language": "both",
            },
        )
        monkeypatch.setattr(search_options, "settings", self._GLOBAL)
        opts = repositories.effective_search_options("p1")
        assert opts.engines == ("bing", "daum")
        assert opts.headless is False
        assert opts.stealth is True
        assert opts.locale == "en-US"
        assert opts.query_language == "both"

    def test_none_falls_back_to_global(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        monkeypatch.setattr(search_options, "settings", self._GLOBAL)
        opts = repositories.effective_search_options("p1")
        assert opts.engines == ("daum",)
        assert opts.headless is True
        assert opts.stealth is False
        assert opts.locale == "ko-KR"
        assert opts.query_language == "native"


class TestProjectSettingsSchema:
    def test_google_pse_engine_round_trips(self):
        from app.schemas.projects import ProjectSettingsUpdate

        payload = ProjectSettingsUpdate(search_engines=["google_pse", "daum"])
        assert payload.search_engines == ["google_pse", "daum"]


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
            repositories, "effective_citation_style", lambda pid: "author_date"
        )
        monkeypatch.setattr(
            repositories,
            "settings",
            SimpleNamespace(llm_model="fallback-model"),
        )
        conditions = repositories._draft_conditions("p1")
        assert conditions["search_enabled"] is False
        assert conditions["section_search_enabled"] is True
        assert conditions["citation_style"] == "author_date"
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
