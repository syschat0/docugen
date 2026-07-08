import threading

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.db.repositories import (
    WorkflowCancelledError,
    WorkflowRunFailedError,
    export_project_markdown,
    get_project,
    get_workflow_progress,
    restore_draft_version,
    run_document_generation,
    set_project_status,
)
from app.services.run_control import clear_cancel, clear_stage_progress, request_cancel
from app.schemas.artifacts import ArtifactRead
from app.schemas.exports import ExportRead
from app.schemas.workflow import WorkflowProgressRead, WorkflowRunRead, WorkflowRunRequest

router = APIRouter(prefix="/projects/{project_id}", tags=["workflow"])

_active_runs: set[str] = set()
_active_runs_lock = threading.Lock()


def _try_start_run(project_id: str) -> bool:
    with _active_runs_lock:
        if project_id in _active_runs:
            return False
        _active_runs.add(project_id)
        return True


def _run_workflow_in_background(project_id: str, force_from: str | None) -> None:
    try:
        run_document_generation(project_id, force_from=force_from)
    except WorkflowCancelledError:
        _cancel_project(project_id)
    except WorkflowRunFailedError:
        pass  # already recorded on the project and the failed agent run
    except Exception as exc:
        _fail_project(project_id, exc)
    finally:
        clear_cancel(project_id)
        clear_stage_progress(project_id)
        with _active_runs_lock:
            _active_runs.discard(project_id)


def _cancel_project(project_id: str) -> None:
    try:
        set_project_status(project_id, "cancelled")
    except Exception:
        pass


def _fail_project(project_id: str, exc: Exception) -> None:
    try:
        set_project_status(project_id, "failed")
    except Exception:
        pass


@router.post("/run", response_model=WorkflowRunRead)
def run_project_workflow_endpoint(
    project_id: str,
    background_tasks: BackgroundTasks,
    payload: WorkflowRunRequest | None = None,
) -> WorkflowRunRead:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not _try_start_run(project_id):
        return WorkflowRunRead(
            project=project,
            artifacts=[],
            pending_questions=[],
            status="running",
            message="A writing run is already in progress for this project.",
        )

    force_from = payload.force_from if payload is not None else None
    # Mark the project running before responding so progress polling never
    # observes the pre-run status and stops early.
    set_project_status(project_id, "running", force_from or "intake")
    background_tasks.add_task(_run_workflow_in_background, project_id, force_from)

    updated_project = get_project(project_id) or project
    return WorkflowRunRead(
        project=updated_project,
        artifacts=[],
        pending_questions=[],
        status="started",
        message="Writing pipeline started in the background.",
    )


@router.post("/cancel", response_model=WorkflowRunRead)
def cancel_project_workflow_endpoint(project_id: str) -> WorkflowRunRead:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    with _active_runs_lock:
        running = project_id in _active_runs
    if not running:
        return WorkflowRunRead(
            project=project,
            status="not_running",
            message="No active writing run to cancel.",
        )

    # The background run checks this flag at each stage boundary (and per section
    # during the long writing phase) and stops cooperatively.
    request_cancel(project_id)
    return WorkflowRunRead(
        project=project,
        status="cancelling",
        message="Cancellation requested; the run will stop at the next step.",
    )


@router.get("/progress", response_model=WorkflowProgressRead)
def get_project_workflow_progress_endpoint(project_id: str) -> WorkflowProgressRead:
    progress = get_workflow_progress(project_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return progress


@router.post("/drafts/{artifact_id}/restore", response_model=ArtifactRead)
def restore_draft_version_endpoint(project_id: str, artifact_id: str) -> ArtifactRead:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = restore_draft_version(project_id, artifact_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Draft version not found")
    return result


@router.post("/export", response_model=ExportRead)
def export_project_markdown_endpoint(project_id: str) -> ExportRead:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = export_project_markdown(project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Draft artifact not found")
    return result
