import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.quality_benchmark import (  # noqa: E402
    DEFAULT_CASES_PATH,
    load_benchmark_cases,
    run_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DocuGen's offline quality benchmark")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        help="Optional directory containing <case-id>.json SLM candidate outputs",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()

    report = run_benchmark(
        load_benchmark_cases(args.cases), candidate_dir=args.candidate_dir
    )
    for result in report["results"]:
        marker = "PASS" if result["passed"] else "FAIL"
        print(
            f"{marker} {result['id']}: "
            f"flags {result['baseline']['total_flags']} -> "
            f"{result['candidate']['total_flags']}"
        )
        for check in result["checks"]:
            if not check["passed"]:
                print(f"  failed {check['name']}: {check}")
    print(f"summary: {report['passed_count']}/{report['case_count']} cases passed")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"report: {args.output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
