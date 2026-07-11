"""User-facing prompt outputs must follow the request's language.

These tests pin the explicit same-language instructions into the prompts
that produce user-visible text (intake questions, brief, outline, section
plan), so an English-leaning guidance block can never silently drop them
again.
"""

from types import SimpleNamespace

from app.services import llm
from app.services.doc_types import get_doc_type_profile


def _capture_json_chat(monkeypatch, response):
    captured = {}

    def fake(system_prompt, user_prompt):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return response, None

    monkeypatch.setattr(llm, "_json_chat", fake)
    return captured


def _project():
    return SimpleNamespace(
        id="p1", title="한글 제목", initial_request="소논문을 한국어로 써줘"
    )


class TestSameLanguageInstructions:
    def test_intake_questions_prompt_demands_request_language(self, monkeypatch):
        captured = _capture_json_chat(monkeypatch, {"needs_questions": False})
        llm.plan_user_questions(_project(), [])
        assert "SAME LANGUAGE" in captured["user"]
        assert "same language" in captured["system"]

    def test_intake_prompt_uses_only_selected_type_priorities(self, monkeypatch):
        captured = _capture_json_chat(monkeypatch, {"needs_questions": False})
        llm.plan_user_questions(
            _project(), [], profile=get_doc_type_profile("academic_paper")
        )
        assert "exact research question or thesis" in captured["user"]
        assert "publishing channel" not in captured["user"]
        assert "do not ask every item mechanically" in captured["user"]

    def test_brief_prompt_demands_request_language(self, monkeypatch):
        captured = _capture_json_chat(monkeypatch, {"topic": "t"})
        llm.generate_brief(_project(), [], None)
        assert "SAME LANGUAGE" in captured["user"]

    def test_outline_prompt_demands_brief_language(self, monkeypatch):
        captured = _capture_json_chat(monkeypatch, {"chapters": [{"id": "1"}]})
        llm.generate_outline(_project(), {"topic": "주제"})
        assert "SAME LANGUAGE" in captured["user"]

    def test_chapter_expansion_prompt_demands_chapter_language(self, monkeypatch):
        captured = _capture_json_chat(
            monkeypatch, {"children": [{"id": "1.1", "title": "t"}]}
        )
        llm.expand_chapter_subtree(
            _project(), {"topic": "주제"}, {"id": "1", "title": "서론"}, []
        )
        assert "SAME LANGUAGE" in captured["user"]
