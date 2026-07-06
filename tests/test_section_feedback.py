from app.db.repositories import _pending_section_feedback, _section_feedback_comments
from app.schemas.questions import UserDecisionRead


def _decision(decision_id, section_id, created_at, answer="fix it"):
    return UserDecisionRead(
        id=decision_id,
        project_id="p1",
        phase="section_feedback",
        question_id=None,
        question=f"Improve section {section_id}",
        answer=answer,
        applies_to={"section_id": section_id},
        created_at=created_at,
    )


DRAFTS = [
    {"section": {"id": "1.1"}, "markdown": "a", "updated_at": "2026-07-06T10:00:00Z"},
    {"section": {"id": "2.1"}, "markdown": "b", "updated_at": "2026-07-06T10:00:00Z"},
]


class TestPendingSectionFeedback:
    def test_newer_feedback_is_pending(self):
        feedback = [_decision("d1", "1.1", "2026-07-06T11:00:00Z")]
        pending = _pending_section_feedback(feedback, DRAFTS)
        assert list(pending) == ["1.1"]
        assert pending["1.1"][0].id == "d1"

    def test_feedback_older_than_draft_is_applied(self):
        feedback = [
            _decision("d1", "1.1", "2026-07-06T09:00:00Z"),
            _decision("d2", "2.1", "2026-07-06T10:00:00Z"),
        ]
        assert _pending_section_feedback(feedback, DRAFTS) == {}

    def test_unknown_section_is_ignored(self):
        feedback = [_decision("d1", "9.9", "2026-07-06T11:00:00Z")]
        assert _pending_section_feedback(feedback, DRAFTS) == {}

    def test_multiple_comments_sorted_by_time(self):
        feedback = [
            _decision("d2", "1.1", "2026-07-06T12:00:00Z", answer="second"),
            _decision("d1", "1.1", "2026-07-06T11:00:00Z", answer="first"),
        ]
        pending = _pending_section_feedback(feedback, DRAFTS)
        assert [item.answer for item in pending["1.1"]] == ["first", "second"]


class TestSectionFeedbackComments:
    def test_collects_comments_for_section_in_time_order(self):
        feedback = [
            _decision("d2", "1.1", "2026-07-06T12:00:00Z", answer="second"),
            _decision("d1", "1.1", "2026-07-06T11:00:00Z", answer="first"),
            _decision("d3", "2.1", "2026-07-06T11:30:00Z", answer="other section"),
        ]
        assert _section_feedback_comments(feedback, "1.1") == ["first", "second"]

    def test_empty_for_section_without_feedback(self):
        assert _section_feedback_comments([], "1.1") == []
