from types import SimpleNamespace

import pytest

from app.db.repositories import _merge_reference_sources
from app.services import llm
from app.services.llm import LLMError, _style_card_block, derive_style_card
from app.services.references import extract_file_reference


def _sample(text="나는 늘 새벽에 글을 쓴다. 그 시간의 고요가 좋다.", title="내 글"):
    return SimpleNamespace(
        kind="style", source="sample.txt", title=title, content_text=text, status="ready"
    )


class TestDeriveStyleCard:
    def test_returns_clipped_card(self, monkeypatch):
        monkeypatch.setattr(
            llm,
            "_json_chat",
            lambda s, u: (
                {
                    "register": "-이다/한다체",
                    "voice": "담담한 1인칭 관찰자",
                    "person": "1인칭",
                    "tense": "현재",
                    "sentence_rhythm": "짧은 문장 위주",
                    "vocabulary": "일상어",
                    "devices": ["감각 묘사"],
                    "avoid": ["감탄사"],
                    "exemplars": ["나는 늘 새벽에 글을 쓴다."],
                },
                None,
            ),
        )
        card, _usage = derive_style_card(SimpleNamespace(title="t"), [_sample()])
        assert card["register"] == "-이다/한다체"
        assert card["exemplars"] == ["나는 늘 새벽에 글을 쓴다."]

    def test_missing_register_and_voice_raises(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_json_chat", lambda s, u: ({"register": "", "voice": ""}, None)
        )
        with pytest.raises(LLMError):
            derive_style_card(SimpleNamespace(title="t"), [_sample()])


class TestStyleCardBlock:
    def test_renders_card_and_exemplars(self):
        block = _style_card_block(
            {"register": "-한다체", "exemplars": ["예문 하나.", ""]}
        )
        assert "Voice & style card" in block
        assert "-한다체" in block
        assert "- 예문 하나." in block

    def test_empty_card_renders_nothing(self):
        assert _style_card_block(None) == ""
        assert _style_card_block({}) == ""
        assert _style_card_block({"exemplars": []}) == ""


class TestStyleSamplesStayOutOfResearch:
    def test_merge_excludes_style_kind(self):
        research = {"results": []}
        summaries = {"sources": []}
        refs = [
            SimpleNamespace(
                kind="style", source="s.txt", title="샘플", content_text="글", status="ready"
            ),
            SimpleNamespace(
                kind="file", source="doc.txt", title="자료", content_text="내용", status="ready"
            ),
        ]
        _merge_reference_sources(refs, research, summaries)
        urls = [item["url"] for item in research["results"]]
        assert urls == ["file://doc.txt"]


class TestExtractFileReferenceKind:
    def test_style_kind_is_stored(self):
        entry = extract_file_reference("me.txt", "my writing".encode(), kind="style")
        assert entry["kind"] == "style"
        assert entry["status"] == "ready"

    def test_default_kind_is_file(self):
        entry = extract_file_reference("doc.txt", "content".encode())
        assert entry["kind"] == "file"
