"""Process-local control channel for in-flight document generation runs.

A run executes in a background thread in the same process as the API, so a
plain in-memory registry (guarded by a lock) is enough to signal cancellation
and publish per-stage sub-progress to the polling ``/progress`` endpoint. None
of this survives a restart, which is fine: background runs do not either.
"""
import threading
from typing import Dict, Optional

_lock = threading.Lock()
_cancel_requested: set[str] = set()
# project_id -> {"phase": str, "done": int, "total": int}
_stage_progress: Dict[str, Dict[str, object]] = {}


# --- cancellation -----------------------------------------------------------

def request_cancel(project_id: str) -> None:
    with _lock:
        _cancel_requested.add(project_id)


def is_cancel_requested(project_id: str) -> bool:
    with _lock:
        return project_id in _cancel_requested


def clear_cancel(project_id: str) -> None:
    with _lock:
        _cancel_requested.discard(project_id)


# --- per-stage sub-progress -------------------------------------------------

def set_stage_progress(project_id: str, phase: str, done: int, total: int) -> None:
    """Publish "done of total" for the stage currently iterating."""
    with _lock:
        if total and total > 0:
            _stage_progress[project_id] = {
                "phase": phase,
                "done": max(0, min(done, total)),
                "total": total,
            }


def get_stage_progress(project_id: str) -> Optional[Dict[str, object]]:
    with _lock:
        progress = _stage_progress.get(project_id)
        return dict(progress) if progress else None


def clear_stage_progress(project_id: str) -> None:
    with _lock:
        _stage_progress.pop(project_id, None)
