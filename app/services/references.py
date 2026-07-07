"""User-provided reference material: URLs fetched at intake and uploaded files.

References are stored per project and merged into the research source pool so
the pipeline treats them as high-priority sources alongside web search results.
"""

from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlparse
import urllib.error
import urllib.request

from app.core.config import settings
from app.services.search import _TextExtractParser

MAX_REFERENCE_COUNT = 10
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_CONTENT_CHARS = 8000
MAX_URL_READ_BYTES = 500_000
ALLOWED_FILE_SUFFIXES = {".txt", ".md", ".markdown"}


def normalize_reference_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for url in urls:
        url = url.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append(url)
    return cleaned


def _base_entry(kind: str, source: str) -> dict[str, str]:
    return {
        "kind": kind,
        "source": source,
        "title": "",
        "content_text": "",
        "status": "ready",
        "error": "",
    }


def _fail(entry: dict[str, str], error: str) -> dict[str, str]:
    entry["status"] = "error"
    entry["error"] = error
    return entry


def fetch_url_reference(url: str) -> dict[str, str]:
    entry = _base_entry("url", url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _fail(entry, "Only http(s) URLs are supported")

    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 DocuGen/0.1"}
    )
    try:
        with urllib.request.urlopen(
            request, timeout=settings.search_timeout_seconds
        ) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(MAX_URL_READ_BYTES)
    except Exception as exc:
        return _fail(entry, str(exc))

    text = raw.decode("utf-8", errors="replace")
    if "html" in content_type:
        parser = _TextExtractParser()
        parser.feed(text)
        entry["title"] = parser.title
        entry["content_text"] = " ".join(parser.text_parts)[:MAX_CONTENT_CHARS]
    elif content_type.startswith("text/") or "json" in content_type:
        entry["content_text"] = text.strip()[:MAX_CONTENT_CHARS]
    else:
        return _fail(entry, f"Unsupported content type: {content_type or 'unknown'}")

    if not entry["content_text"]:
        return _fail(entry, "No readable text found at URL")
    return entry


def _file_suffix(filename: str) -> str:
    # Browsers may send a full client path; keep only the basename's suffix.
    name = PureWindowsPath(filename).name
    return PurePosixPath(name).suffix.lower()


def extract_file_reference(filename: str, data: bytes) -> dict[str, str]:
    entry = _base_entry("file", filename)
    entry["title"] = filename
    suffix = _file_suffix(filename)
    if suffix not in ALLOWED_FILE_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_FILE_SUFFIXES))
        return _fail(entry, f"Unsupported file type: {suffix or 'none'} (allowed: {allowed})")
    if len(data) > MAX_FILE_BYTES:
        return _fail(entry, f"File exceeds {MAX_FILE_BYTES // (1024 * 1024)}MB limit")

    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return _fail(entry, "File contains no readable text")
    entry["content_text"] = text[:MAX_CONTENT_CHARS]
    return entry
