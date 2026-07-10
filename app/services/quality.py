"""Deterministic quality signals that complement small-model reviewers.

The model is still useful for semantic feedback, but it must not be the only
component deciding whether a document is ready.  This module intentionally
uses simple, explainable rules so the same inputs always produce the same
quality status.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any, Dict
from urllib.parse import urlparse


_AUTHORITATIVE_HOSTS = {
    "bok.or.kr",
    "cdc.gov",
    "cochrane.org",
    "doi.org",
    "ema.europa.eu",
    "fda.gov",
    "imf.org",
    "nih.gov",
    "ncbi.nlm.nih.gov",
    "oecd.org",
    "pubmed.ncbi.nlm.nih.gov",
    "sec.gov",
    "un.org",
    "who.int",
}
_LOW_QUALITY_HOSTS = {
    "blog.naver.com",
    "blogspot.com",
    "brunch.co.kr",
    "medium.com",
    "namu.wiki",
    "tistory.com",
    "velog.io",
    "wikipedia.org",
    "wordpress.com",
}
_HIGH_STAKES_TERMS = {
    "banking", "diagnosis", "disease", "drug", "finance", "financial", "health",
    "investment", "investing", "law", "legal", "medicine", "medical", "patient",
    "regulation", "treatment",
    "건강", "금융", "규정", "법률", "소송", "약물", "은행", "의료", "정신", "증상",
    "질병", "질환", "진단", "재무", "치료", "치매", "투자", "환자",
}
_MEDICAL_TERMS = {
    "diagnosis", "disease", "drug", "health", "medicine", "medical", "patient", "treatment",
    "건강", "약물", "의료", "정신", "증상", "질병", "질환", "진단", "치료", "치매", "환자",
}
_LEGAL_TERMS = {"law", "legal", "regulation", "법", "법률", "규정", "소송"}
_FINANCE_TERMS = {
    "banking", "finance", "financial", "investment", "금융", "은행", "재무", "투자",
}
_SECTION_ID_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)+)(?!\d)")
_CITATION_RE = re.compile(r"(?:\[\[?\d+\]?\](?:\([^)]*\))?|\([^)]*(?:\d{4}|n\.d\.)[^)]*\))")
_LOCAL_CITATION_RE = re.compile(r"(?<!\[)\[(\d{1,2})\](?!\()")
_WORD_RE = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
_NEGATION_RE = re.compile(
    r"\b(?:cannot|can't|doesn't|isn't|never|no|not|without)\b|(?:아니|않|없|불가능|금지|못하)",
    re.IGNORECASE,
)
_OVERCLAIM_RE = re.compile(
    r"\b(?:always|completely safe|guaranteed|never|no risk|proven|proves|100%)\b"
    r"|(?:100%|반드시|무조건|완치|절대|확실히|틀림없|부작용(?:이|은)? 없다|보장(?:한다|됩니다))",
    re.IGNORECASE,
)
_COMPARISON_STOPWORDS = {
    "about", "after", "also", "and", "are", "because", "before", "being", "but",
    "for", "from", "has", "have", "into", "its", "that", "the", "their", "then",
    "this", "through", "was", "were", "with", "것이다", "그리고", "그러나", "대한",
    "때문", "또한", "에서", "으로", "있다", "한다",
}


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _matches_host(host: str, candidates: set[str]) -> bool:
    return any(host == candidate or host.endswith(f".{candidate}") for candidate in candidates)


def _contains_topic_term(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    english_words = set(re.findall(r"[a-z]+", lowered))
    return any(
        term in english_words if term.isascii() else term in lowered
        for term in terms
    )


def is_high_stakes_topic(value: Any) -> bool:
    """Return whether a project or section needs stronger source safeguards."""
    return _contains_topic_term(str(value or ""), _HIGH_STAKES_TERMS)


def authoritative_search_queries(
    base_query: str, topic_text: str, limit: int = 2
) -> list[str]:
    """Build short authority-domain queries for a high-stakes topic.

    The site operator is placed first so it survives the search backend's
    conservative query-length cap.
    """
    if not base_query or not is_high_stakes_topic(topic_text) or limit <= 0:
        return []
    korean = bool(re.search(r"[가-힣]", topic_text))
    if _contains_topic_term(topic_text, _MEDICAL_TERMS):
        domains = ("go.kr", "ac.kr") if korean else ("nih.gov", "who.int")
    elif _contains_topic_term(topic_text, _LEGAL_TERMS):
        domains = ("law.go.kr", "go.kr") if korean else ("gov", "law.cornell.edu")
    elif _contains_topic_term(topic_text, _FINANCE_TERMS):
        domains = ("fsc.go.kr", "bok.or.kr") if korean else ("sec.gov", "imf.org")
    else:
        domains = ("go.kr", "ac.kr") if korean else ("gov", "edu")

    compact = " ".join(str(base_query).split())
    queries: list[str] = []
    for domain in domains:
        prefix = f"site:{domain} "
        room = max(20, 100 - len(prefix))
        clipped = compact[:room]
        if len(compact) > room and " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        query = f"{prefix}{clipped.strip()}".strip()
        if query not in queries:
            queries.append(query)
        if len(queries) >= limit:
            break
    return queries


def grade_source(source: Dict[str, Any]) -> Dict[str, Any]:
    """Return an explainable trust tier for one source."""
    url = str(source.get("url") or "").strip()
    host = _host(url)
    if url.startswith("file://") or source.get("kind") == "file":
        return {"tier": "user_provided", "score": 3, "host": host, "reason": "user-provided material"}
    if not host:
        return {"tier": "unknown", "score": 1, "host": "", "reason": "missing source host"}
    if (
        _matches_host(host, _AUTHORITATIVE_HOSTS)
        or host.endswith(".gov")
        or host.endswith(".go.kr")
    ):
        return {"tier": "authoritative", "score": 4, "host": host, "reason": "government, standards, or primary-research host"}
    if host.endswith(".edu") or ".ac." in host or host.endswith(".edu.au"):
        return {"tier": "institutional", "score": 3, "host": host, "reason": "academic or institutional host"}
    if _matches_host(host, _LOW_QUALITY_HOSTS) or any(
        marker in host for marker in ("blog.", "cafe.", "forum.", "community.")
    ):
        return {"tier": "low", "score": 1, "host": host, "reason": "wiki, blog, or community host"}
    return {"tier": "general", "score": 2, "host": host, "reason": "unverified general web source"}


def summarize_source_quality(sources: list[Dict[str, Any]]) -> Dict[str, Any]:
    deduped: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        key = str(source.get("url") or source.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        grade = grade_source(source)
        deduped.append({
            "title": str(source.get("title") or grade["host"] or "Untitled"),
            "url": str(source.get("url") or ""),
            **grade,
        })
    counts = {tier: 0 for tier in ("authoritative", "institutional", "user_provided", "general", "low", "unknown")}
    for source in deduped:
        counts[source["tier"]] += 1
    average = round(sum(item["score"] for item in deduped) / len(deduped), 2) if deduped else None
    return {
        "total": len(deduped),
        "counts": counts,
        "average_score": average,
        "low_quality_count": counts["low"] + counts["unknown"],
        "strong_source_count": counts["authoritative"] + counts["institutional"],
        "sources": deduped,
    }


def _words(value: Any) -> set[str]:
    return {match.group(0).lower() for match in _WORD_RE.finditer(str(value or ""))}


def relevant_evidence_passages(
    section: Dict[str, Any], source: Dict[str, Any], limit: int = 3
) -> list[Dict[str, str]]:
    """Return short source passages ranked for one section.

    Search backends already cap page text. This second pass prevents the writer
    from receiving an arbitrary leading block when a more relevant sentence is
    available later in the captured text.
    """
    raw = str(source.get("summary") or source.get("snippet") or "").strip()
    if not raw:
        return []
    pieces = [
        " ".join(piece.split())
        for piece in re.split(r"(?<=[.!?。！？])\s+|\n+", raw)
        if len(" ".join(piece.split())) >= 25
    ]
    if not pieces:
        pieces = [raw[index : index + 280].strip() for index in range(0, len(raw), 280)]
    section_words = _words(
        " ".join(
            [str(section.get("title") or ""), str(section.get("purpose") or "")]
            + [str(point) for point in (section.get("key_points") or [])]
        )
    )
    ranked = sorted(
        enumerate(pieces),
        key=lambda item: (len(section_words & _words(item[1])), -item[0]),
        reverse=True,
    )[:limit]
    return [
        {"passage_id": f"P{rank + 1}", "text": text[:500]}
        for rank, (_original_index, text) in enumerate(ranked)
    ]


def validate_evidence_ledger(
    *,
    markdown: str,
    evidence: list[Any],
    sources: list[Dict[str, Any]],
    section: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate ledger entries against passages actually shown to the writer."""
    cited_ids = sorted({int(value) for value in _LOCAL_CITATION_RE.findall(markdown)})
    valid_entries: list[Dict[str, Any]] = []
    invalid_entries: list[Dict[str, Any]] = []
    verified_source_ids: set[int] = set()

    passage_maps: dict[int, dict[str, str]] = {}
    for source_id, source in enumerate(sources, start=1):
        passage_maps[source_id] = {
            passage["passage_id"]: passage["text"]
            for passage in relevant_evidence_passages(section, source)
        }

    for raw_entry in evidence[:12]:
        if not isinstance(raw_entry, dict):
            invalid_entries.append({"reason": "invalid_entry"})
            continue
        entry = {
            "claim": str(raw_entry.get("claim") or "").strip()[:300],
            "source_id": raw_entry.get("source_id"),
            "passage_id": str(raw_entry.get("passage_id") or "").strip(),
            "evidence": " ".join(str(raw_entry.get("evidence") or "").split())[:500],
        }
        try:
            source_id = int(entry["source_id"])
        except (TypeError, ValueError):
            invalid_entries.append({**entry, "reason": "invalid_source_id"})
            continue
        entry["source_id"] = source_id
        passages = passage_maps.get(source_id)
        if not entry["claim"] or not entry["evidence"]:
            invalid_entries.append({**entry, "reason": "missing_claim_or_evidence"})
            continue
        if passages is None:
            invalid_entries.append({**entry, "reason": "source_out_of_range"})
            continue
        passage = passages.get(entry["passage_id"])
        if not passage:
            invalid_entries.append({**entry, "reason": "unknown_passage"})
            continue
        normalized_evidence = " ".join(entry["evidence"].lower().split())
        normalized_passage = " ".join(passage.lower().split())
        if len(normalized_evidence) < 15 or normalized_evidence not in normalized_passage:
            invalid_entries.append({**entry, "reason": "evidence_not_in_passage"})
            continue
        valid_entries.append(entry)
        verified_source_ids.add(source_id)

    unverified_ids = [source_id for source_id in cited_ids if source_id not in verified_source_ids]
    return {
        "status": "valid" if not invalid_entries and not unverified_ids else "needs_review",
        "ledger_count": len(evidence),
        "valid_entry_count": len(valid_entries),
        "invalid_entry_count": len(invalid_entries),
        "cited_source_ids": cited_ids,
        "verified_source_ids": sorted(verified_source_ids),
        "unverified_citation_ids": unverified_ids,
        "verified_citation_percent": (
            round((len(cited_ids) - len(unverified_ids)) * 100 / len(cited_ids))
            if cited_ids
            else None
        ),
        "valid_entries": valid_entries,
        "invalid_entries": invalid_entries,
    }


def issue_section_ids(issues: list[Any]) -> list[str]:
    """Recover section ids even when a small model omitted revision_targets."""
    found: list[str] = []
    for issue in issues:
        values: list[Any] = []
        if isinstance(issue, dict):
            values.extend([issue.get("section_id"), issue.get("target_id")])
            values.extend(issue.get("affected_ids") or [])
            values.extend(issue.get("sections") or [])
            values.append(issue.get("description"))
        else:
            values.append(issue)
        for value in values:
            if value is None:
                continue
            text = str(value)
            matches = _SECTION_ID_RE.findall(text)
            if not matches and _SECTION_ID_RE.fullmatch(text.strip()):
                matches = [text.strip()]
            for section_id in matches:
                if section_id not in found:
                    found.append(section_id)
    return found


def citation_stats(section_drafts: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Measure cited body paragraphs; this is a signal, not a truth claim."""
    total = 0
    cited = 0
    for draft in section_drafts:
        markdown = str(draft.get("markdown") or "")
        for paragraph in re.split(r"\n\s*\n", markdown):
            text = paragraph.strip()
            if not text or text.startswith("#") or len(text) < 50:
                continue
            total += 1
            if _CITATION_RE.search(text):
                cited += 1
    return {
        "eligible_paragraphs": total,
        "cited_paragraphs": cited,
        "cited_paragraph_percent": round(cited * 100 / total) if total else None,
    }


def evidence_stats(section_drafts: list[Dict[str, Any]]) -> Dict[str, Any]:
    total_citations = 0
    verified_citations = 0
    invalid_entries = 0
    stale_sections = 0
    missing_ledgers = 0
    repair_attempted = 0
    repair_succeeded = 0
    for draft in section_drafts:
        repair = draft.get("evidence_repair")
        if isinstance(repair, dict) and repair.get("attempted"):
            repair_attempted += 1
            if repair.get("succeeded"):
                repair_succeeded += 1
        validation = draft.get("evidence_validation")
        if not isinstance(validation, dict):
            if _CITATION_RE.search(str(draft.get("markdown") or "")):
                missing_ledgers += 1
            continue
        if validation.get("status") == "stale":
            stale_sections += 1
            continue
        cited = validation.get("cited_source_ids") or []
        unverified = validation.get("unverified_citation_ids") or []
        total_citations += len(cited)
        verified_citations += max(len(cited) - len(unverified), 0)
        invalid_entries += int(validation.get("invalid_entry_count") or 0)
    return {
        "total_citations": total_citations,
        "verified_citations": verified_citations,
        "verified_citation_percent": (
            round(verified_citations * 100 / total_citations)
            if total_citations
            else None
        ),
        "invalid_entry_count": invalid_entries,
        "stale_section_count": stale_sections,
        "missing_ledger_section_count": missing_ledgers,
        "repair_attempted_section_count": repair_attempted,
        "repair_succeeded_section_count": repair_succeeded,
        "repair_failed_section_count": repair_attempted - repair_succeeded,
    }


def _draft_sentences(section_drafts: list[Dict[str, Any]]) -> list[Dict[str, str]]:
    sentences: list[Dict[str, str]] = []
    for draft_index, draft in enumerate(section_drafts):
        section = draft.get("section") if isinstance(draft.get("section"), dict) else {}
        section_id = str(section.get("id") or draft.get("section_id") or draft_index + 1)
        markdown = re.sub(
            r"```.*?```", " ", str(draft.get("markdown") or ""), flags=re.DOTALL
        )
        body_lines: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or re.match(r"^\|?\s*:?-{3,}", stripped):
                continue
            body_lines.append(re.sub(r"^\s*(?:[-*+] |\d+[.)] )", "", stripped))
        body = "\n".join(body_lines)
        # Accept both "claim [1]." and "claim. [1]" citation placement by
        # attaching a trailing marker to the sentence before splitting.
        body = re.sub(
            r"([.!?。！？])\s+(\[\[?\d+\]?\](?:\([^)]*\))?)",
            r" \2\1",
            body,
        )
        for raw in re.split(r"(?<=[.!?。！？])(?:\s+|$)|\n+", body):
            text = " ".join(raw.split()).strip()
            if len(text) < 30 or len(_words(text)) < 4:
                continue
            normalized = _normalize_sentence(text)
            if len(normalized) < 20:
                continue
            sentences.append(
                {
                    "section_id": section_id,
                    "text": text[:400],
                    "normalized": normalized,
                }
            )
            if len(sentences) >= 250:
                return sentences
    return sentences


def _normalize_sentence(text: str) -> str:
    value = _CITATION_RE.sub(" ", text.lower())
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[^0-9a-z가-힣%]+", " ", value)
    return " ".join(value.split())


def _comparison_words(text: str, *, remove_negation: bool = False) -> set[str]:
    value = _NEGATION_RE.sub(" ", text) if remove_negation else text
    return _words(value) - _COMPARISON_STOPWORDS


def _has_negation(text: str) -> bool:
    # "not only" adds emphasis rather than reversing the proposition.
    cleaned = re.sub(r"\bnot only\b", " ", text, flags=re.IGNORECASE)
    return bool(_NEGATION_RE.search(cleaned))


def sentence_quality_stats(
    section_drafts: list[Dict[str, Any]], *, high_stakes: bool = False
) -> Dict[str, Any]:
    """Find likely repetition, polarity conflicts, and unsupported absolutes.

    These are conservative flags for human review, not semantic verdicts. The
    bounded comparisons keep the check cheap and deterministic for local SLM
    workflows.
    """
    sentences = _draft_sentences(section_drafts)
    issues: list[Dict[str, Any]] = []
    duplicate_pairs = 0
    contradiction_pairs = 0

    for left_index, left in enumerate(sentences):
        left_words = _comparison_words(left["normalized"])
        for right in sentences[left_index + 1 :]:
            right_words = _comparison_words(right["normalized"])
            if min(len(left_words), len(right_words)) < 4:
                continue
            left_negated = _has_negation(left["text"])
            right_negated = _has_negation(right["text"])
            semantic_left = _comparison_words(left["normalized"], remove_negation=True)
            semantic_right = _comparison_words(right["normalized"], remove_negation=True)
            shared_semantic = len(semantic_left & semantic_right)
            semantic_overlap = shared_semantic / max(
                min(len(semantic_left), len(semantic_right)), 1
            )

            if left_negated != right_negated and shared_semantic >= 4 and semantic_overlap >= 0.75:
                contradiction_pairs += 1
                if len(issues) < 12:
                    issues.append(
                        {
                            "type": "possible_contradiction",
                            "section_ids": list(
                                dict.fromkeys([left["section_id"], right["section_id"]])
                            ),
                            "excerpts": [left["text"][:180], right["text"][:180]],
                        }
                    )
                continue

            shared = len(left_words & right_words)
            overlap = shared / max(len(left_words | right_words), 1)
            similarity = SequenceMatcher(
                None, left["normalized"], right["normalized"]
            ).ratio()
            if (
                left["normalized"] == right["normalized"]
                or (overlap >= 0.82 and similarity >= 0.88)
            ):
                duplicate_pairs += 1
                if len(issues) < 12:
                    issues.append(
                        {
                            "type": "duplicate",
                            "section_ids": list(
                                dict.fromkeys([left["section_id"], right["section_id"]])
                            ),
                            "excerpts": [left["text"][:180], right["text"][:180]],
                        }
                    )

    unsupported_overclaims = 0
    if high_stakes:
        for sentence in sentences:
            if _OVERCLAIM_RE.search(sentence["text"]) and not _CITATION_RE.search(
                sentence["text"]
            ):
                unsupported_overclaims += 1
                if len(issues) < 12:
                    issues.append(
                        {
                            "type": "unsupported_overclaim",
                            "section_ids": [sentence["section_id"]],
                            "excerpts": [sentence["text"][:180]],
                        }
                    )

    issue_count = duplicate_pairs + contradiction_pairs + unsupported_overclaims
    return {
        "analyzed_sentence_count": len(sentences),
        "duplicate_pair_count": duplicate_pairs,
        "possible_contradiction_count": contradiction_pairs,
        "unsupported_overclaim_count": unsupported_overclaims,
        "issue_count": issue_count,
        "issues": issues,
        "hidden_issue_count": max(issue_count - len(issues), 0),
    }


_INTRO_TITLE_TERMS = {
    "background", "context", "executive summary", "introduction", "objective", "overview",
    "purpose", "scope", "개요", "도입", "목적", "문제 제기", "배경", "범위", "서론",
    "핵심 요약",
}
_CONCLUSION_TITLE_TERMS = {
    "conclusion", "implications", "next steps", "outlook", "recommendation", "summary",
    "takeaway", "결론", "권고", "마무리", "시사점", "요약", "제언", "전망", "향후",
}


def _title_has_term(title: str, terms: set[str]) -> bool:
    lowered = title.lower()
    english_words = set(re.findall(r"[a-z]+", lowered))
    return any(
        term in lowered if not term.isascii() or " " in term else term in english_words
        for term in terms
    )


def _readability_thresholds(document_type: str) -> Dict[str, int | float]:
    if document_type == "blog_post":
        return {"english_words": 35, "korean_chars": 125, "paragraph_chars": 500, "paragraph_sentences": 4, "list_items": 8, "list_ratio": 0.6}
    if document_type == "presentation_script":
        return {"english_words": 30, "korean_chars": 110, "paragraph_chars": 550, "paragraph_sentences": 5, "list_items": 8, "list_ratio": 0.6}
    if document_type == "tech_doc":
        return {"english_words": 45, "korean_chars": 150, "paragraph_chars": 900, "paragraph_sentences": 8, "list_items": 14, "list_ratio": 0.75}
    if document_type == "essay":
        return {"english_words": 45, "korean_chars": 150, "paragraph_chars": 1000, "paragraph_sentences": 10, "list_items": 6, "list_ratio": 0.5}
    return {"english_words": 45, "korean_chars": 145, "paragraph_chars": 900, "paragraph_sentences": 8, "list_items": 10, "list_ratio": 0.65}


def structure_quality_stats(
    section_drafts: list[Dict[str, Any]], *, document_type: str = "report"
) -> Dict[str, Any]:
    """Return deterministic structure and readability review flags."""
    thresholds = _readability_thresholds(document_type)
    issues: list[Dict[str, Any]] = []
    long_sentences = 0
    long_paragraphs = 0
    list_heavy_sections = 0
    heading_issues = 0
    section_meta: list[Dict[str, str]] = []
    total_body_chars = 0

    def add_issue(issue: Dict[str, Any]) -> None:
        if len(issues) < 12:
            issues.append(issue)

    for draft_index, draft in enumerate(section_drafts):
        section = draft.get("section") if isinstance(draft.get("section"), dict) else {}
        section_id = str(section.get("id") or draft.get("section_id") or draft_index + 1)
        path = section.get("path") if isinstance(section.get("path"), list) else []
        title = " ".join(
            dict.fromkeys(
                [str(item).strip() for item in [*path, section.get("title")] if str(item).strip()]
            )
        )
        section_meta.append({"id": section_id, "title": title})
        markdown = str(draft.get("markdown") or "")
        without_code = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
        headings = [line.strip() for line in without_code.splitlines() if re.match(r"^#{1,6}\s+\S", line.strip())]
        if len(headings) != 1:
            heading_issues += 1
            add_issue(
                {
                    "type": "heading_structure",
                    "section_ids": [section_id],
                    "excerpts": [f"heading count: {len(headings)}"],
                }
            )

        body_lines = [
            line
            for line in without_code.splitlines()
            if not line.lstrip().startswith("#")
        ]
        body = "\n".join(body_lines)
        readable_body = _CITATION_RE.sub(" ", body)
        readable_body = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", readable_body)
        plain_body = " ".join(readable_body.split())
        total_body_chars += len(plain_body)

        list_lines = [
            line.strip()
            for line in body_lines
            if re.match(r"^\s*(?:[-*+] |\d+[.)] )", line)
        ]
        list_chars = sum(len(line) for line in list_lines)
        if (
            len(list_lines) >= int(thresholds["list_items"])
            and list_chars / max(len(plain_body), 1) >= float(thresholds["list_ratio"])
        ):
            list_heavy_sections += 1
            add_issue(
                {
                    "type": "list_heavy",
                    "section_ids": [section_id],
                    "excerpts": [f"{len(list_lines)} list items"],
                }
            )

        paragraphs = [
            " ".join(part.split())
            for part in re.split(r"\n\s*\n", readable_body)
            if " ".join(part.split())
        ]
        for paragraph in paragraphs:
            if paragraph.startswith(("|", "- ", "* ", "+ ")) or re.match(r"^\d+[.)] ", paragraph):
                continue
            paragraph_sentences = [
                value.strip()
                for value in re.split(r"(?<=[.!?。！？])(?:\s+|$)", paragraph)
                if value.strip()
            ]
            if (
                len(paragraph) > int(thresholds["paragraph_chars"])
                or len(paragraph_sentences) > int(thresholds["paragraph_sentences"])
            ):
                long_paragraphs += 1
                add_issue(
                    {
                        "type": "long_paragraph",
                        "section_ids": [section_id],
                        "excerpts": [paragraph[:180]],
                    }
                )
            for sentence in paragraph_sentences:
                hangul_count = len(re.findall(r"[가-힣]", sentence))
                english_word_count = len(re.findall(r"\b[A-Za-z]+\b", sentence))
                is_long = (
                    hangul_count >= 10
                    and len(sentence) > int(thresholds["korean_chars"])
                ) or (
                    hangul_count < 10
                    and english_word_count > int(thresholds["english_words"])
                )
                if is_long:
                    long_sentences += 1
                    add_issue(
                        {
                            "type": "long_sentence",
                            "section_ids": [section_id],
                            "excerpts": [sentence[:180]],
                        }
                    )

    missing_introduction = False
    missing_conclusion = False
    requires_bookends = document_type in {"report", "academic_paper"}
    if requires_bookends and len(section_meta) >= 4 and total_body_chars >= 1800:
        window = max(1, min(2, (len(section_meta) + 3) // 4))
        opening = section_meta[:window]
        closing = section_meta[-window:]
        missing_introduction = not any(
            _title_has_term(item["title"], _INTRO_TITLE_TERMS) for item in opening
        )
        missing_conclusion = not any(
            _title_has_term(item["title"], _CONCLUSION_TITLE_TERMS) for item in closing
        )
        if missing_introduction:
            add_issue(
                {
                    "type": "missing_introduction",
                    "section_ids": [item["id"] for item in opening],
                    "excerpts": [item["title"] for item in opening if item["title"]],
                }
            )
        if missing_conclusion:
            add_issue(
                {
                    "type": "missing_conclusion",
                    "section_ids": [item["id"] for item in closing],
                    "excerpts": [item["title"] for item in closing if item["title"]],
                }
            )

    issue_count = (
        long_sentences
        + long_paragraphs
        + list_heavy_sections
        + heading_issues
        + int(missing_introduction)
        + int(missing_conclusion)
    )
    return {
        "document_type": document_type,
        "long_sentence_count": long_sentences,
        "long_paragraph_count": long_paragraphs,
        "list_heavy_section_count": list_heavy_sections,
        "heading_issue_count": heading_issues,
        "missing_introduction": missing_introduction,
        "missing_conclusion": missing_conclusion,
        "issue_count": issue_count,
        "issues": issues,
        "hidden_issue_count": max(issue_count - len(issues), 0),
    }


def build_quality_summary(
    *,
    project_text: str,
    sources: list[Dict[str, Any]],
    section_drafts: list[Dict[str, Any]],
    continuity: Dict[str, Any] | None,
    rubric: Dict[str, Any] | None,
    citations_enabled: bool = True,
    sentence_repair: Dict[str, Any] | None = None,
    document_type: str = "report",
) -> Dict[str, Any]:
    source_quality = summarize_source_quality(sources)
    continuity = continuity or {}
    rubric = rubric or {}
    review_issues = list(continuity.get("issues") or []) + list(rubric.get("issues") or [])
    targets = list(dict.fromkeys(
        [str(item).strip() for item in (continuity.get("revision_targets") or []) + (rubric.get("revision_targets") or []) if str(item).strip()]
        + issue_section_ids(review_issues)
    ))
    criteria = [item for item in (rubric.get("criteria") or []) if isinstance(item, dict)]
    low_scores = [item for item in criteria if isinstance(item.get("min_score"), (int, float)) and item["min_score"] <= 3]
    review_incomplete = continuity.get("verdict") == "incomplete" or rubric.get("verdict") == "incomplete"
    high_stakes = is_high_stakes_topic(project_text)
    writing_quality = sentence_quality_stats(section_drafts, high_stakes=high_stakes)
    writing_quality["repair"] = sentence_repair or {}
    structure_quality = structure_quality_stats(
        section_drafts, document_type=document_type
    )
    warnings: list[str] = []
    if source_quality["low_quality_count"]:
        warnings.append("low_quality_sources")
    if high_stakes and source_quality["strong_source_count"] == 0:
        warnings.append("high_stakes_without_strong_sources")
    if review_issues or low_scores:
        warnings.append("review_findings")
    if review_incomplete:
        warnings.append("review_incomplete")
    if writing_quality["duplicate_pair_count"]:
        warnings.append("duplicate_content")
    if writing_quality["possible_contradiction_count"]:
        warnings.append("possible_contradictions")
    if writing_quality["unsupported_overclaim_count"]:
        warnings.append("unsupported_overclaims")
    if structure_quality["long_sentence_count"]:
        warnings.append("long_sentences")
    if structure_quality["long_paragraph_count"]:
        warnings.append("long_paragraphs")
    if structure_quality["list_heavy_section_count"]:
        warnings.append("list_heavy_sections")
    if structure_quality["heading_issue_count"]:
        warnings.append("heading_structure")
    if structure_quality["missing_introduction"]:
        warnings.append("missing_introduction")
    if structure_quality["missing_conclusion"]:
        warnings.append("missing_conclusion")
    citations = citation_stats(section_drafts) if citations_enabled else {
        "eligible_paragraphs": 0,
        "cited_paragraphs": 0,
        "cited_paragraph_percent": None,
    }
    evidence = evidence_stats(section_drafts) if citations_enabled else {
        "total_citations": 0,
        "verified_citations": 0,
        "verified_citation_percent": None,
        "invalid_entry_count": 0,
        "stale_section_count": 0,
        "missing_ledger_section_count": 0,
        "repair_attempted_section_count": 0,
        "repair_succeeded_section_count": 0,
        "repair_failed_section_count": 0,
    }
    if citations_enabled and citations["eligible_paragraphs"] and not citations["cited_paragraphs"]:
        warnings.append("no_cited_paragraphs")
    if evidence["invalid_entry_count"] or (
        evidence["total_citations"] > evidence["verified_citations"]
    ):
        warnings.append("unverified_evidence")
    if evidence["stale_section_count"] or evidence["missing_ledger_section_count"]:
        warnings.append("stale_evidence")
    status = "review_needed" if warnings else "ready"
    return {
        "status": status,
        "high_stakes": high_stakes,
        "source_quality": source_quality,
        "citations": citations,
        "evidence": evidence,
        "writing_quality": writing_quality,
        "structure_quality": structure_quality,
        "review": {
            "issue_count": len(review_issues),
            "revision_targets": targets[:10],
            "low_score_criteria": [str(item.get("key")) for item in low_scores],
            "incomplete": review_incomplete,
        },
        "warnings": list(dict.fromkeys(warnings)),
    }
