import pytest

from app.services.llm import (
    LLMError,
    _extract_json_object,
    _first_balanced_json_object,
    _strip_json_fence,
)


class TestStripJsonFence:
    def test_plain_text_unchanged(self):
        assert _strip_json_fence('{"a": 1}') == '{"a": 1}'

    def test_removes_json_fence(self):
        fenced = '```json\n{"a": 1}\n```'
        assert _strip_json_fence(fenced) == '{"a": 1}'


class TestFirstBalancedJsonObject:
    def test_extracts_object_from_prose(self):
        text = 'Here is the result: {"a": {"b": 2}} hope it helps'
        assert _first_balanced_json_object(text) == '{"a": {"b": 2}}'

    def test_ignores_braces_inside_strings(self):
        text = '{"a": "}{"}'
        assert _first_balanced_json_object(text) == '{"a": "}{"}'

    def test_no_object_returns_none(self):
        assert _first_balanced_json_object("no json here") is None


class TestExtractJsonObject:
    def test_plain_object(self):
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_fenced_object(self):
        assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_object_embedded_in_prose(self):
        assert _extract_json_object('Sure! {"a": 1} Done.') == {"a": 1}

    def test_repairs_trailing_comma(self):
        assert _extract_json_object('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}

    def test_repairs_missing_comma_between_fields(self):
        text = '{"a": 1\n"b": 2}'
        assert _extract_json_object(text) == {"a": 1, "b": 2}

    def test_array_root_rejected(self):
        with pytest.raises(LLMError):
            _extract_json_object("[1, 2, 3]")

    def test_no_json_raises(self):
        with pytest.raises(LLMError):
            _extract_json_object("just plain prose")
