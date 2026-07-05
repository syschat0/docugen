from typing import Any, Dict

from pydantic import BaseModel, Field


class ArtifactCreate(BaseModel):
    type: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=200)
    node_id: str | None = Field(default=None, max_length=200)
    content: Dict[str, Any] | None = None
    file_path: str | None = Field(default=None, max_length=1000)


class ArtifactRead(BaseModel):
    id: str
    project_id: str
    node_id: str | None
    type: str
    title: str | None
    content: Dict[str, Any] | None
    file_path: str | None
    version: int
    created_at: str
    updated_at: str
