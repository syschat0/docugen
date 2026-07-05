import json
import os
import subprocess
import sys
import time
import tempfile
import urllib.request


def request(base_url: str, method: str, path: str, payload: dict | None = None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base_url + path, data=body, method=method)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, json.load(response)


def text_request(base_url: str, path: str) -> tuple[int, str]:
    with urllib.request.urlopen(base_url + path, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def empty_request(base_url: str, method: str, path: str) -> int:
    req = urllib.request.Request(base_url + path, method=method)
    with urllib.request.urlopen(req, timeout=5) as response:
        response.read()
        return response.status


def wait_for_run(base_url: str, project_id: str, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, progress = request(base_url, "GET", f"/projects/{project_id}/progress")
        if progress["status"] in {"completed", "failed", "waiting_for_user"}:
            return status, progress
        time.sleep(0.5)
    raise RuntimeError("workflow run did not finish in time")


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = sys.argv[2] if len(sys.argv) > 2 else "8765"
    base_url = f"http://{host}:{port}"

    with tempfile.TemporaryDirectory(prefix="docugen-smoke-") as temp_dir:
        env = os.environ.copy()
        env["DATABASE_PATH"] = os.path.join(temp_dir, "app.sqlite3")
        env["LLM_ENABLED"] = "false"
        env["SEARCH_ENABLED"] = "false"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                host,
                "--port",
                port,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

        try:
            time.sleep(3)
            health_status, health = request(base_url, "GET", "/health")
            ui_status, ui_html = text_request(base_url, "/ui/")
            projects_status, projects = request(base_url, "GET", "/projects")

            project_status, project = request(
                base_url,
                "POST",
                "/projects",
                {
                    "title": "Smoke verification",
                    "initial_request": "Verify project, question, and artifact APIs.",
                },
            )
            project_id = project["id"]

            question_status, question = request(
                base_url,
                "POST",
                f"/projects/{project_id}/questions",
                {
                    "phase": "intake",
                    "question": {
                        "question": "Who is the audience?",
                        "priority": "high",
                    },
                },
            )
            question_id = question["id"]

            answer_status, _ = request(
                base_url,
                "POST",
                f"/projects/{project_id}/questions/{question_id}/answer",
                {
                    "answer": "Product managers",
                    "applies_to": {"scope": "brief"},
                },
            )
            answer_update_status, _ = request(
                base_url,
                "PUT",
                f"/projects/{project_id}/questions/{question_id}/answer",
                {
                    "answer": "Product leaders",
                    "applies_to": {"scope": "brief"},
                },
            )
            delete_question_status, delete_question = request(
                base_url,
                "POST",
                f"/projects/{project_id}/questions",
                {
                    "phase": "brief",
                    "question": {
                        "question": "Should this be technical?",
                        "priority": "medium",
                    },
                },
            )
            delete_question_id = delete_question["id"]
            delete_answer_status, _ = request(
                base_url,
                "POST",
                f"/projects/{project_id}/questions/{delete_question_id}/answer",
                {"answer": "No"},
            )
            answer_delete_status = empty_request(
                base_url,
                "DELETE",
                f"/projects/{project_id}/questions/{delete_question_id}/answer",
            )
            restore_answer_status, _ = request(
                base_url,
                "POST",
                f"/projects/{project_id}/questions/{delete_question_id}/answer",
                {"answer": "No"},
            )
            artifact_status, _ = request(
                base_url,
                "POST",
                f"/projects/{project_id}/artifacts",
                {
                    "type": "brief",
                    "title": "Initial brief",
                    "content": {"audience": "Product managers"},
                },
            )
            _, answered_questions = request(
                base_url, "GET", f"/projects/{project_id}/questions?status=answered"
            )
            run_status, run_result = request(
                base_url, "POST", f"/projects/{project_id}/run", {}
            )
            progress_status, progress = wait_for_run(base_url, project_id)
            rerun_status, rerun_result = request(
                base_url,
                "POST",
                f"/projects/{project_id}/run",
                {"force_from": "outline_review"},
            )
            _, rerun_progress = wait_for_run(base_url, project_id)
            export_status, export_result = request(
                base_url, "POST", f"/projects/{project_id}/export", {}
            )
            _, artifacts = request(base_url, "GET", f"/projects/{project_id}/artifacts")

            if health_status != 200 or health.get("status") != "ok":
                raise RuntimeError("health check failed")
            if ui_status != 200 or "LLM Document Agent" not in ui_html:
                raise RuntimeError("ui check failed")
            if projects_status != 200 or not isinstance(projects, list):
                raise RuntimeError("project list failed")
            if project_status != 201:
                raise RuntimeError("project create failed")
            if question_status != 201:
                raise RuntimeError("question create failed")
            if answer_status != 200 or len(answered_questions) != 2:
                raise RuntimeError("question answer failed")
            if answer_update_status != 200:
                raise RuntimeError("question answer update failed")
            if (
                delete_question_status != 201
                or delete_answer_status != 200
                or answer_delete_status != 204
                or restore_answer_status != 200
            ):
                raise RuntimeError("question answer delete failed")
            if artifact_status != 201:
                raise RuntimeError("artifact create failed")
            if run_status != 200 or run_result["status"] != "started":
                raise RuntimeError("workflow run failed")
            if progress["status"] != "completed":
                raise RuntimeError("workflow status update failed")
            if progress_status != 200 or progress["percent"] != 100:
                raise RuntimeError("workflow progress failed")
            if rerun_status != 200 or rerun_result["status"] != "started":
                raise RuntimeError("workflow rerun failed")
            if rerun_progress["status"] != "completed":
                raise RuntimeError("workflow rerun completion failed")
            if export_status != 200 or not export_result["file_path"].endswith("final.md"):
                raise RuntimeError("markdown export failed")
            if len(artifacts) < 10:
                raise RuntimeError("artifact list after workflow failed")
            delete_status = empty_request(
                base_url, "DELETE", f"/projects/{project_id}"
            )
            _, projects_after_delete = request(base_url, "GET", "/projects")
            if delete_status != 204 or len(projects_after_delete) != len(projects):
                raise RuntimeError("project delete failed")

            print(
                "health=ok; "
                "ui=ok; "
                f"projects_before={len(projects)}; "
                f"question={question_status}; "
                f"answer={answer_status}; "
                f"answer_update={answer_update_status}; "
                f"answer_delete={answer_delete_status}; "
                f"run={run_status}; "
                f"rerun={rerun_status}; "
                f"progress={progress['percent']}; "
                f"export={export_status}; "
                f"delete={delete_status}; "
                f"artifacts={len(artifacts)}"
            )
            return 0
        finally:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
