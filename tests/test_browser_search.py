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
            if "api_search" in config:
                # API engines have no browser page/selectors.
                assert callable(config["api_search"]), name
                continue
            assert "{query}" in config["url_template"], name
            assert config["result_selector"], name
            assert config["extract_js"], name

    def test_engine_config_resolves_setting(self):
        assert _engine_config("bing") is _ENGINES["bing"]
        assert _engine_config("google") is _ENGINES["google"]

    def test_unknown_engine_raises(self):
        with pytest.raises(BrowserSearchError, match="Unknown SEARCH_ENGINE"):
            _engine_config("yahoo")


class TestEnginePriority:
    def test_resolves_and_orders(self):
        priority = browser_search._engine_priority(("google", "daum"))
        assert [name for name, _config in priority] == ["google", "daum"]

    def test_drops_unknown_and_duplicates(self):
        priority = browser_search._engine_priority(("bing", "yahoo", "bing", "daum"))
        assert [name for name, _config in priority] == ["bing", "daum"]

    def test_raises_when_none_usable(self):
        with pytest.raises(BrowserSearchError):
            browser_search._engine_priority(("yahoo", "aol"))


class TestDecodeGoogleUrl:
    def test_unwraps_redirect(self):
        href = "https://www.google.com/url?q=https://example.com/page&sa=U"
        assert browser_search.decode_google_url(href) == "https://example.com/page"

    def test_direct_url_unchanged(self):
        assert (
            browser_search.decode_google_url("https://example.com/p")
            == "https://example.com/p"
        )


class TestSearchQueryFallback:
    _PRIORITY = [("daum", _ENGINES["daum"]), ("bing", _ENGINES["bing"])]

    def test_falls_back_on_challenge_and_blocks_engine(self, monkeypatch):
        def fake_run(page, config, query, timeout_ms):
            if config is _ENGINES["daum"]:
                raise browser_search.SearchChallengeError("blocked")
            return [{"title": "T", "url": "https://x", "snippet": "s"}]

        monkeypatch.setattr(browser_search, "_run_search_query", fake_run)
        blocked: set[str] = set()
        name, config, items, error = browser_search._search_query_with_fallback(
            None, self._PRIORITY, blocked, "q", 1000
        )
        assert name == "bing"
        assert items[0]["url"] == "https://x"
        assert error is None
        assert "daum" in blocked

    def test_all_engines_fail_returns_none(self, monkeypatch):
        def fake_run(page, config, query, timeout_ms):
            raise RuntimeError("boom")

        monkeypatch.setattr(browser_search, "_run_search_query", fake_run)
        name, config, items, error = browser_search._search_query_with_fallback(
            None, self._PRIORITY, set(), "q", 1000
        )
        assert name is None
        assert items == []
        assert error is not None

    def test_blocked_engine_is_skipped(self, monkeypatch):
        tried = []

        def fake_run(page, config, query, timeout_ms):
            tried.append(config)
            return [{"title": "T", "url": "https://y", "snippet": ""}]

        monkeypatch.setattr(browser_search, "_run_search_query", fake_run)
        name, config, items, error = browser_search._search_query_with_fallback(
            None, self._PRIORITY, {"daum"}, "q", 1000
        )
        assert name == "bing"
        assert tried == [_ENGINES["bing"]]

    def test_empty_result_is_not_a_fallback(self, monkeypatch):
        tried = []

        def fake_run(page, config, query, timeout_ms):
            tried.append(config)
            return []  # valid empty answer -> should NOT try the next engine

        monkeypatch.setattr(browser_search, "_run_search_query", fake_run)
        name, config, items, error = browser_search._search_query_with_fallback(
            None, self._PRIORITY, set(), "q", 1000
        )
        assert name == "daum"
        assert items == []
        assert tried == [_ENGINES["daum"]]

    def test_api_engine_is_called_without_browser(self, monkeypatch):
        called = []

        def fake_api(query):
            called.append(query)
            return [{"title": "T", "url": "https://api", "snippet": "s"}]

        def boom_run(*args, **kwargs):
            raise AssertionError("_run_search_query should not be called")

        monkeypatch.setattr(browser_search, "_run_search_query", boom_run)
        priority = [("google_pse", {"api_search": fake_api, "decode_url": None})]
        name, config, items, error = browser_search._search_query_with_fallback(
            None, priority, set(), "q", 1000
        )
        assert name == "google_pse"
        assert called == ["q"]
        assert items[0]["url"] == "https://api"
        assert error is None

    def test_api_engine_challenge_blocks_and_falls_back(self, monkeypatch):
        def fake_api(query):
            raise browser_search.SearchChallengeError("quota")

        def fake_run(page, config, query, timeout_ms):
            return [{"title": "T", "url": "https://x", "snippet": "s"}]

        monkeypatch.setattr(browser_search, "_run_search_query", fake_run)
        priority = [
            ("google_pse", {"api_search": fake_api, "decode_url": None}),
            ("bing", _ENGINES["bing"]),
        ]
        blocked: set[str] = set()
        name, config, items, error = browser_search._search_query_with_fallback(
            None, priority, blocked, "q", 1000
        )
        assert name == "bing"
        assert items[0]["url"] == "https://x"
        assert "google_pse" in blocked


class TestApplyStealth:
    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr(
            browser_search,
            "current_search_options",
            lambda: SimpleNamespace(stealth=False),
        )
        touched = []
        page = SimpleNamespace(add_init_script=lambda *a, **k: touched.append(a))
        assert browser_search._apply_stealth(page) is None
        assert touched == []
