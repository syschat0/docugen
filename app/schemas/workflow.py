from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.schemas.artifacts import ArtifactRead
from app.schemas.questions import PendingQuestionRead
from app.schemas.projects import ProjectRead


class WorkflowRunRead(BaseModel):
    project: ProjectRead
    artifacts: List[ArtifactRead] = Field(default_factory=list)
    pending_questions: List[PendingQuestionRead] = Field(default_factory=list)
    status: str
    message: str


class WorkflowRunRequest(BaseModel):
    force_from: str | None = None


class WorkflowStepRead(BaseModel):
    phase: str
    label: str
    status: str
    created_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    details: Dict[str, Any] = Field(default_factory=dict)
    # {"done": int, "total": int} while an iterative stage is running; else None.
    progress: Dict[str, int] | None = None


class WorkflowProgressRead(BaseModel):
    project: ProjectRead
    steps: List[WorkflowStepRead]
    percent: int
    current_phase: str | None
    status: str

