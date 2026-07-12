from types import SimpleNamespace

import pytest

from app.db import session
from app.services import source_eval
from app.services.llm import LLMError, select_section_sources


def _section_settings(**overrides):
    base = dict(
        section_eval_enabled=True,
        llm_enabled=True,
        llm_model="test-model",
        section_eval_limit=20,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def section_eval_db(tmp_path, monkeypatch):
    """Temp DB plus deterministic section-eval settings for the orchestrator."""
    monkeypatch.setattr(
        session, "settings", SimpleNamespace(database_path=tmp_path / "seval.sqlite3")
    )
    monkeypatch.setattr(source_eval, "settings", _section_settings())
    session.init_db()
    return tmp_path


# --- (a) normalization --------------------------------------------------------


def test_normalize_ignores_out_of_range_and_duplicate_ids():
    candidates = [{"url": "https://a"}, {"url": "https://b"}]
    raw = [
        {"id": 1, "relevance": 3, "reason": "core"},
        {"id": 1, "relevance": 0, "reason": "dup"},  # duplicate id: first wins
        {"id": 5, "relevance": 2, "reason": "oob"},  # out of range: ignored
        {"id": 2, "relevance": 9, "reason": "x" * 200},  # clamp + clip
    ]
    result = source_eval._normalize_section_rankings(raw, candidates)
    assert set(result.keys()) == {"https://a", "https://b"}
    assert result["https://a"]["relevance"] == 3
    assert result["https://a"]["reason"] == "core"
    assert result["https://b"]["relevance"] == 3  # 9 clamped to 3
    assert len(result["https://b"]["reason"]) <= 100


def test_normalize_omits_candidates_missing_from_response():
    candidates = [{"url": "https://a"}, {"url": "https://b"}, {"url": "https://c"}]
    raw = [{"id": 1, "relevance": 2, "reason": ""}]
    result = source_eval._normalize_section_rankings(raw, candidates)
    assert result["https://a"]["relevance"] == 2
    assert "https://b" not in result
    assert "https://c" not in result


# --- (b) gate -----------------------------------------------------------------


def test_gate_excludes_low_relevance_and_allows_empty_slot():
    section = {"title": "docker network bridge overlay driver"}
    good = {"url": "https://good", "summary": "docker network bridge overlay guide"}
    weak = {"url": "https://weak", "summary": "docker network bridge overlay notes"}

    fit = {
        "https://good": {"relevance": 3, "reason": ""},
        "https://weak": {"relevance": 1, "reason": ""},
    }
    picked = select_section_sources(section, [], [good, weak], limit=2, section_fit=fit)
    urls = [source["url"] for source in picked]
    assert "https://good" in urls
    assert "https://weak" not in urls

    # Every candidate scored <= 1 leaves an empty selection rather than a filler.
    all_low = {
        "https://good": {"relevance": 1, "reason": ""},
        "https://weak": {"relevance": 0, "reason": ""},
    }
    assert (
        select_section_sources(section, [], [good, weak], limit=2, section_fit=all_low)
        == []
    )


# --- (c) ranking --------------------------------------------------------------


def test_relevance_outranks_lexical_overlap():
    section = {"title": "docker network bridge overlay driver"}
    # Zero keyword overlap, but the judge scored it top relevance.
    off_topic = {
        "url": "https://rel3",
        "title": "gardening compost tips",
        "snippet": "roses tulips soil",
    }
    # High keyword overlap, but only a relevance of 2.
    on_topic = {
        "url": "https://rel2",
        "title": "docker network bridge overlay driver guide",
        "snippet": "",
    }
    fit = {
        "https://rel3": {"relevance": 3, "reason": ""},
        "https://rel2": {"relevance": 2, "reason": ""},
    }
    picked = select_section_sources(
        section, [], [off_topic, on_topic], limit=1, section_fit=fit
    )
    assert [source["url"] for source in picked] == ["https://rel3"]


def test_section_fit_none_preserves_heuristic_order():
    section = {"title": "docker network bridge overlay driver"}
    off_topic = {
        "url": "https://a",
        "title": "gardening compost tips",
        "snippet": "roses",
    }
    on_topic = {
        "url": "https://b",
        "title": "docker network bridge overlay driver",
        "snippet": "",
    }
    picked = select_section_sources(
        section, [], [off_topic, on_topic], limit=2, section_fit=None
    )
    # Pure heuristic: the lexical-overlap source ranks first, unchanged from P2.
    assert [source["url"] for source in picked] == ["https://b", "https://a"]


# --- (d) fallback -------------------------------------------------------------


def test_llm_error_falls_back_to_none_and_matches_unevaluated(
    section_eval_db, monkeypatch
):
    def boom(section, candidates):
        raise LLMError("nope")

    monkeypatch.setattr(source_eval, "rank_section_relevance", boom)

    section = {"id": "1.1", "title": "docker bridge"}
    candidates = [{"url": "https://a", "summary": "docker bridge networking guide"}]

    fit_map, stats = source_eval.rank_sources_for_section(section, candidates)
    assert fit_map is None
    assert stats["called"] is False
    assert stats["error"]

    # Selection with the failed map matches the unevaluated heuristic path.
    picked_none = select_section_sources(section, [], candidates, section_fit=None)
    picked_fallback = select_section_sources(section, [], candidates, section_fit=fit_map)
    assert [s["url"] for s in picked_none] == [s["url"] for s in picked_fallback]


# --- (e) cache ----------------------------------------------------------------


def test_cache_hit_avoids_second_call(section_eval_db, monkeypatch):
    calls = {"n": 0}

    def fake_rank(section, candidates):
        calls["n"] += 1
        return (
            [
                {"id": index, "relevance": 2, "reason": ""}
                for index in range(1, len(candidates) + 1)
            ],
            None,
        )

    monkeypatch.setattr(source_eval, "rank_section_relevance", fake_rank)

    section = {"id": "2.1", "title": "docker overlay", "purpose": "", "key_points": []}

    def make():
        return [{"url": "https://a", "summary": "docker overlay driver"}]

    first, stats1 = source_eval.rank_sources_for_section(section, make())
    assert stats1["called"] is True

    # Fresh dicts, same section + candidate text: served from cache, no new call.
    second, stats2 = source_eval.rank_sources_for_section(section, make())
    assert calls["n"] == 1
    assert stats2["cache_hit"] is True
    assert second == first

    with session.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM source_eval_cache"
        ).fetchone()["c"]
    assert count == 1


# --- (f) non-mutation ---------------------------------------------------------


def test_ranking_does_not_mutate_candidate_dicts(section_eval_db, monkeypatch):
    def fake_rank(section, candidates):
        return ([{"id": 1, "relevance": 3, "reason": "r"}], None)

    monkeypatch.setattr(source_eval, "rank_section_relevance", fake_rank)

    section = {"id": "3.1", "title": "docker"}
    candidate = {"url": "https://a", "summary": "docker overlay"}
    keys_before = set(candidate.keys())

    fit_map, _stats = source_eval.rank_sources_for_section(section, [candidate])
    assert fit_map == {"https://a": {"relevance": 3, "reason": "r"}}
    assert set(candidate.keys()) == keys_before


# --- (g) budget ---------------------------------------------------------------


def test_budget_exhausted_skips_call(section_eval_db, monkeypatch):
    calls = {"n": 0}

    def fake_rank(section, candidates):
        calls["n"] += 1
        return ([{"id": 1, "relevance": 2, "reason": ""}], None)

    monkeypatch.setattr(source_eval, "rank_section_relevance", fake_rank)

    section = {"id": "4.1", "title": "docker"}
    candidates = [{"url": "https://a", "summary": "docker overlay"}]

    fit_map, stats = source_eval.rank_sources_for_section(
        section, candidates, allow_llm_call=False
    )
    assert fit_map is None
    assert stats["called"] is False
    assert calls["n"] == 0


@pytest.mark.parametrize(
    "overrides",
    [{"section_eval_enabled": False}, {"llm_enabled": False}],
)
def test_disabled_returns_none(monkeypatch, overrides):
    monkeypatch.setattr(source_eval, "settings", _section_settings(**overrides))
    called = {"n": 0}

    def fake_rank(section, candidates):
        called["n"] += 1
        return ([], None)

    monkeypatch.setattr(source_eval, "rank_section_relevance", fake_rank)

    fit_map, stats = source_eval.rank_sources_for_section(
        {"id": "1"}, [{"url": "https://a", "summary": "x"}]
    )
    assert fit_map is None
    assert stats["called"] is False
    assert called["n"] == 0


# --- (h) top-up skip trigger --------------------------------------------------


def test_eval_marks_relevant_trigger():
    from app.db.repositories import _eval_marks_relevant

    sources = [{"url": "https://a"}, {"url": "https://b"}]
    assert _eval_marks_relevant(sources, {"https://a": {"relevance": 2}}) is True
    assert _eval_marks_relevant(sources, {"https://b": {"relevance": 3}}) is True
    assert _eval_marks_relevant(sources, {"https://a": {"relevance": 1}}) is False
    assert _eval_marks_relevant(sources, None) is False
    assert _eval_marks_relevant(sources, {}) is False
