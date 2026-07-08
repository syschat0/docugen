"""Runtime-selectable LLM provider configuration.

The active provider (base URL / API key / model) is chosen from the UI and
persisted in the ``app_settings`` table. When nothing is stored yet, this falls
back to the ``.env`` values in :data:`app.core.config.settings`, so existing
setups keep working with no change.

Only ``base_url`` / ``api_key`` / ``model`` differ per provider; everything else
(timeouts, whether the LLM is enabled at all) stays env-driven.
"""
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from app.core.config import settings

_SETTING_KEY = "llm_provider"

# Preset providers surfaced in the UI. ``base_url_editable`` / ``model_editable``
# / ``needs_api_key`` drive which fields the frontend shows for each preset.
PROVIDERS: list[Dict[str, Any]] = [
    {
        "id": "local",
        "label_en": "Local LLM (LM Studio / Ollama)",
        "label_ko": "로컬 LLM (LM Studio / Ollama)",
        "base_url": "http://localhost:8088/v1",
        "default_model": "",
        "needs_api_key": False,
        "base_url_editable": True,
        "model_editable": True,
        "note_en": "Any OpenAI-compatible server on localhost.",
        "note_ko": "localhost의 OpenAI 호환 서버.",
    },
    {
        "id": "chatgpt_oauth",
        "label_en": "ChatGPT account (openai-oauth proxy)",
        "label_ko": "ChatGPT 계정 (openai-oauth 프록시)",
        "base_url": "http://127.0.0.1:10531/v1",
        "default_model": "gpt-5-codex",
        "needs_api_key": False,
        "base_url_editable": False,
        "model_editable": True,
        "note_en": (
            "Run `npx @openai/codex login` once, then keep `npx openai-oauth` "
            "running. Uses your ChatGPT plan; not affiliated with OpenAI and "
            "subject to their terms."
        ),
        "note_ko": (
            "`npx @openai/codex login`으로 1회 로그인 후 `npx openai-oauth` "
            "프록시를 실행해 두세요. ChatGPT 플랜을 사용하며 OpenAI 공식이 "
            "아니고 약관 적용 대상입니다."
        ),
    },
    {
        "id": "openai",
        "label_en": "OpenAI API (direct key)",
        "label_ko": "OpenAI API (직접 키)",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "needs_api_key": True,
        "base_url_editable": False,
        "model_editable": True,
        "note_en": "The API key is stored in plain text in the local database.",
        "note_ko": "API 키는 로컬 데이터베이스에 평문으로 저장됩니다.",
    },
    {
        "id": "custom",
        "label_en": "Custom (OpenAI-compatible)",
        "label_ko": "커스텀 (OpenAI 호환)",
        "base_url": "",
        "default_model": "",
        "needs_api_key": False,
        "base_url_editable": True,
        "model_editable": True,
        "note_en": "Point at any OpenAI-compatible /v1 endpoint.",
        "note_ko": "임의의 OpenAI 호환 /v1 엔드포인트를 지정합니다.",
    },
]

_PROVIDERS_BY_ID = {preset["id"]: preset for preset in PROVIDERS}

# Process-local cache; a pipeline run makes many LLM calls, so avoid a DB read
# each time. Invalidated on every write via set_active_llm_config().
_cache: Optional[Dict[str, str]] = None


class LLMConfigError(ValueError):
    """Raised when a provider configuration is invalid."""


def _infer_provider(base_url: str) -> str:
    lowered = (base_url or "").lower()
    if "10531" in lowered:
        return "chatgpt_oauth"
    if "api.openai.com" in lowered:
        return "openai"
    if "localhost" in lowered or "127.0.0.1" in lowered:
        return "local"
    return "custom"


def _env_config() -> Dict[str, str]:
    base_url = settings.llm_base_url
    return {
        "provider": _infer_provider(base_url),
        "base_url": base_url,
        "api_key": settings.llm_api_key,
        "model": settings.llm_model,
    }


def get_active_llm_config() -> Dict[str, str]:
    """Active provider config, from the DB if set, else the env defaults."""
    global _cache
    if _cache is not None:
        return _cache

    # Lazy import: repositories imports this module's siblings, so importing it
    # at module load would create a cycle (repositories -> llm -> llm_settings).
    from app.db.repositories import get_app_setting

    stored = get_app_setting(_SETTING_KEY)
    if stored and stored.get("base_url"):
        config = {
            "provider": str(stored.get("provider") or _infer_provider(stored["base_url"])),
            "base_url": str(stored["base_url"]),
            "api_key": str(stored.get("api_key") or "local"),
            "model": str(stored.get("model") or ""),
        }
    else:
        config = _env_config()
    _cache = config
    return config


def _clean(value: Any) -> str:
    return str(value or "").strip()


def resolve_config(
    provider: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, str]:
    """Validate + normalize a provider config against its preset rules.

    ``api_key`` of None means "keep the currently stored key" (so the UI can
    submit without re-typing a masked key). Raises LLMConfigError on problems.
    """
    preset = _PROVIDERS_BY_ID.get(provider)
    if preset is None:
        raise LLMConfigError(f"Unknown provider '{provider}'")

    resolved_base = _clean(base_url) if preset["base_url_editable"] else preset["base_url"]
    if not resolved_base:
        resolved_base = preset["base_url"]
    if not resolved_base:
        raise LLMConfigError("Base URL is required")
    if not resolved_base.lower().startswith(("http://", "https://")):
        raise LLMConfigError("Base URL must start with http:// or https://")

    resolved_model = _clean(model) or preset["default_model"]
    if not resolved_model:
        raise LLMConfigError("Model name is required")

    if api_key is None:
        existing = get_active_llm_config()
        resolved_key = existing["api_key"] if existing["provider"] == provider else ""
    else:
        resolved_key = _clean(api_key)

    if preset["needs_api_key"] and not resolved_key:
        raise LLMConfigError("This provider requires an API key")
    if not resolved_key:
        # Local servers / proxies ignore the key but the header must be present.
        resolved_key = "local"

    return {
        "provider": provider,
        "base_url": resolved_base.rstrip("/"),
        "api_key": resolved_key,
        "model": resolved_model,
    }


def set_active_llm_config(
    provider: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, str]:
    """Validate, persist, and activate a provider config."""
    global _cache
    config = resolve_config(provider, base_url, api_key, model)

    from app.db.repositories import set_app_setting

    set_app_setting(_SETTING_KEY, config)
    _cache = config
    return config


def mask_api_key(key: str) -> str:
    key = key or ""
    if not key or key == "local":
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:3]}…{key[-4:]}"


def public_config(config: Dict[str, str]) -> Dict[str, Any]:
    """Config safe to return over the API (API key masked, never raw)."""
    return {
        "provider": config["provider"],
        "base_url": config["base_url"],
        "model": config["model"],
        "api_key_masked": mask_api_key(config.get("api_key", "")),
        "has_api_key": bool(config.get("api_key") and config["api_key"] != "local"),
    }


def test_llm_config(
    provider: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout_seconds: int = 15,
) -> Dict[str, Any]:
    """Send a tiny chat completion to verify the endpoint/model respond."""
    try:
        config = resolve_config(provider, base_url, api_key, model)
    except LLMConfigError as exc:
        return {"ok": False, "error": str(exc), "model": model or ""}

    url = config["base_url"] + "/chat/completions"
    payload = {
        "model": config["model"],
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            json.loads(response.read().decode("utf-8"))
        return {"ok": True, "error": None, "model": config["model"]}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        return {
            "ok": False,
            "error": f"HTTP {exc.code}: {detail}",
            "model": config["model"],
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "error": f"Server not reachable: {exc.reason}",
            "model": config["model"],
        }
    except (TimeoutError, ValueError) as exc:
        return {"ok": False, "error": str(exc) or "Request failed", "model": config["model"]}
