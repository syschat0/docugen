import json

from app.services import llm
from app.services.doc_types import get_doc_type_profile


def test_stage_context_uses_profile_options_and_resets(monkeypatch):
    captured = {}

    def fake_json_chat(system_prompt, user_prompt):
        captured.update(llm._GENERATION_OPTIONS.get())
        return {}, None

    monkeypatch.setattr(llm, "_json_chat", fake_json_chat)
    profile = get_doc_type_profile("essay")

    llm._stage_json_chat(profile, "section_writing", "system", "user")

    assert captured == {"temperature": 0.65, "max_tokens": 5000}
    assert llm._GENERATION_OPTIONS.get() == {}


def test_request_payload_reads_active_generation_options(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(
        llm,
        "get_active_llm_config",
        lambda: {
            "model": "small-model",
            "base_url": "http://localhost:1234/v1",
            "api_key": "local",
        },
    )
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    token = llm._GENERATION_OPTIONS.set(
        {"temperature": 0.15, "max_tokens": 3200}
    )
    try:
        llm._request_chat_completion([{"role": "user", "content": "hi"}])
    finally:
        llm._GENERATION_OPTIONS.reset(token)

    assert captured["temperature"] == 0.15
    assert captured["max_tokens"] == 3200
