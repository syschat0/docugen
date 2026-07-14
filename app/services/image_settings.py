"""Runtime-selectable image-generation provider configuration.

Mirrors :mod:`app.services.llm_settings`: the active provider (base URL / API
key / model) is chosen from the UI and persisted in the ``app_settings`` table,
falling back to the ``.env`` values in :data:`app.core.config.settings` when
nothing is stored. The default provider is ``disabled``, so section
illustrations are off until a provider is configured.

Image size, per-document cap, timeout, and style suffix stay env-driven; only
``base_url`` / ``api_key`` / ``model`` differ per provider.
"""
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from app.core.config import settings

_SETTING_KEY = "image_provider"
_OPTIONS_KEY = "image_options"
_STYLES = ("photo", "illustration")

# Preset providers surfaced in the UI. ``base_url_editable`` / ``model_editable``
# / ``needs_api_key`` drive which fields the frontend shows for each preset.
PROVIDERS: list[Dict[str, Any]] = [
    {
        "id": "disabled",
        "label_en": "Disabled",
        "label_ko": "사용 안 함",
        "base_url": "",
        "default_model": "",
        "needs_api_key": False,
        "base_url_editable": False,
        "model_editable": False,
        "note_en": "Section illustrations are turned off; documents generate as before.",
        "note_ko": "섹션 일러스트를 사용하지 않습니다. 문서는 기존과 동일하게 생성됩니다.",
    },
    {
        "id": "openai",
        "label_en": "OpenAI (gpt-image-1)",
        "label_ko": "OpenAI (gpt-image-1)",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-image-1",
        "needs_api_key": True,
        "base_url_editable": False,
        "model_editable": True,
        "note_en": "The API key is stored in plain text in the local database.",
        "note_ko": "API 키는 로컬 데이터베이스에 평문으로 저장됩니다.",
    },
    {
        "id": "gemini",
        "label_en": "Gemini (image generation)",
        "label_ko": "Gemini (이미지 생성)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "gemini-2.5-flash-image",
        "needs_api_key": True,
        "base_url_editable": False,
        "model_editable": True,
        "note_en": (
            "Needs a billing-enabled Google AI key — the free tier has zero "
            "image-generation quota. The key is stored in plain text in the "
            "local database."
        ),
        "note_ko": (
            "결제가 활성화된 Google AI 키가 필요합니다 — 무료 등급은 이미지 "
            "생성 할당량이 0입니다. 키는 로컬 데이터베이스에 평문으로 "
            "저장됩니다."
        ),
    },
    {
        "id": "custom",
        "label_en": "Custom (OpenAI-compatible images)",
        "label_ko": "커스텀 (OpenAI 호환 images)",
        "base_url": "",
        "default_model": "",
        "needs_api_key": False,
        "base_url_editable": True,
        "model_editable": True,
        "note_en": "Point at any OpenAI-compatible /images/generations endpoint.",
        "note_ko": "임의의 OpenAI 호환 /images/generations 엔드포인트를 지정합니다.",
    },
]

_PROVIDERS_BY_ID = {preset["id"]: preset for preset in PROVIDERS}

# Process-local cache; a run generates several images, so avoid a DB read each
# time. Invalidated on every write via set_active_image_config().
_cache: Optional[Dict[str, str]] = None
# Process-local cache for the runtime image options, invalidated on write via
# set_image_options().
_options_cache: Optional[Dict[str, Any]] = None


class ImageConfigError(ValueError):
    """Raised when a provider configuration is invalid."""


def _disabled_config() -> Dict[str, str]:
    return {"provider": "disabled", "base_url": "", "api_key": "", "model": ""}


def _env_config() -> Dict[str, str]:
    provider = (settings.image_provider or "").strip().lower()
    if not provider or provider not in _PROVIDERS_BY_ID or provider == "disabled":
        return _disabled_config()
    preset = _PROVIDERS_BY_ID[provider]
    base_url = settings.image_base_url or preset["base_url"]
    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": settings.image_api_key,
        "model": settings.image_model or preset["default_model"],
    }


def get_active_image_config() -> Dict[str, str]:
    """Active provider config, from the DB if set, else the env defaults."""
    global _cache
    if _cache is not None:
        return _cache

    # Lazy import to avoid an import cycle (repositories -> ... -> image_settings).
    from app.db.repositories import get_app_setting

    stored = get_app_setting(_SETTING_KEY)
    if stored and stored.get("provider"):
        provider = str(stored.get("provider"))
        if provider == "disabled" or provider not in _PROVIDERS_BY_ID:
            config = _disabled_config()
        else:
            preset = _PROVIDERS_BY_ID[provider]
            config = {
                "provider": provider,
                "base_url": str(stored.get("base_url") or preset["base_url"]),
                "api_key": str(stored.get("api_key") or ""),
                "model": str(stored.get("model") or preset["default_model"]),
            }
    else:
        config = _env_config()
    _cache = config
    return config


def image_generation_enabled() -> bool:
    """True when a real provider is selected and its required key is present."""
    config = get_active_image_config()
    provider = config.get("provider")
    preset = _PROVIDERS_BY_ID.get(provider or "")
    if preset is None or provider == "disabled":
        return False
    if preset["needs_api_key"] and not config.get("api_key"):
        return False
    return True


def _env_options() -> Dict[str, Any]:
    """Runtime image options from the env defaults in :data:`settings`."""
    style = settings.image_style if settings.image_style in _STYLES else "photo"
    return {
        "main_image": settings.image_main_image,
        "section_images": settings.image_section_images,
        "max_images": max(0, min(20, settings.image_max_per_doc)),
        "style": style,
    }


def get_image_options() -> Dict[str, Any]:
    """Runtime image options, from the DB if set, else the env defaults.

    Cover-image / section-image toggles, the per-document cap, and the style
    preset are chosen from the UI and persisted in ``app_settings``; when
    nothing is stored the env values apply. Stored values are coerced field by
    field so a stale or hand-edited row can never crash the pipeline.
    """
    global _options_cache
    if _options_cache is not None:
        return _options_cache

    # Lazy import to avoid an import cycle (repositories -> ... -> image_settings).
    from app.db.repositories import get_app_setting

    env = _env_options()
    stored = get_app_setting(_OPTIONS_KEY)
    if stored:
        try:
            max_images = int(stored.get("max_images"))
        except (TypeError, ValueError):
            max_images = env["max_images"]
        if max_images < 0 or max_images > 20:
            max_images = env["max_images"]
        style = stored.get("style")
        if style not in _STYLES:
            style = env["style"]
        options = {
            "main_image": bool(stored.get("main_image")),
            "section_images": bool(stored.get("section_images")),
            "max_images": max_images,
            "style": style,
        }
    else:
        options = env
    _options_cache = options
    return options


def resolve_options(
    main_image: Any,
    section_images: Any,
    max_images: Any,
    style: Any,
) -> Dict[str, Any]:
    """Validate + normalize runtime image options for the API path.

    Stricter than :func:`get_image_options`: an out-of-range or non-integer
    ``max_images`` or an unknown ``style`` raises ImageConfigError instead of
    falling back, so a bad UI submission is rejected.
    """
    if isinstance(max_images, bool) or not isinstance(max_images, int):
        raise ImageConfigError("max_images must be an integer")
    if max_images < 0 or max_images > 20:
        raise ImageConfigError("max_images must be between 0 and 20")
    if style not in _STYLES:
        raise ImageConfigError(f"Unknown image style '{style}'")
    return {
        "main_image": bool(main_image),
        "section_images": bool(section_images),
        "max_images": max_images,
        "style": style,
    }


def set_image_options(
    main_image: Any,
    section_images: Any,
    max_images: Any,
    style: Any,
) -> Dict[str, Any]:
    """Validate, persist, and activate the runtime image options."""
    global _options_cache
    options = resolve_options(main_image, section_images, max_images, style)

    from app.db.repositories import set_app_setting

    set_app_setting(_OPTIONS_KEY, options)
    _options_cache = options
    return options


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
    submit without re-typing a masked key). Raises ImageConfigError on problems.
    """
    preset = _PROVIDERS_BY_ID.get(provider)
    if preset is None:
        raise ImageConfigError(f"Unknown provider '{provider}'")

    if provider == "disabled":
        return _disabled_config()

    resolved_base = _clean(base_url) if preset["base_url_editable"] else preset["base_url"]
    if not resolved_base:
        resolved_base = preset["base_url"]
    if not resolved_base:
        raise ImageConfigError("Base URL is required")
    if not resolved_base.lower().startswith(("http://", "https://")):
        raise ImageConfigError("Base URL must start with http:// or https://")

    resolved_model = _clean(model) or preset["default_model"]
    if provider == "gemini":
        # AI Studio lists models as "models/<id>"; store the bare id so the
        # REST path (which prefixes "models/") does not double it.
        resolved_model = resolved_model.removeprefix("models/")
    if not resolved_model:
        raise ImageConfigError("Model name is required")

    if api_key is None:
        existing = get_active_image_config()
        resolved_key = existing["api_key"] if existing["provider"] == provider else ""
    else:
        resolved_key = _clean(api_key)

    if preset["needs_api_key"] and not resolved_key:
        raise ImageConfigError("This provider requires an API key")

    return {
        "provider": provider,
        "base_url": resolved_base.rstrip("/"),
        "api_key": resolved_key,
        "model": resolved_model,
    }


def set_active_image_config(
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
    if not key:
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
        "has_api_key": bool(config.get("api_key")),
    }


def test_image_config(
    provider: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout_seconds: int = 15,
) -> Dict[str, Any]:
    """Verify the endpoint by listing models.

    Generating a real image would bill the account, so testing only lists the
    provider's models (a cheap, read-only call) and reports whether it responds.
    """
    try:
        config = resolve_config(provider, base_url, api_key, model)
    except ImageConfigError as exc:
        return {"ok": False, "error": str(exc), "model": model or ""}

    if config["provider"] == "disabled":
        return {"ok": False, "error": "Image generation is disabled", "model": ""}

    if config["provider"] == "gemini":
        url = f"{config['base_url']}/models"
        headers = {"x-goog-api-key": config["api_key"]}
    else:
        url = f"{config['base_url']}/models"
        headers = {"Authorization": f"Bearer {config['api_key']}"}

    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        # A reachable endpoint can still 404 at generation time when the model
        # id is wrong, so check the configured model against the list when the
        # preset's list shape is known. Custom endpoints skip the check.
        if config["provider"] == "gemini":
            known = {
                str(item.get("name") or "").removeprefix("models/")
                for item in payload.get("models") or []
            }
            target = config["model"].removeprefix("models/")
        elif config["provider"] == "openai":
            known = {str(item.get("id") or "") for item in payload.get("data") or []}
            target = config["model"]
        else:
            known, target = set(), ""
        if target and known and target not in known:
            return {
                "ok": False,
                "error": f"Endpoint responded, but model '{target}' is not in its model list",
                "model": target,
            }
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
