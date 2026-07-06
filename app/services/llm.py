import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict

from app.core.config import settings
from app.schemas.projects import ProjectRead
from app.schemas.questions import UserDecisionRead


class LLMError(Exception):
    pass


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


def _chat_completions_url() -> str:
    return settings.llm_base_url.rstrip("/") + "/chat/completions"


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
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 6000,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _chat_completions_url(),
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
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
    }
    if summary_keys.intersection(parsed.keys()):
        return {
            "section_id": parsed.get("section_id", ""),
            "summary": parsed.get("summary", ""),
            "claims": parsed.get("claims", []),
            "terms": parsed.get("terms", []),
            "open_threads": parsed.get("open_threads", []),
            "next_section_handoff": parsed.get("next_section_handoff", ""),
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

    def score(source: Dict[str, Any]) -> int:
        return len(section_words & _source_words(source))

    ranked = sorted(usable, key=score, reverse=True)
    return ranked[:limit]


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


def _source_context(sources: list[Dict[str, Any]], per_source_cap: int = 400) -> str:
    lines = []
    for index, source in enumerate(sources, start=1):
        body = _clip(source.get("summary") or source.get("snippet") or "", per_source_cap)
        lines.append(f"[{index}] {_clip(source.get('title'), 80)} - {source.get('url', '')}")
        if body:
            lines.append(f"    {body}")
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


def plan_user_questions(
    project: ProjectRead, decisions: list[UserDecisionRead]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    decision_lines = "\n".join(
        f"- {decision.question}: {decision.answer}" for decision in decisions
    ) or "- No user answers recorded yet."
    system_prompt = (
        "You are an intake agent for a document writing workflow. "
        "Ask only questions that would materially improve the document. "
        "Return only one valid JSON object. Do not wrap the response in markdown."
    )
    user_prompt = f"""
Project title:
{project.title}

Initial request:
{project.initial_request}

Known user answers:
{decision_lines}

Decide whether more user input is needed before writing.
Ask at most 5 questions. Do not ask questions already answered above.
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
    parsed, usage = _json_chat(system_prompt, user_prompt)
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


def plan_search_queries(
    project: ProjectRead, decisions: list[UserDecisionRead]
) -> tuple[list[str], dict[str, Any] | None]:
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
useful reference sources for this document. Write the queries in the same
language as the request. Extract key search terms; do not copy full sentences
or question text from the request.

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


def plan_chapter_queries(
    project: ProjectRead, chapters: list[Dict[str, Any]]
) -> tuple[list[str], dict[str, Any] | None]:
    chapter_list = [
        {"id": str(chapter.get("id", "")), "title": str(chapter.get("title", ""))}
        for chapter in chapters
    ]
    parsed, usage = _json_chat(
        "You create short web search queries for document research. Return only valid JSON.",
        f"""
Project topic:
{project.title}

Chapters:
{json.dumps(chapter_list, ensure_ascii=False)}

For each chapter, in order, create one short web search query (2 to 6 keywords)
that would find useful reference material for that chapter. Write the queries
in the same language as the chapter titles. Use searchable keywords, not full
sentences; do not copy the chapter title verbatim if it reads like a sentence.

Return this exact JSON shape with exactly {len(chapter_list)} queries in chapter order:
{{
  "queries": ["", ""]
}}
""",
    )
    raw_queries = parsed.get("queries")
    if not isinstance(raw_queries, list):
        raise LLMError("LLM chapter query plan missing list field: queries")
    queries = [" ".join(str(query).split())[:100].strip() for query in raw_queries]
    queries = [query for query in queries if query]
    if len(queries) != len(chapter_list):
        raise LLMError("LLM chapter query plan returned wrong query count")
    return queries, usage


def generate_brief(
    project: ProjectRead,
    decisions: list[UserDecisionRead],
    research: Dict[str, Any] | None,
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    parsed, usage = _json_chat(
        "You create compact document briefs. Return only valid JSON.",
        f"""
Project title:
{project.title}

Initial request:
{project.initial_request}

User answers and decisions:
{_decision_lines(decisions)}

Search sources:
{_source_lines(research)}

"style" is the exact sentence register every section must use, written in the
document's language. For Korean documents choose one register explicitly,
for example "-이다/한다체 (격식 있는 문어체)" or "-입니다체 (정중한 설명체)".

Return this JSON shape:
{{
  "topic": "",
  "goal": "",
  "audience": "",
  "tone": "",
  "style": "",
  "format": "markdown document",
  "must_include": [],
  "must_avoid": [],
  "source_notes": [],
  "success_criteria": []
}}
""",
    )
    return parsed, usage


def generate_outline(
    project: ProjectRead, brief: Dict[str, Any]
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    parsed, usage = _json_chat(
        "You create concise document outlines. Return only valid JSON.",
        f"""
Project title:
{project.title}

Brief JSON:
{json.dumps(brief, ensure_ascii=False)}

Create a high-level outline. Return this JSON shape:
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
    return _json_chat(
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
    parsed, usage = _json_chat(
        "You expand one outline chapter into a compact hierarchical writing subtree. Return only valid JSON.",
        f"""
Project title:
{project.title}

Brief summary JSON:
{json.dumps(_brief_context(brief), ensure_ascii=False)}

Current chapter JSON:
{json.dumps(chapter, ensure_ascii=False)}

Sections already planned in other chapters (do NOT repeat these topics):
{covered}
{feedback_block}
Expand only this chapter into subtopics. If a subtopic is still broad, give it
children. Stop when leaf nodes are narrow enough to write in one focused call.
Do not include sibling chapters. Do not include the final article text.

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
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    chapters = outline.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise LLMError("Section plan input missing outline chapters")

    outline_tree: list[Dict[str, Any]] = []
    usage_items: list[dict[str, Any]] = []
    planned_leaf_titles: list[str] = []

    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        chapter_id = str(chapter.get("id") or len(outline_tree) + 1)
        chapter_title = str(chapter.get("title") or f"Chapter {chapter_id}")
        children, usage = expand_chapter_subtree(
            project, brief, chapter, planned_leaf_titles
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
    return _json_chat(
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
    content, usage = _chat_content(
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
) -> tuple[str, Dict[str, Any], dict[str, Any] | None]:
    style = str(brief.get("style") or brief.get("tone") or "match the initial request")
    target_length = section.get("target_length") or 500
    depth = section.get("depth") or 3
    titles_block = "\n".join(f"- {title}" for title in section_titles) or "- (none)"
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
    content, usage = _chat_content(
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

All sections of the document (do NOT cover their topics here):
{titles_block}

Current section JSON:
{json.dumps(section, ensure_ascii=False)}

Previous section summary JSON:
{json.dumps(_clip_summary(previous_summary), ensure_ascii=False)}

Relevant sources:
{_source_context(sources)}{feedback_block}

Write only this section in Markdown, in the same language as the brief topic.
Rules:
- Sentence register: {style}. Every sentence must use this register consistently.
- Aim for roughly {target_length} characters of body text.
- Start with exactly one heading: "{'#' * min(max(int(depth) if str(depth).isdigit() else 3, 2), 6)} {section.get('id', '')} {section.get('title', '')}".
- Do NOT add sub-headings inside this section. Use bold lead-ins or lists instead.
- Do not repeat content from the previous summary or topics owned by other sections.
- When a source above supports a statement, cite it inline as [1] or [2] matching
  the source numbers. Do not cite sources that are not listed.{diagram_rule}

Return this JSON shape:
{{
  "markdown": "### 1.2 Section title\\n\\nSection body...",
  "summary": {{
    "section_id": "",
    "summary": "",
    "claims": [],
    "terms": [],
    "open_threads": [],
    "next_section_handoff": ""
  }}
}}
Use the exact key name "markdown" for the section body. Do not rename it to
"content", "body", or any other key. Do not return an empty markdown value.
""".strip(),
            },
        ]
    )

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
        }
    return markdown, summary, usage


def summarize_section(
    section: Dict[str, Any], markdown: str
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
    parsed, usage = _json_chat(
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


def _markdown_from_merge_response(
    parsed: Dict[str, Any],
    raw_content: str,
    section_drafts: list[Dict[str, Any]],
) -> str:
    sections = parsed.get("sections")
    if isinstance(sections, list):
        parts = [
            str(item.get("markdown", "")).strip()
            for item in sections
            if isinstance(item, dict) and str(item.get("markdown", "")).strip()
        ]
        if len(parts) >= len(section_drafts) or (
            len(parts) > 1 and len(section_drafts) > 1
        ):
            return "\n\n".join(parts)

    return _markdown_from_parsed_response(parsed, raw_content, "Final merge")


def merge_sections(
    project: ProjectRead,
    brief: Dict[str, Any],
    outline: Dict[str, Any],
    section_drafts: list[Dict[str, Any]],
    summaries: list[Dict[str, Any]],
    research: Dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    content, usage = _chat_content(
        [
            {
                "role": "system",
                "content": "You merge section drafts into a polished Markdown document. Prefer valid JSON, but the final body must be usable Markdown.",
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

Section drafts JSON:
{json.dumps(section_drafts, ensure_ascii=False)}

Section summaries JSON:
{json.dumps(summaries, ensure_ascii=False)}

Search sources:
{_source_lines(research)}

Merge the sections into one coherent Markdown document. Smooth transitions,
remove obvious duplication, and keep the same language as the drafts. Preserve
all outline numbering in headings, such as "## 1 Title" and
"### 1.2 Section title". Do not remove or renumber heading prefixes. Preserve
inline citation links such as [[1]](https://example.com) exactly as written;
do not renumber or unlink them. Keep ```mermaid code blocks unchanged. Add a final "Sources" section listing each
search source above as "N. [title](url)" using the same numbers as the inline
citations. Return either:
{{
  "markdown": "# Title\\n\\nFinal document..."
}}

or plain Markdown.
If returning JSON, use the exact key name "markdown" for the final document.
""".strip(),
            },
        ]
    )
    try:
        parsed = _extract_json_object(content)
    except LLMError:
        markdown = _strip_fence(content)
    else:
        markdown = _markdown_from_merge_response(parsed, content, section_drafts)
    if not isinstance(markdown, str) or not markdown.strip():
        raise LLMError("Final merge response missing markdown")

    input_length = sum(
        len(str(draft.get("markdown", "")).strip()) for draft in section_drafts
    )
    if len(section_drafts) > 1 and input_length and len(markdown.strip()) < input_length * 0.5:
        markdown = "\n\n".join(
            str(item.get("markdown", "")).strip()
            for item in section_drafts
            if str(item.get("markdown", "")).strip()
        )

    return markdown, usage


def review_continuity(
    project: ProjectRead,
    brief: Dict[str, Any],
    section_drafts: list[Dict[str, Any]],
    summaries: list[Dict[str, Any]],
) -> tuple[Dict[str, Any], dict[str, Any] | None]:
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
    style = str(brief.get("style") or brief.get("tone") or "")
    return _json_chat(
        "You review a multi-section draft for continuity, repeated ideas, terminology and register consistency. Return only valid JSON.",
        f"""
Project title:
{project.title}

Required writing style/register: {style or "unspecified"}

Section overview (id, title, summary, opening sentence, key terms):
{json.dumps(overview, ensure_ascii=False)}

Check for:
- Topics repeated across sections (name both section ids)
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


def _revise_one_section(
    project: ProjectRead,
    brief: Dict[str, Any],
    draft: Dict[str, Any],
    issues: list,
) -> tuple[str, dict[str, Any] | None]:
    section = draft.get("section") or {}
    style = str(brief.get("style") or brief.get("tone") or "match the document")
    content, usage = _chat_content(
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
    content, usage = _chat_content(
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
        revised.append({"section": section, "markdown": markdown})
        if usage is not None:
            usages.append({"section_id": section.get("id"), **usage})

    if not revised:
        return section_drafts, None
    return (
        apply_section_revisions(section_drafts, revised),
        {"section_calls": usages} if usages else None,
    )


def generate_document_artifacts(
    project: ProjectRead, decisions: list[UserDecisionRead]
) -> tuple[list[tuple[str, str, Dict[str, Any]]], dict[str, Any] | None]:
    decision_lines = "\n".join(
        f"- {decision.question}: {decision.answer}" for decision in decisions
    ) or "- No user answers recorded."
    system_prompt = (
        "You are a document generation agent. Return only one valid JSON object. "
        "Do not wrap the response in markdown. Do not include commentary."
    )
    user_prompt = f"""
Create a first-pass document for this project.

Project title:
{project.title}

Initial request:
{project.initial_request}

User answers and decisions to incorporate:
{decision_lines}

Write in the same language as the user's request unless the user explicitly asks
for another language. Reflect the user answers directly in the brief, outline,
and draft.

Return this exact JSON shape:
{{
  "brief": {{
    "topic": "",
    "goal": "",
    "audience": "",
    "tone": "",
    "format": "markdown document",
    "success_criteria": []
  }},
  "outline": {{
    "chapters": [
      {{
        "id": "1",
        "title": "",
        "purpose": "",
        "expected_sections": []
      }}
    ]
  }},
  "draft_markdown": "# Title\\n\\nMarkdown body..."
}}
"""
    response = _request_chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt.strip()},
        ]
    )

    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("LLM response did not match OpenAI chat completions format") from exc

    parsed = _extract_json_object(content)
    brief = parsed.get("brief")
    outline = parsed.get("outline")
    draft_markdown = parsed.get("draft_markdown")

    if not isinstance(brief, dict):
        raise LLMError("LLM response missing object field: brief")
    if not isinstance(outline, dict):
        raise LLMError("LLM response missing object field: outline")
    if not isinstance(draft_markdown, str) or not draft_markdown.strip():
        raise LLMError("LLM response missing text field: draft_markdown")

    artifacts = [
        ("brief", "LLM brief", brief),
        ("outline", "LLM outline", outline),
        (
            "draft",
            "LLM draft",
            {
                "format": "markdown",
                "markdown": draft_markdown,
            },
        ),
    ]
    return artifacts, response.get("usage")
