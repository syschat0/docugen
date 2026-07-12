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
from app.services.evidence import overlap_score
from app.services.llm import (
    LLMError,
    _eval_rank,
    _section_words,
    _source_words,
    evaluate_source_quality,
    rank_section_relevance,
)
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


# Prompt revision tag baked into the section-fit cache key. Bump it whenever the
# listwise ranking prompt changes so stale verdicts are invalidated.
_SECTION_EVAL_PROMPT_VERSION = "sect-v1"

# Maximum candidates fed into a single listwise ranking prompt. Sources beyond
# the cap stay unranked (neutral) so the prompt stays small for a small model.
_SECTION_EVAL_MAX_CANDIDATES = 8


def _candidate_text(source: Dict[str, Any]) -> str:
    """The one-line text used to describe a candidate in prompt and cache key."""
    evaluation = source.get("eval")
    if isinstance(evaluation, dict) and evaluation.get("summary"):
        return str(evaluation["summary"])
    return str(source.get("summary") or source.get("snippet") or "")


def _section_signature(section: Dict[str, Any]) -> str:
    key_points = "|".join(str(point) for point in (section.get("key_points") or []))
    return "|".join(
        [str(section.get("title") or ""), str(section.get("purpose") or ""), key_points]
    )


def _section_cache_key(
    section: Dict[str, Any], candidates: List[Dict[str, Any]]
) -> str:
    parts = []
    for source in candidates:
        url = str(source.get("url") or "")
        text_hash = hashlib.sha256(_candidate_text(source).encode("utf-8")).hexdigest()
        parts.append(f"{url}#{text_hash}")
    parts.sort()
    raw = "|".join(
        [
            _SECTION_EVAL_PROMPT_VERSION,
            settings.llm_model,
            _section_signature(section),
            "|".join(parts),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_put_section(
    cache_key: str, section: Dict[str, Any], fit_map: Dict[str, Dict[str, Any]]
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO source_eval_cache "
            "(cache_key, url, eval_json, created_at) VALUES (?, ?, ?, ?)",
            (
                cache_key,
                f"section:{section.get('id', '')}",
                json.dumps(fit_map, ensure_ascii=False),
                _now(),
            ),
        )


def _top_candidates(
    section: Dict[str, Any], pool: List[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """Pick the heuristically strongest candidates for the listwise prompt.

    Reuses the P2 ranking signal (keyword overlap, judge density, trust) so the
    single prompt spends its slots on the most promising sources; anything past
    the cap stays unranked and neutral downstream.
    """
    if len(pool) <= limit:
        return list(pool)
    section_words = _section_words(section)

    def key(source: Dict[str, Any]) -> tuple[float, float, int]:
        return (
            overlap_score(section_words, _source_words(source)),
            _eval_rank(source),
            int(grade_source(source)["score"]),
        )

    return sorted(pool, key=key, reverse=True)[:limit]


def _normalize_section_rankings(
    raw_rankings: List[Any], candidates: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Map 1-based ranking ids back to candidate urls with clamped relevance.

    Out-of-range and duplicate ids are ignored (the first occurrence wins),
    relevance is coerced to an int and clamped to 0-3, and reason is clipped.
    Candidates the judge omitted are simply absent, so the caller treats them as
    neutral.
    """
    result: Dict[str, Dict[str, Any]] = {}
    seen_ids: set[int] = set()
    for entry in raw_rankings:
        if not isinstance(entry, dict):
            continue
        try:
            ident = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        if ident in seen_ids or ident < 1 or ident > len(candidates):
            continue
        seen_ids.add(ident)
        url = str(candidates[ident - 1].get("url") or "")
        if not url:
            continue
        try:
            relevance = int(float(entry.get("relevance")))
        except (TypeError, ValueError):
            relevance = 0
        result[url] = {
            "relevance": max(0, min(3, relevance)),
            "reason": _clip(entry.get("reason"), 100),
        }
    return result


def _restore_section_map(
    cached: Dict[str, Any], candidates: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Rebuild a fit map from a cached verdict, keeping only current candidates."""
    urls = {str(source.get("url") or "") for source in candidates}
    result: Dict[str, Dict[str, Any]] = {}
    for url, entry in cached.items():
        if url not in urls or not isinstance(entry, dict):
            continue
        try:
            relevance = int(entry.get("relevance"))
        except (TypeError, ValueError):
            continue
        result[url] = {
            "relevance": max(0, min(3, relevance)),
            "reason": _clip(entry.get("reason"), 100),
        }
    return result


def rank_sources_for_section(
    section: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    allow_llm_call: bool = True,
) -> tuple[Dict[str, Dict[str, Any]] | None, Dict[str, Any]]:
    """Listwise-rank a section's candidate sources by relevance in one LLM call.

    Returns ``(fit_map, stats)`` where ``fit_map`` is ``{url: {"relevance": int,
    "reason": str}}`` for the ranked candidates, or ``None`` when ranking is
    disabled, budget-skipped (``allow_llm_call`` false on a cache miss), or
    failed. ``stats`` always reports what happened. The candidate source dicts
    are never mutated — the same dict is reused across sections, so a per-section
    verdict travels only in the returned map. A raised exception never escapes;
    an ``LLMError`` degrades to ``(None, stats)`` so section writing continues.
    """
    stats: Dict[str, Any] = {
        "called": False,
        "cache_hit": False,
        "ranked": 0,
        "excluded": 0,
        "error": None,
    }
    if not settings.section_eval_enabled or not settings.llm_enabled:
        return None, stats

    pool = [
        source
        for source in candidates
        if isinstance(source, dict) and source.get("url")
    ]
    if not pool:
        return None, stats

    ranked_candidates = _top_candidates(
        section, pool, _SECTION_EVAL_MAX_CANDIDATES
    )
    cache_key = _section_cache_key(section, ranked_candidates)

    cached = _cache_get(cache_key)
    if cached is not None:
        stats["cache_hit"] = True
        fit_map = _restore_section_map(cached, ranked_candidates)
        stats["ranked"] = len(fit_map)
        stats["excluded"] = sum(
            1 for entry in fit_map.values() if entry["relevance"] <= 1
        )
        return fit_map, stats

    if not allow_llm_call:
        return None, stats

    try:
        raw_rankings, _usage = rank_section_relevance(section, ranked_candidates)
    except LLMError as exc:
        stats["error"] = str(exc)
        return None, stats

    stats["called"] = True
    fit_map = _normalize_section_rankings(raw_rankings, ranked_candidates)
    _cache_put_section(cache_key, section, fit_map)
    stats["ranked"] = len(fit_map)
    stats["excluded"] = sum(
        1 for entry in fit_map.values() if entry["relevance"] <= 1
    )
    return fit_map, stats
