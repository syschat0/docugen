import io
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import urllib.error

import pytest

from app.services import google_pse


def _configured_settings(**overrides) -> SimpleNamespace:
    values = {
        "google_pse_api_key": "key123",
        "google_pse_cx": "cx456",
        "search_timeout_seconds": 15,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, *args):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(
        google_pse,
        "settings",
        _configured_settings(google_pse_api_key="", google_pse_cx=""),
    )
    with pytest.raises(google_pse.GooglePSEError):
        google_pse.search_google_pse("q")


def test_successful_parse_returns_results(monkeypatch):
    monkeypatch.setattr(google_pse, "settings", _configured_settings())
    payload = json.dumps(
        {
            "items": [
                {"title": "First", "link": "https://example.com/1", "snippet": "snippet one"},
                {"title": "No link", "snippet": "missing link"},
            ]
        }
    ).encode("utf-8")
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        return FakeResponse(payload)

    monkeypatch.setattr(google_pse.urllib.request, "urlopen", fake_urlopen)
    results = google_pse.search_google_pse("docker guide")
    assert results == [
        {"title": "First", "url": "https://example.com/1", "snippet": "snippet one"}
    ]
    query = parse_qs(urlparse(seen["url"]).query)
    assert query["key"] == ["key123"]
    assert query["cx"] == ["cx456"]
    assert query["q"] == ["docker guide"]
    assert query["num"] == ["10"]


def test_http_429_raises_quota_error(monkeypatch):
    monkeypatch.setattr(google_pse, "settings", _configured_settings())

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(json.dumps({"error": {"message": "quota"}}).encode("utf-8")),
        )

    monkeypatch.setattr(google_pse.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(google_pse.GooglePSEQuotaError, match="quota"):
        google_pse.search_google_pse("q")
