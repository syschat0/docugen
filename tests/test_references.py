import urllib.request

from app.db.repositories import _merge_reference_sources
from app.schemas.projects import ProjectReferenceRead
from app.services.references import (
    MAX_CONTENT_CHARS,
    MAX_FILE_BYTES,
    extract_file_reference,
    fetch_url_reference,
    normalize_reference_urls,
)


def make_reference(**overrides) -> ProjectReferenceRead:
    values = {
        "id": "r1",
        "project_id": "p1",
        "kind": "url",
        "source": "https://example.com/doc",
        "title": "Example Doc",
        "content_text": "Reference body text about the topic.",
        "status": "ready",
        "error": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    values.update(overrides)
    return ProjectReferenceRead(**values)


class FakeResponse:
    def __init__(self, body: bytes, content_type: str):
        self._body = body
        self.headers = {"content-type": content_type}

    def read(self, limit: int) -> bytes:
        return self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_normalize_reference_urls_trims_and_dedupes():
    urls = ["  https://a.com ", "", "https://a.com", "https://b.com", "   "]
    assert normalize_reference_urls(urls) == ["https://a.com", "https://b.com"]


def test_fetch_url_reference_rejects_non_http_schemes():
    entry = fetch_url_reference("ftp://example.com/file")
    assert entry["status"] == "error"
    assert "http(s)" in entry["error"]

    entry = fetch_url_reference("not a url")
    assert entry["status"] == "error"


def test_fetch_url_reference_extracts_html_text(monkeypatch):
    long_sentence = "This paragraph carries enough characters to pass the extractor threshold."
    html = f"<html><head><title>Doc Title</title></head><body><p>{long_sentence}</p></body></html>"

    def fake_urlopen(request, timeout):
        return FakeResponse(html.encode("utf-8"), "text/html; charset=utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    entry = fetch_url_reference("https://example.com/doc")
    assert entry["status"] == "ready"
    assert entry["title"] == "Doc Title"
    assert long_sentence in entry["content_text"]


def test_fetch_url_reference_accepts_plain_text(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(b"plain text body", "text/plain")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    entry = fetch_url_reference("https://example.com/readme.txt")
    assert entry["status"] == "ready"
    assert entry["content_text"] == "plain text body"


def test_fetch_url_reference_rejects_binary_content(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(b"\x00\x01", "application/pdf")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    entry = fetch_url_reference("https://example.com/doc.pdf")
    assert entry["status"] == "error"
    assert "content type" in entry["error"].lower()


def test_extract_file_reference_reads_markdown():
    entry = extract_file_reference("notes.md", "# Heading\n\nBody text".encode("utf-8"))
    assert entry["status"] == "ready"
    assert entry["content_text"].startswith("# Heading")


def test_extract_file_reference_rejects_unsupported_extension():
    entry = extract_file_reference("binary.exe", b"MZ")
    assert entry["status"] == "error"
    assert "Unsupported file type" in entry["error"]


def test_extract_file_reference_rejects_oversized_file():
    entry = extract_file_reference("big.txt", b"a" * (MAX_FILE_BYTES + 1))
    assert entry["status"] == "error"
    assert "limit" in entry["error"]


def test_extract_file_reference_rejects_empty_file():
    entry = extract_file_reference("empty.txt", b"   \n  ")
    assert entry["status"] == "error"


def test_extract_file_reference_truncates_long_content():
    entry = extract_file_reference("long.txt", b"a" * (MAX_CONTENT_CHARS + 500))
    assert entry["status"] == "ready"
    assert len(entry["content_text"]) == MAX_CONTENT_CHARS


def test_extract_file_reference_uses_basename_suffix_from_client_path():
    entry = extract_file_reference("C:\\Users\\me\\notes.md", b"body text")
    assert entry["status"] == "ready"


def test_merge_reference_sources_prepends_ready_references():
    references = [
        make_reference(),
        make_reference(id="r2", status="error", error="fetch failed"),
        make_reference(id="r3", kind="file", source="notes.md", title="notes.md",
                       content_text="File body"),
    ]
    research = {
        "results": [
            {"title": "Web Hit", "url": "https://web.example/hit", "snippet": "snippet"}
        ]
    }
    source_summaries = {
        "sources": [
            {"title": "Web Hit", "url": "https://web.example/hit", "summary": "s", "error": ""}
        ]
    }

    _merge_reference_sources(references, research, source_summaries)

    urls = [item["url"] for item in research["results"]]
    assert urls == [
        "https://example.com/doc",
        "file://notes.md",
        "https://web.example/hit",
    ]
    summary_urls = [item["url"] for item in source_summaries["sources"]]
    assert summary_urls == urls
    assert research["results"][0]["query"] == "user-provided reference"


def test_merge_reference_sources_skips_duplicate_urls():
    references = [make_reference()]
    research = {
        "results": [
            {"title": "Same", "url": "https://example.com/doc", "snippet": "snippet"}
        ]
    }
    source_summaries = {"sources": []}

    _merge_reference_sources(references, research, source_summaries)

    assert len(research["results"]) == 1
    assert [item["url"] for item in source_summaries["sources"]] == [
        "https://example.com/doc"
    ]


def test_merge_reference_sources_handles_missing_result_lists():
    references = [make_reference()]
    research = {}
    source_summaries = {}

    _merge_reference_sources(references, research, source_summaries)

    assert len(research["results"]) == 1
    assert len(source_summaries["sources"]) == 1
