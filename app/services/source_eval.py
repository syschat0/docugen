"""LLM-judge layer over search sources: gate, compress, and score each page.

For every eligible source this runs one LLM call
(:func:`app.services.llm.evaluate_source_quality`) that decides whether the page
is usable, compresses it into a short summary plus a few key facts, and scores
its information density. Verdicts are normalized, cached by URL and body hash,
and attached in place as ``source["eval"]``. The pipeline uses the gate and
density to filter and rank section sources; the summary is rendered only as a
non-citable helper line and the key facts are stored on the artifact and never
shown to the writer, so an LLM-generated fact can never masquerade as verifiable
evidence in the ``[n.Pk]`` ledger.

Standard library only. This module must NOT import ``app.db.repositories`` —
repositories imports it, and a reverse import would create a cycle. Importing
llm, quality, and session is safe.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.config import settings
from app.db.session import get_connection
from app.services.llm import LLMError, evaluate_source_quality
from app.services.quality import grade_source


# Prompt revision tag baked into the cache key. Bump it whenever the evaluation
# prompt changes so stale verdicts are invalidated instead of silently reused.
_EVAL_PROMPT_VERSION = "v1"

# A page needs at least this many characters of cleaned body to be worth a call.
_MIN_ELIGIBLE_CHARS = 200

# Length of the body excerpt sent to the judge (and hashed into the cache key).
_EXCERPT_CHARS = 1500

# Stop after this many consecutive-in-total LLM errors so one flaky endpoint
# cannot burn the whole budget on failures.
_MAX_ERRORS = 2

_PAGE_TYPES = {"content", "error", "paywall", "listing"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip() if len(text) > limit else text


def _is_eligible(source: Dict[str, Any]) -> bool:
    """Eligible = enough real body and not user-provided material."""
    if source.get("kind") == "file":
        return False
    if str(source.get("url") or "").startswith("file://"):
        return False
    return len(str(source.get("full_text") or "")) >= _MIN_ELIGIBLE_CHARS


def _excerpt(source: Dict[str, Any]) -> str:
    return str(source.get("full_text") or "")[:_EXCERPT_CHARS]


def _cache_key(url: str, excerpt: str) -> str:
    body_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
    raw = f"{_EVAL_PROMPT_VERSION}|{settings.llm_model}|{url}|{body_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(cache_key: str) -> Dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT eval_json FROM source_eval_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row["eval_json"])
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _cache_put(cache_key: str, url: str, normalized: Dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO source_eval_cache "
            "(cache_key, url, eval_json, created_at) VALUES (?, ?, ?, ?)",
            (cache_key, url, json.dumps(normalized, ensure_ascii=False), _now()),
        )


def _normalize_eval(raw: Dict[str, Any], tier: str) -> Dict[str, Any]:
    """Coerce and clamp a raw judge verdict into the stored ``eval`` shape.

    An unknown ``page_type`` falls back to "content"; a page_type of "error"
    forces ``usable`` false; ``info_density`` is coerced to an int and clamped to
    0-3, and a "low" trust tier caps it at 2 so a weak host cannot buy a high
    density score. Summary and key facts are whitespace-normalized and clipped.
    """
    page_type = str(raw.get("page_type") or "").strip().lower()
    if page_type not in _PAGE_TYPES:
        page_type = "content"

    usable = bool(raw.get("usable"))
    if page_type == "error":
        usable = False

    try:
        density = int(float(raw.get("info_density")))
    except (TypeError, ValueError):
        density = 0
    density = max(0, min(3, density))
    if tier == "low":
        density = min(density, 2)

    key_facts: List[str] = []
    facts_raw = raw.get("key_facts")
    if isinstance(facts_raw, list):
        for item in facts_raw:
            fact = _clip(item, 120)
            if fact:
                key_facts.append(fact)
            if len(key_facts) >= 5:
                break

    return {
        "usable": usable,
        "page_type": page_type,
        "info_density": density,
        "summary": _clip(raw.get("summary"), 200),
        "key_facts": key_facts,
    }


def evaluate_sources(
    sources: List[Dict[str, Any]],
    topic_text: str,
    limit: int | None = None,
) -> Dict[str, Any]:
    """Evaluate sources in place, attaching ``source["eval"]`` per source.

    Eligible sources (enough body, not user-provided) are judged highest-trust
    first so the call budget lands on the most promising candidates. Cache hits
    are free; only real LLM calls count against ``limit`` (default
    ``settings.source_eval_limit``). Returns a stats dict; a no-op ``{"enabled":
    False, ...}`` is returned when evaluation or the LLM is disabled.
    """
    stats: Dict[str, Any] = {
        "enabled": True,
        "eligible": 0,
        "evaluated": 0,
        "cache_hits": 0,
        "llm_calls": 0,
        "gated": 0,
        "errors": 0,
    }
    if not settings.source_eval_enabled or not settings.llm_enabled:
        stats["enabled"] = False
        return stats

    if limit is None:
        limit = settings.source_eval_limit

    eligible = [
        source
        for source in sources
        if isinstance(source, dict) and _is_eligible(source)
    ]
    stats["eligible"] = len(eligible)
    if not eligible:
        return stats

    # Spend budget on promising candidates first; ties keep original order.
    order = sorted(
        range(len(eligible)),
        key=lambda i: (-int(grade_source(eligible[i]).get("score", 0)), i),
    )

    for i in order:
        source = eligible[i]
        url = str(source.get("url") or "")
        excerpt = _excerpt(source)
        cache_key = _cache_key(url, excerpt)

        cached = _cache_get(cache_key)
        if cached is not None:
            source["eval"] = {**cached, "cached": True}
            stats["evaluated"] += 1
            stats["cache_hits"] += 1
            if cached.get("usable") is False:
                stats["gated"] += 1
            continue

        if stats["llm_calls"] >= limit:
            # Budget exhausted: leave the rest unevaluated but keep scanning for
            # more cache hits, which are free.
            continue

        try:
            raw, _usage = evaluate_source_quality(source, topic_text)
        except LLMError:
            stats["errors"] += 1
            if stats["errors"] >= _MAX_ERRORS:
                break
            continue

        stats["llm_calls"] += 1
        normalized = _normalize_eval(raw, grade_source(source)["tier"])
        _cache_put(cache_key, url, normalized)
        source["eval"] = {**normalized, "cached": False}
        stats["evaluated"] += 1
        if normalized["usable"] is False:
            stats["gated"] += 1

    return stats
