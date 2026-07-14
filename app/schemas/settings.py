from typing import Any, Dict, List

from pydantic import BaseModel, Field


class LLMConfigUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    base_url: str | None = Field(default=None, max_length=500)
    # None means "keep the currently stored key" (UI submits without re-typing).
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)


class LLMConfigRead(BaseModel):
    active: Dict[str, Any]
    providers: List[Dict[str, Any]]


class LLMTestResult(BaseModel):
    ok: bool
    error: str | None = None
    model: str = ""


class ImageOptionsUpdate(BaseModel):
    main_image: bool = False
    section_images: bool = True
    max_images: int = Field(default=5, ge=0, le=20)
    style: str = Field(default="photo", max_length=30)


class ImageConfigUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    base_url: str | None = Field(default=None, max_length=500)
    # None means "keep the currently stored key" (UI submits without re-typing).
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    options: ImageOptionsUpdate | None = None


class ImageConfigRead(BaseModel):
    active: Dict[str, Any]
    providers: List[Dict[str, Any]]
    options: Dict[str, Any]


class ImageTestResult(BaseModel):
    ok: bool
    error: str | None = None
    model: str = ""
