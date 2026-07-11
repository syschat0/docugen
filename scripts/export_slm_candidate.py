import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.repositories import _latest_artifacts, get_project  # noqa: E402
from app.services.llm_settings import get_active_llm_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export one generated project as an SLM benchmark candidate"
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-label", default="")
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    project = get_project(args.project_id)
    if project is None:
        parser.error(f"project not found: {args.project_id}")
    latest_by_section = {}
    for artifact in _latest_artifacts(args.project_id, "section_draft"):
        content = artifact.content or {}
        section_id = str((content.get("section") or {}).get("id") or "")
        if section_id and str(content.get("markdown") or "").strip():
            latest_by_section[section_id] = content
    if not latest_by_section:
        parser.error("project has no section drafts")

    config = get_active_llm_config()
    payload = {
        "schema_version": 1,
        "metadata": {
            "project_id": project.id,
            "request": project.initial_request,
            "document_type": project.document_type,
            "model": config.get("model"),
            "run_label": args.run_label,
            "commit": args.commit,
        },
        "section_drafts": list(latest_by_section.values()),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"{args.case_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"exported: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
