from types import SimpleNamespace

import pytest

from app.db import session
from app.services import source_eval
from app.services.evidence import assemble_source_context
from app.services.llm import select_section_sources


def _eval_settings(**overrides):
    base = dict(
        source_eval_enabled=True,
        llm_enabled=True,
        llm_model="test-model",
        source_eval_limit=8,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def eval_db(tmp_path, monkeypatch):
    """Temp DB plus deterministic eval settings for the orchestrator."""
    monkeypatch.setattr(
        session, "settings", SimpleNamespace(database_path=tmp_path / "eval.sqlite3")
    )
    monkeypatch.setattr(source_eval, "settings", _eval_settings())
    session.init_db()
    return tmp_path


# --- (a) normalization --------------------------------------------------------


def test_normalize_clamps_info_density_into_range():
    high = source_eval._normalize_eval({"info_density": 9}, "general")
    low = source_eval._normalize_eval({"info_density": -4}, "general")
    assert high["info_density"] == 3
    assert low["info_density"] == 0


def test_normalize_unknown_page_type_becomes_content():
    result = source_eval._normalize_eval({"page_type": "spaceship"}, "general")
    assert result["page_type"] == "content"


def test_normalize_error_page_forces_unusable():
    result = source_eval._normalize_eval(
        {"usable": True, "page_type": "error"}, "general"
    )
    assert result["usable"] is False


def test_normalize_low_tier_caps_density_at_two():
    result = source_eval._normalize_eval(
        {"usable": True, "page_type": "content", "info_density": 3}, "low"
    )
    assert result["info_density"] == 2


def test_normalize_clips_summary_and_limits_key_facts():
    result = source_eval._normalize_eval(
        {
            "summary": "word " * 100,
            "key_facts": ["a" * 200, "b", "c", "d", "e", "f", "g"],
        },
        "general",
    )
    assert len(result["summary"]) <= 200
    assert len(result["key_facts"]) == 5
    assert all(len(fact) <= 120 for fact in result["key_facts"])


# --- (b) caching --------------------------------------------------------------


def test_cache_hit_avoids_second_call_and_body_change_recalls(eval_db, monkeypatch):
    calls = {"n": 0}

    def fake_eval(source, topic_text):
        calls["n"] += 1
        return (
            {
                "usable": True,
                "page_type": "content",
                "info_density": 2,
                "summary": "ok",
                "key_facts": ["fact"],
            },
            None,
        )

    monkeypatch.setattr(source_eval, "evaluate_source_quality", fake_eval)

    body = "x" * 300

    def make():
        return [{"title": "T", "url": "https://ex.gov/a", "full_text": body}]

    first = make()
    source_eval.evaluate_sources(first, "topic")
    assert first[0]["eval"]["cached"] is False

    # Fresh dicts, same URL + body: served from cache, no new call.
    second = make()
    source_eval.evaluate_sources(second, "topic")
    assert calls["n"] == 1
    assert second[0]["eval"]["cached"] is True

    # Body change invalidates the cache key and forces a re-call.
    changed = [{"title": "T", "url": "https://ex.gov/a", "full_text": "y" * 300}]
    source_eval.evaluate_sources(changed, "topic")
    assert calls["n"] == 2

    with session.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM source_eval_cache"
        ).fetchone()["c"]
    assert count == 2


# --- (c) budget ---------------------------------------------------------------


def test_budget_limits_calls_and_prefers_trusted(eval_db, monkeypatch):
    seen = []

    def fake_eval(source, topic_text):
        seen.append(source["url"])
        return (
            {"usable": True, "page_type": "content", "info_density": 2},
            None,
        )

    monkeypatch.setattr(source_eval, "evaluate_source_quality", fake_eval)

    body = "x" * 300
    sources = [
        {"title": "low", "url": "https://blog.naver.com/a", "full_text": body},
        {"title": "gov", "url": "https://ex.go.kr/b", "full_text": body},
        {"title": "gen", "url": "https://ex.com/c", "full_text": body},
        {"title": "edu", "url": "https://ex.ac.kr/d", "full_text": body},
    ]
    stats = source_eval.evaluate_sources(sources, "topic", limit=2)

    assert stats["llm_calls"] == 2
    assert stats["evaluated"] == 2
    # Highest trust first: authoritative (.go.kr) then institutional (.ac.).
    assert seen == ["https://ex.go.kr/b", "https://ex.ac.kr/d"]


# --- (d) gate -----------------------------------------------------------------


def test_gate_excludes_unusable_source_and_allows_empty_slot():
    section = {"title": "docker network bridge"}
    good = {
        "url": "https://good.com",
        "summary": "docker network bridge configuration guide",
        "eval": {"usable": True, "info_density": 2},
    }
    bad = {
        "url": "https://bad.com",
        "summary": "docker network bridge configuration guide",
        "eval": {"usable": False, "info_density": 0},
    }
    picked = select_section_sources(section, [], [good, bad], limit=2)
    urls = [source["url"] for source in picked]
    assert "https://bad.com" not in urls
    assert "https://good.com" in urls

    # A pool of only-gated sources leaves an empty slot rather than including one.
    assert select_section_sources(section, [], [bad], limit=2) == []


# --- (e) ranking --------------------------------------------------------------


def test_ranking_density_over_unevaluated_over_low():
    section = {"title": "docker network bridge overlay"}
    high = {
        "url": "https://high.com",
        "summary": "docker network bridge overlay alpha beta gamma delta",
        "eval": {"usable": True, "info_density": 3},
    }
    unevaluated = {
        "url": "https://mid.com",
        "summary": "docker network bridge overlay epsilon zeta eta theta",
    }
    low = {
        "url": "https://low.com",
        "summary": "docker network bridge overlay iota kappa lambda mu",
        "eval": {"usable": True, "info_density": 0},
    }
    picked = select_section_sources(
        section, [], [high, unevaluated, low], limit=3
    )
    assert [source["url"] for source in picked] == [
        "https://high.com",
        "https://mid.com",
        "https://low.com",
    ]


# --- (f) assemble_source_context ----------------------------------------------


def test_assemble_renders_summary_line_but_not_key_facts():
    body = (
        "Docker network bridge mode connects containers on one host cleanly. " * 6
    )
    source = {
        "title": "Src",
        "url": "https://a.com",
        "full_text": body,
        "eval": {
            "usable": True,
            "info_density": 2,
            "summary": "This page explains docker bridge networking.",
            "key_facts": ["Bridge is the default driver", "SECRETFACT12345"],
        },
    }
    section = {"title": "docker network bridge"}

    out = assemble_source_context([source], section, budget_chars=3000)
    assert "(summary) This page explains docker bridge networking." in out
    assert "[1.P1]" in out  # citable passages still render as before
    # key_facts must never appear in the writer's context in any form.
    assert "SECRETFACT12345" not in out
    assert "Bridge is the default driver" not in out


def test_assemble_summary_line_counts_against_budget():
    body = (
        "Docker network bridge mode connects containers on one host cleanly. " * 20
    )
    with_eval = {
        "title": "Src",
        "url": "https://a.com",
        "full_text": body,
        "eval": {
            "usable": True,
            "info_density": 2,
            "summary": "s" * 160,
            "key_facts": [],
        },
    }
    without_eval = {"title": "Src", "url": "https://a.com", "full_text": body}
    section = {"title": "docker network bridge"}

    budget = 500
    with_lines = assemble_source_context([with_eval], section, budget)
    without_lines = assemble_source_context([without_eval], section, budget)

    assert "(summary)" in with_lines
    # The summary line consumes budget, so it never fits more passages than the
    # same source without one.
    assert with_lines.count("[1.P") <= without_lines.count("[1.P")


# --- (g) disabled no-op -------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [{"source_eval_enabled": False}, {"llm_enabled": False}],
)
def test_disabled_is_noop(monkeypatch, overrides):
    monkeypatch.setattr(source_eval, "settings", _eval_settings(**overrides))
    called = {"n": 0}

    def fake_eval(source, topic_text):
        called["n"] += 1
        return ({}, None)

    monkeypatch.setattr(source_eval, "evaluate_source_quality", fake_eval)

    sources = [{"url": "https://a.com", "full_text": "x" * 300}]
    stats = source_eval.evaluate_sources(sources, "topic")

    assert stats["enabled"] is False
    assert "eval" not in sources[0]
    assert called["n"] == 0
