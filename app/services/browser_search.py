"""Headless-browser search backend.

Drives a real browser via Playwright against a configurable engine
(SEARCH_ENGINE, see _ENGINES). Real browser builds (Chrome/Edge
channels) pass bot checks that block plain HTTP clients and bundled
Chromium; DuckDuckGo, Google, Ecosia, and Mojeek block even those, so
the supported engines are Daum (best Korean results) and Bing. Source
pages are also fetched with the browser so JS-rendered sites can be
summarized.
"""

import base64
import time
from urllib.parse import parse_qs, quote_plus, urlparse

from app.core.config import settings


class BrowserSearchError(Exception):
    pass


class SearchChallengeError(BrowserSearchError):
    """The engine served a CAPTCHA / rate-limit challenge instead of results."""


_CHALLENGE_MARKERS = (
    "계속하려면 아래 과제",
    "마지막 한 단계",
    "solve the challenge",
    "verify you are human",
)


# Real browser builds pass Bing's bot checks; bundled Chromium usually
# does not, but is kept as a last resort.
_BROWSER_CHANNELS: tuple[str | None, ...] = ("chrome", "msedge", None)

_EXTRACT_BING_JS = """
(nodes) => nodes.map((node) => {
  const link = node.querySelector("h2 a");
  const snippet = node.querySelector(".b_caption p, p");
  return {
    title: link ? (link.textContent || "").trim() : "",
    url: link ? link.href : "",
    snippet: snippet ? (snippet.textContent || "").trim() : "",
  };
}).filter((item) => item.title && item.url)
"""

_EXTRACT_DAUM_JS = """
(nodes) => nodes.map((node) => {
  const link = node.querySelector(".tit-g a, a[class*='tit']");
  const snippet = node.querySelector("p.conts-desc, .desc, p");
  return {
    title: link ? (link.textContent || "").trim() : "",
    url: link ? link.href : "",
    snippet: snippet ? (snippet.textContent || "").trim() : "",
  };
}).filter((item) => item.title && item.url)
"""

_EXTRACT_PAGE_TEXT_JS = """
() => ({
  title: document.title || "",
  text: document.body ? document.body.innerText : "",
})
"""


# Engine registry: URL template, container selector for one result, and
# extraction JS returning [{title, url, snippet}]. "decode_url" unwraps
# engine redirect links to the real URL when needed.
_ENGINES: dict[str, dict] = {}


def _engine_config() -> dict:
    config = _ENGINES.get(settings.search_engine)
    if config is None:
        available = ", ".join(sorted(_ENGINES))
        raise BrowserSearchError(
            f"Unknown SEARCH_ENGINE '{settings.search_engine}' (available: {available})"
        )
    return config


def decode_bing_url(href: str) -> str:
    parsed = urlparse(href)
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/"):
        u = parse_qs(parsed.query).get("u", [""])[0]
        if u.startswith("a1"):
            payload = u[2:]
            payload += "=" * (-len(payload) % 4)
            try:
                decoded = base64.b64decode(
                    payload, altchars=b"-_", validate=True
                ).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return href
            if decoded.startswith(("http://", "https://")):
                return decoded
    return href


_ENGINES.update(
    {
        "daum": {
            "url_template": "https://search.daum.net/search?w=web&q={query}",
            "result_selector": ".c-item-doc",
            "extract_js": _EXTRACT_DAUM_JS,
            "decode_url": None,
        },
        "bing": {
            "url_template": "https://www.bing.com/search?q={query}",
            "result_selector": "li.b_algo",
            "extract_js": _EXTRACT_BING_JS,
            "decode_url": decode_bing_url,
        },
    }
)


def _launch_browser(playwright):
    last_error: Exception | None = None
    for channel in _BROWSER_CHANNELS:
        try:
            return playwright.chromium.launch(
                headless=True,
                channel=channel,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            last_error = exc
    raise BrowserSearchError(
        f"No usable browser found (install Chrome/Edge or run 'playwright install chromium'): {last_error}"
    )


def _sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserSearchError(
            "playwright is not installed (pip install playwright)"
        ) from exc
    return sync_playwright


def _run_search_query(page, config: dict, query: str, timeout_ms: int) -> list[dict[str, str]]:
    # Some engines (Bing) follow the search request with a self-redirect,
    # so waiting on a selector can race the navigation. Poll for extracted
    # results instead; evaluation errors during a navigation are retried.
    selector = config["result_selector"]
    extract_js = config["extract_js"]
    page.goto(
        config["url_template"].format(query=quote_plus(query)),
        timeout=timeout_ms,
        wait_until="commit",
    )
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            items = page.eval_on_selector_all(selector, extract_js)
        except Exception:
            items = []
        if not items:
            try:
                body = page.evaluate(
                    "() => document.body ? document.body.innerText.slice(0, 600) : ''"
                )
            except Exception:
                body = ""
            if any(marker in body for marker in _CHALLENGE_MARKERS):
                raise SearchChallengeError(
                    "search engine served a rate-limit challenge (try again later)"
                )
        if items:
            # One settle pass: text/snippets may still be streaming in.
            page.wait_for_timeout(700)
            try:
                settled = page.eval_on_selector_all(selector, extract_js)
                return settled or items
            except Exception:
                return items
        page.wait_for_timeout(400)
    return []


def search_with_browser(
    queries: list[str], max_results: int
) -> tuple[list[dict[str, str]], list[str]]:
    """Run each query on the configured engine in a headless real browser.

    Returns (deduped results, per-query error messages).
    """
    sync_playwright = _sync_playwright()
    config = _engine_config()
    decode_url = config.get("decode_url") or (lambda href: href)
    timeout_ms = settings.search_timeout_seconds * 1000
    results: list[dict[str, str]] = []
    extras: list[dict[str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    # Spread the result budget across queries so one query (possibly
    # relaxed by the engine into something broader) cannot fill it alone.
    per_query_cap = max(2, -(-max_results // max(len(queries), 1)))

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(
                locale="ko-KR",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            for index, query in enumerate(queries):
                if len(results) >= max_results:
                    break
                if index > 0:
                    page.wait_for_timeout(1000)
                try:
                    items = _run_search_query(page, config, query, timeout_ms)
                except SearchChallengeError as exc:
                    # The whole session is rate-limited; further queries
                    # would only extend the block.
                    errors.append(f"{query}: {exc}")
                    break
                except Exception as exc:
                    errors.append(f"{query}: {type(exc).__name__}: {exc}")
                    continue
                if not items:
                    errors.append(f"{query}: no results extracted")
                    continue
                taken = 0
                for item in items:
                    url = decode_url(item.get("url", ""))
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    normalized = {
                        "title": item.get("title", ""),
                        "url": url,
                        "snippet": item.get("snippet", ""),
                    }
                    if taken < per_query_cap and len(results) < max_results:
                        results.append(normalized)
                        taken += 1
                    else:
                        extras.append(normalized)
        finally:
            browser.close()

    for extra in extras:
        if len(results) >= max_results:
            break
        results.append(extra)

    return results, errors


def search_grouped(
    queries: list[str], per_query: int
) -> list[dict[str, object]]:
    """Run each query in one shared browser session, keeping results per query.

    Returns one entry per query: {"query", "results", "error"}.
    """
    sync_playwright = _sync_playwright()
    config = _engine_config()
    decode_url = config.get("decode_url") or (lambda href: href)
    timeout_ms = settings.search_timeout_seconds * 1000
    grouped: list[dict[str, object]] = []

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(
                locale="ko-KR",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            for index, query in enumerate(queries):
                if index > 0:
                    page.wait_for_timeout(1000)
                try:
                    items = _run_search_query(page, config, query, timeout_ms)
                except SearchChallengeError as exc:
                    grouped.append({"query": query, "results": [], "error": str(exc)})
                    for skipped in queries[index + 1 :]:
                        grouped.append(
                            {
                                "query": skipped,
                                "results": [],
                                "error": "skipped after rate-limit challenge",
                            }
                        )
                    break
                except Exception as exc:
                    grouped.append(
                        {
                            "query": query,
                            "results": [],
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                results: list[dict[str, str]] = []
                seen: set[str] = set()
                for item in items:
                    url = decode_url(item.get("url", ""))
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    results.append(
                        {
                            "title": item.get("title", ""),
                            "url": url,
                            "snippet": item.get("snippet", ""),
                        }
                    )
                    if len(results) >= per_query:
                        break
                grouped.append(
                    {
                        "query": query,
                        "results": results,
                        "error": None if results else "no results extracted",
                    }
                )
        finally:
            browser.close()

    return grouped


def _clean_page_text(raw: str) -> str:
    # Drop short lines (navigation, buttons, menus) so summaries carry the
    # article body instead of site chrome.
    lines = (" ".join(line.split()) for line in raw.splitlines())
    return " ".join(line for line in lines if len(line) >= 25)


def fetch_page_texts(urls: list[str]) -> list[dict[str, str]]:
    """Fetch each URL in a headless real browser and extract title + visible text.

    Returns one entry per URL: {"url", "title", "text", "error"}.
    """
    sync_playwright = _sync_playwright()
    timeout_ms = settings.search_timeout_seconds * 1000
    pages: list[dict[str, str]] = []

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(
                locale="ko-KR",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            for url in urls:
                entry = {"url": url, "title": "", "text": "", "error": ""}
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(500)
                    extracted = page.evaluate(_EXTRACT_PAGE_TEXT_JS)
                    entry["title"] = (extracted.get("title") or "").strip()
                    entry["text"] = _clean_page_text(extracted.get("text") or "")
                except Exception as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                pages.append(entry)
        finally:
            browser.close()

    return pages
