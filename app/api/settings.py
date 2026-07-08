from fastapi import APIRouter, HTTPException

from app.schemas.settings import LLMConfigRead, LLMConfigUpdate, LLMTestResult
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
