from typing import Literal

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
    # Total body-length budget in characters; None lets the brief-extracted
    # length (or no budget) apply.
    target_length: int | None = Field(default=None, ge=100, le=200000)
    # Browser-search knobs (also settable via env; see app/core/config.py).
    # search_engines is a priority list tried in order (fallback on block/error).
    search_engines: list[Literal["daum", "bing", "google"]] | None = None
    search_headless: bool | None = None
    search_stealth: bool | None = None
    search_locale: Literal["ko-KR", "en-US"] | None = None
    search_query_language: Literal["native", "english", "both"] | None = None

    @field_validator("search_engines")
    @classmethod
    def _dedupe_engines(cls, value: list[str] | None) -> list[str] | None:
        """Drop duplicates (keep order); an empty list means "use default"."""
        if not value:
            return None
        deduped: list[str] = []
        for engine in value:
            if engine not in deduped:
                deduped.append(engine)
        return deduped or None


class ProjectSettingsRead(BaseModel):
    search_enabled: bool | None = None
    section_search_enabled: bool | None = None
    citation_style: str | None = None
    target_length: int | None = None
    search_engines: list[str] | None = None
    search_headless: bool | None = None
    search_stealth: bool | None = None
    search_locale: str | None = None
    search_query_language: str | None = None
    # Global env defaults, so the UI can show what "use default" resolves to.
    defaults: dict[str, bool | str | list[str]]


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

