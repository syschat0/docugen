from typing import List

from fastapi import APIRouter, HTTPException
from fastapi import Response

from app.db.repositories import create_project, delete_project, get_project, list_projects
from app.schemas.projects import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=201)
def create_project_endpoint(payload: ProjectCreate) -> ProjectRead:
    return create_project(payload)


@router.get("", response_model=List[ProjectRead])
def list_projects_endpoint() -> List[ProjectRead]:
    return list_projects()


@router.get("/{project_id}", response_model=ProjectRead)
def get_project_endpoint(project_id: str) -> ProjectRead:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project_endpoint(project_id: str) -> Response:
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return Response(status_code=204)
