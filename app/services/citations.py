import re
from typing import Any, Dict
from urllib.parse import urlparse

# Supported bibliography styles. "numeric" renders [1]-style links with a
# numbered source list; "author_date" renders (site, n.d.)-style links with an
# alphabetized source list. The canonical tuple lives here so settings
# validation and rendering can never disagree.
CITATION_STYLES = ("numeric", "author_date")

# Matches bare inline citation markers like [1] or [12] (including adjacent
# ones like [1][2]), but not markdown links "[1](url)" or link text "[[1]]".
_CITATION_PATTERN = re.compile(r"(?<!\[)\[(\d{1,2})\](?!\()")

_FILE_REFERENCE_PREFIX = "file://"


def _is_file_reference(url: str) -> bool:
    return str(url or "").startswith(_FILE_REFERENCE_PREFIX)


def _site_name(url: str) -> str:
    """Hostname without a leading www., used as the site/organization name."""
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _author_label(source: Dict[str, Any]) -> str:
    """Author for citation labels: page author, else site name, else domain.

    author / site_name come from page metadata extracted at fetch time
    (services/page_meta.py); user files fall back to their title.
    """
    url = str(source.get("url", ""))
    if _is_file_reference(url):
        title = str(source.get("title") or "").strip()
        return (title or url[len(_FILE_REFERENCE_PREFIX) :])[:60]
    author = " ".join(str(source.get("author") or "").split())
    if author:
        return author[:60]
    site = " ".join(str(source.get("site_name") or "").split())
    if site:
        return site[:60]
    return _site_name(url) or str(source.get("title") or "Source")[:60]


_YEAR_LABEL_PATTERN = re.compile(r"(19|20)\d{2}")


def _date_label(source: Dict[str, Any]) -> str:
    """Publication year from page metadata, or the APA no-date marker."""
    year = str(source.get("published_year") or "").strip()
    return year if _YEAR_LABEL_PATTERN.fullmatch(year) else "n.d."


def _display_site(source: Dict[str, Any]) -> str:
    site = " ".join(str(source.get("site_name") or "").split())
    return site[:60] if site else _site_name(str(source.get("url", "")))


def renumber_citations(
    drafts: list[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Rewrite per-section [n] markers into globally numbered source links.

    Each section is written against its own small source list, so a "[1]" in
    one section and a "[1]" in another usually point at different sources.
    This maps every marker onto one global source list (deduplicated by URL,
    numbered in first-use order) and turns it into a real markdown link:
    "[[3]](https://example.com)". Markers that cite a source index that was
    never provided to the section are dropped.

    Each draft dict needs "markdown" and "sources" (the ordered source list
    the section was written against). Returns (new_drafts, used_sources).
    """
    used_sources: list[Dict[str, Any]] = []
    index_by_url: dict[str, int] = {}
    renumbered: list[Dict[str, Any]] = []

    for draft in drafts:
        sources = [
            source
            for source in (draft.get("sources") or [])
            if isinstance(source, dict) and source.get("url")
        ]

        def replace(match: re.Match[str]) -> str:
            local_index = int(match.group(1))
            if not 1 <= local_index <= len(sources):
                return ""
            source = sources[local_index - 1]
            url = str(source["url"])
            if url not in index_by_url:
                used_sources.append(source)
                index_by_url[url] = len(used_sources)
            return f"[[{index_by_url[url]}]]({url})"

        markdown = _CITATION_PATTERN.sub(replace, str(draft.get("markdown", "")))
        renumbered.append({**draft, "markdown": markdown})

    return renumbered, used_sources


def _nd_suffix(index: int) -> str:
    """0 -> a, 1 -> b, ... 25 -> z, 26 -> aa (APA n.d.-a disambiguation)."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


def _assign_author_date_labels(
    sources: list[Dict[str, Any]],
) -> dict[str, tuple[str, str]]:
    """Map each source URL to its (author, date) citation label parts.

    The date is the page's publication year when metadata provided one,
    otherwise "n.d.". When the same author shares a date, APA disambiguates
    in reference-list (title) order: 2024a, 2024b for years, n.d.-a, n.d.-b
    for undated sources.
    """
    by_key: dict[tuple[str, str], list[Dict[str, Any]]] = {}
    for source in sources:
        key = (_author_label(source), _date_label(source))
        by_key.setdefault(key, []).append(source)

    labels: dict[str, tuple[str, str]] = {}
    for (author, date), group in by_key.items():
        if len(group) == 1:
            labels[str(group[0]["url"])] = (author, date)
            continue
        ordered = sorted(group, key=lambda item: str(item.get("title") or "").lower())
        for index, source in enumerate(ordered):
            suffix = _nd_suffix(index)
            dated = f"{date}-{suffix}" if date == "n.d." else f"{date}{suffix}"
            labels[str(source["url"])] = (author, dated)
    return labels


def author_date_citations(
    drafts: list[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Rewrite per-section [n] markers into (author, n.d.) citation links.

    Same contract as renumber_citations, but the inline form is an APA-style
    author-date link: "[(example.com, n.d.)](https://example.com)". Labels are
    assigned in two passes because n.d.-a/-b suffixes depend on every source
    cited anywhere in the document. used_sources entries carry the label parts
    as "citation_author" / "citation_date" for the sources section.
    """
    used_sources: list[Dict[str, Any]] = []
    index_by_url: dict[str, int] = {}
    draft_sources: list[list[Dict[str, Any]]] = []

    for draft in drafts:
        sources = [
            source
            for source in (draft.get("sources") or [])
            if isinstance(source, dict) and source.get("url")
        ]
        draft_sources.append(sources)
        for match in _CITATION_PATTERN.finditer(str(draft.get("markdown", ""))):
            local_index = int(match.group(1))
            if not 1 <= local_index <= len(sources):
                continue
            url = str(sources[local_index - 1]["url"])
            if url not in index_by_url:
                index_by_url[url] = len(used_sources)
                used_sources.append(sources[local_index - 1])

    labels = _assign_author_date_labels(used_sources)

    rewritten: list[Dict[str, Any]] = []
    for draft, sources in zip(drafts, draft_sources):

        def replace(match: re.Match[str]) -> str:
            local_index = int(match.group(1))
            if not 1 <= local_index <= len(sources):
                return ""
            url = str(sources[local_index - 1]["url"])
            author, date = labels[url]
            return f"[({author}, {date})]({url})"

        markdown = _CITATION_PATTERN.sub(replace, str(draft.get("markdown", "")))
        rewritten.append({**draft, "markdown": markdown})

    labeled_sources = [
        {
            **source,
            "citation_author": labels[str(source["url"])][0],
            "citation_date": labels[str(source["url"])][1],
        }
        for source in used_sources
    ]
    return rewritten, labeled_sources


def render_citations(
    drafts: list[Dict[str, Any]], style: str = "numeric"
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Apply the configured citation style to the section drafts."""
    if style == "author_date":
        return author_date_citations(drafts)
    return renumber_citations(drafts)


# Matches renumbered global citation links like "[[3]](https://example.com)".
_GLOBAL_CITATION_PATTERN = re.compile(r"\[\[(\d+)\]\]\(")

# Matches author-date citation links like "[(example.com, n.d.)](https://...)".
_AUTHOR_DATE_LINK_PATTERN = re.compile(r"\[\(([^()\n]{1,120})\)\]\(")


def global_citation_numbers(markdown: str) -> set[str]:
    """Citation numbers cited via global links in the text."""
    return set(_GLOBAL_CITATION_PATTERN.findall(str(markdown or "")))


def citation_markers(markdown: str) -> set[str]:
    """Inline citation identities in either style (numbers or author-date labels).

    Used by seam smoothing to verify a rewritten paragraph kept exactly the
    citations of the original, whichever citation style the document uses.
    """
    text = str(markdown or "")
    return set(_GLOBAL_CITATION_PATTERN.findall(text)) | set(
        _AUTHOR_DATE_LINK_PATTERN.findall(text)
    )


def _accessed_note(accessed_at: str | None) -> str:
    date = str(accessed_at or "").strip()[:10]
    return f" (accessed {date})" if date else ""


def _numeric_source_lines(
    sources: list[Dict[str, Any]], accessed_at: str | None
) -> list[str]:
    lines = []
    for index, source in enumerate(sources, start=1):
        title = source.get("title") or "Source"
        url = str(source["url"])
        if _is_file_reference(url):
            lines.append(f"{index}. {title} (user-provided reference)")
            continue
        year = _date_label(source)
        descriptor = ", ".join(
            part for part in (_display_site(source), year if year != "n.d." else "") if part
        )
        tail = f" {descriptor}{_accessed_note(accessed_at)}".rstrip()
        suffix = f".{tail}" if tail else ""
        lines.append(f"{index}. [{title}]({url}){suffix}")
    return lines


def _author_date_source_lines(
    sources: list[Dict[str, Any]], accessed_at: str | None
) -> list[str]:
    # Sources that came through author_date_citations carry their label parts;
    # compute labels for the rest (e.g. the uncited-research fallback list).
    computed = _assign_author_date_labels(
        [s for s in sources if not s.get("citation_author")]
    )

    def label(source: Dict[str, Any]) -> tuple[str, str]:
        author = source.get("citation_author")
        if author:
            return str(author), str(source.get("citation_date") or "n.d.")
        return computed[str(source["url"])]

    def sort_key(source: Dict[str, Any]) -> tuple:
        author, date = label(source)
        # APA orders an author's undated works before dated ones.
        return (
            author.lower(),
            0 if date.startswith("n.d.") else 1,
            date,
            str(source.get("title") or "").lower(),
        )

    lines = []
    for source in sorted(sources, key=sort_key):
        author, date = label(source)
        title = source.get("title") or "Source"
        url = str(source["url"])
        if _is_file_reference(url):
            lines.append(f"- {author}. ({date}). (user-provided reference)")
            continue
        entry = f"- {author}. ({date}). [{title}]({url})"
        # APA web citations name the site after the title unless the author
        # already is the site.
        site = _display_site(source)
        if site and site.lower() != author.lower():
            entry += f". {site}"
        lines.append(entry + _accessed_note(accessed_at))
    return lines


def format_sources_section(
    sources: list[Dict[str, Any]],
    style: str = "numeric",
    accessed_at: str | None = None,
) -> str:
    """Render the "## Sources" block matching the inline citation style.

    numeric: numbered in inline-citation order, so [n] markers and list
    entries always agree. author_date: alphabetized by author label, matching
    the (author, n.d.) inline links. accessed_at is the research fetch time
    (ISO timestamp); only its date part is shown.
    """
    usable = [
        source
        for source in sources
        if isinstance(source, dict) and source.get("url")
    ]
    if not usable:
        return ""
    if style == "author_date":
        lines = _author_date_source_lines(usable, accessed_at)
    else:
        lines = _numeric_source_lines(usable, accessed_at)
    return "\n\n## Sources\n\n" + "\n".join(lines) + "\n"
