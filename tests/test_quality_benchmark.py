import json

from app.services.quality_benchmark import (
    DEFAULT_CASES_PATH,
    evaluate_case,
    load_benchmark_cases,
    run_benchmark,
)


def test_default_benchmark_covers_all_document_types_and_passes():
    cases = load_benchmark_cases()
    assert {case["document_type"] for case in cases} == {
        "report",
        "academic_paper",
        "blog_post",
        "essay",
        "tech_doc",
        "presentation_script",
    }
    report = run_benchmark(cases)
    assert report["passed"] is True
    assert report["passed_count"] == 6
    assert all(
        result["candidate"]["total_flags"] < result["baseline"]["total_flags"]
        for result in report["results"]
    )


def test_external_candidate_file_overrides_fixture_and_can_fail(tmp_path):
    case = next(
        item
        for item in load_benchmark_cases(DEFAULT_CASES_PATH)
        if item["id"] == "presentation_spoken_pacing"
    )
    candidate = {
        "sections": [
            {
                "id": "1.1",
                "title": "What changes on Monday",
                "body": "Responsible adoption begins when leaders define a narrow decision, name every affected group, calculate every possible failure, document all escalation paths, compare each alternative, and complete every review before allowing any team to use the system in production.",
            }
        ]
    }
    (tmp_path / "presentation_spoken_pacing.json").write_text(
        json.dumps(candidate), encoding="utf-8"
    )
    result = evaluate_case(case, candidate_dir=tmp_path)
    assert result["passed"] is False
    assert "long_sentences" in result["candidate_warnings"]


def test_invalid_case_file_is_rejected(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"cases": []}), encoding="utf-8")
    try:
        load_benchmark_cases(path)
    except ValueError as exc:
        assert "non-empty cases" in str(exc)
    else:
        raise AssertionError("empty benchmark should be rejected")
