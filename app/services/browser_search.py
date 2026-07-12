"""Headless-browser search backend.

Drives a real browser via Playwright against an engine priority list
(SEARCH_ENGINE, comma-separated; see _ENGINES). Engines are tried in order
and, on a bot challenge or error, the next engine takes over. Real browser
builds (Chrome/Edge channels) plus stealth pass bot checks that block plain
HTTP clients and bundled Chromium. Daum gives the best Korean results and
Bing is a reliable fallback; Google is supported but blocks aggressively and
its result-page selectors are brittle, so it is best used as a first choice
with Bing/Daum behind it in the priority list. "google_pse" is an API-type
engine (Custom Search JSON API, needs GOOGLE_PSE_API_KEY/GOOGLE_PSE_CX): it is
queried over HTTPS with no browser page, so it never sees a bot challenge.
Source pages are also fetched with the browser so JS-rendered sites can be
summarized.
"""

import base64
import time
from urllib.parse import parse_qs, quote_plus, urlparse

from app.core.config import settings
from app.services.page_meta import interpret_page_meta
from app.services.search_options import current_search_options


class BrowserSearchError(Exception):
    pass


class SearchChallengeError(BrowserSearchError):
    """The engine served a CAPTCHA / rate-limit challenge instead of results."""


_CHALLENGE_MARKERS = (
    "계속하려면 아래 과제",
    "마지막 한 단계",
    "solve the challenge",
    "verify you are human",
    # Google's block / CAPTCHA interstitials.
    "unusual traffic",
    "our systems have detected",
    "not a robot",
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

_EXTRACT_GOOGLE_JS = """
(nodes) => nodes.map((node) => {
  const link = node.querySelector("a[href]");
  const title = node.querySelector("h3");
  const snippet = node.querySelector("div[data-sncf], .VwiC3b, .IsZvec");
  return {
    title: title ? (title.textContent || "").trim() : "",
    url: link ? link.href : "",
    snippet: snippet ? (snippet.textContent || "").trim() : "",
  };
}).filter((item) => item.title && item.url)
"""

_EXTRACT_PAGE_TEXT_JS = """
() => {
  const meta = {};
  for (const el of document.querySelectorAll("meta[name][content], meta[property][content]")) {
    const key = (el.getAttribute("name") || el.getAttribute("property") || "").trim().toLowerCase();
    if (key && !(key in meta)) meta[key] = (el.getAttribute("content") || "").trim();
  }
  const ld = [];
  for (const el of document.querySelectorAll('script[type="application/ld+json"]')) {
    if (ld.length >= 5) break;
    const body = (el.textContent || "").trim();
    if (body) ld.push(body);
  }
  return {
    title: document.title || "",
    text: document.body ? document.body.innerText : "",
    meta,
    ld_json: ld,
  };
}
"""


# Engine registry: URL template, container selector for one result, and
# extraction JS returning [{title, url, snippet}]. "decode_url" unwraps
# engine redirect links to the real URL when needed.
_ENGINES: dict[str, dict] = {}


def _engine_config(engine: str) -> dict:
    config = _ENGINES.get(engine)
    if config is None:
        available = ", ".join(sorted(_ENGINES))
        raise BrowserSearchError(
            f"Unknown SEARCH_ENGINE '{engine}' (available: {available})"
        )
    return config


def _engine_priority(engines: tuple[str, ...]) -> list[tuple[str, dict]]:
    """Resolve an engine priority list to (name, config) pairs in order.

    Unknown engine names are dropped; raises if none are usable.
    """
    resolved: list[tuple[str, dict]] = []
    chosen: set[str] = set()
    for name in engines:
        config = _ENGINES.get(name)
        if config is not None and name not in chosen:
            resolved.append((name, config))
            chosen.add(name)
    if not resolved:
        available = ", ".join(sorted(_ENGINES))
        raise BrowserSearchError(
            f"No usable search engine in {list(engines)} (available: {available})"
        )
    return resolved


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


def decode_google_url(href: str) -> str:
    # Organic Google results are usually direct links, but some are wrapped in
    # a /url?q=<real> redirect.
    parsed = urlparse(href)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q", [""])[0]
        if target.startswith(("http://", "https://")):
            return target
    return href


def _search_google_pse_api(query: str) -> list[dict[str, str]]:
    from app.services.google_pse import GooglePSEQuotaError, search_google_pse

    try:
        return search_google_pse(query)
    except GooglePSEQuotaError as exc:
        # Quota/permission failures won't heal within a run; blocking the
        # engine (like a bot challenge) stops pointless retries.
        raise SearchChallengeError(str(exc)) from exc


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
        # Google blocks aggressively and its markup is obfuscated/volatile, so
        # these selectors are best-effort; the priority fallback covers misses.
        "google": {
            "url_template": "https://www.google.com/search?q={query}",
            "result_selector": "div.tF2Cxc, div.g",
            "extract_js": _EXTRACT_GOOGLE_JS,
            "decode_url": decode_google_url,
        },
        # API engine: queried over HTTPS, no browser page or selectors.
        "google_pse": {
            "api_search": _search_google_pse_api,
            "decode_url": None,
        },
    }
)


def _launch_browser(playwright):
    last_error: Exception | None = None
    for channel in _BROWSER_CHANNELS:
        try:
            return playwright.chromium.launch(
                headless=current_search_options().headless,
                channel=channel,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            last_error = exc
    raise BrowserSearchError(
        f"No usable browser found (install Chrome/Edge or run 'playwright install chromium'): {last_error}"
    )


def _apply_stealth(page) -> None:
    """Patch a page with playwright-stealth when SEARCH_STEALTH is enabled.

    Stealth masks the automation fingerprints (navigator.webdriver, headless
    quirks) that engines use to serve bot challenges. Opt-in: it adds a
    dependency and a small per-page cost. Supports both the 1.x module-level
    helper and the 2.x Stealth class entry points.
    """
    if not current_search_options().stealth:
        return
    try:
        import playwright_stealth as stealth
    except ImportError as exc:
        raise BrowserSearchError(
            "SEARCH_STEALTH is on but playwright-stealth is not installed "
            "(pip install playwright-stealth)"
        ) from exc

    apply = getattr(stealth, "stealth_sync", None)  # playwright-stealth 1.x
    if callable(apply):
        apply(page)
        return
    stealth_cls = getattr(stealth, "Stealth", None)  # playwright-stealth 2.x
    if stealth_cls is not None:
        instance = stealth_cls()
        method = getattr(instance, "apply_stealth_sync", None) or getattr(
            instance, "apply_sync", None
        )
        if callable(method):
            method(page)
            return
    raise BrowserSearchError(
        "playwright-stealth is installed but exposes no known stealth API "
        "(check its version)"
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


def _search_query_with_fallback(
    page,
    engine_priority: list[tuple[str, dict]],
    blocked: set[str],
    query: str,
    timeout_ms: int,
) -> tuple[str | None, dict | None, list[dict[str, str]], str | None]:
    """Try each non-blocked engine in priority order for one query.

    Fallback happens on a bot challenge or an engine error, NOT on a valid
    empty result (the first engine that answers wins, even with zero hits). A
    challenge marks that engine blocked for the rest of the session so later
    queries skip it. Returns (engine_name, config, items, error): items may be
    empty on success; on total failure returns (None, None, [], last_error).
    """
    last_error: str | None = None
    for name, config in engine_priority:
        if name in blocked:
            continue
        try:
            api_search = config.get("api_search")
            if api_search is not None:
                items = api_search(query)
            else:
                items = _run_search_query(page, config, query, timeout_ms)
        except SearchChallengeError:
            blocked.add(name)  # engine-level block for the rest of the run
            last_error = f"{name}: rate-limit challenge"
            continue
        except Exception as exc:
            last_error = f"{name}: {type(exc).__name__}: {exc}"
            continue
        return name, config, items, None
    return None, None, [], last_error


def search_with_browser(
    queries: list[str], max_results: int
) -> tuple[list[dict[str, str]], list[str]]:
    """Run each query against the engine priority list in a real browser.

    Returns (deduped results, per-query error messages).
    """
    sync_playwright = _sync_playwright()
    options = current_search_options()
    engine_priority = _engine_priority(options.engines)
    timeout_ms = settings.search_timeout_seconds * 1000
    results: list[dict[str, str]] = []
    extras: list[dict[str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    blocked: set[str] = set()
    # Spread the result budget across queries so one query (possibly
    # relaxed by the engine into something broader) cannot fill it alone.
    per_query_cap = max(2, -(-max_results // max(len(queries), 1)))

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(
                locale=options.locale,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            _apply_stealth(page)
            for index, query in enumerate(queries):
                if len(results) >= max_results:
                    break
                if index > 0:
                    page.wait_for_timeout(1000)
                name, config, items, error = _search_query_with_fallback(
                    page, engine_priority, blocked, query, timeout_ms
                )
                if name is None:
                    errors.append(f"{query}: {error or 'all engines failed'}")
                    continue
                if not items:
                    errors.append(f"{query}: no results extracted ({name})")
                    continue
                decode_url = config.get("decode_url") or (lambda href: href)
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
                        "engine": name,
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

    Each query independently walks the engine priority list, so a challenge on
    one engine drops to the next. Returns one entry per query:
    {"query", "results", "error"}.
    """
    sync_playwright = _sync_playwright()
    options = current_search_options()
    engine_priority = _engine_priority(options.engines)
    timeout_ms = settings.search_timeout_seconds * 1000
    grouped: list[dict[str, object]] = []
    blocked: set[str] = set()

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(
                locale=options.locale,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            _apply_stealth(page)
            for index, query in enumerate(queries):
                if index > 0:
                    page.wait_for_timeout(1000)
                name, config, items, error = _search_query_with_fallback(
                    page, engine_priority, blocked, query, timeout_ms
                )
                if name is None:
                    grouped.append(
                        {
                            "query": query,
                            "results": [],
                            "error": error or "all engines failed",
                            "engine": None,
                        }
                    )
                    continue
                decode_url = config.get("decode_url") or (lambda href: href)
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
                            "engine": name,
                        }
                    )
                    if len(results) >= per_query:
                        break
                grouped.append(
                    {
                        "query": query,
                        "results": results,
                        "error": None if results else f"no results extracted ({name})",
                        "engine": name,
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
                locale=current_search_options().locale,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            _apply_stealth(page)
            for url in urls:
                entry = {"url": url, "title": "", "text": "", "error": ""}
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(500)
                    extracted = page.evaluate(_EXTRACT_PAGE_TEXT_JS)
                    entry["title"] = (extracted.get("title") or "").strip()
                    entry["text"] = _clean_page_text(extracted.get("text") or "")
                    entry.update(
                        interpret_page_meta(
                            extracted.get("meta") or {},
                            extracted.get("ld_json") or [],
                        )
                    )
                except Exception as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                pages.append(entry)
        finally:
            browser.close()

    return pages
