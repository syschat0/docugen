"""Offline regression benchmark for deterministic document quality signals."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from app.services.quality import build_quality_summary, validate_evidence_ledger


DEFAULT_CASES_PATH = Path(__file__).resolve().parents[2] / "benchmarks" / "quality_cases.json"


def load_benchmark_cases(path: Path = DEFAULT_CASES_PATH) -> list[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark file must contain a non-empty cases array")
    return [case for case in cases if isinstance(case, dict)]


def _materialize_sections(variant: Dict[str, Any]) -> list[Dict[str, Any]]:
    if isinstance(variant.get("section_drafts"), list):
        return deepcopy(variant["section_drafts"])

    drafts: list[Dict[str, Any]] = []
    shared_sources = [
        source for source in (variant.get("sources") or []) if isinstance(source, dict)
    ]
    for index, raw in enumerate(variant.get("sections") or [], start=1):
        if not isinstance(raw, dict):
            continue
        section_id = str(raw.get("id") or index)
        title = str(raw.get("title") or f"Section {section_id}")
        heading = str(raw.get("heading") or f"### {section_id} {title}")
        body = str(raw.get("body") or "").strip()
        markdown = f"{heading}\n\n{body}".strip()
        sources = [
            source for source in (raw.get("sources") or shared_sources) if isinstance(source, dict)
        ]
        evidence = [
            item for item in (raw.get("evidence") or []) if isinstance(item, dict)
        ]
        section = {
            "id": section_id,
            "title": title,
            "path": raw.get("path") or [title],
        }
        draft = {
            "section": section,
            "markdown": markdown,
            "sources": sources,
            "evidence": evidence,
        }
        if evidence or "[1]" in markdown:
            draft["evidence_validation"] = validate_evidence_ledger(
                markdown=markdown,
                evidence=evidence,
                sources=sources,
                section=section,
            )
        drafts.append(draft)
    return drafts


def evaluate_variant(case: Dict[str, Any], variant: Dict[str, Any]) -> Dict[str, Any]:
    drafts = _materialize_sections(variant)
    sources = [
        source for source in (variant.get("sources") or []) if isinstance(source, dict)
    ]
    if not sources:
        for draft in drafts:
            sources.extend(draft.get("sources") or [])
    return build_quality_summary(
        project_text=str(case.get("project_text") or case.get("id") or "benchmark"),
        sources=sources,
        section_drafts=drafts,
        continuity={"verdict": "pass", "issues": [], "revision_targets": []},
        rubric={"verdict": "pass", "issues": [], "revision_targets": [], "criteria": []},
        citations_enabled=bool(case.get("citations_enabled", False)),
        document_type=str(case.get("document_type") or "report"),
    )


def metric_snapshot(summary: Dict[str, Any]) -> Dict[str, int]:
    writing = summary.get("writing_quality") or {}
    structure = summary.get("structure_quality") or {}
    source = summary.get("source_quality") or {}
    evidence = summary.get("evidence") or {}
    review = summary.get("review") or {}
    metrics = {
        "warning_count": len(summary.get("warnings") or []),
        "writing_issues": int(writing.get("issue_count") or 0),
        "structure_issues": int(structure.get("issue_count") or 0),
        "low_quality_sources": int(source.get("low_quality_count") or 0),
        "strong_sources": int(source.get("strong_source_count") or 0),
        "unverified_evidence": int(evidence.get("invalid_entry_count") or 0)
        + max(
            int(evidence.get("total_citations") or 0)
            - int(evidence.get("verified_citations") or 0),
            0,
        ),
        "review_issues": int(review.get("issue_count") or 0),
    }
    metrics["total_flags"] = (
        metrics["warning_count"]
        + metrics["writing_issues"]
        + metrics["structure_issues"]
        + metrics["unverified_evidence"]
        + metrics["review_issues"]
    )
    return metrics


def _load_external_candidate(candidate_dir: Path | None, case_id: str) -> Dict[str, Any] | None:
    if candidate_dir is None:
        return None
    path = candidate_dir / f"{case_id}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Candidate file must contain an object: {path}")
    return payload


def _resolve_fixture_variant(
    case: Dict[str, Any], variant: Dict[str, Any]
) -> Dict[str, Any]:
    resolved = deepcopy(case.get("shared_variant") or {})
    for key, value in variant.items():
        if key != "title_overrides":
            resolved[key] = deepcopy(value)
    overrides = variant.get("title_overrides") or {}
    for section in resolved.get("sections") or []:
        section_id = str(section.get("id") or "")
        if section_id in overrides:
            section["title"] = str(overrides[section_id])
            section.pop("heading", None)
    return resolved


def evaluate_case(
    case: Dict[str, Any], candidate_dir: Path | None = None
) -> Dict[str, Any]:
    case_id = str(case.get("id") or "unnamed")
    baseline_summary = evaluate_variant(
        case, _resolve_fixture_variant(case, case.get("baseline") or {})
    )
    external_candidate = _load_external_candidate(candidate_dir, case_id)
    candidate_variant = external_candidate or _resolve_fixture_variant(
        case, case.get("candidate") or {}
    )
    candidate_summary = evaluate_variant(case, candidate_variant)
    baseline = metric_snapshot(baseline_summary)
    candidate = metric_snapshot(candidate_summary)
    expectations = case.get("expectations") or {}
    checks: list[Dict[str, Any]] = []

    for metric in expectations.get("decrease") or ["total_flags"]:
        checks.append(
            {
                "name": f"decrease:{metric}",
                "passed": candidate.get(metric, 0) < baseline.get(metric, 0),
                "baseline": baseline.get(metric),
                "candidate": candidate.get(metric),
            }
        )
    for metric in expectations.get("increase") or []:
        checks.append(
            {
                "name": f"increase:{metric}",
                "passed": candidate.get(metric, 0) > baseline.get(metric, 0),
                "baseline": baseline.get(metric),
                "candidate": candidate.get(metric),
            }
        )
    max_flags = expectations.get("candidate_max_total_flags")
    if isinstance(max_flags, int):
        checks.append(
            {
                "name": "candidate_max_total_flags",
                "passed": candidate["total_flags"] <= max_flags,
                "expected": max_flags,
                "candidate": candidate["total_flags"],
            }
        )
    forbidden = set(expectations.get("candidate_forbidden_warnings") or [])
    if forbidden:
        present = sorted(forbidden & set(candidate_summary.get("warnings") or []))
        checks.append(
            {
                "name": "candidate_forbidden_warnings",
                "passed": not present,
                "present": present,
            }
        )

    return {
        "id": case_id,
        "document_type": case.get("document_type"),
        "description": case.get("description"),
        "passed": all(check["passed"] for check in checks),
        "baseline": baseline,
        "candidate": candidate,
        "delta": {
            key: candidate.get(key, 0) - baseline.get(key, 0)
            for key in sorted(set(baseline) | set(candidate))
        },
        "baseline_warnings": baseline_summary.get("warnings") or [],
        "candidate_warnings": candidate_summary.get("warnings") or [],
        "checks": checks,
    }


def run_benchmark(
    cases: list[Dict[str, Any]], candidate_dir: Path | None = None
) -> Dict[str, Any]:
    results = [evaluate_case(case, candidate_dir=candidate_dir) for case in cases]
    return {
        "passed": all(result["passed"] for result in results),
        "case_count": len(results),
        "passed_count": sum(1 for result in results if result["passed"]),
        "results": results,
    }
