"""Google Programmable Search Engine (Custom Search JSON API) client.

An API-type engine: results come from an HTTPS endpoint, so no browser page
is involved and it is immune to bot challenges. Needs GOOGLE_PSE_API_KEY and
GOOGLE_PSE_CX. The free tier is limited (about 100 queries/day); quota or
permission failures raise GooglePSEQuotaError so the engine fallback chain
can move on and stop retrying it for the run.
"""

import json
from urllib.parse import urlencode
import urllib.error
import urllib.request

from app.core.config import settings
from app.services.search_options import current_search_options


class GooglePSEError(Exception):
    pass


class GooglePSEQuotaError(GooglePSEError):
    """Quota, rate-limit, or permission failure — won't heal within a run."""


def google_pse_configured() -> bool:
    return bool(settings.google_pse_api_key and settings.google_pse_cx)


def search_google_pse(query: str, limit: int = 10) -> list[dict[str, str]]:
    if not google_pse_configured():
        raise GooglePSEError("google_pse needs GOOGLE_PSE_API_KEY and GOOGLE_PSE_CX")

    params = {
        "key": settings.google_pse_api_key,
        "cx": settings.google_pse_cx,
        "q": query,
        # num is capped at 10 by the API.
        "num": max(1, min(limit, 10)),
    }
    # Use the request language (e.g. "ko" from "ko-KR") when available.
    locale = current_search_options().locale or ""
    lang = locale.split("-")[0].strip()
    if lang:
        params["hl"] = lang

    url = f"https://www.googleapis.com/customsearch/v1?{urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "DocuGen/0.1"})
    try:
        with urllib.request.urlopen(
            request, timeout=settings.search_timeout_seconds
        ) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str((body.get("error") or {}).get("message") or "")
        except Exception:
            detail = ""
        message = f"HTTP {exc.code}: {detail}" if detail else f"HTTP {exc.code}"
        # 403 (quota/permission) and 429 (rate limit) won't recover in a run.
        if exc.code in (403, 429):
            raise GooglePSEQuotaError(message) from exc
        raise GooglePSEError(message) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GooglePSEError(str(exc)) from exc

    results: list[dict[str, str]] = []
    for item in payload.get("items") or []:
        link = str(item.get("link") or "")
        if not link:
            continue
        results.append(
            {
                "title": str(item.get("title") or ""),
                "url": link,
                "snippet": str(item.get("snippet") or ""),
            }
        )
    return results
