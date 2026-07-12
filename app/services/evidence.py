"""SLM-friendly evidence compression and selection helpers.

Search backends now keep a longer cleaned page body (``full_text``) instead of
only a truncated lead. These helpers turn that body into short, relevant, and
non-redundant passages so a small local model receives compact context under a
fixed character budget.

Only the standard library is used, matching the rest of this codebase. Korean
matching relies on syllable bigrams so inflected forms (for example the topic
marker variants "인공지능은" and "인공지능의") still overlap.
"""

from __future__ import annotations

import re


_WORD_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_HANGUL_RE = re.compile(r"[가-힣]")
_DIGITS_RE = re.compile(r"\d+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")

# Passages are packed toward this lower bound so they land in the 200-350 char
# range that reads well for a small model; a text shorter than this stays split
# per sentence so a brief summary still yields sentence-level candidates.
_PASSAGE_SOFT_MIN = 200


def bigram_tokens(text: str) -> set[str]:
    """Tokenize text into overlap-friendly units.

    ASCII/numeric words become one lowercased whole token; a word containing
    Hangul is broken into consecutive syllable bigrams (a single-syllable word
    keeps that syllable). This lets inflected Korean forms share tokens.
    """
    tokens: set[str] = set()
    for match in _WORD_RE.finditer(str(text or "")):
        word = match.group(0)
        if _DIGITS_RE.fullmatch(word):
            tokens.add(word)
        elif _HANGUL_RE.search(word):
            lowered = word.lower()
            if len(lowered) == 1:
                tokens.add(lowered)
            else:
                for index in range(len(lowered) - 1):
                    tokens.add(lowered[index : index + 2])
        else:
            tokens.add(word.lower())
    return tokens


def overlap_score(a: set[str], b: set[str]) -> float:
    """Shared token count with a 0.5 bonus per shared numeric token.

    Numbers carry more meaning than ordinary words, so a shared figure nudges a
    passage up the ranking.
    """
    shared = a & b
    bonus = 0.5 * sum(1 for token in shared if _DIGITS_RE.fullmatch(token))
    return len(shared) + bonus


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets (0.0 when both are empty)."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def split_passages(text: str, max_len: int = 350) -> list[str]:
    """Split text into compact passages of up to ``max_len`` characters.

    Newlines are honored first (paragraph boundaries), then sentence boundaries.
    Sentences are packed greedily and a passage is flushed once it reaches the
    soft lower bound so passages land in the 200-350 char range. A single
    sentence longer than ``max_len`` is hard-cut. Fragments under 25 chars are
    dropped. When the whole text is shorter than the soft lower bound, each
    sentence is kept separate so a short summary still yields several candidates.
    """
    sentences: list[str] = []
    for block in re.split(r"\n+", str(text or "")):
        block = " ".join(block.split())
        if not block:
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(block):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > max_len:
                for start in range(0, len(sentence), max_len):
                    chunk = sentence[start : start + max_len].strip()
                    if chunk:
                        sentences.append(chunk)
            else:
                sentences.append(sentence)

    soft_min = min(_PASSAGE_SOFT_MIN, max_len)
    passages: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        add_len = len(sentence) + (1 if current else 0)
        if current and current_len + add_len > max_len:
            passages.append(" ".join(current))
            current = []
            current_len = 0
            add_len = len(sentence)
        current.append(sentence)
        current_len += add_len
        if current_len >= soft_min:
            passages.append(" ".join(current))
            current = []
            current_len = 0
    if current:
        if passages:
            passages.append(" ".join(current))
        else:
            # Whole text stayed under the soft lower bound: keep sentences apart.
            passages.extend(current)
    return [passage for passage in passages if len(passage) >= 25]


def rank_passages(section_text: str, passages: list[str], limit: int) -> list[str]:
    """Rank passages by overlap with the section, keeping input order on ties."""
    section_tokens = bigram_tokens(section_text)
    ranked = sorted(
        enumerate(passages),
        key=lambda item: (overlap_score(section_tokens, bigram_tokens(item[1])), -item[0]),
        reverse=True,
    )
    return [passage for _index, passage in ranked[:limit]]


def collapse_near_duplicates(
    sources: list[dict], threshold: float = 0.6
) -> list[dict]:
    """Drop near-duplicate sources, keeping the more trustworthy one.

    Two sources whose bigram tokens have Jaccard similarity >= ``threshold`` are
    treated as duplicates. The survivor is the one graded higher by
    ``quality.grade_source`` (ties keep the earlier source), and it records the
    dropped urls under ``merged_urls`` so downstream steps stay explainable.
    """
    from app.services.quality import grade_source

    kept: list[dict] = []
    kept_tokens: list[set[str]] = []
    kept_scores: list[int] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        text = str(
            source.get("full_text")
            or source.get("summary")
            or source.get("snippet")
            or ""
        )
        tokens = bigram_tokens(text)
        score = int(grade_source(source).get("score", 0))
        duplicate_index = None
        if tokens:
            for index, other_tokens in enumerate(kept_tokens):
                if other_tokens and jaccard(tokens, other_tokens) >= threshold:
                    duplicate_index = index
                    break
        if duplicate_index is None:
            kept.append(source)
            kept_tokens.append(tokens)
            kept_scores.append(score)
            continue
        winner = kept[duplicate_index]
        if score > kept_scores[duplicate_index]:
            loser_url = str(winner.get("url") or "")
            source["merged_urls"] = _record_merged(source, winner, loser_url)
            kept[duplicate_index] = source
            kept_tokens[duplicate_index] = tokens
            kept_scores[duplicate_index] = score
        else:
            loser_url = str(source.get("url") or "")
            winner["merged_urls"] = _record_merged(winner, source, loser_url)
    return kept


def _record_merged(winner: dict, loser: dict, loser_url: str) -> list[str]:
    # Carry any urls the loser had already absorbed and dedupe so repeated
    # collapse passes over the same reused source dicts stay idempotent.
    merged = list(winner.get("merged_urls") or [])
    merged.extend(loser.get("merged_urls") or [])
    if loser_url:
        merged.append(loser_url)
    return list(dict.fromkeys(url for url in merged if url))


def _clip_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def assemble_source_context(
    sources: list[dict], section: dict | None, budget_chars: int
) -> str:
    """Build the writer's source block under a fixed character budget.

    Every selected source contributes a header line and at least one passage.
    Remaining passages are added round-robin (each source's next passage in
    turn) until the block would exceed ``budget_chars``. Passages come from
    ``quality.relevant_evidence_passages`` so their ids and text match the
    evidence ledger validator exactly.
    """
    from app.services.quality import grade_source, relevant_evidence_passages

    usable = [source for source in sources if isinstance(source, dict)]
    if not usable:
        return "- No sources available."

    headers: list[str] = []
    summary_lines: list[str | None] = []
    passage_lines: list[list[str]] = []
    for index, source in enumerate(usable, start=1):
        grade = grade_source(source)
        headers.append(
            f"[{index}][trust={grade['tier']}] "
            f"{_clip_text(source.get('title'), 80)} - {source.get('url', '')}"
        )
        # The judge's summary is a non-citable helper line: it uses a "(summary)"
        # label rather than an "[n.Pk]" id so LLM-generated text can never pose as
        # a verifiable evidence passage. key_facts are stored on the artifact only
        # and are deliberately never rendered here.
        evaluation = source.get("eval")
        summary_text = (
            _clip_text(evaluation.get("summary"), 160)
            if isinstance(evaluation, dict)
            else ""
        )
        summary_lines.append(f"    (summary) {summary_text}" if summary_text else None)
        passages = relevant_evidence_passages(section or {}, source)
        passage_lines.append(
            [f"    [{index}.{passage['passage_id']}] {passage['text']}" for passage in passages]
        )

    included: list[list[str]] = [[] for _ in usable]
    total = sum(len(header) + 1 for header in headers)
    # Summary helper lines always render, so charge them to the budget up front
    # like headers before the round-robin fills remaining space with passages.
    total += sum(len(line) + 1 for line in summary_lines if line)
    # Guarantee one passage per source, even if it slightly overruns the budget.
    for source_index, lines in enumerate(passage_lines):
        if lines:
            included[source_index].append(lines[0])
            total += len(lines[0]) + 1

    max_rounds = max((len(lines) for lines in passage_lines), default=0)
    stop = False
    for round_index in range(1, max_rounds):
        for source_index, lines in enumerate(passage_lines):
            if round_index >= len(lines):
                continue
            line = lines[round_index]
            if total + len(line) + 1 > budget_chars:
                stop = True
                break
            included[source_index].append(line)
            total += len(line) + 1
        if stop:
            break

    out: list[str] = []
    for source_index, header in enumerate(headers):
        out.append(header)
        if summary_lines[source_index]:
            out.append(summary_lines[source_index])
        out.extend(included[source_index])
    return "\n".join(out) or "- No sources available."
