from app.services.evidence import (
    assemble_source_context,
    bigram_tokens,
    collapse_near_duplicates,
    overlap_score,
    split_passages,
)
from app.services.llm import select_section_sources
from app.services.quality import relevant_evidence_passages


def test_korean_bigram_tokens_overlap_across_inflection():
    # "인공지능은" and "인공지능의" differ only by the trailing particle, so
    # syllable bigrams still share the stem bigrams.
    a = bigram_tokens("인공지능은")
    b = bigram_tokens("인공지능의")
    assert a == {"인공", "공지", "지능", "능은"}
    assert len(a & b) == 3
    assert overlap_score(a, b) == 3


def test_split_passages_packs_within_range_and_hard_cuts():
    sentence = "This is a medium length sentence that carries enough characters to matter here. "
    passages = split_passages(sentence * 6)
    assert passages
    assert all(len(passage) <= 350 for passage in passages)
    assert any(200 <= len(passage) <= 350 for passage in passages)

    cut = split_passages("x" * 800, max_len=350)
    assert cut
    assert all(len(passage) <= 350 for passage in cut)
    assert max(len(passage) for passage in cut) == 350


def test_split_passages_keeps_short_text_sentence_level():
    text = (
        "First short sentence stands on its own line. "
        "Second short sentence also stands on its own. "
        "Third short sentence rounds out the summary."
    )
    passages = split_passages(text)
    assert len(passages) == 3


def test_collapse_near_duplicates_keeps_trusted_and_records_merged():
    body = "인공지능 모델은 대량의 데이터를 학습하여 예측 결과를 생성한다."
    sources = [
        {"url": "https://blog.naver.com/copy", "summary": body},
        {"url": "https://example.gov/original", "summary": body},
    ]
    kept = collapse_near_duplicates(sources)
    assert len(kept) == 1
    assert kept[0]["url"] == "https://example.gov/original"
    assert kept[0]["merged_urls"] == ["https://blog.naver.com/copy"]


def test_mmr_second_slot_prefers_diverse_source():
    section = {"title": "docker network bridge configuration"}
    chapter = [
        {
            "url": "https://ch.example.com",
            "summary": "docker network bridge overlay mesh tunnel vlan",
        }
    ]
    similar = {
        "url": "https://a.example.com",
        "summary": "docker network bridge overlay mesh alpha beta",
    }
    diverse = {
        "url": "https://b.example.com",
        "summary": "docker network bridge gamma delta epsilon zeta eta",
    }
    picked = select_section_sources(section, chapter, [similar, diverse], limit=2)
    assert picked[0]["url"] == "https://ch.example.com"
    # Both globals tie on section overlap, so MMR breaks the tie toward the one
    # least similar to the already-picked chapter source.
    assert picked[1]["url"] == "https://b.example.com"


def test_assemble_source_context_respects_budget_and_min_one_passage():
    long_body = "Sentence one has quite a few words to fill this passage space here. " * 12
    sources = [
        {"title": "Src A", "url": "https://a.example.com", "full_text": long_body},
        {"title": "Src B", "url": "https://b.example.com", "full_text": long_body},
    ]
    section = {"title": "words passage space"}

    tight = assemble_source_context(sources, section, budget_chars=200)
    assert "[1][trust=" in tight and "[2][trust=" in tight
    assert "[1.P1]" in tight and "[2.P1]" in tight
    # A tiny budget still guarantees one passage per source but no more.
    assert "[1.P2]" not in tight and "[2.P2]" not in tight

    generous = assemble_source_context(sources, section, budget_chars=5000)
    assert "[1.P2]" in generous


def test_relevant_passages_prefer_full_text_over_summary():
    section = {"title": "docker network bridge"}
    source = {
        "summary": "Unrelated gardening note about flowers and garden soil only.",
        "full_text": (
            "Intro about cooking recipes and kitchens. "
            "Docker network bridge mode connects containers on a single host. "
            "Closing note about travel plans and vacations."
        ),
    }
    passages = relevant_evidence_passages(section, source, limit=1)
    assert passages
    assert "Docker network bridge mode connects containers" in passages[0]["text"]
    assert "gardening" not in passages[0]["text"]
