import io
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.schemas.projects import ProjectRead
from app.schemas.questions import UserDecisionRead
from app.services import search
from app.services.search import (
    _DuckDuckGoHTMLParser,
    _fallback_queries,
    _is_challenge_page,
    _search_once,
    _truncate_at_word,
    build_search_query,
    search_web,
)


def make_project(title="Docker 사용 가이드", request="docker 운영부터 빌드스크립트 제작. 필수 유지보수 팁") -> ProjectRead:
    return ProjectRead(
        id="p1",
        title=title,
        initial_request=request,
        status="created",
        current_phase="intake",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def make_decision(question: str, answer: str) -> UserDecisionRead:
    return UserDecisionRead(
        id="d1",
        project_id="p1",
        phase="intake",
        question_id="q1",
        question=question,
        answer=answer,
        applies_to=None,
        created_at="2026-01-01T00:00:00+00:00",
    )


LITE_RESULT_HTML = """
<table>
  <tr><td>
    <a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocker&amp;rut=abc"
       class='result-link'>Docker Guide</a>
  </td></tr>
  <tr><td class='result-snippet'>A practical Docker guide for beginners.</td></tr>
  <tr><td>
    <a rel="nofollow" href="https://example.org/other" class='result-link'>Other Guide</a>
  </td></tr>
  <tr><td class='result-snippet'>Second snippet text.</td></tr>
</table>
"""

CHALLENGE_HTML = """
<html><head><title>DuckDuckGo - Protection. Privacy. Peace of mind.</title></head>
<body><script>challenge()</script></body></html>
"""


class TestTruncateAtWord:
    def test_short_text_unchanged(self):
        assert _truncate_at_word("docker guide", 100) == "docker guide"

    def test_cuts_at_word_boundary(self):
        text = "alpha beta gamma delta"
        assert _truncate_at_word(text, 15) == "alpha beta"

    def test_collapses_whitespace(self):
        assert _truncate_at_word("a  b\n c", 100) == "a b c"


class TestBuildSearchQuery:
    def test_query_is_short(self):
        project = make_project(request="x " * 400)
        query = build_search_query(project, [])
        assert len(query) <= 100

    def test_excludes_decision_text(self):
        decisions = [make_decision("이 가이드의 주요 대상 독자는 누구인가요?", "초보 개발자")]
        query = build_search_query(make_project(), decisions)
        assert "누구인가요" not in query

    def test_uses_first_sentence_only(self):
        query = build_search_query(make_project(), [])
        assert "유지보수" not in query
        assert "Docker" in query or "docker" in query


class TestFallbackQueries:
    def test_includes_title_query(self):
        queries = _fallback_queries(make_project(), [])
        assert "Docker 사용 가이드" in queries

    def test_no_duplicates(self):
        project = make_project(title="Docker", request="Docker")
        queries = _fallback_queries(project, [])
        assert len(queries) == len(set(queries))


class TestDuckDuckGoParser:
    def test_parses_lite_results_with_snippets(self):
        parser = _DuckDuckGoHTMLParser()
        parser.feed(LITE_RESULT_HTML)
        assert len(parser.results) == 2
        first = parser.results[0]
        assert first["title"] == "Docker Guide"
        assert first["url"] == "https://example.com/docker"
        assert first["snippet"] == "A practical Docker guide for beginners."
        assert parser.results[1]["snippet"] == "Second snippet text."

    def test_challenge_page_yields_no_results(self):
        parser = _DuckDuckGoHTMLParser()
        parser.feed(CHALLENGE_HTML)
        assert parser.results == []


class TestChallengeDetection:
    def test_detects_protection_page(self):
        assert _is_challenge_page(CHALLENGE_HTML)

    def test_normal_results_page_is_not_challenge(self):
        assert not _is_challenge_page(LITE_RESULT_HTML)


class FakeResponse:
    def __init__(self, html: str):
        self._body = io.BytesIO(html.encode("utf-8"))

    def read(self, *args):
        return self._body.read(*args)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestSearchOnce:
    def test_challenge_page_reported_as_error(self, monkeypatch):
        monkeypatch.setattr(
            search.urllib.request, "urlopen", lambda *a, **k: FakeResponse(CHALLENGE_HTML)
        )
        results, error = _search_once("some query")
        assert results == []
        assert error is not None and "bot-protection" in error

    def test_results_page_parsed(self, monkeypatch):
        monkeypatch.setattr(
            search.urllib.request, "urlopen", lambda *a, **k: FakeResponse(LITE_RESULT_HTML)
        )
        results, error = _search_once("docker guide")
        assert error is None
        assert [r["url"] for r in results] == [
            "https://example.com/docker",
            "https://example.org/other",
        ]

    def test_sends_short_encoded_query(self, monkeypatch):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            return FakeResponse(LITE_RESULT_HTML)

        monkeypatch.setattr(search.urllib.request, "urlopen", fake_urlopen)
        _search_once("docker 가이드")
        query = parse_qs(urlparse(seen["url"]).query)["q"][0]
        assert query == "docker 가이드"


def fake_settings(**overrides) -> SimpleNamespace:
    values = {
        "search_enabled": True,
        "llm_enabled": False,
        "search_backend": "http",
        "search_max_results": 5,
        "chapter_search_results": 2,
        "search_timeout_seconds": 15,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestSearchWeb:
    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(search, "settings", fake_settings(search_enabled=False))
        result = search_web(make_project(), [])
        assert result["enabled"] is False
        assert result["results"] == []
        assert result["error"] is None

    def test_collects_and_dedupes_across_queries(self, monkeypatch):
        monkeypatch.setattr(search, "settings", fake_settings())
        monkeypatch.setattr(
            search.urllib.request, "urlopen", lambda *a, **k: FakeResponse(LITE_RESULT_HTML)
        )
        result = search_web(make_project(), [])
        assert result["query_source"] == "fallback"
        assert result["backend"] == "http"
        urls = [r["url"] for r in result["results"]]
        assert urls == sorted(set(urls), key=urls.index)
        assert result["error"] is None

    def test_all_queries_challenged_sets_error(self, monkeypatch):
        monkeypatch.setattr(search, "settings", fake_settings())
        monkeypatch.setattr(
            search.urllib.request, "urlopen", lambda *a, **k: FakeResponse(CHALLENGE_HTML)
        )
        result = search_web(make_project(), [])
        assert result["results"] == []
        assert result["error"] is not None


class TestResearchChapters:
    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(search, "settings", fake_settings(search_enabled=False))
        result = search.research_chapters(make_project(), {"outline_tree": [{"id": "1", "title": "Intro"}]})
        assert result["enabled"] is False
        assert result["chapters"] == []

    def test_http_fallback_collects_per_chapter(self, monkeypatch):
        monkeypatch.setattr(
            search,
            "settings",
            fake_settings(search_backend="http", chapter_search_results=2),
        )
        monkeypatch.setattr(
            search.urllib.request, "urlopen", lambda *a, **k: FakeResponse(LITE_RESULT_HTML)
        )
        plan = {"outline_tree": [{"id": "1", "title": "Intro"}, {"id": "2", "title": "Body"}]}
        result = search.research_chapters(make_project(), plan)
        assert result["enabled"] is True
        assert len(result["chapters"]) == 2
        for chapter in result["chapters"]:
            assert len(chapter["sources"]) == 2
            assert chapter["query"]

    def test_chapter_query_is_short(self):
        project = make_project(title="T " * 100)
        query = search.build_chapter_query(project, {"title": "챕터 제목"})
        assert len(query) <= 100


class TestSearchBackends:
    def test_browser_backend_used_when_available(self, monkeypatch):
        monkeypatch.setattr(search, "settings", fake_settings(search_backend="auto"))
        monkeypatch.setattr(
            search,
            "_search_browser",
            lambda queries: ([{"title": "T", "url": "https://a.com", "snippet": "s"}], []),
        )
        result = search_web(make_project(), [])
        assert result["backend"] == "browser"
        assert result["results"][0]["url"] == "https://a.com"
        assert result["error"] is None

    def test_auto_falls_back_to_http_when_browser_fails(self, monkeypatch):
        monkeypatch.setattr(search, "settings", fake_settings(search_backend="auto"))

        def broken_browser(queries):
            raise RuntimeError("no chromium")

        monkeypatch.setattr(search, "_search_browser", broken_browser)
        monkeypatch.setattr(
            search.urllib.request, "urlopen", lambda *a, **k: FakeResponse(LITE_RESULT_HTML)
        )
        result = search_web(make_project(), [])
        assert result["backend"] == "http"
        assert len(result["results"]) > 0
        assert result["error"] is None

    def test_browser_only_backend_reports_failure(self, monkeypatch):
        monkeypatch.setattr(search, "settings", fake_settings(search_backend="browser"))

        def broken_browser(queries):
            raise RuntimeError("no chromium")

        monkeypatch.setattr(search, "_search_browser", broken_browser)
        result = search_web(make_project(), [])
        assert result["backend"] == "browser"
        assert result["results"] == []
        assert "no chromium" in result["error"]
