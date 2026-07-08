from pydantic import BaseModel, Field, field_validator

from app.services.doc_types import is_valid_doc_type


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    initial_request: str = Field(min_length=1)
    document_type: str | None = None

    @field_validator("document_type")
    @classmethod
    def _normalize_doc_type(cls, value: str | None) -> str | None:
        """None/"auto" mean "classify at the next run"."""
        if value in (None, "", "auto"):
            return None
        if not is_valid_doc_type(value):
            raise ValueError(f"Unknown document_type: {value}")
        return value


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    initial_request: str | None = Field(default=None, min_length=1)
    # "auto" resets the type so the next run re-classifies; None means
    # "leave unchanged" (consistent with the other PATCH fields).
    document_type: str | None = None

    @field_validator("document_type")
    @classmethod
    def _validate_doc_type(cls, value: str | None) -> str | None:
        if value in (None, "auto"):
            return value
        if not is_valid_doc_type(value):
            raise ValueError(f"Unknown document_type: {value}")
        return value


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
    document_type: str | None = None
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

