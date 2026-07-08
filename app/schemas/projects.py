from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    initial_request: str = Field(min_length=1)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    initial_request: str | None = Field(default=None, min_length=1)


class ProjectSettingsUpdate(BaseModel):
    # None means "use the global default"; a set value is an explicit
    # per-project override.
    search_enabled: bool | None = None
    section_search_enabled: bool | None = None
    citation_style: Literal["numeric", "author_date"] | None = None


class ProjectSettingsRead(BaseModel):
    search_enabled: bool | None = None
    section_search_enabled: bool | None = None
    citation_style: str | None = None
    # Global env defaults, so the UI can show what "use default" resolves to.
    defaults: dict[str, bool | str]


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

