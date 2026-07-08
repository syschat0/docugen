from types import SimpleNamespace

from app.db import repositories


class TestDocumentTargetLength:
    def test_setting_beats_brief_extraction(self, monkeypatch):
        monkeypatch.setattr(
            repositories, "get_project_settings", lambda pid: {"target_length": 4000}
        )
        assert (
            repositories._document_target_length("p1", {"target_length_chars": 9000})
            == 4000
        )

    def test_brief_extraction_used_when_no_setting(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        assert (
            repositories._document_target_length("p1", {"target_length_chars": 3000})
            == 3000
        )

    def test_none_when_nothing_specified(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        assert repositories._document_target_length("p1", {}) is None
        assert (
            repositories._document_target_length("p1", {"target_length_chars": None})
            is None
        )

    def test_clamps_extreme_values(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        assert (
            repositories._document_target_length("p1", {"target_length_chars": 10})
            == 500
        )
        assert (
            repositories._document_target_length(
                "p1", {"target_length_chars": 9_999_999}
            )
            == 100_000
        )

    def test_garbage_brief_value_ignored(self, monkeypatch):
        monkeypatch.setattr(repositories, "get_project_settings", lambda pid: {})
        assert (
            repositories._document_target_length("p1", {"target_length_chars": "많이"})
            is None
        )


class TestScaleSectionLengths:
    def _plan(self, lengths):
        return {
            "sections": [
                {"id": str(index), "target_length": length}
                for index, length in enumerate(lengths, start=1)
            ]
        }

    def test_distributes_proportionally(self):
        plan = self._plan([500, 1000, 500])
        repositories._scale_section_lengths(plan, 4000)
        lengths = [section["target_length"] for section in plan["sections"]]
        assert lengths == [1000, 2000, 1000]

    def test_no_target_leaves_plan_unchanged(self):
        plan = self._plan([500, 700])
        repositories._scale_section_lengths(plan, None)
        assert [s["target_length"] for s in plan["sections"]] == [500, 700]

    def test_clamps_per_section_bounds(self):
        plan = self._plan([500, 500])
        repositories._scale_section_lengths(plan, 500)
        assert all(section["target_length"] >= 150 for section in plan["sections"])
        repositories._scale_section_lengths(plan, 100_000)
        assert all(section["target_length"] <= 3000 for section in plan["sections"])

    def test_missing_lengths_use_default_weight(self):
        plan = {"sections": [{"id": "1"}, {"id": "2"}]}
        repositories._scale_section_lengths(plan, 2000)
        assert [s["target_length"] for s in plan["sections"]] == [1000, 1000]


class TestNormalizeDefaultLength:
    def test_profile_default_reaches_sections(self):
        plan = {
            "outline_tree": [],
            "sections": [{"id": "1.1", "title": "S", "path": ["S"]}],
        }
        normalized = repositories._normalize_section_plan(plan, default_length=350)
        assert normalized["sections"][0]["target_length"] == 350

    def test_planned_length_wins_over_default(self):
        plan = {
            "outline_tree": [],
            "sections": [
                {"id": "1.1", "title": "S", "path": ["S"], "target_length": 800}
            ],
        }
        normalized = repositories._normalize_section_plan(plan, default_length=350)
        assert normalized["sections"][0]["target_length"] == 800
