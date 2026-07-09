from types import SimpleNamespace

from app.services import search_options
from app.services.search_options import (
    SearchOptions,
    current_search_options,
    default_search_options,
    parse_engines,
    reset_search_options,
    use_search_options,
)


def test_parse_engines_dedupes_and_orders():
    assert parse_engines("google, bing ,daum") == ("google", "bing", "daum")
    assert parse_engines("bing,bing,daum") == ("bing", "daum")
    assert parse_engines("") == ("daum",)
    assert parse_engines("   ") == ("daum",)


def test_defaults_read_from_settings(monkeypatch):
    monkeypatch.setattr(
        search_options,
        "settings",
        SimpleNamespace(
            search_engine="google,bing",
            search_headless=True,
            search_stealth=False,
            search_locale="ko-KR",
            search_query_language="native",
        ),
    )
    opts = default_search_options()
    assert opts.engines == ("google", "bing")
    assert opts.headless is True
    # Nothing installed -> current resolves to the defaults.
    assert current_search_options() == opts


def test_installed_options_take_precedence():
    installed = SearchOptions(
        engines=("bing", "daum"),
        headless=False,
        stealth=True,
        locale="en-US",
        query_language="both",
    )
    token = use_search_options(installed)
    try:
        assert current_search_options() is installed
    finally:
        reset_search_options(token)
    # After reset the context falls back to the env defaults again.
    assert current_search_options().engines == default_search_options().engines
