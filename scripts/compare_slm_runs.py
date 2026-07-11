import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.quality_benchmark import DEFAULT_CASES_PATH, load_benchmark_cases  # noqa: E402
from app.services.slm_evaluation import (  # noqa: E402
    build_blind_human_packet,
    build_slm_comparison,
    summarize_human_results,
)


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare before/after SLM outputs and create a blind human review packet"
    )
    parser.add_argument("--before-dir", type=Path, required=True)
    parser.add_argument("--after-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--seed", default="docugen-slm-eval")
    parser.add_argument(
        "--human-results",
        type=Path,
        help="Optional completed human_evaluation.json to aggregate",
    )
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()

    cases = load_benchmark_cases(args.cases)
    comparison = build_slm_comparison(cases, args.before_dir, args.after_dir)
    packet, key = build_blind_human_packet(
        cases, args.before_dir, args.after_dir, seed=args.seed
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write(args.output_dir / "deterministic_comparison.json", comparison)
    _write(args.output_dir / "human_evaluation.json", packet)
    _write(args.output_dir / "blind_key.json", key)
    if args.human_results:
        completed = json.loads(args.human_results.read_text(encoding="utf-8"))
        _write(
            args.output_dir / "human_summary.json",
            summarize_human_results(completed, key),
        )

    print(
        "automatic: "
        f"{comparison['improved_or_equal_count']}/{comparison['case_count']} "
        "cases improved or stayed equal"
    )
    print(f"human packet: {args.output_dir / 'human_evaluation.json'}")
    if args.fail_on_regression:
        return 0 if comparison["improved_or_equal_count"] == comparison["case_count"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
