from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    initial_request: str = Field(min_length=1)


class ProjectRead(BaseModel):
    id: str
    title: str
    initial_request: str
    status: str
    current_phase: str | None
    created_at: str
    updated_at: str


class ProjectReferenceRead(BaseModel):
    id: str
    project_id: str
    kind: str
    source: str
    title: str | None
    content_text: str | None
    status: str
    error: str | None
    created_at: str


class ReferenceUrlsCreate(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=10)

