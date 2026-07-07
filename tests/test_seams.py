from app.schemas.projects import ProjectRead
from app.services import llm
from app.services.llm import (
    LLMError,
    _markdown_tail,
    _split_opening_paragraph,
    smooth_chapter_seams,
)


def make_project() -> ProjectRead:
    return ProjectRead(
        id="p1",
        title="Docker 가이드",
        initial_request="docker 문서",
        status="running",
        current_phase="final_merge",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


BRIEF = {"style": "-이다체"}


class TestSplitOpeningParagraph:
    def test_splits_heading_opening_rest(self):
        heading, opening, rest = _split_opening_paragraph(
            "### 2.1 Title\n\nFirst paragraph.\n\nSecond paragraph."
        )
        assert heading == "### 2.1 Title"
        assert opening == "First paragraph."
        assert rest == "Second paragraph."

    def test_no_heading_returns_unsafe(self):
        heading, opening, rest = _split_opening_paragraph("Just text.")
        assert (heading, opening) == ("", "")
        assert rest == "Just text."

    def test_list_opening_is_unsafe(self):
        heading, opening, rest = _split_opening_paragraph("## 3 Title\n\n- bullet one\n- two")
        assert heading == "## 3 Title"
        assert opening == ""
        assert rest.startswith("- bullet one")

    def test_code_fence_opening_is_unsafe(self):
        _heading, opening, _rest = _split_opening_paragraph("## 3 T\n\n```mermaid\nA-->B\n```")
        assert opening == ""


class TestMarkdownTail:
    def test_returns_last_paragraphs(self):
        markdown = "## H\n\nFirst.\n\nSecond.\n\nThird."
        tail = _markdown_tail(markdown, limit=20)
        assert "Third." in tail
        assert "## H" not in tail

    def test_skips_code_and_tables(self):
        markdown = "Prose.\n\n```code\nx\n```\n\n| a | b |"
        assert _markdown_tail(markdown) == "Prose."


def _drafts():
    return [
        {"section": {"id": "1.1"}, "markdown": "### 1.1 A\n\nChapter one ends [[1]](https://a.com)."},
        {"section": {"id": "2.1"}, "markdown": "### 2.1 B\n\nOld opening [[2]](https://b.com).\n\nBody."},
    ]


class TestSmoothChapterSeams:
    def test_smooths_chapter_boundary(self, monkeypatch):
        monkeypatch.setattr(
            llm,
            "_smooth_one_transition",
            lambda project, brief, tail, heading, opening: (
                "New opening [[2]](https://b.com).",
                {"total_tokens": 5},
            ),
        )
        smoothed, usage, seams = smooth_chapter_seams(make_project(), BRIEF, _drafts())
        assert seams == ["2.1"]
        assert smoothed[1]["markdown"] == (
            "### 2.1 B\n\nNew opening [[2]](https://b.com).\n\nBody."
        )
        assert smoothed[0]["markdown"] == _drafts()[0]["markdown"]
        assert usage == {"seam_calls": [{"section_id": "2.1", "total_tokens": 5}]}

    def test_rejects_rewrite_that_drops_citations(self, monkeypatch):
        monkeypatch.setattr(
            llm,
            "_smooth_one_transition",
            lambda *args: ("New opening without citation.", None),
        )
        smoothed, usage, seams = smooth_chapter_seams(make_project(), BRIEF, _drafts())
        assert seams == []
        assert smoothed[1]["markdown"] == _drafts()[1]["markdown"]
        assert usage is None

    def test_llm_error_keeps_original(self, monkeypatch):
        def boom(*args):
            raise LLMError("down")

        monkeypatch.setattr(llm, "_smooth_one_transition", boom)
        smoothed, _usage, seams = smooth_chapter_seams(make_project(), BRIEF, _drafts())
        assert seams == []
        assert smoothed[1]["markdown"] == _drafts()[1]["markdown"]

    def test_no_call_within_same_chapter(self, monkeypatch):
        calls = []

        def record(*args):
            calls.append(args)
            return "x", None

        monkeypatch.setattr(llm, "_smooth_one_transition", record)
        drafts = [
            {"section": {"id": "1.1"}, "markdown": "### 1.1 A\n\nText."},
            {"section": {"id": "1.2"}, "markdown": "### 1.2 B\n\nText."},
        ]
        smooth_chapter_seams(make_project(), BRIEF, drafts)
        assert calls == []


class TestReviewContinuityStaged:
    SUMMARIES = [
        {"section_id": "1.1", "summary": "s11", "terms": []},
        {"section_id": "1.2", "summary": "s12", "terms": []},
        {"section_id": "2.1", "summary": "s21", "terms": []},
        {"section_id": "2.2", "summary": "s22", "terms": []},
    ]
    DRAFTS = [
        {"section": {"id": sid, "title": sid}, "markdown": f"### {sid}\n\nBody."}
        for sid in ("1.1", "1.2", "2.1", "2.2")
    ]
    DIGESTS = [
        {"chapter_id": "1", "title": "One", "digest": "d1", "terms": []},
        {"chapter_id": "2", "title": "Two", "digest": "d2", "terms": []},
    ]

    def test_merges_chapter_and_cross_reviews(self, monkeypatch):
        monkeypatch.setattr(
            llm,
            "_review_chapter_continuity",
            lambda project, brief, chapter_id, overview: (
                {
                    "verdict": "pass" if chapter_id == "1" else "needs_revision",
                    "issues": [f"issue-{chapter_id}"],
                    "revision_targets": [f"{chapter_id}.1"],
                    "notes": "",
                },
                None,
            ),
        )
        monkeypatch.setattr(
            llm,
            "_review_cross_chapter_continuity",
            lambda project, brief, digests: (
                {"verdict": "pass", "issues": ["cross-issue"], "notes": "ok"},
                None,
            ),
        )
        review, _usage = llm.review_continuity_staged(
            make_project(), BRIEF, self.DRAFTS, self.SUMMARIES, self.DIGESTS
        )
        assert review["verdict"] == "needs_revision"
        assert review["issues"] == ["issue-1", "issue-2", "cross-issue"]
        assert review["revision_targets"] == ["1.1", "2.1"]
        assert review["chapter_review_count"] == 3

    def test_single_chapter_failure_is_skipped(self, monkeypatch):
        def flaky(project, brief, chapter_id, overview):
            if chapter_id == "1":
                raise LLMError("bad json")
            return {"verdict": "pass", "issues": [], "revision_targets": [], "notes": ""}, None

        monkeypatch.setattr(llm, "_review_chapter_continuity", flaky)
        monkeypatch.setattr(
            llm,
            "_review_cross_chapter_continuity",
            lambda *args: ({"verdict": "pass", "issues": [], "notes": ""}, None),
        )
        review, _usage = llm.review_continuity_staged(
            make_project(), BRIEF, self.DRAFTS, self.SUMMARIES, self.DIGESTS
        )
        assert review["verdict"] == "pass"
        assert "Chapter 1" in review["notes"]

    def test_total_failure_raises(self, monkeypatch):
        def boom(*args):
            raise LLMError("down")

        monkeypatch.setattr(llm, "_review_chapter_continuity", boom)
        monkeypatch.setattr(llm, "_review_cross_chapter_continuity", boom)
        try:
            llm.review_continuity_staged(
                make_project(), BRIEF, self.DRAFTS, self.SUMMARIES, self.DIGESTS
            )
        except LLMError:
            pass
        else:
            raise AssertionError("expected LLMError")
