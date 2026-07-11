import json

import pytest

from app.services.quality_benchmark import _resolve_fixture_variant, load_benchmark_cases
from app.services.slm_evaluation import (
    HUMAN_RUBRIC,
    build_blind_human_packet,
    build_slm_comparison,
    load_run_variant,
    summarize_human_results,
)


def _write_runs(tmp_path, cases):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    for case in cases:
        baseline = _resolve_fixture_variant(case, case.get("baseline") or {})
        candidate = _resolve_fixture_variant(case, case.get("candidate") or {})
        (before / f"{case['id']}.json").write_text(
            json.dumps(baseline), encoding="utf-8"
        )
        (after / f"{case['id']}.json").write_text(
            json.dumps(candidate), encoding="utf-8"
        )
    return before, after


def test_before_after_report_and_blind_packet(tmp_path):
    cases = load_benchmark_cases()[:2]
    before, after = _write_runs(tmp_path, cases)

    report = build_slm_comparison(cases, before, after)
    packet, key = build_blind_human_packet(cases, before, after, seed="test")

    assert report["improved_or_equal_count"] == len(cases)
    assert all(item["delta"]["total_flags"] < 0 for item in report["results"])
    assert len(packet["cases"]) == len(cases)
    assert set(packet["rubric"]) == set(HUMAN_RUBRIC)
    assert set(key["cases"][cases[0]["id"]].values()) == {"before", "after"}
    assert "before" not in json.dumps(packet)


def test_completed_human_scores_are_unblinded_and_aggregated(tmp_path):
    cases = load_benchmark_cases()[:1]
    before, after = _write_runs(tmp_path, cases)
    packet, key = build_blind_human_packet(cases, before, after, seed="test")
    evaluation = packet["cases"][0]["evaluation"]
    for scores in evaluation["scores"].values():
        scores["A"] = 5
        scores["B"] = 3
    evaluation["preference"] = "A"

    summary = summarize_human_results(packet, key)

    preferred_run = key["cases"][cases[0]["id"]]["A"]
    other_run = "before" if preferred_run == "after" else "after"
    assert summary["completed_count"] == 1
    assert summary["mean_scores"][preferred_run] == 5
    assert summary["mean_scores"][other_run] == 3
    assert summary["preferences"][preferred_run] == 1


def test_missing_candidate_file_is_reported(tmp_path):
    with pytest.raises(ValueError, match="Missing SLM output"):
        load_run_variant(tmp_path, "missing")
