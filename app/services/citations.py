import re
from typing import Any, Dict

# Matches bare inline citation markers like [1] or [12] (including adjacent
# ones like [1][2]), but not markdown links "[1](url)" or link text "[[1]]".
_CITATION_PATTERN = re.compile(r"(?<!\[)\[(\d{1,2})\](?!\()")


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


# Matches renumbered global citation links like "[[3]](https://example.com)".
_GLOBAL_CITATION_PATTERN = re.compile(r"\[\[(\d+)\]\]\(")


def global_citation_numbers(markdown: str) -> set[str]:
    """Citation numbers cited via global links in the text."""
    return set(_GLOBAL_CITATION_PATTERN.findall(str(markdown or "")))


def format_sources_section(sources: list[Dict[str, Any]]) -> str:
    """Render the numbered "## Sources" block matching inline citation numbers."""
    lines = [
        f"{index}. [{source.get('title') or 'Source'}]({source.get('url', '')})"
        for index, source in enumerate(sources, start=1)
        if isinstance(source, dict) and source.get("url")
    ]
    if not lines:
        return ""
    return "\n\n## Sources\n\n" + "\n".join(lines) + "\n"
