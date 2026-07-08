from types import SimpleNamespace

from app.db.repositories import _combine_reviews
from app.services import llm
from app.services.doc_types import DOC_TYPES, get_doc_type_profile
from app.services.llm import LLMError, review_rubric_staged


def _project():
    return SimpleNamespace(title="t", initial_request="r")


def _drafts():
    return [
        {"section": {"id": "1.1", "title": "A"}, "markdown": "### 1.1 A\n\nBody A."},
        {"section": {"id": "1.2", "title": "B"}, "markdown": "### 1.2 B\n\nBody B."},
        {"section": {"id": "2.1", "title": "C"}, "markdown": "### 2.1 C\n\nBody C."},
    ]


class TestRubricDefinitions:
    def test_every_type_declares_four_criteria(self):
        for key, profile in DOC_TYPES.items():
            rubric = profile.get("rubric")
            assert isinstance(rubric, list) and len(rubric) == 4, key
            for item in rubric:
                assert item.get("key") and item.get("name") and item.get("description")

    def test_criterion_keys_unique_per_type(self):
        for key, profile in DOC_TYPES.items():
            keys = [item["key"] for item in profile["rubric"]]
            assert len(keys) == len(set(keys)), key


class TestReviewRubricStaged:
    def test_aggregates_scores_and_targets_across_chapters(self, monkeypatch):
        responses = iter(
            [
                (
                    {
                        "scores": [
                            {"key": "accuracy", "score": 2, "note": "vague"},
                            {"key": "structure", "score": 5, "note": ""},
                        ],
                        "issues": ["1.1: claims lack support"],
                        "revision_targets": ["1.1"],
                    },
                    None,
                ),
                (
                    {
                        "scores": [{"key": "accuracy", "score": 4, "note": ""}],
                        "issues": [],
                        "revision_targets": ["1.1", "2.1"],
                    },
                    None,
                ),
            ]
        )
        monkeypatch.setattr(llm, "_json_chat", lambda s, u: next(responses))
        review, usage = review_rubric_staged(
            _project(), {"goal": "g"}, get_doc_type_profile("report"), _drafts()
        )
        by_key = {item["key"]: item for item in review["criteria"]}
        assert by_key["accuracy"]["average_score"] == 3.0
        assert by_key["accuracy"]["min_score"] == 2
        assert by_key["structure"]["average_score"] == 5.0
        assert by_key["completeness"]["average_score"] is None
        assert review["revision_targets"] == ["1.1", "2.1"]
        assert review["verdict"] == "needs_revision"
        assert usage is None  # no usage data in stubbed responses

    def test_unknown_score_keys_and_garbage_ignored(self, monkeypatch):
        monkeypatch.setattr(
            llm,
            "_json_chat",
            lambda s, u: (
                {
                    "scores": [
                        {"key": "nonsense", "score": 1},
                        {"key": "accuracy", "score": "not a number"},
                    ],
                    "issues": [],
                    "revision_targets": [],
                },
                None,
            ),
        )
        review, _ = review_rubric_staged(
            _project(), {}, get_doc_type_profile("report"), _drafts()
        )
        assert review["verdict"] == "pass"
        by_key = {item["key"]: item for item in review["criteria"]}
        assert by_key["accuracy"]["average_score"] is None

    def test_failed_chapters_never_block_the_run(self, monkeypatch):
        def boom(s, u):
            raise LLMError("down")

        monkeypatch.setattr(llm, "_json_chat", boom)
        review, usage = review_rubric_staged(
            _project(), {}, get_doc_type_profile("report"), _drafts()
        )
        assert review["verdict"] == "pass"
        assert "failed" in review["notes"]
        assert usage is None

    def test_no_rubric_returns_pass(self):
        review, usage = review_rubric_staged(_project(), {}, {"rubric": []}, _drafts())
        assert review["verdict"] == "pass"
        assert usage is None


class TestCombineReviews:
    def test_merges_issues_and_dedupes_targets(self):
        combined = _combine_reviews(
            {"issues": ["a"], "revision_targets": ["1.1", "1.2"]},
            {"issues": ["b"], "revision_targets": ["1.2", "2.1"]},
        )
        assert combined["issues"] == ["a", "b"]
        assert combined["revision_targets"] == ["1.1", "1.2", "2.1"]
        assert combined["verdict"] == "needs_revision"

    def test_caps_targets_at_five(self):
        combined = _combine_reviews(
            {"issues": [], "revision_targets": [f"1.{i}" for i in range(1, 6)]},
            {"issues": [], "revision_targets": ["9.9"]},
        )
        assert len(combined["revision_targets"]) == 5
        assert "9.9" not in combined["revision_targets"]

    def test_no_targets_means_pass(self):
        combined = _combine_reviews({"issues": []}, {"issues": []})
        assert combined["verdict"] == "pass"
        assert combined["revision_targets"] == []
