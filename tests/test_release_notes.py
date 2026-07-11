import json
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_release_data_has_current_bilingual_release_and_features():
    payload = json.loads((STATIC / "releases.json").read_text(encoding="utf-8"))
    releases = payload["releases"]
    current = next(
        item for item in releases if item["version"] == payload["current_version"]
    )
    assert current["date"]
    assert current["name"]["en"] and current["name"]["ko"]
    assert {section["key"] for section in current["sections"]} == {
        "added",
        "improved",
        "fixed",
        "known",
    }
    assert len(payload["features"]) >= 6
    for feature in payload["features"]:
        assert feature["title"]["en"] and feature["title"]["ko"]
        assert feature["summary"]["en"] and feature["summary"]["ko"]
        assert feature["bullets"]["en"] and feature["bullets"]["ko"]


def test_workspace_links_to_release_page_and_page_loads_versioned_assets():
    workspace = (STATIC / "index.html").read_text(encoding="utf-8")
    page = (STATIC / "release-notes.html").read_text(encoding="utf-8")
    assert 'href="/ui/release-notes.html"' in workspace
    assert 'href="/ui/"' in page
    assert "/ui/releases.json" not in page  # data is fetched by the page script
    assert "/ui/release-notes.css?v=" in page
    assert "/ui/release-notes.js?v=" in page
