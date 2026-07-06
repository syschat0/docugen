from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
import urllib.error
import urllib.request

from app.core.config import settings
from app.schemas.projects import ProjectRead
from app.schemas.questions import UserDecisionRead


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture_title = False
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        class_name = attr.get("class", "")
        if tag == "a" and ("result__a" in class_name or "result-link" in class_name):
            href = attr.get("href", "")
            self._current = {"title": "", "url": _clean_duckduckgo_url(href), "snippet": ""}
            self._capture_title = True
        elif self._current is not None and (
            "result__snippet" in class_name or "result-snippet" in class_name
        ):
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            self._capture_title = False
            if self._current is not None and self._current.get("title") and self._current.get("url"):
                self.results.append(self._current)
        elif self._capture_snippet and tag in {"a", "div", "td"}:
            self._capture_snippet = False
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = " ".join(unescape(data).split())
        if not text:
            return
        if self._capture_title:
            self._current["title"] = (self._current["title"] + " " + text).strip()
        elif self._capture_snippet:
            self._current["snippet"] = (self._current["snippet"] + " " + text).strip()


class _TextExtractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.text_parts: list[str] = []
        self._skip = False
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = " ".join(unescape(data).split())
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()
        elif len(text) > 40:
            self.text_parts.append(text)

def _clean_duckduckgo_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)
    return url


# DuckDuckGo rejects long machine-built queries with a bot-protection page
# (HTTP 200, zero results), so queries must stay short.
_MAX_QUERY_CHARS = 100

_CHALLENGE_MARKERS = (
    "Protection. Privacy. Peace of mind",
    "anomaly",
    "not a robot",
)


def _truncate_at_word(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip()


def build_search_query(project: ProjectRead, decisions: list[UserDecisionRead]) -> str:
    request_head = project.initial_request.split(".")[0].split("?")[0]
    return _truncate_at_word(f"{project.title} {request_head}", _MAX_QUERY_CHARS)


def _fallback_queries(project: ProjectRead, decisions: list[UserDecisionRead]) -> list[str]:
    queries = [build_search_query(project, decisions)]
    title = _truncate_at_word(project.title, _MAX_QUERY_CHARS)
    if title and title not in queries:
        queries.append(title)
    return [query for query in queries if query]


def _plan_queries(
    project: ProjectRead, decisions: list[UserDecisionRead]
) -> tuple[list[str], str]:
    if settings.llm_enabled:
        from app.services.llm import LLMError, plan_search_queries

        try:
            queries, _usage = plan_search_queries(project, decisions)
            return queries, "llm"
        except LLMError:
            pass
    return _fallback_queries(project, decisions), "fallback"


def _is_challenge_page(html: str) -> bool:
    return any(marker in html for marker in _CHALLENGE_MARKERS)


def _search_once(query: str) -> tuple[list[dict[str, str]], str | None]:
    url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 DocuGen/0.1",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=settings.search_timeout_seconds
        ) as response:
            html = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        return [], str(exc)

    parser = _DuckDuckGoHTMLParser()
    parser.feed(html)
    if not parser.results and _is_challenge_page(html):
        return [], f"Search engine returned a bot-protection page for query: {query}"
    return parser.results, None


def _search_http(queries: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    errors: list[str] = []
    for query in queries:
        if len(deduped) >= settings.search_max_results:
            break
        results, error = _search_once(query)
        if error:
            errors.append(error)
            continue
        for result in results:
            url = result["url"]
            if url in seen:
                continue
            seen.add(url)
            deduped.append(result)
            if len(deduped) >= settings.search_max_results:
                break
    return deduped, errors


def _search_browser(queries: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    from app.services.browser_search import search_with_browser

    return search_with_browser(queries, settings.search_max_results)


def search_web(project: ProjectRead, decisions: list[UserDecisionRead]) -> dict[str, Any]:
    if not settings.search_enabled:
        return {
            "enabled": False,
            "query": build_search_query(project, decisions),
            "queries": [],
            "results": [],
            "error": None,
        }

    queries, query_source = _plan_queries(project, decisions)
    backend = settings.search_backend
    results: list[dict[str, str]] = []
    errors: list[str] = []
    used_backend = "http"

    if backend in {"auto", "browser"}:
        used_backend = "browser"
        try:
            results, errors = _search_browser(queries)
        except Exception as exc:
            errors.append(f"browser search unavailable: {exc}")

    if not results and backend != "browser":
        used_backend = "http"
        http_results, http_errors = _search_http(queries)
        if http_results:
            results = http_results
            errors = []
        else:
            errors.extend(http_errors)

    return {
        "enabled": True,
        "query": " | ".join(queries),
        "queries": queries,
        "query_source": query_source,
        "backend": used_backend,
        "results": results,
        "error": "; ".join(errors) if errors and not results else None,
    }


def build_chapter_query(project: ProjectRead, chapter: dict[str, Any]) -> str:
    title = str(chapter.get("title") or "")
    # Chapter titles are often "서론: ..." style sentences; the part after the
    # colon carries the searchable topic. The full project title makes the
    # query too narrative for search engines, so it is left out.
    if ":" in title:
        title = title.split(":", 1)[1].strip() or title
    return _truncate_at_word(title, _MAX_QUERY_CHARS)


def _plan_chapter_queries(
    project: ProjectRead, chapters: list[dict[str, Any]]
) -> tuple[list[str], str]:
    if settings.llm_enabled:
        from app.services.llm import LLMError, plan_chapter_queries

        try:
            queries, _usage = plan_chapter_queries(project, chapters)
            return queries, "llm"
        except LLMError:
            pass
    return [build_chapter_query(project, chapter) for chapter in chapters], "fallback"


def research_chapters(
    project: ProjectRead, section_plan: dict[str, Any]
) -> dict[str, Any]:
    """Targeted follow-up research: a few sources per top-level chapter."""
    chapters = [
        chapter
        for chapter in (section_plan.get("outline_tree") or [])
        if isinstance(chapter, dict)
    ]
    if not settings.search_enabled or not chapters:
        return {"enabled": settings.search_enabled, "chapters": []}

    queries, query_source = _plan_chapter_queries(project, chapters)
    entries: list[dict[str, Any]] = []
    for chapter, query in zip(chapters, queries):
        entries.append(
            {
                "chapter_id": str(chapter.get("id", "")),
                "title": str(chapter.get("title", "")),
                "query": query,
                "sources": [],
                "error": None,
            }
        )

    per_query = settings.chapter_search_results
    grouped: list[dict[str, Any]] | None = None
    browser_ok = False
    if settings.search_backend in {"auto", "browser"}:
        try:
            from app.services.browser_search import search_grouped

            grouped = search_grouped(queries, per_query)
            browser_ok = True
        except Exception as exc:
            if settings.search_backend == "browser":
                return {
                    "enabled": True,
                    "chapters": entries,
                    "error": f"browser search unavailable: {exc}",
                }

    if grouped is None:
        grouped = []
        for query in queries:
            results, error = _search_once(query)
            grouped.append({"query": query, "results": results[:per_query], "error": error})

    pages_by_url: dict[str, dict[str, str]] = {}
    if browser_ok:
        urls: list[str] = []
        for group in grouped:
            for result in group.get("results") or []:
                url = result.get("url")
                if url and url not in urls:
                    urls.append(url)
        if urls:
            try:
                from app.services.browser_search import fetch_page_texts

                pages_by_url = {page["url"]: page for page in fetch_page_texts(urls)}
            except Exception:
                pages_by_url = {}

    for entry, group in zip(entries, grouped):
        entry["error"] = group.get("error")
        for result in (group.get("results") or [])[:per_query]:
            url = result.get("url", "")
            page = pages_by_url.get(url, {})
            text = page.get("text") or ""
            # Very short page text is usually an error page or a paywall;
            # the search snippet is more informative then.
            summary = text[:600] if len(text) >= 200 else (result.get("snippet") or text)
            entry["sources"].append(
                {
                    "title": page.get("title") or result.get("title", ""),
                    "url": url,
                    "snippet": result.get("snippet", ""),
                    "summary": summary,
                }
            )

    return {"enabled": True, "query_source": query_source, "chapters": entries}


def build_section_query(section: dict[str, Any]) -> str:
    """Short keyword query for one leaf section (title + first key point)."""
    title = str(section.get("title") or "")
    if ":" in title:
        title = title.split(":", 1)[1].strip() or title
    key_points = [
        str(point).strip() for point in (section.get("key_points") or []) if str(point).strip()
    ]
    first_point = key_points[0] if key_points else ""
    if first_point and first_point.lower() != title.lower():
        return _truncate_at_word(f"{title} {first_point}", _MAX_QUERY_CHARS)
    return _truncate_at_word(title, _MAX_QUERY_CHARS)


def search_section_sources(
    section: dict[str, Any], limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    """Top-up search for one section whose planned sources are irrelevant."""
    if not settings.search_enabled:
        return [], None
    query = build_section_query(section)
    if not query:
        return [], None

    results: list[dict[str, str]] = []
    error: str | None = None
    if settings.search_backend in {"auto", "browser"}:
        try:
            from app.services.browser_search import search_grouped

            grouped = search_grouped([query], limit)
            results = (grouped[0].get("results") or [])[:limit] if grouped else []
            error = grouped[0].get("error") if grouped else None
        except Exception as exc:
            if settings.search_backend == "browser":
                return [], f"browser search unavailable: {exc}"

    if not results:
        http_results, http_error = _search_once(query)
        results = http_results[:limit]
        error = error or http_error

    sources = [
        {
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "snippet": result.get("snippet", ""),
            "summary": result.get("snippet", ""),
            "query": query,
        }
        for result in results
        if result.get("url")
    ]
    return sources, (None if sources else error)


def _summaries_via_browser(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    from app.services.browser_search import fetch_page_texts

    entries = [result for result in results if result.get("url")]
    pages = fetch_page_texts([result["url"] for result in entries])
    summaries: list[dict[str, str]] = []
    for result, page in zip(entries, pages):
        text = page.get("text", "")
        summaries.append(
            {
                "title": page.get("title") or result.get("title", ""),
                "url": result["url"],
                "summary": text[:1200] or result.get("snippet", ""),
                "error": page.get("error", ""),
            }
        )
    return summaries


def summarize_search_sources(research: dict[str, Any]) -> dict[str, Any]:
    results = (research.get("results") or [])[: settings.search_max_results]

    if settings.search_backend in {"auto", "browser"}:
        try:
            return {
                "query": research.get("query"),
                "backend": "browser",
                "sources": _summaries_via_browser(results),
            }
        except Exception:
            if settings.search_backend == "browser":
                raise

    summaries: list[dict[str, str]] = []
    for result in results:
        url = result.get("url")
        if not url:
            continue
        summary = {
            "title": result.get("title", ""),
            "url": url,
            "summary": result.get("snippet", ""),
            "error": "",
        }
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 DocuGen/0.1"})
            with urllib.request.urlopen(req, timeout=settings.search_timeout_seconds) as response:
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type:
                    summary["summary"] = summary["summary"] or f"Non-HTML source: {content_type}"
                else:
                    html = response.read(250000).decode("utf-8", errors="replace")
                    parser = _TextExtractParser()
                    parser.feed(html)
                    text = " ".join(parser.text_parts)
                    summary["title"] = parser.title or summary["title"]
                    summary["summary"] = text[:1200] or summary["summary"]
        except Exception as exc:
            summary["error"] = str(exc)
        summaries.append(summary)

    return {
        "query": research.get("query"),
        "backend": "http",
        "sources": summaries,
    }
