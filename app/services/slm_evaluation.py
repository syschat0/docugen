"""Before/after SLM comparison and blind human-evaluation records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.services.quality_benchmark import evaluate_variant, metric_snapshot


HUMAN_RUBRIC = {
    "task_fulfillment": "Fulfills the request and covers the necessary content.",
    "structure": "Organizes ideas clearly with useful progression and headings.",
    "coherence": "Maintains logic, terminology, voice, and cross-section continuity.",
    "genre_fit": "Matches the selected document type and its reader expectations.",
    "readability": "Uses clear, natural sentences at an appropriate level of detail.",
    "factual_support": "Qualifies claims and uses evidence appropriately when required.",
}


def load_run_variant(directory: Path, case_id: str) -> Dict[str, Any]:
    path = directory / f"{case_id}.json"
    if not path.exists():
        raise ValueError(f"Missing SLM output for case '{case_id}': {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"SLM output must contain one JSON object: {path}")
    if not isinstance(payload.get("sections"), list) and not isinstance(
        payload.get("section_drafts"), list
    ):
        raise ValueError(
            f"SLM output needs sections or section_drafts: {path}"
        )
    return payload


def _variant_markdown(variant: Dict[str, Any]) -> str:
    drafts = variant.get("section_drafts")
    if isinstance(drafts, list):
        blocks = [
            str(item.get("markdown") or "").strip()
            for item in drafts
            if isinstance(item, dict) and str(item.get("markdown") or "").strip()
        ]
    else:
        blocks = []
        for index, item in enumerate(variant.get("sections") or [], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or f"Section {index}")
            heading = str(item.get("heading") or f"### {item.get('id') or index} {title}")
            body = str(item.get("body") or "").strip()
            blocks.append(f"{heading}\n\n{body}".strip())
    return "\n\n".join(blocks)


def build_slm_comparison(
    cases: list[Dict[str, Any]], before_dir: Path, after_dir: Path
) -> Dict[str, Any]:
    results = []
    for case in cases:
        case_id = str(case.get("id") or "unnamed")
        before_variant = load_run_variant(before_dir, case_id)
        after_variant = load_run_variant(after_dir, case_id)
        before = metric_snapshot(evaluate_variant(case, before_variant))
        after = metric_snapshot(evaluate_variant(case, after_variant))
        results.append(
            {
                "id": case_id,
                "document_type": case.get("document_type"),
                "before": before,
                "after": after,
                "delta": {
                    key: after.get(key, 0) - before.get(key, 0)
                    for key in sorted(set(before) | set(after))
                },
                "improved_or_equal": after["total_flags"] <= before["total_flags"],
            }
        )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results),
        "improved_or_equal_count": sum(
            1 for item in results if item["improved_or_equal"]
        ),
        "results": results,
    }


def build_blind_human_packet(
    cases: list[Dict[str, Any]],
    before_dir: Path,
    after_dir: Path,
    *,
    seed: str = "docugen-slm-eval",
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    packet_cases = []
    key_cases: Dict[str, Any] = {}
    for case in cases:
        case_id = str(case.get("id") or "unnamed")
        before = load_run_variant(before_dir, case_id)
        after = load_run_variant(after_dir, case_id)
        swap = hashlib.sha256(f"{seed}:{case_id}".encode()).digest()[0] % 2 == 1
        variants = {"A": after if swap else before, "B": before if swap else after}
        key_cases[case_id] = {
            "A": "after" if swap else "before",
            "B": "before" if swap else "after",
        }
        request = (
            (after.get("metadata") or {}).get("request")
            or (before.get("metadata") or {}).get("request")
            or case.get("project_text")
            or case.get("description")
            or case_id
        )
        packet_cases.append(
            {
                "id": case_id,
                "document_type": case.get("document_type"),
                "request": request,
                "evaluation": {
                    "scores": {
                        dimension: {"A": None, "B": None}
                        for dimension in HUMAN_RUBRIC
                    },
                    "preference": None,
                    "rationale": "",
                    "critical_issues": {"A": [], "B": []},
                },
                "variants": {
                    label: {"markdown": _variant_markdown(variant)}
                    for label, variant in variants.items()
                },
            }
        )
    packet = {
        "schema_version": 1,
        "instructions": (
            "Score each dimension from 1 (poor) to 5 (excellent), then set "
            "preference to A, B, or tie. Judge only the supplied request and text."
        ),
        "rubric": HUMAN_RUBRIC,
        "cases": packet_cases,
    }
    key = {"schema_version": 1, "seed": seed, "cases": key_cases}
    return packet, key


def summarize_human_results(
    packet: Dict[str, Any], key: Dict[str, Any]
) -> Dict[str, Any]:
    totals = {"before": [], "after": []}
    preferences = {"before": 0, "after": 0, "tie": 0}
    incomplete: list[str] = []
    for case in packet.get("cases") or []:
        case_id = str(case.get("id") or "unnamed")
        mapping = (key.get("cases") or {}).get(case_id) or {}
        evaluation = case.get("evaluation") or {}
        scores = evaluation.get("scores") or {}
        label_scores = {"A": [], "B": []}
        valid = True
        for dimension in HUMAN_RUBRIC:
            row = scores.get(dimension) or {}
            for label in ("A", "B"):
                value = row.get(label)
                if not isinstance(value, (int, float)) or not 1 <= value <= 5:
                    valid = False
                else:
                    label_scores[label].append(float(value))
        preference = evaluation.get("preference")
        if preference not in {"A", "B", "tie"} or not valid:
            incomplete.append(case_id)
            continue
        for label in ("A", "B"):
            run = mapping.get(label)
            if run in totals:
                totals[run].append(sum(label_scores[label]) / len(HUMAN_RUBRIC))
        if preference == "tie":
            preferences["tie"] += 1
        else:
            preferred_run = mapping.get(preference)
            if preferred_run in {"before", "after"}:
                preferences[preferred_run] += 1
    return {
        "schema_version": 1,
        "completed_count": sum(len(values) for values in totals.values()) // 2,
        "incomplete_case_ids": incomplete,
        "mean_scores": {
            run: (round(sum(values) / len(values), 3) if values else None)
            for run, values in totals.items()
        },
        "preferences": preferences,
    }
