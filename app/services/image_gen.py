"""Generate one section illustration via the active image provider.

Uses only the standard library (urllib) — the project does not depend on
``requests``. Generated PNGs are cached under :data:`settings.media_dir` by a
hash of ``provider|model|size|prompt``, so re-running the pipeline or re-merging
a draft never issues (or re-bills) a second API call for the same image.
"""
import base64
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

from app.core.config import settings


class ImageGenError(Exception):
    """A single image could not be generated; the caller records it and moves on."""


def _cache_path(provider: str, model: str, size: str, prompt: str) -> Path:
    # AI Studio spells models as "models/<id>"; normalize so both spellings
    # share one cache entry.
    model = model.removeprefix("models/")
    digest = hashlib.sha256(
        f"{provider}|{model}|{size}|{prompt}".encode("utf-8")
    ).hexdigest()[:20]
    return settings.media_dir / f"{digest}.png"


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    """Pull an error message out of a JSON error body, like google_pse does."""
    try:
        body = json.loads(exc.read().decode("utf-8", errors="replace"))
        message = str((body.get("error") or {}).get("message") or "")
    except Exception:
        message = ""
    return f"HTTP {exc.code}: {message}" if message else f"HTTP {exc.code}"


def _aspect_ratio(size: str) -> str:
    """Map an OpenAI-style WxH size to a Gemini aspectRatio string."""
    mapping = {"1536x1024": "3:2", "1024x1536": "2:3", "1024x1024": "1:1"}
    if size in mapping:
        return mapping[size]
    try:
        width, height = (int(part) for part in size.lower().split("x", 1))
    except (ValueError, TypeError):
        return "3:2"
    if width == height:
        return "1:1"
    return "3:2" if width > height else "2:3"


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=settings.image_timeout_seconds
        ) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise ImageGenError(_http_error_detail(exc)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ImageGenError(str(exc)) from exc


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DocuGen/0.1"})
    try:
        with urllib.request.urlopen(
            request, timeout=settings.image_timeout_seconds
        ) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ImageGenError(_http_error_detail(exc)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ImageGenError(str(exc)) from exc


def _openai_image_bytes(prompt: str, config: Dict[str, str]) -> bytes:
    payload: Dict[str, Any] = {
        "model": config["model"],
        "prompt": prompt,
        "size": settings.image_size,
        "n": 1,
    }
    # gpt-image-1 rejects response_format and always returns b64; only the older
    # dall-e models need it requested explicitly.
    if config["model"].startswith("dall-e"):
        payload["response_format"] = "b64_json"
    result = _post_json(
        f"{config['base_url']}/images/generations",
        payload,
        {"Authorization": f"Bearer {config['api_key']}"},
    )
    data = result.get("data") or []
    if not data:
        raise ImageGenError("Image response contained no data")
    first = data[0]
    b64 = first.get("b64_json")
    if b64:
        return base64.b64decode(b64)
    # Some OpenAI-compatible servers return a URL instead of inline base64.
    url = first.get("url")
    if url:
        return _fetch_bytes(url)
    raise ImageGenError("Image response had neither b64_json nor url")


def _gemini_image_bytes(prompt: str, config: Dict[str, str]) -> bytes:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": _aspect_ratio(settings.image_size)},
        },
    }
    # The REST path already prefixes "models/"; a full "models/<id>" name
    # pasted from AI Studio would otherwise 404 as "models/models/<id>".
    model = config["model"].removeprefix("models/")
    result = _post_json(
        f"{config['base_url']}/models/{model}:generateContent",
        payload,
        {"x-goog-api-key": config["api_key"]},
    )
    candidates = result.get("candidates") or []
    for candidate in candidates:
        parts = ((candidate.get("content") or {}).get("parts")) or []
        for part in parts:
            # Response keys vary between camelCase and snake_case by endpoint.
            inline = part.get("inlineData") or part.get("inline_data")
            if isinstance(inline, dict) and inline.get("data"):
                return base64.b64decode(inline["data"])
    raise ImageGenError("Gemini response contained no image part")


def generate_section_image(prompt: str, *, config: Dict[str, str]) -> Path:
    """Generate one PNG via the active provider and cache it under media_dir.

    Cache key: sha256(f"{provider}|{model}|{size}|{prompt}") first 20 hex chars,
    filename f"{digest}.png". If the file already exists, return it without an
    API call (re-runs and re-merges never re-bill).
    """
    provider = config.get("provider") or ""
    model = config.get("model") or ""
    path = _cache_path(provider, model, settings.image_size, prompt)
    if path.exists():
        return path

    if provider == "gemini":
        image_bytes = _gemini_image_bytes(prompt, config)
    elif provider in {"openai", "custom"}:
        image_bytes = _openai_image_bytes(prompt, config)
    else:
        raise ImageGenError(f"Unsupported image provider '{provider}'")

    if not image_bytes:
        raise ImageGenError("Provider returned empty image bytes")

    settings.media_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return path
