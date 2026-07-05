from typing import List

from fastapi import APIRouter, HTTPException

from app.db.repositories import (
    create_artifact,
    get_artifact,
    get_project,
    list_artifacts,
)
from app.schemas.artifacts import ArtifactCreate, ArtifactRead

router = APIRouter(prefix="/projects/{project_id}/artifacts", tags=["artifacts"])


def _ensure_project(project_id: str) -> None:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("", response_model=ArtifactRead, status_code=201)
def create_artifact_endpoint(project_id: str, payload: ArtifactCreate) -> ArtifactRead:
    _ensure_project(project_id)
    return create_artifact(project_id, payload)


@router.get("", response_model=List[ArtifactRead])
def list_artifacts_endpoint(project_id: str) -> List[ArtifactRead]:
    _ensure_project(project_id)
    return list_artifacts(project_id)


@router.get("/{artifact_id}", response_model=ArtifactRead)
def get_artifact_endpoint(project_id: str, artifact_id: str) -> ArtifactRead:
    _ensure_project(project_id)
    artifact = get_artifact(project_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact
