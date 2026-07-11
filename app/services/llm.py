import json
import re
import urllib.error
import urllib.request
from collections import Counter
from contextvars import ContextVar
from typing import Any, Dict

from app.core.config import settings
from app.services.llm_settings import get_active_llm_config
from app.schemas.projects import ProjectRead
from app.schemas.questions import UserDecisionRead
from app.services.citations import citation_markers
from app.services.doc_types import DEFAULT_DOC_TYPE, DOC_TYPES, get_doc_type_profile
from app.services.quality import (
    grade_source,
    is_high_stakes_topic,
    issue_section_ids,
    relevant_evidence_passages,
    sentence_quality_stats,
    validate_evidence_ledger,
)
from app.services.search_options import current_search_options


class LLMError(Exception):
    pass


_GENERATION_OPTIONS: ContextVar[Dict[str, Any]] = ContextVar(
    "generation_options", default={}
)


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            language = cleaned[:first_newline].strip().lower()
            if language in {"json", "javascript", "js", "text"}:
                cleaned = cleaned[first_newline + 1 :].strip()
    return cleaned


def _first_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _repair_json_text(text: str) -> str:
    repaired = text.strip()
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = re.sub(r"(?<=[}\]])\s*(?=[{\[])", ",", repaired)
    repaired = re.sub(
        r'(?<=[}"\]\d])\s*\n\s*(?="[^"\n]+"\s*:)',
        ",\n",
        repaired,
    )
    return repaired


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = _strip_json_fence(text)
    balanced = _first_balanced_json_object(cleaned)
    candidates = [cleaned]
    if balanced and balanced != cleaned:
        candidates.append(balanced)

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        for variant in (candidate, _repair_json_text(candidate)):
            try:
                parsed = json.loads(variant)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                return parsed
            raise LLMError("LLM response JSON root was not an object")

    if balanced is None:
        raise LLMError("LLM response did not contain a JSON object")
    if last_error is not None:
        raise LLMError(f"LLM response JSON could not be parsed: {last_error}") from last_error
    raise LLMError("LLM response JSON could not be parsed")


def _request_chat_completion(messages: list[dict[str, str]]) -> dict[str, Any]:
    config = get_active_llm_config()
    generation = _GENERATION_OPTIONS.get()
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": generation.get("temperature", 0.4),
        "max_tokens": generation.get("max_tokens", 6000),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config["base_url"].rstrip("/") + "/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request, timeout=settings.llm_timeout_seconds
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"LLM server returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"LLM server is not reachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMError("LLM request timed out") from exc


def _chat_content(messages: list[dict[str, str]]) -> tuple[str, dict[str, Any] | None]:
    response = _request_chat_completion(messages)
    try:
        return response["choices"][0]["message"]["content"], response.get("usage")
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("LLM response did not match OpenAI chat completions format") from exc


def _strip_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.strip("`").strip()
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            language = cleaned[:first_newline].strip().lower()
            if language in {"markdown", "md", "json", "text"}:
                cleaned = cleaned[first_newline + 1 :].strip()
    return cleaned


def _looks_like_markdown(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    markdown_markers = ("#", "-", "*", ">", "|", "```")
    return (
        stripped.startswith(markdown_markers)
        or "\n#" in stripped
        or "\n\n" in stripped
        or len(stripped) >= 120
    )


def _markdown_outside_json(raw_content: str) -> str | None:
    cleaned = _strip_fence(raw_content)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return cleaned.strip() if _looks_like_markdown(cleaned) else None

    before = cleaned[:start].strip()
    after = cleaned[end + 1 :].strip()
    for candidate in (before, after):
        if _looks_like_markdown(candidate):
            return candidate
    return None


def _markdown_from_parsed_response(
    parsed: Dict[str, Any], raw_content: str, context: str
) -> str:
    candidates = (
        "markdown",
        "markdown_content",
        "section_markdown",
        "draft_markdown",
        "content",
        "body",
        "text",
    )
    for key in candidates:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("section", "draft", "document", "result", "output"):
        value = parsed.get(key)
        if isinstance(value, dict):
            for nested_key in candidates:
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str) and nested_value.strip():
                    return nested_value.strip()

    outside_json = _markdown_outside_json(raw_content)
    if outside_json:
        return outside_json

    available = ", ".join(sorted(str(key) for key in parsed.keys())) or "none"
    preview = _strip_fence(raw_content).replace("\n", " ")[:320]
    raise LLMError(
        f"{context} response missing markdown. Available keys: {available}. "
        f"Response preview: {preview}"
    )


def _summary_from_parsed_response(parsed: Dict[str, Any]) -> Dict[str, Any] | None:
    summary = parsed.get("summary")
    if isinstance(summary, dict):
        return summary

    summary_keys = {
        "section_id",
        "summary",
        "claims",
        "terms",
        "open_threads",
        "next_section_handoff",
        "memory",
        "evidence",
    }
    if summary_keys.intersection(parsed.keys()):
        return {
            "section_id": parsed.get("section_id", ""),
            "summary": parsed.get("summary", ""),
            "claims": parsed.get("claims", []),
            "terms": parsed.get("terms", []),
            "open_threads": parsed.get("open_threads", []),
            "next_section_handoff": parsed.get("next_section_handoff", ""),
            "memory": parsed.get("memory", {}),
            "evidence": parsed.get("evidence", []),
        }

    for key in ("section", "draft", "document", "result", "output"):
        value = parsed.get(key)
        if isinstance(value, dict):
            nested = value.get("summary")
            if isinstance(nested, dict):
                return nested

    return None


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _clip_summary(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    summary = summary or {}
    return {
        "section_id": summary.get("section_id", ""),
        "summary": _clip(summary.get("summary"), 200),
        "claims": [_clip(claim, 80) for claim in (summary.get("claims") or [])[:5]],
        "terms": [_clip(term, 40) for term in (summary.get("terms") or [])[:8]],
        "open_threads": [
            _clip(thread, 80) for thread in (summary.get("open_threads") or [])[:3]
        ],
        "next_section_handoff": _clip(summary.get("next_section_handoff"), 150),
        "memory": _clip_memory(summary.get("memory")),
    }


def _clip_memory(memory: Any) -> Dict[str, Any]:
    if not isinstance(memory, dict):
        return {}
    clipped: Dict[str, Any] = {}
    for key, value in list(memory.items())[:6]:
        clean_key = str(key).strip()[:50]
        if not clean_key:
            continue
        if isinstance(value, list):
            clipped[clean_key] = [_clip(item, 100) for item in value[:4]]
        else:
            clipped[clean_key] = _clip(value, 180)
    return clipped


def _normalize_memory(memory: Any, profile: Dict[str, Any]) -> Dict[str, Any]:
    schema = profile.get("memory_schema") or {}
    source = memory if isinstance(memory, dict) else {}
    return {
        str(key): _clip_memory({str(key): source.get(key, [])}).get(str(key), [])
        for key in schema
    }


def _tokenize(text: str) -> set[str]:
    return {word for word in str(text or "").lower().split() if len(word) >= 2}


def _section_words(section: Dict[str, Any]) -> set[str]:
    return _tokenize(
        " ".join(
            [str(section.get("title", "")), str(section.get("purpose", ""))]
            + [str(point) for point in (section.get("key_points") or [])]
        )
    )


def _source_words(source: Dict[str, Any]) -> set[str]:
    return _tokenize(
        " ".join(str(source.get(key, "")) for key in ("title", "snippet", "summary"))
    )


def select_relevant_sources(
    section: Dict[str, Any],
    sources: list[Dict[str, Any]],
    limit: int = 2,
) -> list[Dict[str, Any]]:
    """Pick the sources with the largest keyword overlap with the section."""
    usable = [source for source in sources if isinstance(source, dict) and source.get("url")]
    if len(usable) <= limit:
        return usable

    section_words = _section_words(section)

    def score(source: Dict[str, Any]) -> tuple[int, int]:
        return (
            len(section_words & _source_words(source)),
            int(grade_source(source)["score"]),
        )

    ranked = sorted(usable, key=score, reverse=True)
    return ranked[:limit]


def select_section_sources(
    section: Dict[str, Any],
    chapter_candidates: list[Dict[str, Any]],
    global_candidates: list[Dict[str, Any]],
    limit: int = 2,
    project_text: str = "",
) -> list[Dict[str, Any]]:
    """Pick section sources, preferring the section's own chapter research.

    Chapter research was queried for this chapter specifically, so any
    chapter source with keyword overlap outranks the global pool; global
    sources only fill the remaining slots. Without a relevant chapter
    source this degrades to ranking the combined pool.
    """
    section_words = _section_words(section)

    def usable(sources: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        return [s for s in sources if isinstance(s, dict) and s.get("url")]

    def overlap(source: Dict[str, Any]) -> int:
        return len(section_words & _source_words(source))

    def score(source: Dict[str, Any]) -> tuple[int, int]:
        return overlap(source), int(grade_source(source)["score"])

    chapter_ranked = sorted(usable(chapter_candidates), key=score, reverse=True)
    global_usable = usable(global_candidates)
    picked: list[Dict[str, Any]] = []
    topic_text = " ".join(
        [project_text, str(section.get("title") or ""), str(section.get("purpose") or "")]
        + [str(point) for point in (section.get("key_points") or [])]
    )
    if is_high_stakes_topic(topic_text):
        # On high-stakes topics, relevant government or academic evidence must
        # not be crowded out merely because a weaker result came from the
        # chapter-specific query.
        strong_relevant = sorted(
            (
                source
                for source in chapter_ranked + global_usable
                if overlap(source) > 0
                and grade_source(source)["tier"] in {"authoritative", "institutional"}
            ),
            key=score,
            reverse=True,
        )
        strong_seen: set[str] = set()
        for source in strong_relevant:
            if source["url"] in strong_seen:
                continue
            strong_seen.add(source["url"])
            picked.append(source)
            if len(picked) >= limit:
                return picked

    picked.extend(
        source
        for source in chapter_ranked
        if overlap(source) > 0 and source["url"] not in {item["url"] for item in picked}
    )
    picked = picked[:limit]
    seen = {source["url"] for source in picked}
    if len(picked) < limit:
        rest = sorted(
            (
                source
                for source in global_usable + chapter_ranked
                if source["url"] not in seen
            ),
            key=score,
            reverse=True,
        )
        for source in rest:
            if source["url"] in seen:
                continue
            seen.add(source["url"])
            picked.append(source)
            if len(picked) >= limit:
                break
    return picked


def best_overlap_score(section: Dict[str, Any], sources: list[Dict[str, Any]]) -> int:
    """Largest keyword overlap between the section and any of its sources."""
    section_words = _section_words(section)
    return max(
        (
            len(section_words & _source_words(source))
            for source in sources
            if isinstance(source, dict) and source.get("url")
        ),
        default=0,
    )


def _source_context(
    sources: list[Dict[str, Any]],
    section: Dict[str, Any] | None = None,
) -> str:
    lines = []
    for index, source in enumerate(sources, start=1):
        grade = grade_source(source)
        lines.append(
            f"[{index}][trust={grade['tier']}] "
            f"{_clip(source.get('title'), 80)} - {source.get('url', '')}"
        )
        passages = relevant_evidence_passages(section or {}, source)
        for passage in passages:
            lines.append(f"    [{index}.{passage['passage_id']}] {passage['text']}")
    return "\n".join(lines) or "- No sources available."


def _decision_lines(decisions: list[UserDecisionRead]) -> str:
    return "\n".join(
        f"- {decision.question}: {decision.answer}" for decision in decisions
    ) or "- No user answers recorded."


def _source_lines(research: Dict[str, Any] | None) -> str:
    if not research:
        return "- No search sources available."
    results = research.get("results") or []
    if not isinstance(results, list) or not results:
        error = research.get("error")
        if error:
            return f"- Search attempted but failed: {error}"
        return "- No search sources available."
    lines = []
    for index, result in enumerate(results, start=1):
        if not isinstance(result, dict):
            continue
        title = result.get("title") or "Untitled"
        url = result.get("url") or ""
        snippet = result.get("snippet") or ""
        lines.append(f"[{index}] {title} - {url} - {snippet}")
    return "\n".join(lines) or "- No search sources available."


def _json_chat(system_prompt: str, user_prompt: str) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    strict_system_prompt = f"""{system_prompt}

JSON output contract:
- Return exactly one JSON object and nothing else.
- Use double quotes for every key and string value.
- Do not use markdown fences.
- Do not add comments.
- Do not use trailing commas.
- Put a comma between every object field and every array item.
- Escape newlines inside string values as \\n.
- If unsure, use shorter arrays instead of producing invalid JSON.
"""
    content, usage = _chat_content(
        [
            {"role": "system", "content": strict_system_prompt},
            {
                "role": "user",
                "content": (
                    f"{user_prompt.strip()}\n\n"
                    "Remember: respond with one valid JSON object only. No prose, no markdown."
                ),
            },
        ]
    )
    try:
        return _extract_json_object(content), usage
    except LLMError as exc:
        repair_content, repair_usage = _chat_content(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a strict JSON repair tool. Return exactly one valid JSON object. "
                        "Do not add explanations, markdown, comments, or extra keys."
                    ),
                },
                {
                    "role": "user",
                    "content": f"""
The previous response was invalid JSON.

Parser error:
{exc}

Repair the response below into valid JSON while preserving its intended data.
Use double quotes, insert missing commas, remove trailing commas, and escape
invalid string characters. Return only the repaired JSON object.

Invalid response:
{content}
""".strip(),
                },
            ]
        )
        repaired = _extract_json_object(repair_content)
        if usage or repair_usage:
            return repaired, {"initial": usage, "repair": repair_usage}
        return repaired, None


def _generation_options(
    profile: Dict[str, Any] | None, stage: str
) -> Dict[str, Any]:
    profile = profile or get_doc_type_profile(None)
    raw = (profile.get("generation_params") or {}).get(stage) or {}
    try:
        temperature = min(max(float(raw.get("temperature", 0.4)), 0.0), 1.5)
    except (TypeError, ValueError):
        temperature = 0.4
    try:
        max_tokens = min(max(int(raw.get("max_tokens", 6000)), 256), 12000)
    except (TypeError, ValueError):
        max_tokens = 6000
    return {"temperature": temperature, "max_tokens": max_tokens}


def _stage_json_chat(
    profile: Dict[str, Any] | None,
    stage: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    token = _GENERATION_OPTIONS.set(_generation_options(profile, stage))
    try:
        return _json_chat(system_prompt, user_prompt)
    finally:
        _GENERATION_OPTIONS.reset(token)


def _stage_chat_content(
    profile: Dict[str, Any] | None,
    stage: str,
    messages: list[dict[str, str]],
) -> tuple[str, dict[str, Any] | None]:
    token = _GENERATION_OPTIONS.set(_generation_options(profile, stage))
    try:
        return _chat_content(messages)
    finally:
        _GENERATION_OPTIONS.reset(token)


def _type_block(profile: Dict[str, Any] | None, guidance_key: str) -> str:
    """Genre conventions block injected into a stage prompt ('' when absent)."""
    profile = profile or get_doc_type_profile(None)
    guidance = str(profile.get(guidance_key) or "").strip()
    if not guidance:
        return ""
    return (
        f"\nDocument type: {profile.get('label_en', 'Report')}\n"
        f"Type conventions:\n{guidance}\n"
    )


def _intake_priority_block(profile: Dict[str, Any] | None) -> str:
    """Compact, genre-specific checklist for deciding what is truly missing."""
    profile = profile or get_doc_type_profile(None)
    priorities = [
        str(item).strip()
        for item in (profile.get("intake_priorities") or [])
        if str(item).strip()
    ][:5]
    if not priorities:
        return ""
    checklist = "\n".join(
        f"{index}. {item}" for index, item in enumerate(priorities, start=1)
    )
    return (
        "\nDocument-type intake priorities (ordered):\n"
        f"{checklist}\n"
        "Use this only as a missing-information checklist. Infer answers from the "
        "request and known answers; do not ask every item mechanically.\n"
    )


def _memory_schema_block(profile: Dict[str, Any] | None) -> str:
    """Explain the small genre-specific state object required in handoffs."""
    profile = profile or get_doc_type_profile(None)
    schema = profile.get("memory_schema") or {}
    if not schema:
        return ""
    fields = "\n".join(f'- "{key}": {description}' for key, description in schema.items())
    shape = {str(key): [] for key in schema}
    return (
        "\nGenre memory fields for summary.memory:\n"
        f"{fields}\n"
        "Keep each field compact (a short string or up to 4 short items). "
        "Record only state future sections must remember.\n"
        f"Use exactly these memory keys: {json.dumps(shape, ensure_ascii=False)}\n"
    )


def classify_document_type(
    project: ProjectRead,
) -> tuple[str, dict[str, Any] | None]:
    """Pick the document type key that best matches the writing request."""
    choices = "\n".join(
        f"- {key}: {profile['classify_hint']}" for key, profile in DOC_TYPES.items()
    )
    parsed, usage = _json_chat(
        "You classify a writing request into one document type. Return only valid JSON.",
        f"""
Project title:
{project.title}

Initial request:
{project.initial_request}

Document types:
{choices}

Pick the single best matching type key for this request. When nothing fits
well, use "{DEFAULT_DOC_TYPE}".

Return this JSON shape:
{{
  "document_type": ""
}}
""",
    )
    key = str(parsed.get("document_type", "")).strip()
    return (key if key in DOC_TYPES else DEFAULT_DOC_TYPE), usage


def plan_user_questions(
    project: ProjectRead,
    decisions: list[UserDecisionRead],
    profile: Dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    decision_lines = "\n".join(
        f"- {decision.question}: {decision.answer}" for decision in decisions
    ) or "- No user answers recorded yet."
    system_prompt = (
        "You are an intake agent for a document writing workflow. "
        "Ask only questions that would materially improve the document. "
        "Always write questions in the same language as the user's request. "
        "Return only one valid JSON object. Do not wrap the response in markdown."
    )
    user_prompt = f"""
Project title:
{project.title}

Initial request:
{project.initial_request}
{_type_block(profile, "brief_guidance")}
{_intake_priority_block(profile)}
Known user answers:
{decision_lines}

Decide whether more user input is needed before writing.
Ask at most 5 questions. Do not ask questions already answered above.
Prefer the highest-priority unresolved item from the document-type checklist
over generic questions. Combine closely related missing items when one concise
question can resolve them.
Write every "question" and "reason" value in the SAME LANGUAGE as the initial
request above (a Korean request gets Korean questions), regardless of the
language of these instructions.
If the request is already clear enough for a useful first draft, return no questions.

Return this exact JSON shape:
{{
  "needs_questions": true,
  "questions": [
    {{
      "phase": "intake",
      "question": "",
      "reason": "",
      "priority": "high"
    }}
  ]
}}
"""
    parsed, usage = _stage_json_chat(profile, "intake", system_prompt, user_prompt)
    if not parsed.get("needs_questions"):
        return [], usage

    raw_questions = parsed.get("questions")
    if not isinstance(raw_questions, list):
        raise LLMError("LLM question plan missing list field: questions")

    questions: list[dict[str, Any]] = []
    for item in raw_questions[:5]:
        if not isinstance(item, dict):
            continue
        text = item.get("question")
        if not isinstance(text, str) or not text.strip():
            continue
        questions.append(
            {
                "phase": str(item.get("phase") or "intake"),
                "question": text.strip(),
                "reason": str(item.get("reason") or ""),
                "priority": str(item.get("priority") or "medium"),
            }
        )
    return questions, usage


def _query_language_instruction(*, multi: bool, subject: str) -> str:
    """Prompt line pinning the search-query language to SEARCH_QUERY_LANGUAGE."""
    mode = current_search_options().query_language
    noun = "queries" if multi else "query"
    if mode == "english":
        return (
            f"Write the {noun} in English, translating key terms if {subject} is "
            "in another language."
        )
    if mode == "both":
        if multi:
            return (
                "Write about half of the queries in the same language as the "
                "request and the rest in English, so the results span both languages."
            )
        return (
            f"Write the query in whichever language — that of {subject}, or "
            "English — will surface the most useful sources for this topic."
        )
    return f"Write the {noun} in the same language as {subject}."


def plan_search_queries(
    project: ProjectRead, decisions: list[UserDecisionRead]
) -> tuple[list[str], dict[str, Any] | None]:
    language_instruction = _query_language_instruction(multi=True, subject="the request")
    parsed, usage = _json_chat(
        "You create short web search queries for document research. Return only valid JSON.",
        f"""
Project title:
{project.title}

Initial request:
{project.initial_request}

User answers and decisions:
{_decision_lines(decisions)}

Create 2 to 4 short web search queries (3 to 8 words each) that would find
useful reference sources for this document. {language_instruction} Extract key
search terms; do not copy full sentences or question text from the request.

Return this exact JSON shape:
{{
  "queries": ["", ""]
}}
""",
    )
    raw_queries = parsed.get("queries")
    if not isinstance(raw_queries, list):
        raise LLMError("LLM search plan missing list field: queries")

    queries: list[str] = []
    for item in raw_queries:
        if not isinstance(item, str):
            continue
        query = " ".join(item.split())[:100].strip()
        if query and query not in queries:
            queries.append(query)
    if not queries:
        raise LLMError("LLM search plan contained no usable queries")
    return queries[:4], usage


def plan_chapter_query(
    project: ProjectRead, chapter: Dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """One tiny call per chapter: a failed query only loses that chapter."""
    chapter_title = str(chapter.get("title", ""))
    language_instruction = _query_language_instruction(
        multi=False, subject="the chapter title"
    )
    parsed, usage = _json_chat(
        "You create one short web search query for document research. Return only valid JSON.",
        f"""
Project topic:
{project.title}

Chapter title:
{chapter_title}

Create one short web search query (2 to 6 keywords) that would find useful
reference material for this chapter. {language_instruction} Use searchable
keywords, not a full sentence; do not copy the chapter title verbatim if it
reads like a sentence.

Return this JSON shape:
{{
  "query": ""
}}
""",
    )
    query = " ".join(str(parsed.get("query", "")).split())[:100].strip()
    if not query:
        raise LLMError("LLM chapter query response missing query")
    return query, usage


def plan_section_query(
    section: Dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """One tiny query for a single leaf section (top-up research)."""
    title = str(section.get("title", ""))
    key_points = [
        str(point).strip()
        for point in (section.get("key_points") or [])
        if str(point).strip()
    ]
    language_instruction = _query_language_instruction(
        multi=False, subject="the section title"
    )
    key_point_lines = "\n".join(f"- {point}" for point in key_points) or "(none)"
    parsed, usage = _json_chat(
        "You create one short web search query for document research. Return only valid JSON.",
        f"""
Section title:
{title}

Key points:
{key_point_lines}

Create one short web search query (2 to 6 keywords) that would find useful
reference material for this section. {language_instruction} Use searchable
keywords, not a full sentence.

Return this JSON shape:
{{
  "query": ""
}}
""",
    )
    query = " ".join(str(parsed.get("query", "")).split())[:100].strip()
    if not query:
        raise LLMError("LLM section query response missing query")
    return query, usage


def derive_style_card(
    project: ProjectRead, samples: list[Any]
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    """Distill user-provided writing samples into a reusable style card.

    The card captures how the samples sound (register, voice, rhythm,
    vocabulary) plus a few verbatim exemplar sentences, and is injected into
    every section-writing prompt so the document mimics the samples.
    """
    excerpts = []
    for sample in samples[:3]:
        title = str(getattr(sample, "title", "") or getattr(sample, "source", "sample"))
        text = str(getattr(sample, "content_text", "") or "")[:1500]
        excerpts.append(f"--- Sample: {title} ---\n{text}")
    samples_block = "\n\n".join(excerpts)

    parsed, usage = _json_chat(
        "You analyze writing samples and produce a compact style card that lets "
        "another writer imitate them faithfully. Return only valid JSON.",
        f"""
Writing samples provided by the user:

{samples_block}

Describe, in the same language as the samples, exactly how these samples are
written. Quote 2-4 short verbatim sentences from the samples as exemplars.
For Korean samples name the sentence register explicitly (e.g. "-이다/한다체",
"-습니다체", "-이에요/해요체").

Return this JSON shape:
{{
  "register": "",
  "voice": "",
  "person": "",
  "tense": "",
  "sentence_rhythm": "",
  "vocabulary": "",
  "devices": [],
  "avoid": [],
  "exemplars": []
}}
""",
    )
    if not str(parsed.get("register") or "").strip() and not str(
        parsed.get("voice") or ""
    ).strip():
        raise LLMError("Style card response missing register and voice")
    return {
        "register": _clip(parsed.get("register"), 120),
        "voice": _clip(parsed.get("voice"), 200),
        "person": _clip(parsed.get("person"), 80),
        "tense": _clip(parsed.get("tense"), 80),
        "sentence_rhythm": _clip(parsed.get("sentence_rhythm"), 200),
        "vocabulary": _clip(parsed.get("vocabulary"), 200),
        "devices": [_clip(item, 80) for item in (parsed.get("devices") or [])[:6]],
        "avoid": [_clip(item, 80) for item in (parsed.get("avoid") or [])[:6]],
        "exemplars": [
            _clip(item, 200) for item in (parsed.get("exemplars") or [])[:4]
        ],
    }, usage


def _style_card_block(style_card: Dict[str, Any] | None) -> str:
    if not style_card:
        return ""
    card = {
        key: style_card.get(key)
        for key in (
            "register",
            "voice",
            "person",
            "tense",
            "sentence_rhythm",
            "vocabulary",
            "devices",
            "avoid",
        )
        if style_card.get(key)
    }
    if not card:
        return ""
    block = f"""

Voice & style card, distilled from the user's own writing samples
(authoritative for how this document must sound):
{json.dumps(card, ensure_ascii=False)}"""
    exemplars = [
        str(item).strip()
        for item in (style_card.get("exemplars") or [])[:4]
        if str(item).strip()
    ]
    if exemplars:
        exemplar_lines = "\n".join(f"- {item}" for item in exemplars)
        block += f"""
Example sentences in the target style (imitate their sound, not their content):
{exemplar_lines}"""
    return block


def generate_brief(
    project: ProjectRead,
    decisions: list[UserDecisionRead],
    research: Dict[str, Any] | None,
    profile: Dict[str, Any] | None = None,
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    profile = profile or get_doc_type_profile(None)
    parsed, usage = _stage_json_chat(
        profile,
        "brief",
        "You create compact document briefs. Return only valid JSON.",
        f"""
Project title:
{project.title}

Initial request:
{project.initial_request}
{_type_block(profile, "brief_guidance")}
User answers and decisions:
{_decision_lines(decisions)}

Search sources:
{_source_lines(research)}

"style" is the exact sentence register every section must use, written in the
document's language. For Korean documents choose one register explicitly,
for example "-이다/한다체 (격식 있는 문어체)" or "-입니다체 (정중한 설명체)".
Default register for this document type: {profile.get("style_hint", "")}.
Use it unless the request or answers imply another.

Set "target_length_chars" to the total body length in characters ONLY when the
request or answers state one (e.g. "3000자" -> 3000, "A4 2장" -> about 3600).
Use null when no length was specified. Never invent a length.

Write every string value in the SAME LANGUAGE as the initial request above
(a Korean request gets a Korean brief), regardless of the language of these
instructions. Keep the JSON keys in English exactly as shown.

Return this JSON shape:
{{
  "topic": "",
  "goal": "",
  "audience": "",
  "tone": "",
  "style": "",
  "format": "markdown document",
  "target_length_chars": null,
  "must_include": [],
  "must_avoid": [],
  "source_notes": [],
  "success_criteria": []
}}
""",
    )
    return parsed, usage


def _length_block(doc_target: int | None) -> str:
    if not doc_target:
        return ""
    return (
        f"\nDocument length budget: about {doc_target} characters of body text "
        "in total. Size the structure to fit it - fewer, larger parts for a "
        "short document; do not pad a short budget with many small parts.\n"
    )


def generate_outline(
    project: ProjectRead,
    brief: Dict[str, Any],
    profile: Dict[str, Any] | None = None,
    doc_target: int | None = None,
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    profile = profile or get_doc_type_profile(None)
    parsed, usage = _stage_json_chat(
        profile,
        "outline",
        "You create concise document outlines. Return only valid JSON.",
        f"""
Project title:
{project.title}

Brief JSON:
{json.dumps(brief, ensure_ascii=False)}
{_type_block(profile, "outline_guidance")}{_length_block(doc_target)}
Create a high-level outline. Write every title and purpose in the
SAME LANGUAGE as the brief's topic and goal (a Korean brief gets Korean
chapter titles), regardless of the language of these instructions.

Return this JSON shape:
{{
  "chapters": [
    {{
      "id": "1",
      "title": "",
      "purpose": "",
      "expected_sections": []
    }}
  ]
}}
""",
    )
    if not isinstance(parsed.get("chapters"), list):
        raise LLMError("Outline response missing chapters list")
    return parsed, usage


def review_outline(
    project: ProjectRead, brief: Dict[str, Any], outline: Dict[str, Any]
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    return _stage_json_chat(
        profile,
        "review",
        "You review document outlines for gaps, duplication, and flow, and fix them when needed. Return only valid JSON.",
        f"""
Project title:
{project.title}

Brief JSON:
{json.dumps(brief, ensure_ascii=False)}

Outline JSON:
{json.dumps(outline, ensure_ascii=False)}

If the outline is already good, set verdict to "pass" and revised_outline to null.
If it has substantive problems (missing topics, duplicated chapters, wrong order),
set verdict to "revise", list the issues, and put the corrected complete outline
in revised_outline using the same chapters shape as the input.

Return this JSON shape:
{{
  "verdict": "pass",
  "issues": [],
  "recommended_changes": [],
  "notes": "",
  "revised_outline": null
}}
""",
    )


def _brief_context(brief: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "topic": brief.get("topic"),
        "goal": brief.get("goal"),
        "audience": brief.get("audience"),
        "tone": brief.get("tone"),
        "must_include": brief.get("must_include", [])[:5]
        if isinstance(brief.get("must_include"), list)
        else [],
    }


def collect_leaf_titles(nodes: list[Dict[str, Any]]) -> list[str]:
    titles: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        children = node.get("children")
        if isinstance(children, list) and children:
            titles.extend(collect_leaf_titles(children))
        else:
            title = str(node.get("title") or "").strip()
            if title:
                titles.append(title)
    return titles


def tree_skeleton(nodes: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    skeleton: list[Dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        entry: Dict[str, Any] = {
            "id": node.get("id"),
            "title": node.get("title"),
        }
        children = node.get("children")
        if isinstance(children, list) and children:
            entry["children"] = tree_skeleton(children)
        skeleton.append(entry)
    return skeleton


def expand_chapter_subtree(
    project: ProjectRead,
    brief: Dict[str, Any],
    chapter: Dict[str, Any],
    existing_leaf_titles: list[str],
    feedback: Dict[str, Any] | None = None,
    profile: Dict[str, Any] | None = None,
    doc_target: int | None = None,
) -> tuple[list[Dict[str, Any]], dict[str, Any] | None]:
    chapter_id = str(chapter.get("id") or "1")
    chapter_title = str(chapter.get("title") or f"Chapter {chapter_id}")
    covered = "\n".join(f"- {title}" for title in existing_leaf_titles[-40:]) or "- (none yet)"
    feedback_block = ""
    if feedback:
        feedback_block = f"""
Reviewer feedback to address in this expansion:
{json.dumps(feedback, ensure_ascii=False)}
"""
    parsed, usage = _stage_json_chat(
        profile,
        "section_plan",
        "You expand one outline chapter into a compact hierarchical writing subtree. Return only valid JSON.",
        f"""
Project title:
{project.title}

Brief summary JSON:
{json.dumps(_brief_context(brief), ensure_ascii=False)}
{_type_block(profile, "outline_guidance")}{_length_block(doc_target)}
Current chapter JSON:
{json.dumps(chapter, ensure_ascii=False)}

Sections already planned in other chapters (do NOT repeat these topics):
{covered}
{feedback_block}
Expand only this chapter into subtopics. If a subtopic is still broad, give it
children. Stop when leaf nodes are narrow enough to write in one focused call.
Do not include sibling chapters. Do not include the final article text.
Write every title, purpose, and key point in the SAME LANGUAGE as the chapter
title above, regardless of the language of these instructions.

Return this JSON shape:
{{
  "children": [
    {{
      "id": "{chapter_id}.1",
      "title": "",
      "purpose": "",
      "key_points": [],
      "target_length": 500,
      "children": []
    }}
  ]
}}
""",
    )
    children = parsed.get("children")
    if not isinstance(children, list) or not children:
        expected = chapter.get("expected_sections")
        fallback_titles = expected if isinstance(expected, list) and expected else [chapter_title]
        children = [
            {
                "id": f"{chapter_id}.{index}",
                "title": str(title),
                "purpose": str(chapter.get("purpose", "")),
                "key_points": [str(title)],
                "target_length": 500,
                "children": [],
            }
            for index, title in enumerate(fallback_titles, start=1)
        ]
    return children, usage


def generate_section_plan(
    project: ProjectRead,
    brief: Dict[str, Any],
    outline: Dict[str, Any],
    research: Dict[str, Any] | None,
    profile: Dict[str, Any] | None = None,
    doc_target: int | None = None,
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    chapters = outline.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise LLMError("Section plan input missing outline chapters")
    # Each chapter sees its share of the document budget so leaf counts and
    # target lengths come out proportionate.
    chapter_target = (
        max(int(doc_target / max(len(chapters), 1)), 300) if doc_target else None
    )

    outline_tree: list[Dict[str, Any]] = []
    usage_items: list[dict[str, Any]] = []
    planned_leaf_titles: list[str] = []

    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        chapter_id = str(chapter.get("id") or len(outline_tree) + 1)
        chapter_title = str(chapter.get("title") or f"Chapter {chapter_id}")
        children, usage = expand_chapter_subtree(
            project, brief, chapter, planned_leaf_titles, profile=profile,
            doc_target=chapter_target,
        )
        planned_leaf_titles.extend(collect_leaf_titles(children))
        outline_tree.append(
            {
                "id": chapter_id,
                "title": chapter_title,
                "purpose": str(chapter.get("purpose", "")),
                "key_points": [],
                "children": children,
            }
        )
        if usage is not None:
            usage_items.append({"chapter_id": chapter_id, **usage})

    if not outline_tree:
        raise LLMError("Section plan response missing outline tree")
    return {"outline_tree": outline_tree}, {"chapter_calls": usage_items} if usage_items else None


def review_section_plan(
    project: ProjectRead,
    brief: Dict[str, Any],
    section_plan: Dict[str, Any],
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    skeleton = tree_skeleton(section_plan.get("outline_tree") or [])
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    return _stage_json_chat(
        profile,
        "review",
        "You review hierarchical section plans for depth, overlap, missing sections, and sequencing. Return only valid JSON.",
        f"""
Project title:
{project.title}

Brief summary JSON:
{json.dumps(_brief_context(brief), ensure_ascii=False)}

Section plan tree (ids and titles only):
{json.dumps(skeleton, ensure_ascii=False)}

Check for: duplicated or overlapping topics across chapters, missing topics
required by the brief, chapters that are too shallow, and wrong ordering.
List duplicated topics explicitly in issues. Put ids of chapters that need
re-expansion in nodes_to_expand (top-level chapter ids like "2").

Return this JSON shape:
{{
  "verdict": "pass",
  "issues": [],
  "recommended_changes": [],
  "needs_more_depth": false,
  "nodes_to_expand": [],
  "notes": ""
}}
""",
    )


def write_section(
    project: ProjectRead,
    brief: Dict[str, Any],
    outline: Dict[str, Any],
    section: Dict[str, Any],
    previous_summary: Dict[str, Any] | None,
    research: Dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    content, usage = _stage_chat_content(
        profile,
        "section_writing",
        [
            {
                "role": "system",
                "content": "You write one document section at a time. Prefer valid JSON, but the section body must be usable Markdown.",
            },
            {
                "role": "user",
                "content": f"""
Project title:
{project.title}

Brief JSON:
{json.dumps(brief, ensure_ascii=False)}

Outline JSON:
{json.dumps(outline, ensure_ascii=False)}

Current section JSON:
{json.dumps(section, ensure_ascii=False)}

Previous section summary JSON:
{json.dumps(previous_summary or {}, ensure_ascii=False)}

Search sources:
{_source_lines(research)}

Write only this section in Markdown. Use the same language as the user's request
unless the brief says otherwise. Use relevant search sources when they help,
and cite them inline as [1], [2], etc. Avoid repeating previous content. Return either:
{{
  "markdown": "## Section title\\n\\nSection body..."
}}

or plain Markdown.
If returning JSON, use the exact key name "markdown" for the section body.
""".strip(),
            },
        ]
    )
    try:
        parsed = _extract_json_object(content)
    except LLMError:
        markdown = _strip_fence(content)
    else:
        markdown = _markdown_from_parsed_response(parsed, content, "Section writer")
    if not isinstance(markdown, str) or not markdown.strip():
        raise LLMError("Section writer response missing markdown")
    return markdown, usage


def write_section_with_summary(
    project: ProjectRead,
    brief: Dict[str, Any],
    section: Dict[str, Any],
    previous_summary: Dict[str, Any] | None,
    sources: list[Dict[str, Any]],
    section_titles: list[str],
    feedback: list[str] | None = None,
    chapter_digests: list[Dict[str, Any]] | None = None,
    glossary: list[str] | None = None,
    profile: Dict[str, Any] | None = None,
    style_card: Dict[str, Any] | None = None,
) -> tuple[str, Dict[str, Any], dict[str, Any] | None]:
    profile = profile or get_doc_type_profile(None)
    style = str(brief.get("style") or brief.get("tone") or "match the initial request")
    target_length = section.get("target_length") or profile.get(
        "default_section_length", 500
    )
    depth = section.get("depth") or 3
    titles_block = "\n".join(f"- {title}" for title in section_titles) or "- (none)"
    digest_block = ""
    if chapter_digests:
        digest_lines = json.dumps(
            [
                {
                    "chapter_id": str(digest.get("chapter_id", "")),
                    "title": _clip(digest.get("title"), 80),
                    "digest": _clip(digest.get("digest"), 300),
                    "memory": _clip_memory(digest.get("memory")),
                }
                for digest in chapter_digests[-6:]
            ],
            ensure_ascii=False,
        )
        digest_block = f"""

What earlier chapters already established (do not re-explain):
{digest_lines}"""
    glossary_block = ""
    if glossary:
        glossary_block = f"""

Established terminology (keep using these exact terms):
{", ".join(_clip(term, 40) for term in glossary[:15])}"""
    feedback_block = ""
    if feedback:
        feedback_lines = "\n".join(f"- {_clip(comment, 400)}" for comment in feedback[:8])
        feedback_block = f"""

User improvement requests for this section (must be reflected):
{feedback_lines}"""
    diagram_rule = ""
    if settings.diagrams_enabled:
        diagram_rule = (
            "\n- If a process, structure, or comparison is much clearer as a diagram, "
            'you may add ONE ```mermaid code block (flowchart TD or sequenceDiagram). '
            "Keep node labels short, wrap labels containing special characters in "
            'double quotes, and never put citation markers inside the diagram.'
        )
    section_title = str(section.get("title", ""))
    heading_title = (
        f"{section.get('id', '')} {section_title}".strip()
        if profile.get("numbered_headings", True)
        else section_title
    )
    if profile.get("citations_enabled", True):
        high_stakes_rule = ""
        if is_high_stakes_topic(f"{project.title} {section_title} {section.get('purpose', '')}"):
            high_stakes_rule = (
                "\n- This is a high-stakes topic. Prefer relevant sources labeled "
                "trust=authoritative or trust=institutional. Treat trust=general, "
                "trust=low, and trust=unknown as background only; qualify or omit "
                "claims that lack stronger support."
            )
        citation_rule = (
            "- When a source above supports a statement, cite it inline as [1] or [2] "
            "matching the source numbers. Do not cite sources that are not listed.\n"
            "- For every factual claim carrying a citation, add an evidence ledger entry. "
            "The evidence value must be a verbatim continuous excerpt from the chosen "
            "passage, and passage_id must match labels such as P1 or P2."
            f"{high_stakes_rule}"
        )
    else:
        citation_rule = (
            "- Use the sources only as background knowledge. Do NOT insert citation "
            "markers such as [1] or a source list; this document type has no citations."
        )
    content, usage = _stage_chat_content(
        profile,
        "section_writing",
        [
            {
                "role": "system",
                "content": (
                    "You write one document section and provide a compact handoff "
                    f"summary for the next section. Writing style/register: {style}. "
                    "Return valid JSON when possible."
                ),
            },
            {
                "role": "user",
                "content": f"""
Project title:
{project.title}

Brief summary JSON:
{json.dumps(_brief_context(brief), ensure_ascii=False)}

Other planned document content (do NOT cover these topics here):
{titles_block}

Current section JSON:
{json.dumps(section, ensure_ascii=False)}

Previous section summary JSON:
{json.dumps(_clip_summary(previous_summary), ensure_ascii=False)}{digest_block}{glossary_block}{_style_card_block(style_card)}

Relevant sources:
{_source_context(sources, section)}{feedback_block}

Write only this section in Markdown, in the same language as the brief topic.
{_type_block(profile, "section_guidance")}{_memory_schema_block(profile)}Rules:
- Sentence register: {style}. Every sentence must use this register consistently.
- Aim for roughly {target_length} characters of body text.
- Start with exactly one heading: "{'#' * min(max(int(depth) if str(depth).isdigit() else 3, 2), 6)} {heading_title}".
- Do NOT add sub-headings inside this section. Use bold lead-ins or lists instead.
- Do not repeat content from the previous summary or topics owned by other sections.
{citation_rule}{diagram_rule}

Return this JSON shape:
{{
  "markdown": "### 1.2 Section title\\n\\nSection body...",
  "summary": {{
    "section_id": "",
    "summary": "",
    "claims": [],
    "terms": [],
    "open_threads": [],
    "next_section_handoff": "",
    "memory": {json.dumps({str(key): [] for key in (profile.get("memory_schema") or {})}, ensure_ascii=False)}
  }},
  "evidence": [
    {{
      "claim": "The factual claim supported in the section",
      "source_id": 1,
      "passage_id": "P1",
      "evidence": "Exact continuous excerpt copied from [1.P1]"
    }}
  ]
}}
Use the exact key name "markdown" for the section body. Do not rename it to
"content", "body", or any other key. Do not return an empty markdown value.
""".strip(),
            },
        ]
    )

    parsed: Dict[str, Any] = {}
    try:
        parsed = _extract_json_object(content)
    except LLMError:
        markdown = _strip_fence(content)
        summary = None
    else:
        markdown = _markdown_from_parsed_response(parsed, content, "Section writer")
        summary = _summary_from_parsed_response(parsed)

    if not isinstance(markdown, str) or not markdown.strip():
        raise LLMError("Section writer response missing markdown")
    if not isinstance(summary, dict):
        summary = {
            "section_id": section.get("id", ""),
            "summary": markdown[:500],
            "claims": [],
            "terms": [],
            "open_threads": [],
            "next_section_handoff": f"Continue after {section.get('title', 'this section')}.",
            "memory": {},
            "evidence": [],
        }
    summary["memory"] = _normalize_memory(summary.get("memory"), profile)
    if isinstance(parsed, dict) and isinstance(parsed.get("evidence"), list):
        summary["evidence"] = parsed["evidence"][:12]
    elif not isinstance(summary.get("evidence"), list):
        summary["evidence"] = []
    return markdown, summary, usage


def repair_section_evidence(
    project: ProjectRead,
    brief: Dict[str, Any],
    section: Dict[str, Any],
    markdown: str,
    sources: list[Dict[str, Any]],
    validation: Dict[str, Any],
) -> tuple[str, list[Dict[str, Any]], dict[str, Any] | None]:
    """Repair one section whose citations failed deterministic verification.

    This is deliberately a single bounded call. The caller validates the new
    ledger again and keeps any remaining failure visible to the quality layer.
    """
    style = str(brief.get("style") or brief.get("tone") or "match the document")
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    content, usage = _stage_chat_content(
        profile,
        "revision",
        [
            {
                "role": "system",
                "content": (
                    "You repair unsupported citations in one document section. "
                    "Use only the supplied evidence passages. Return exactly one valid "
                    "JSON object with markdown and evidence."
                ),
            },
            {
                "role": "user",
                "content": f"""
Project title:
{project.title}

Section JSON:
{json.dumps(section, ensure_ascii=False)}

Current Markdown:
{markdown}

Evidence validation failures:
{json.dumps(validation, ensure_ascii=False)}

Available sources and exact passages:
{_source_context(sources, section)}

Fix only claims affected by invalid or unverified citations.
- Every remaining [n] citation must have at least one valid ledger entry.
- Copy the evidence value exactly from the selected [n.Px] passage.
- If no passage supports a factual claim, remove that claim. Do not merely
  remove its citation while leaving the unsupported factual statement.
- Do not introduce new facts, sources, headings, or sections.
- Preserve the existing heading, language, register "{style}", and approximate length.

Return this JSON shape:
{{
  "markdown": "",
  "evidence": [
    {{
      "claim": "",
      "source_id": 1,
      "passage_id": "P1",
      "evidence": "Exact continuous excerpt from the selected passage"
    }}
  ]
}}
""".strip(),
            },
        ]
    )
    parsed = _extract_json_object(content)
    repaired_markdown = _markdown_from_parsed_response(
        parsed, content, "Evidence repair"
    )
    evidence = parsed.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    return repaired_markdown, [item for item in evidence[:12] if isinstance(item, dict)], usage


_LOCAL_CITATION_ID_RE = re.compile(r"(?<!\[)\[(\d{1,2})\](?!\()")


def _all_citation_counts(markdown: str) -> Counter[str]:
    counts: Counter[str] = Counter(_LOCAL_CITATION_ID_RE.findall(markdown))
    counts.update(f"linked:{marker}" for marker in citation_markers(markdown))
    return counts


def _first_heading_line(markdown: str) -> str:
    return next(
        (line.strip() for line in str(markdown or "").splitlines() if line.strip()),
        "",
    )


def _repair_one_sentence_quality_section(
    project: ProjectRead,
    brief: Dict[str, Any],
    draft: Dict[str, Any],
    issues: list[Dict[str, Any]],
) -> tuple[str, list[Dict[str, Any]], dict[str, Any] | None]:
    section = draft.get("section") or {}
    original = str(draft.get("markdown") or "")
    sources = [source for source in (draft.get("sources") or []) if isinstance(source, dict)]
    style = str(brief.get("style") or brief.get("tone") or "match the document")
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    content, usage = _stage_chat_content(
        profile,
        "revision",
        [
            {
                "role": "system",
                "content": (
                    "You make a minimal quality repair to one document section. "
                    "Fix only the supplied sentence-level issues and return one JSON object."
                ),
            },
            {
                "role": "user",
                "content": f"""
Project title:
{project.title}

Section JSON:
{json.dumps(section, ensure_ascii=False)}

Current Markdown:
{original}

Sentence-level issues to fix:
{json.dumps(issues[:6], ensure_ascii=False)}

Available sources and exact passages:
{_source_context(sources, section)}

Make the smallest edit that resolves the listed excerpts.
- For duplicate content, remove or consolidate the repeated wording without
  deleting unique information.
- For a possible contradiction, make the statements consistent only when the
  current section clearly supports that correction; otherwise qualify the claim.
- For an unsupported absolute claim, replace the absolute wording with a
  cautious statement supported by the available passages, or remove it.
- Preserve the first heading exactly, including level, number, and title.
- Preserve the same language, register "{style}", and approximate length.
- Do not introduce new facts, sources, headings, citation numbers, or lists.
- Preserve every existing citation marker and return an evidence ledger for
  every remaining citation. Evidence must be copied verbatim from an [n.Px]
  passage above. If there are no citations, return an empty evidence array.

Return exactly this JSON shape:
{{
  "markdown": "",
  "evidence": [
    {{
      "claim": "",
      "source_id": 1,
      "passage_id": "P1",
      "evidence": "Exact continuous excerpt from the selected passage"
    }}
  ]
}}
""".strip(),
            },
        ]
    )
    parsed = _extract_json_object(content)
    repaired = _markdown_from_parsed_response(parsed, content, "Sentence quality repair")
    evidence = parsed.get("evidence")
    if not isinstance(evidence, list):
        raise LLMError("Sentence quality repair response missing evidence ledger")
    if _first_heading_line(repaired) != _first_heading_line(original):
        raise LLMError("Sentence quality repair changed the section heading")
    if _all_citation_counts(repaired) != _all_citation_counts(original):
        raise LLMError("Sentence quality repair changed citation markers")
    if len(repaired) > len(original) * 1.6 + 300 or len(repaired) < len(original) * 0.45:
        raise LLMError("Sentence quality repair changed section length too much")
    return repaired, [item for item in evidence[:12] if isinstance(item, dict)], usage


def repair_sentence_quality_sections(
    project: ProjectRead,
    brief: Dict[str, Any],
    section_drafts: list[Dict[str, Any]],
    quality: Dict[str, Any],
    *,
    high_stakes: bool = False,
    limit: int = 3,
) -> tuple[list[Dict[str, Any]], Dict[str, Any], dict[str, Any] | None]:
    """Try one guarded repair call for each of a few flagged sections.

    A candidate is accepted only if evidence validation succeeds and the
    deterministic issue count decreases when the whole document is rechecked.
    """
    issues = [issue for issue in (quality.get("issues") or []) if isinstance(issue, dict)]
    target_order: list[str] = []
    issues_by_target: dict[str, list[Dict[str, Any]]] = {}
    for issue in issues:
        section_ids = [str(value) for value in (issue.get("section_ids") or []) if str(value)]
        if not section_ids:
            continue
        target = section_ids[-1] if issue.get("type") in {"duplicate", "possible_contradiction"} else section_ids[0]
        if target not in issues_by_target:
            target_order.append(target)
            issues_by_target[target] = []
        issues_by_target[target].append(issue)
    target_order = target_order[: max(int(limit), 0)]

    working = list(section_drafts)
    current_quality = quality
    results: list[Dict[str, Any]] = []
    usages: list[Dict[str, Any]] = []
    for target in target_order:
        current_target_issues = [
            issue
            for issue in (current_quality.get("issues") or [])
            if target in [str(value) for value in (issue.get("section_ids") or [])]
        ]
        if not current_target_issues:
            results.append(
                {"section_id": target, "succeeded": False, "reason": "already_resolved"}
            )
            continue
        draft_index = next(
            (
                index
                for index, draft in enumerate(working)
                if str((draft.get("section") or {}).get("id") or "") == target
            ),
            None,
        )
        if draft_index is None:
            results.append({"section_id": target, "succeeded": False, "reason": "section_not_found"})
            continue
        draft = working[draft_index]
        try:
            markdown, evidence, usage = _repair_one_sentence_quality_section(
                project, brief, draft, current_target_issues
            )
            if usage is not None:
                usages.append({"section_id": target, **usage})
            validation = validate_evidence_ledger(
                markdown=markdown,
                evidence=evidence,
                sources=[source for source in (draft.get("sources") or []) if isinstance(source, dict)],
                section=draft.get("section") or {},
            )
            if validation.get("status") != "valid":
                raise LLMError("Sentence quality repair produced unverified evidence")
            candidate_draft = {
                **draft,
                "markdown": markdown,
                "evidence": evidence,
                "evidence_validation": validation,
                "sentence_quality_repair": {"attempted": True, "succeeded": True},
            }
            candidate = list(working)
            candidate[draft_index] = candidate_draft
            candidate_quality = sentence_quality_stats(candidate, high_stakes=high_stakes)
            if candidate_quality["issue_count"] >= current_quality["issue_count"]:
                raise LLMError("Sentence quality repair did not reduce deterministic issues")
        except LLMError as exc:
            results.append({"section_id": target, "succeeded": False, "reason": str(exc)})
            continue
        working = candidate
        current_quality = candidate_quality
        results.append({"section_id": target, "succeeded": True, "reason": None})

    report = {
        "attempted": bool(target_order),
        "initial_issue_count": int(quality.get("issue_count") or 0),
        "final_issue_count": int(current_quality.get("issue_count") or 0),
        "attempted_section_count": len(target_order),
        "repaired_section_count": sum(1 for result in results if result["succeeded"]),
        "results": results,
        "remaining_issues": (current_quality.get("issues") or [])[:12],
    }
    return working, report, ({"section_calls": usages} if usages else None)


def summarize_section(
    section: Dict[str, Any],
    markdown: str,
    profile: Dict[str, Any] | None = None,
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    parsed, usage = _stage_json_chat(
        profile,
        "summary",
        "You summarize a written section for downstream context. Return only valid JSON.",
        f"""
Section JSON:
{json.dumps(section, ensure_ascii=False)}

Section Markdown:
{markdown}

Return this JSON shape:
{{
  "section_id": "",
  "summary": "",
  "claims": [],
  "terms": [],
  "open_threads": [],
  "next_section_handoff": ""
}}
""",
    )
    return parsed, usage


def summarize_chapter(
    project: ProjectRead,
    chapter: Dict[str, Any],
    section_summaries: list[Dict[str, Any]],
    profile: Dict[str, Any] | None = None,
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    """Compress one finished chapter's section summaries into a short digest.

    Later chapters receive these digests instead of the full summary chain,
    so cross-chapter context stays a few hundred characters per chapter.
    """
    profile = profile or get_doc_type_profile(getattr(project, "document_type", None))
    chapter_id = str(chapter.get("id", ""))
    chapter_title = str(chapter.get("title", ""))
    overview = [
        {
            "section_id": str(summary.get("section_id", "")),
            "summary": _clip(summary.get("summary"), 200),
            "claims": [_clip(claim, 80) for claim in (summary.get("claims") or [])[:3]],
            "memory": _clip_memory(summary.get("memory")),
        }
        for summary in section_summaries
    ]
    parsed, usage = _stage_json_chat(
        profile,
        "summary",
        "You compress one finished document chapter into a compact digest that later chapters rely on. Return only valid JSON.",
        f"""
Project title:
{project.title}

Chapter {chapter_id}: {chapter_title}

Section summaries JSON:
{json.dumps(overview, ensure_ascii=False)}
{_memory_schema_block(profile)}

Summarize what this chapter established in 2-3 sentences, in the same language
as the summaries. Also list up to 5 key claims and up to 8 key terms the
chapter introduced.

Return this JSON shape:
{{
  "digest": "",
  "claims": [],
  "terms": [],
  "memory": {json.dumps({str(key): [] for key in (profile.get("memory_schema") or {})}, ensure_ascii=False)}
}}
""",
    )
    digest = parsed.get("digest")
    if not isinstance(digest, str) or not digest.strip():
        raise LLMError("Chapter digest response missing digest")
    return {
        "chapter_id": chapter_id,
        "title": chapter_title,
        "digest": _clip(digest, 400),
        "claims": [_clip(claim, 80) for claim in (parsed.get("claims") or [])[:5]],
        "terms": [_clip(term, 40) for term in (parsed.get("terms") or [])[:8]],
        "memory": _normalize_memory(parsed.get("memory"), profile),
    }, usage


def _section_draft_key(item: Dict[str, Any]) -> str:
    section = item.get("section") or {}
    section_id = str(section.get("id", "")).strip()
    if section_id:
        return section_id
    return str(section.get("title", "")).strip()


def apply_section_revisions(
    section_drafts: list[Dict[str, Any]],
    revisions: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    if not revisions:
        return section_drafts

    by_key = {
        key: item
        for item in revisions
        if (key := _section_draft_key(item))
    }
    if not by_key:
        return section_drafts

    return [
        by_key.get(_section_draft_key(draft), draft)
        for draft in section_drafts
    ]


def _split_opening_paragraph(markdown: str) -> tuple[str, str, str]:
    """Split a section draft into (heading, opening paragraph, remainder).

    Returns an empty opening when the first block after the heading is not a
    plain text paragraph (list, table, code fence, sub-heading) - those are
    unsafe to rewrite.
    """
    text = markdown.strip()
    if not text.startswith("#"):
        return "", "", markdown
    if "\n" not in text:
        return text, "", ""
    heading, rest = text.split("\n", 1)
    rest = rest.lstrip("\n")
    opening, _sep, remainder = rest.partition("\n\n")
    stripped = opening.lstrip()
    if (
        not stripped
        or stripped.startswith(("#", "```", "-", "*", "|", ">"))
        or re.match(r"^\d+\.\s", stripped)
    ):
        return heading, "", rest
    return heading, opening, remainder


def _markdown_tail(markdown: str, limit: int = 400) -> str:
    """Last plain-text paragraphs of a section, capped at `limit` characters."""
    paragraphs = [
        paragraph
        for paragraph in markdown.strip().split("\n\n")
        if paragraph.strip() and not paragraph.lstrip().startswith(("```", "|", "#"))
    ]
    tail = ""
    for paragraph in reversed(paragraphs):
        candidate = f"{paragraph}\n\n{tail}".strip() if tail else paragraph
        if tail and len(candidate) > limit:
            break
        tail = candidate
        if len(tail) >= limit:
            break
    return tail[-limit:]


def _smooth_one_transition(
    project: ProjectRead,
    brief: Dict[str, Any],
    previous_tail: str,
    heading: str,
    opening: str,
) -> tuple[str, dict[str, Any] | None]:
    style = str(brief.get("style") or brief.get("tone") or "match the document")
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    parsed, usage = _stage_json_chat(
        profile,
        "revision",
        "You rewrite the opening paragraph of a chapter so it flows naturally from the previous chapter. Return only valid JSON.",
        f"""
Project title:
{project.title}

End of the previous chapter:
{previous_tail}

Heading of the current chapter's first section (do not change it):
{heading}

Current opening paragraph:
{opening}

Rewrite ONLY the opening paragraph so it reads as a natural continuation of
the previous chapter's ending. Keep the same language, the register "{style}",
and roughly the same length. Preserve inline citation links exactly, such as
[[1]](https://example.com) or [(example.com, n.d.)](https://example.com).
Do not add new facts, headings, or lists.

Return this JSON shape:
{{
  "opening": ""
}}
""",
    )
    new_opening = parsed.get("opening")
    if not isinstance(new_opening, str) or not new_opening.strip():
        raise LLMError("Seam smoothing response missing opening")
    return new_opening.strip(), usage


def smooth_chapter_seams(
    project: ProjectRead,
    brief: Dict[str, Any],
    section_drafts: list[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], dict[str, Any] | None, list[str]]:
    """Smooth chapter transitions with one small call per boundary.

    Replaces the old whole-document merge call, which packed every draft into
    a single prompt and routinely overflowed small models. Intra-chapter flow
    is already handled at write time by the summary handoff; only chapter
    boundaries get an extra pass. Every seam is best-effort and guarded: a
    rewrite that drops citations or balloons in length is discarded.
    """
    smoothed: list[Dict[str, Any]] = []
    usages: list[Dict[str, Any]] = []
    seams: list[str] = []
    previous_chapter: str | None = None
    previous_markdown = ""
    for draft in section_drafts:
        section = draft.get("section") or {}
        section_id = str(section.get("id", ""))
        chapter_id = section_id.split(".")[0]
        markdown = str(draft.get("markdown", ""))
        if previous_chapter is not None and chapter_id != previous_chapter:
            heading, opening, remainder = _split_opening_paragraph(markdown)
            if heading and opening:
                try:
                    new_opening, usage = _smooth_one_transition(
                        project, brief, _markdown_tail(previous_markdown), heading, opening
                    )
                except LLMError:
                    new_opening, usage = None, None
                if (
                    new_opening
                    and citation_markers(new_opening) == citation_markers(opening)
                    and len(new_opening) <= 2 * len(opening) + 200
                ):
                    parts = [heading, new_opening]
                    if remainder.strip():
                        parts.append(remainder)
                    markdown = "\n\n".join(parts)
                    seams.append(section_id)
                    if usage is not None:
                        usages.append({"section_id": section_id, **usage})
        smoothed.append({**draft, "markdown": markdown})
        previous_chapter = chapter_id
        previous_markdown = markdown
    return smoothed, ({"seam_calls": usages} if usages else None), seams



def _continuity_overview(
    section_drafts: list[Dict[str, Any]],
    summaries: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    # Full drafts overflow small models (30k+ chars); review from the
    # per-section summaries plus a short opening excerpt instead.
    summary_by_id = {
        str(summary.get("section_id", "")): summary for summary in summaries
    }
    overview = []
    for draft in section_drafts:
        section = draft.get("section") or {}
        section_id = str(section.get("id", ""))
        summary = summary_by_id.get(section_id, {})
        markdown = str(draft.get("markdown", ""))
        body = markdown.split("\n", 1)[-1] if "\n" in markdown else markdown
        overview.append(
            {
                "id": section_id,
                "title": section.get("title", ""),
                "summary": _clip(summary.get("summary"), 150),
                "opening": _clip(body, 120),
                "terms": [_clip(term, 40) for term in (summary.get("terms") or [])[:5]],
            }
        )
    return overview


def _review_chapter_continuity(
    project: ProjectRead,
    brief: Dict[str, Any],
    chapter_id: str,
    overview: list[Dict[str, Any]],
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    style = str(brief.get("style") or brief.get("tone") or "")
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    return _stage_json_chat(
        profile,
        "review",
        "You review the sections of one document chapter for continuity, repeated ideas, terminology and register consistency. Return only valid JSON.",
        f"""
Project title:
{project.title}

Required writing style/register: {style or "unspecified"}

Chapter {chapter_id} section overview (id, title, summary, opening sentence, key terms):
{json.dumps(overview, ensure_ascii=False)}

Check for:
- Topics repeated across these sections (name both section ids)
- Inconsistent terminology for the same concept
- Sections whose opening sentence does not match the required register/style
- Broken logical flow between adjacent sections

Put the ids of sections that need rewriting in revision_targets.

Return this JSON shape:
{{
  "verdict": "pass",
  "issues": [],
  "revision_targets": [],
  "notes": ""
}}
""",
    )


def _review_cross_chapter_continuity(
    project: ProjectRead,
    brief: Dict[str, Any],
    chapter_digests: list[Dict[str, Any]],
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    digests = [
        {
            "chapter_id": str(digest.get("chapter_id", "")),
            "title": _clip(digest.get("title"), 80),
            "digest": _clip(digest.get("digest"), 300),
            "terms": [_clip(term, 40) for term in (digest.get("terms") or [])[:8]],
        }
        for digest in chapter_digests
    ]
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    return _stage_json_chat(
        profile,
        "review",
        "You review chapter digests of a document for cross-chapter repetition, terminology drift, and ordering problems. Return only valid JSON.",
        f"""
Project title:
{project.title}

Chapter digests JSON:
{json.dumps(digests, ensure_ascii=False)}

Check for:
- The same topic explained in more than one chapter (name both chapter ids)
- Different terms used for the same concept across chapters
- Chapters that assume content a later chapter introduces

Return this JSON shape:
{{
  "verdict": "pass",
  "issues": [],
  "notes": ""
}}
""",
    )


def review_continuity_staged(
    project: ProjectRead,
    brief: Dict[str, Any],
    section_drafts: list[Dict[str, Any]],
    summaries: list[Dict[str, Any]],
    chapter_digests: list[Dict[str, Any]],
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    """Two-stage continuity review sized for small models.

    Stage one reviews each chapter's sections in its own call; stage two
    reviews cross-chapter issues from the chapter digests. A single failed
    call skips that chapter instead of aborting the review; only a total
    failure raises.
    """
    overview = _continuity_overview(section_drafts, summaries)
    by_chapter: Dict[str, list[Dict[str, Any]]] = {}
    for entry in overview:
        by_chapter.setdefault(str(entry["id"]).split(".")[0], []).append(entry)

    verdict = "pass"
    issues: list[Any] = []
    targets: list[str] = []
    notes: list[str] = []
    usages: list[Dict[str, Any]] = []
    attempted = 0
    succeeded = 0

    for chapter_id, entries in by_chapter.items():
        if len(entries) < 2:
            continue
        attempted += 1
        try:
            review, usage = _review_chapter_continuity(project, brief, chapter_id, entries)
        except LLMError:
            notes.append(f"Chapter {chapter_id} continuity review failed; skipped.")
            continue
        succeeded += 1
        if usage is not None:
            usages.append({"chapter_id": chapter_id, **usage})
        if str(review.get("verdict", "pass")) != "pass":
            verdict = "needs_revision"
        issues.extend(review.get("issues") or [])
        targets.extend(
            str(target) for target in (review.get("revision_targets") or []) if str(target).strip()
        )
        if review.get("notes"):
            notes.append(f"[{chapter_id}] {review['notes']}")

    if len(chapter_digests) >= 2:
        attempted += 1
        try:
            review, usage = _review_cross_chapter_continuity(project, brief, chapter_digests)
        except LLMError:
            notes.append("Cross-chapter continuity review failed; skipped.")
        else:
            succeeded += 1
            if usage is not None:
                usages.append({"chapter_id": "cross", **usage})
            if str(review.get("verdict", "pass")) != "pass":
                verdict = "needs_revision"
            issues.extend(review.get("issues") or [])
            if review.get("notes"):
                notes.append(f"[cross-chapter] {review['notes']}")

    if attempted and not succeeded:
        return {
            "verdict": "incomplete",
            "issues": [],
            "revision_targets": [],
            "notes": " ".join(notes) or "Continuity review did not complete.",
            "chapter_review_count": 0,
        }, None

    # Small models sometimes describe concrete problems but still emit
    # verdict=pass and an empty target list.  Recover targets from structured
    # issues and let the deterministic contract win over contradictory fields.
    targets.extend(issue_section_ids(issues))
    deduped_targets = list(dict.fromkeys(targets))
    if issues:
        verdict = "needs_revision"
    return {
        "verdict": verdict,
        "issues": issues,
        "revision_targets": deduped_targets,
        "notes": " ".join(notes),
        "chapter_review_count": succeeded,
    }, ({"chapter_calls": usages} if usages else None)


def _rubric_lines(rubric: list[Dict[str, Any]]) -> str:
    return "\n".join(
        f"- {item.get('key')}: {item.get('name')} - {item.get('description')}"
        for item in rubric
        if isinstance(item, dict) and item.get("key")
    )


def _review_chapter_rubric(
    project: ProjectRead,
    brief: Dict[str, Any],
    chapter_id: str,
    sections_block: str,
    rubric: list[Dict[str, Any]],
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    style = str(brief.get("style") or brief.get("tone") or "unspecified")
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    return _stage_json_chat(
        profile,
        "review",
        "You grade one chapter of a document against a quality rubric. Return only valid JSON.",
        f"""
Project title:
{project.title}

Document goal:
{_clip(brief.get("goal"), 200)}

Required writing register: {style}

Rubric criteria (grade each from 1 to 5; 5 = excellent):
{_rubric_lines(rubric)}

Chapter {chapter_id} sections:
{sections_block}

Grade strictly against the rubric. For every criterion scored 3 or lower,
add one concrete issue that names the section id and says what to change.
Put the ids of sections that need rewriting in revision_targets.

Return this JSON shape:
{{
  "scores": [{{"key": "", "score": 5, "note": ""}}],
  "issues": [],
  "revision_targets": []
}}
""",
    )


def review_rubric_staged(
    project: ProjectRead,
    brief: Dict[str, Any],
    profile: Dict[str, Any] | None,
    section_drafts: list[Dict[str, Any]],
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    """Grade the draft against the document type's rubric, chapter by chapter.

    Sized for small models like the continuity review: one call per chapter
    over clipped section text. Best effort throughout - a failed chapter is
    noted and skipped, and a fully failed review returns a pass verdict so
    rubric grading can never block a run.
    """
    rubric = [
        item
        for item in ((profile or {}).get("rubric") or [])
        if isinstance(item, dict) and item.get("key")
    ]
    if not rubric:
        return {
            "verdict": "pass",
            "criteria": [],
            "issues": [],
            "revision_targets": [],
            "notes": "No rubric defined for this document type.",
        }, None

    by_chapter: Dict[str, list[Dict[str, Any]]] = {}
    for draft in section_drafts:
        section = draft.get("section") or {}
        chapter_id = str(section.get("id", "")).split(".")[0]
        by_chapter.setdefault(chapter_id, []).append(draft)

    score_lists: Dict[str, list[int]] = {item["key"]: [] for item in rubric}
    score_notes: Dict[str, list[str]] = {item["key"]: [] for item in rubric}
    issues: list[Any] = []
    targets: list[str] = []
    notes: list[str] = []
    usages: list[Dict[str, Any]] = []
    succeeded = 0

    for chapter_id, drafts in by_chapter.items():
        sections_block = "\n\n".join(
            f"[{(draft.get('section') or {}).get('id', '')}] "
            f"{(draft.get('section') or {}).get('title', '')}\n"
            f"{str(draft.get('markdown', ''))[:1800]}"
            for draft in drafts
        )
        try:
            review, usage = _review_chapter_rubric(
                project, brief, chapter_id, sections_block, rubric
            )
        except LLMError:
            notes.append(f"Chapter {chapter_id} rubric review failed; skipped.")
            continue
        succeeded += 1
        if usage is not None:
            usages.append({"chapter_id": chapter_id, **usage})
        for entry in review.get("scores") or []:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key", "")).strip()
            if key not in score_lists:
                continue
            try:
                score = int(entry.get("score"))
            except (TypeError, ValueError):
                continue
            score_lists[key].append(min(max(score, 1), 5))
            note = _clip(entry.get("note"), 150)
            if note:
                score_notes[key].append(f"[{chapter_id}] {note}")
        issues.extend(_clip(issue, 250) for issue in (review.get("issues") or [])[:6])
        targets.extend(
            str(target).strip()
            for target in (review.get("revision_targets") or [])
            if str(target).strip()
        )

    criteria = [
        {
            "key": item["key"],
            "name": item.get("name", item["key"]),
            "average_score": (
                round(sum(scores) / len(scores), 1) if scores else None
            ),
            "min_score": min(scores) if scores else None,
            "notes": score_notes[item["key"]][:4],
        }
        for item in rubric
        for scores in [score_lists[item["key"]]]
    ]
    targets.extend(issue_section_ids(issues))
    deduped_targets = list(dict.fromkeys(targets))[:5]
    low_score = any(
        isinstance(item.get("min_score"), int) and item["min_score"] <= 3
        for item in criteria
    )
    if by_chapter and not succeeded:
        verdict = "incomplete"
    elif issues or deduped_targets or low_score:
        verdict = "needs_revision"
    else:
        verdict = "pass"
    return {
        "verdict": verdict,
        "criteria": criteria,
        "issues": issues,
        "revision_targets": deduped_targets,
        "notes": " ".join(notes),
    }, ({"chapter_calls": usages} if usages else None)


def _revise_one_section(
    project: ProjectRead,
    brief: Dict[str, Any],
    draft: Dict[str, Any],
    issues: list,
) -> tuple[str, dict[str, Any] | None]:
    section = draft.get("section") or {}
    style = str(brief.get("style") or brief.get("tone") or "match the document")
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    content, usage = _stage_chat_content(
        profile,
        "revision",
        [
            {
                "role": "system",
                "content": (
                    "You rewrite one document section to fix continuity issues. "
                    f"Writing style/register: {style}. Return valid JSON when possible."
                ),
            },
            {
                "role": "user",
                "content": f"""
Project title:
{project.title}

Section JSON:
{json.dumps(section, ensure_ascii=False)}

Current section Markdown:
{draft.get("markdown", "")}

Issues to fix (only those relevant to this section):
{json.dumps([_clip(issue, 200) for issue in issues[:8]], ensure_ascii=False)}

Rewrite this section fixing the issues. Keep the same heading (level, numbering,
title), the same language, the register "{style}", and roughly the same length.
Preserve inline citation markers such as [1].

Return this JSON shape:
{{
  "markdown": ""
}}
""".strip(),
            },
        ]
    )
    try:
        parsed = _extract_json_object(content)
    except LLMError:
        markdown = _strip_fence(content)
    else:
        markdown = _markdown_from_parsed_response(parsed, content, "Section reviser")
    if not isinstance(markdown, str) or not markdown.strip():
        raise LLMError("Section reviser response missing markdown")
    return markdown, usage


def revise_section_with_feedback(
    project: ProjectRead,
    brief: Dict[str, Any],
    draft: Dict[str, Any],
    comments: list[str],
) -> tuple[str, dict[str, Any] | None]:
    section = draft.get("section") or {}
    style = str(brief.get("style") or brief.get("tone") or "match the document")
    comment_lines = "\n".join(f"- {_clip(comment, 400)}" for comment in comments[:8])
    profile = get_doc_type_profile(getattr(project, "document_type", None))
    content, usage = _stage_chat_content(
        profile,
        "revision",
        [
            {
                "role": "system",
                "content": (
                    "You rewrite one document section to apply the user's improvement "
                    f"requests. Writing style/register: {style}. Return valid JSON when possible."
                ),
            },
            {
                "role": "user",
                "content": f"""
Project title:
{project.title}

Section JSON:
{json.dumps(section, ensure_ascii=False)}

Current section Markdown:
{draft.get("markdown", "")}

User improvement requests (apply all of them):
{comment_lines}

Rewrite this section so every request above is reflected. Keep the same heading
(level, numbering, title), the same language, and the register "{style}".
Preserve inline citation markers such as [1] unless a request says otherwise.
Do not add content that belongs to other sections.

Return this JSON shape:
{{
  "markdown": ""
}}
""".strip(),
            },
        ]
    )
    try:
        parsed = _extract_json_object(content)
    except LLMError:
        markdown = _strip_fence(content)
    else:
        markdown = _markdown_from_parsed_response(parsed, content, "Feedback reviser")
    if not isinstance(markdown, str) or not markdown.strip():
        raise LLMError("Feedback reviser response missing markdown")
    return markdown, usage


def revise_targeted_sections(
    project: ProjectRead,
    brief: Dict[str, Any],
    section_drafts: list[Dict[str, Any]],
    continuity_review: Dict[str, Any],
) -> tuple[list[Dict[str, Any]], dict[str, Any] | None]:
    targets = continuity_review.get("revision_targets") or []
    target_keys = {str(target).strip() for target in targets if str(target).strip()}
    if not target_keys:
        return section_drafts, None

    issues = continuity_review.get("issues") or []
    revised: list[Dict[str, Any]] = []
    usages: list[dict[str, Any]] = []
    # One small call per flagged section instead of one giant call with
    # every draft: keeps prompts within small-model budgets.
    for draft in section_drafts:
        section = draft.get("section") or {}
        keys = {str(section.get("id", "")).strip(), str(section.get("title", "")).strip()}
        if not (keys & target_keys):
            continue
        try:
            markdown, usage = _revise_one_section(project, brief, draft, issues)
        except LLMError:
            continue
        revised.append(
            {
                **draft,
                "section": section,
                "markdown": markdown,
                "evidence_validation": {
                    "status": "stale",
                    "reason": "section_revised_after_evidence_capture",
                },
                "evidence_repair": {
                    "attempted": False,
                    "succeeded": False,
                    "reason": "section_revised_after_evidence_capture",
                },
            }
        )
        if usage is not None:
            usages.append({"section_id": section.get("id"), **usage})

    if not revised:
        return section_drafts, None
    return (
        apply_section_revisions(section_drafts, revised),
        {"section_calls": usages} if usages else None,
    )

