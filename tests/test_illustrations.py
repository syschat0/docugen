"""Section illustration planning, insertion, generation, and settings."""

import base64
import io
import urllib.error
from types import SimpleNamespace

import pytest

from app.db import repositories, session
from app.services import image_gen, image_settings, llm


# --- select_illustration_entries ------------------------------------------


def _sections():
    return [
        {"id": "1.1", "title": "Intro", "summary": "An overview."},
        {"id": "1.2", "title": "Concept", "summary": "A concept."},
        {"id": "1.3", "title": "Data", "summary": "A table."},
    ]


def _with_suffix(monkeypatch, suffix="STYLE"):
    monkeypatch.setattr(llm, "settings", SimpleNamespace(image_style_suffix=suffix))


class TestSelectIllustrationEntries:
    def test_keeps_image_entries_and_appends_style_suffix(self, monkeypatch):
        _with_suffix(monkeypatch)
        parsed = [{"id": 1, "image": True, "prompt": "a scene", "caption": "c", "alt": "a"}]
        result = llm.select_illustration_entries(parsed, _sections(), {}, 5)
        assert len(result) == 1
        assert result[0]["section_id"] == "1.1"
        assert result[0]["prompt"] == "a scene, STYLE"

    def test_drops_false_and_empty_prompt(self, monkeypatch):
        _with_suffix(monkeypatch)
        parsed = [
            {"id": 1, "image": False, "prompt": "x"},
            {"id": 2, "image": True, "prompt": "   "},
        ]
        assert llm.select_illustration_entries(parsed, _sections(), {}, 5) == []

    def test_truncates_to_max_images(self, monkeypatch):
        _with_suffix(monkeypatch)
        parsed = [
            {"id": 1, "image": True, "prompt": "a"},
            {"id": 2, "image": True, "prompt": "b"},
            {"id": 3, "image": True, "prompt": "c"},
        ]
        result = llm.select_illustration_entries(parsed, _sections(), {}, 2)
        assert len(result) == 2

    def test_skips_sections_with_mermaid_or_existing_image(self, monkeypatch):
        _with_suffix(monkeypatch)
        parsed = [
            {"id": 1, "image": True, "prompt": "a"},
            {"id": 2, "image": True, "prompt": "b"},
        ]
        drafts = {
            "1.1": "# Intro\n\n```mermaid\ngraph TD\n```",
            "1.2": "# Concept\n\n![existing](/media/x.png)",
        }
        assert llm.select_illustration_entries(parsed, _sections(), drafts, 5) == []


# --- _insert_illustration --------------------------------------------------


class TestInsertIllustration:
    ENTRY = {"url": "/media/x.png", "alt": "alt text", "caption": "a caption"}

    def test_inserts_after_first_heading(self):
        markdown = "## Title\n\nBody paragraph."
        out = repositories._insert_illustration(markdown, self.ENTRY)
        lines = out.split("\n")
        assert lines[0] == "## Title"
        assert "![alt text](/media/x.png)" in out
        assert "*a caption*" in out
        # Image comes before the body.
        assert out.index("![alt text]") < out.index("Body paragraph")

    def test_prepends_when_no_heading(self):
        markdown = "Just a paragraph, no heading."
        out = repositories._insert_illustration(markdown, self.ENTRY)
        assert out.startswith("![alt text](/media/x.png)")

    def test_sanitizes_brackets_in_alt(self):
        entry = {"url": "/media/x.png", "alt": "a [risky] alt", "caption": ""}
        out = repositories._insert_illustration("# H\n\nBody", entry)
        assert "![a (risky) alt](/media/x.png)" in out


# --- generate_section_image ------------------------------------------------


class _FakeResponse:
    def __init__(self, payload_bytes):
        self._data = payload_bytes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


def _patch_image_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(
        image_gen,
        "settings",
        SimpleNamespace(
            media_dir=tmp_path,
            image_size="1536x1024",
            image_timeout_seconds=30,
        ),
    )


class TestGenerateSectionImage:
    def test_openai_b64_path(self, monkeypatch, tmp_path):
        _patch_image_settings(monkeypatch, tmp_path)
        b64 = base64.b64encode(b"PNGDATA").decode()
        body = f'{{"data": [{{"b64_json": "{b64}"}}]}}'.encode()
        monkeypatch.setattr(
            image_gen.urllib.request,
            "urlopen",
            lambda request, timeout=None: _FakeResponse(body),
        )
        config = {
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "k",
            "model": "gpt-image-1",
        }
        path = image_gen.generate_section_image("a scene", config=config)
        assert path.exists()
        assert path.read_bytes() == b"PNGDATA"

    def test_gemini_inline_data_path(self, monkeypatch, tmp_path):
        _patch_image_settings(monkeypatch, tmp_path)
        b64 = base64.b64encode(b"GEMINIPNG").decode()
        body = (
            '{"candidates": [{"content": {"parts": ['
            f'{{"inlineData": {{"data": "{b64}"}}}}]}}}}]}}'
        ).encode()
        monkeypatch.setattr(
            image_gen.urllib.request,
            "urlopen",
            lambda request, timeout=None: _FakeResponse(body),
        )
        config = {
            "provider": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": "k",
            "model": "gemini-2.5-flash-image",
        }
        path = image_gen.generate_section_image("a scene", config=config)
        assert path.exists()
        assert path.read_bytes() == b"GEMINIPNG"

    def test_gemini_strips_models_prefix_from_model_name(self, monkeypatch, tmp_path):
        _patch_image_settings(monkeypatch, tmp_path)
        b64 = base64.b64encode(b"G").decode()
        body = (
            '{"candidates": [{"content": {"parts": ['
            f'{{"inlineData": {{"data": "{b64}"}}}}]}}}}]}}'
        ).encode()
        seen = {}

        def _fake(request, timeout=None):
            seen["url"] = request.full_url
            return _FakeResponse(body)

        monkeypatch.setattr(image_gen.urllib.request, "urlopen", _fake)
        config = {
            "provider": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": "k",
            "model": "models/gemini-2.5-flash-image",
        }
        image_gen.generate_section_image("a scene", config=config)
        assert "/models/gemini-2.5-flash-image:generateContent" in seen["url"]
        assert "models/models/" not in seen["url"]

    def test_cache_path_ignores_models_prefix(self, monkeypatch, tmp_path):
        _patch_image_settings(monkeypatch, tmp_path)
        assert image_gen._cache_path(
            "gemini", "models/x", "1536x1024", "p"
        ) == image_gen._cache_path("gemini", "x", "1536x1024", "p")

    def test_cache_hit_makes_no_network_call(self, monkeypatch, tmp_path):
        _patch_image_settings(monkeypatch, tmp_path)
        config = {
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "k",
            "model": "gpt-image-1",
        }
        # Pre-create the exact cache file the call would target.
        path = image_gen._cache_path("openai", "gpt-image-1", "1536x1024", "a scene")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"CACHED")

        def _boom(*args, **kwargs):
            raise AssertionError("network call on cache hit")

        monkeypatch.setattr(image_gen.urllib.request, "urlopen", _boom)
        out = image_gen.generate_section_image("a scene", config=config)
        assert out == path
        assert out.read_bytes() == b"CACHED"

    def test_http_error_raises_image_gen_error(self, monkeypatch, tmp_path):
        _patch_image_settings(monkeypatch, tmp_path)

        def _raise(*args, **kwargs):
            raise urllib.error.HTTPError(
                "https://api.openai.com/v1/images/generations",
                400,
                "Bad Request",
                {},
                io.BytesIO(b'{"error": {"message": "bad prompt"}}'),
            )

        monkeypatch.setattr(image_gen.urllib.request, "urlopen", _raise)
        config = {
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "k",
            "model": "gpt-image-1",
        }
        with pytest.raises(image_gen.ImageGenError) as exc:
            image_gen.generate_section_image("a scene", config=config)
        assert "bad prompt" in str(exc.value)


# --- image_settings --------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        session, "settings", SimpleNamespace(database_path=tmp_path / "test.sqlite3")
    )
    session.init_db()
    image_settings._cache = None
    yield
    image_settings._cache = None


class TestImageSettings:
    def test_resolve_disabled(self):
        config = image_settings.resolve_config("disabled")
        assert config == {"provider": "disabled", "base_url": "", "api_key": "", "model": ""}

    def test_resolve_openai_requires_api_key(self):
        with pytest.raises(image_settings.ImageConfigError):
            image_settings.resolve_config("openai", api_key="")

    def test_resolve_openai_normalizes_defaults(self):
        config = image_settings.resolve_config("openai", api_key="sk-x")
        assert config["provider"] == "openai"
        assert config["base_url"] == "https://api.openai.com/v1"
        assert config["model"] == "gpt-image-1"
        assert config["api_key"] == "sk-x"

    def test_resolve_gemini_strips_models_prefix(self):
        config = image_settings.resolve_config(
            "gemini", api_key="k", model="models/gemini-2.5-flash-image"
        )
        assert config["model"] == "gemini-2.5-flash-image"

    def test_test_config_flags_model_missing_from_list(self, monkeypatch):
        body = b'{"models": [{"name": "models/gemini-2.5-flash-image"}]}'
        monkeypatch.setattr(
            image_settings.urllib.request,
            "urlopen",
            lambda request, timeout=None: _FakeResponse(body),
        )
        result = image_settings.test_image_config("gemini", api_key="k", model="nope")
        assert result["ok"] is False
        assert "nope" in result["error"]

    def test_test_config_accepts_prefixed_model_in_list(self, monkeypatch):
        body = b'{"models": [{"name": "models/gemini-2.5-flash-image"}]}'
        monkeypatch.setattr(
            image_settings.urllib.request,
            "urlopen",
            lambda request, timeout=None: _FakeResponse(body),
        )
        result = image_settings.test_image_config(
            "gemini", api_key="k", model="models/gemini-2.5-flash-image"
        )
        assert result["ok"] is True

    def test_env_config_disabled_when_provider_empty(self, monkeypatch):
        monkeypatch.setattr(
            image_settings,
            "settings",
            SimpleNamespace(
                image_provider="", image_base_url="", image_api_key="", image_model=""
            ),
        )
        assert image_settings._env_config()["provider"] == "disabled"

    def test_env_config_openai_from_env(self, monkeypatch):
        monkeypatch.setattr(
            image_settings,
            "settings",
            SimpleNamespace(
                image_provider="openai",
                image_base_url="",
                image_api_key="sk-env",
                image_model="",
            ),
        )
        config = image_settings._env_config()
        assert config["provider"] == "openai"
        assert config["model"] == "gpt-image-1"
        assert config["api_key"] == "sk-env"

    def test_active_config_defaults_to_disabled(self, temp_db, monkeypatch):
        monkeypatch.setattr(
            image_settings,
            "settings",
            SimpleNamespace(
                image_provider="", image_base_url="", image_api_key="", image_model=""
            ),
        )
        assert image_settings.get_active_image_config()["provider"] == "disabled"
        assert image_settings.image_generation_enabled() is False

    def test_enabled_after_setting_provider(self, temp_db):
        image_settings.set_active_image_config("openai", api_key="sk-x")
        assert image_settings.image_generation_enabled() is True
        assert image_settings.get_active_image_config()["provider"] == "openai"


# --- illustration plan reuse -------------------------------------------------


class TestIllustrationPlanHasFailures:
    def test_clean_plan_is_reusable(self):
        content = {"entries": [{"status": "generated"}, {"status": "cached"}], "error": None}
        assert repositories._illustration_plan_has_failures(content) is False

    def test_failed_entry_blocks_reuse(self):
        content = {"entries": [{"status": "generated"}, {"status": "failed"}], "error": None}
        assert repositories._illustration_plan_has_failures(content) is True

    def test_planner_error_blocks_reuse(self):
        assert repositories._illustration_plan_has_failures({"entries": [], "error": "boom"}) is True

    def test_empty_content_is_reusable(self):
        assert repositories._illustration_plan_has_failures(None) is False
