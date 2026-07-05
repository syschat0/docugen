import base64
from types import SimpleNamespace

import pytest

from app.services import browser_search
from app.services.browser_search import (
    _ENGINES,
    BrowserSearchError,
    _engine_config,
    decode_bing_url,
)


class TestDecodeBingUrl:
    def test_decodes_ck_redirect(self):
        real = "https://example.com/docker-guide"
        encoded = base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
        href = f"https://www.bing.com/ck/a?!&&p=hash&u=a1{encoded}&ntb=1"
        assert decode_bing_url(href) == real

    def test_direct_url_unchanged(self):
        href = "https://example.com/page"
        assert decode_bing_url(href) == href

    def test_malformed_payload_returns_original(self):
        href = "https://www.bing.com/ck/a?u=a1%%%invalid"
        assert decode_bing_url(href) == href


class TestEngineRegistry:
    def test_known_engines_have_required_keys(self):
        for name, config in _ENGINES.items():
            assert "{query}" in config["url_template"], name
            assert config["result_selector"], name
            assert config["extract_js"], name

    def test_engine_config_resolves_setting(self, monkeypatch):
        monkeypatch.setattr(
            browser_search, "settings", SimpleNamespace(search_engine="bing")
        )
        assert _engine_config() is _ENGINES["bing"]

    def test_unknown_engine_raises(self, monkeypatch):
        monkeypatch.setattr(
            browser_search, "settings", SimpleNamespace(search_engine="google")
        )
        with pytest.raises(BrowserSearchError, match="Unknown SEARCH_ENGINE"):
            _engine_config()
