import pytest

from app.db.repositories import WorkflowCancelledError, _start_agent_run
from app.services import run_control


class TestCancelRegistry:
    def test_request_and_clear(self):
        run_control.clear_cancel("proj-x")
        assert run_control.is_cancel_requested("proj-x") is False
        run_control.request_cancel("proj-x")
        assert run_control.is_cancel_requested("proj-x") is True
        run_control.clear_cancel("proj-x")
        assert run_control.is_cancel_requested("proj-x") is False


class TestStageProgress:
    def test_set_get_clear(self):
        run_control.clear_stage_progress("proj-y")
        assert run_control.get_stage_progress("proj-y") is None
        run_control.set_stage_progress("proj-y", "section_writing", 3, 10)
        assert run_control.get_stage_progress("proj-y") == {
            "phase": "section_writing",
            "done": 3,
            "total": 10,
        }
        run_control.clear_stage_progress("proj-y")
        assert run_control.get_stage_progress("proj-y") is None

    def test_zero_total_is_ignored(self):
        run_control.clear_stage_progress("proj-z")
        run_control.set_stage_progress("proj-z", "section_writing", 0, 0)
        assert run_control.get_stage_progress("proj-z") is None

    def test_done_is_clamped_to_total(self):
        run_control.set_stage_progress("proj-w", "section_writing", 99, 5)
        assert run_control.get_stage_progress("proj-w")["done"] == 5
        run_control.clear_stage_progress("proj-w")


class TestStartAgentRunCancellation:
    def test_raises_before_any_db_write_when_cancelled(self):
        # The cancel check is the first line of _start_agent_run, so a requested
        # cancel aborts the stage before it touches the database.
        run_control.request_cancel("cancel-me")
        try:
            with pytest.raises(WorkflowCancelledError):
                _start_agent_run("cancel-me", "writer", "brief", {})
        finally:
            run_control.clear_cancel("cancel-me")
