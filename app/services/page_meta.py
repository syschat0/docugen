"""Citation metadata (author, published year, site name) from page HTML.

Web pages rarely need more than their meta tags and schema.org JSON-LD to
cite properly, and both are site-declared facts, so extraction here is
deterministic — no model calls, no guessing. Missing values stay empty and
the citation renderer falls back to (site, n.d.).
"""

import json
import re
from html.parser import HTMLParser
from typing import Any, Iterator

_MAX_LD_BLOCKS = 5
_MAX_AUTHOR_CHARS = 60

_AUTHOR_META_KEYS = ("author", "article:author", "dc.creator", "sailthru.author")
_PUBLISHED_META_KEYS = (
    "article:published_time",
    "og:article:published_time",
    "datepublished",
    "date",
    "dc.date",
    "dc.date.issued",
    "sailthru.date",
)
_SITE_META_KEYS = ("og:site_name", "application-name")

# Schema.org types whose author/datePublished describe the page content
# itself (rather than e.g. a review embedded in it).
_ARTICLE_LD_TYPES = {
    "article",
    "newsarticle",
    "blogposting",
    "scholarlyarticle",
    "techarticle",
    "report",
    "webpage",
}

_YEAR_PATTERN = re.compile(r"(19|20)\d{2}")


class _MetaExtractParser(HTMLParser):
    """Collects <meta name/property=... content=...> pairs and JSON-LD bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.ld_json: list[str] = []
        self._in_ld_script = False
        self._script_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "meta":
            key = (attr.get("name") or attr.get("property") or "").strip().lower()
            content = attr.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif (
            tag == "script"
            and attr.get("type", "").strip().lower() == "application/ld+json"
        ):
            self._in_ld_script = True
            self._script_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ld_script:
            self._in_ld_script = False
            body = "".join(self._script_parts).strip()
            if body and len(self.ld_json) < _MAX_LD_BLOCKS:
                self.ld_json.append(body)

    def handle_data(self, data: str) -> None:
        if self._in_ld_script:
            self._script_parts.append(data)


def _clean_author(value: Any) -> str:
    """A usable author name, or empty. Rejects URLs (article:author is often
    a profile link) and site chrome like bare handles."""
    text = " ".join(str(value or "").split())
    if not text or "://" in text or text.startswith(("@", "/")):
        return ""
    return text[:_MAX_AUTHOR_CHARS]


def _author_names(value: Any) -> list[str]:
    if isinstance(value, str):
        name = _clean_author(value)
        return [name] if name else []
    if isinstance(value, dict):
        return _author_names(value.get("name"))
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_author_names(item))
        return names
    return []


def _join_authors(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"[:_MAX_AUTHOR_CHARS]
    return f"{names[0]} et al."[:_MAX_AUTHOR_CHARS]


def _year_from(value: Any) -> str:
    match = _YEAR_PATTERN.search(str(value or ""))
    return match.group(0) if match else ""


def _walk_ld_nodes(data: Any) -> Iterator[dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _walk_ld_nodes(item)
    elif isinstance(data, dict):
        yield data
        yield from _walk_ld_nodes(data.get("@graph"))


def _node_types(node: dict[str, Any]) -> set[str]:
    value = node.get("@type")
    if isinstance(value, str):
        return {value.strip().lower()}
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value}
    return set()


def _ld_nodes(ld_json: list[str]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for blob in ld_json[:_MAX_LD_BLOCKS]:
        try:
            parsed = json.loads(blob)
        except (json.JSONDecodeError, TypeError):
            continue
        nodes.extend(_walk_ld_nodes(parsed))
    # Article-typed nodes describe the page content; other nodes only count
    # when nothing article-typed is present.
    articles = [node for node in nodes if _node_types(node) & _ARTICLE_LD_TYPES]
    return articles or nodes


def interpret_page_meta(
    meta: dict[str, str], ld_json: list[str]
) -> dict[str, str]:
    """Resolve author / published_year / site_name with JSON-LD first.

    Returns only non-empty fields, so callers can `update()` a source dict
    without writing blank keys into stored artifacts.
    """
    meta = {str(key).strip().lower(): str(value) for key, value in (meta or {}).items()}
    nodes = _ld_nodes(ld_json or [])

    author = ""
    year = ""
    site = ""
    for node in nodes:
        author = author or _join_authors(_author_names(node.get("author")))
        year = year or _year_from(node.get("datePublished"))
        publisher = node.get("publisher")
        if not site and isinstance(publisher, dict):
            site = " ".join(str(publisher.get("name") or "").split())[:_MAX_AUTHOR_CHARS]

    if not author:
        for key in _AUTHOR_META_KEYS:
            author = _clean_author(meta.get(key))
            if author:
                break
    if not year:
        for key in _PUBLISHED_META_KEYS:
            year = _year_from(meta.get(key))
            if year:
                break
    if not site:
        for key in _SITE_META_KEYS:
            site = " ".join(str(meta.get(key) or "").split())[:_MAX_AUTHOR_CHARS]
            if site:
                break

    result = {"author": author, "published_year": year, "site_name": site}
    return {key: value for key, value in result.items() if value}


def extract_page_meta(html_text: str) -> dict[str, str]:
    """Parse raw HTML and resolve citation metadata (see interpret_page_meta)."""
    parser = _MetaExtractParser()
    try:
        parser.feed(str(html_text or ""))
    except Exception:
        return {}
    return interpret_page_meta(parser.meta, parser.ld_json)
