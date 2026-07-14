from fastapi import APIRouter, HTTPException

from app.schemas.settings import (
    ImageConfigRead,
    ImageConfigUpdate,
    ImageTestResult,
    LLMConfigRead,
    LLMConfigUpdate,
    LLMTestResult,
)
from app.services.image_settings import (
    PROVIDERS as IMAGE_PROVIDERS,
    ImageConfigError,
    get_active_image_config,
    get_image_options,
    public_config as image_public_config,
    set_active_image_config,
    set_image_options,
    test_image_config,
)
from app.services.llm_settings import (
    PROVIDERS,
    LLMConfigError,
    get_active_llm_config,
    public_config,
    set_active_llm_config,
    test_llm_config,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/llm", response_model=LLMConfigRead)
def get_llm_settings() -> LLMConfigRead:
    return LLMConfigRead(
        active=public_config(get_active_llm_config()),
        providers=PROVIDERS,
    )


@router.put("/llm", response_model=LLMConfigRead)
def update_llm_settings(payload: LLMConfigUpdate) -> LLMConfigRead:
    try:
        config = set_active_llm_config(
            payload.provider, payload.base_url, payload.api_key, payload.model
        )
    except LLMConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LLMConfigRead(active=public_config(config), providers=PROVIDERS)


@router.post("/llm/test", response_model=LLMTestResult)
def test_llm_settings(payload: LLMConfigUpdate) -> LLMTestResult:
    result = test_llm_config(
        payload.provider, payload.base_url, payload.api_key, payload.model
    )
    return LLMTestResult(**result)


@router.get("/image", response_model=ImageConfigRead)
def get_image_settings() -> ImageConfigRead:
    return ImageConfigRead(
        active=image_public_config(get_active_image_config()),
        providers=IMAGE_PROVIDERS,
        options=get_image_options(),
    )


@router.put("/image", response_model=ImageConfigRead)
def update_image_settings(payload: ImageConfigUpdate) -> ImageConfigRead:
    try:
        config = set_active_image_config(
            payload.provider, payload.base_url, payload.api_key, payload.model
        )
        if payload.options is not None:
            set_image_options(
                payload.options.main_image,
                payload.options.section_images,
                payload.options.max_images,
                payload.options.style,
            )
    except ImageConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImageConfigRead(
        active=image_public_config(config),
        providers=IMAGE_PROVIDERS,
        options=get_image_options(),
    )


@router.post("/image/test", response_model=ImageTestResult)
def test_image_settings(payload: ImageConfigUpdate) -> ImageTestResult:
    result = test_image_config(
        payload.provider, payload.base_url, payload.api_key, payload.model
    )
    return ImageTestResult(**result)
