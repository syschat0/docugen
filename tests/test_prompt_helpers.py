import json
from types import SimpleNamespace

from app.services import llm
from app.services.llm import (
    _clip,
    _clip_summary,
    repair_section_evidence,
    repair_sentence_quality_sections,
    select_relevant_sources,
    select_section_sources,
    write_section_with_summary,
)
from app.services.quality import sentence_quality_stats


class TestClip:
    def test_short_text_unchanged(self):
        assert _clip("hello world", 20) == "hello world"

    def test_collapses_whitespace(self):
        assert _clip("a\n b\t c", 20) == "a b c"

    def test_truncates_with_ellipsis(self):
        result = _clip("x" * 50, 10)
        assert len(result) == 11
        assert result.endswith("…")

    def test_none_becomes_empty(self):
        assert _clip(None, 10) == ""


class TestClipSummary:
    def test_caps_all_fields(self):
        summary = {
            "section_id": "1.1",
            "summary": "s" * 500,
            "claims": [f"claim {i}" * 30 for i in range(10)],
            "terms": ["t" * 100] * 20,
            "open_threads": ["o" * 200] * 10,
            "next_section_handoff": "h" * 500,
        }
        clipped = _clip_summary(summary)
        assert len(clipped["summary"]) <= 201
        assert len(clipped["claims"]) == 5
        assert all(len(c) <= 81 for c in clipped["claims"])
        assert len(clipped["terms"]) == 8
        assert len(clipped["open_threads"]) == 3
        assert len(clipped["next_section_handoff"]) <= 151

    def test_none_summary(self):
        clipped = _clip_summary(None)
        assert clipped["summary"] == ""
        assert clipped["claims"] == []


class TestSelectRelevantSources:
    SOURCES = [
        {"title": "Docker 설치 가이드", "url": "https://a.com", "snippet": "docker 설치 방법"},
        {"title": "Kubernetes 입문", "url": "https://b.com", "snippet": "쿠버네티스 클러스터"},
        {"title": "Docker 네트워크 심화", "url": "https://c.com", "summary": "docker 네트워크 브리지 설정"},
    ]

    def test_prefers_keyword_overlap(self):
        section = {"title": "Docker 네트워크 구성", "key_points": ["브리지", "네트워크"]}
        picked = select_relevant_sources(section, self.SOURCES, limit=1)
        assert picked[0]["url"] == "https://c.com"

    def test_returns_all_when_under_limit(self):
        section = {"title": "anything"}
        assert select_relevant_sources(section, self.SOURCES[:2], limit=2) == self.SOURCES[:2]

    def test_skips_sources_without_url(self):
        section = {"title": "Docker"}
        sources = [{"title": "Docker", "snippet": "docker"}] + self.SOURCES
        picked = select_relevant_sources(section, sources, limit=3)
        assert all(s.get("url") for s in picked)

    def test_empty_sources(self):
        assert select_relevant_sources({"title": "x"}, [], limit=2) == []


class TestSelectSectionSources:
    SECTION = {"title": "Docker 네트워크 구성", "key_points": ["브리지", "네트워크"]}
    CHAPTER_RELEVANT = {
        "title": "Docker 네트워크 개요",
        "url": "https://ch1.com",
        "summary": "docker 네트워크 기본",
    }
    CHAPTER_IRRELEVANT = {
        "title": "요리 레시피",
        "url": "https://ch2.com",
        "snippet": "김치찌개 만들기",
    }
    GLOBAL_STRONG = {
        "title": "Docker 네트워크 심화",
        "url": "https://g1.com",
        "summary": "docker 네트워크 브리지 설정",
    }
    GLOBAL_WEAK = {
        "title": "Docker 설치",
        "url": "https://g2.com",
        "snippet": "docker 설치 방법",
    }

    def test_relevant_chapter_source_beats_stronger_global(self):
        picked = select_section_sources(
            self.SECTION,
            [self.CHAPTER_RELEVANT],
            [self.GLOBAL_STRONG, self.GLOBAL_WEAK],
            limit=2,
        )
        assert picked[0]["url"] == "https://ch1.com"
        assert picked[1]["url"] == "https://g1.com"

    def test_irrelevant_chapter_sources_do_not_crowd_out_global(self):
        picked = select_section_sources(
            self.SECTION,
            [self.CHAPTER_IRRELEVANT],
            [self.GLOBAL_STRONG, self.GLOBAL_WEAK],
            limit=2,
        )
        assert [source["url"] for source in picked] == ["https://g1.com", "https://g2.com"]

    def test_deduplicates_by_url(self):
        duplicate = {**self.CHAPTER_RELEVANT}
        picked = select_section_sources(
            self.SECTION,
            [self.CHAPTER_RELEVANT],
            [duplicate, self.GLOBAL_WEAK],
            limit=2,
        )
        assert [source["url"] for source in picked] == ["https://ch1.com", "https://g2.com"]

    def test_falls_back_to_combined_pool_when_no_overlap_anywhere(self):
        picked = select_section_sources(
            {"title": "완전히 다른 주제"},
            [self.CHAPTER_IRRELEVANT],
            [self.GLOBAL_WEAK],
            limit=2,
        )
        assert len(picked) == 2

    def test_skips_sources_without_url(self):
        picked = select_section_sources(
            self.SECTION,
            [{"title": "Docker 네트워크", "summary": "docker 네트워크"}],
            [self.GLOBAL_WEAK],
            limit=2,
        )
        assert [source["url"] for source in picked] == ["https://g2.com"]

    def test_source_trust_breaks_relevance_ties(self):
        equally_relevant = [
            {
                "title": "Docker network guide",
                "url": "https://blog.naver.com/docker",
                "summary": "docker network bridge",
            },
            {
                "title": "Docker network standard",
                "url": "https://example.gov/docker",
                "summary": "docker network bridge",
            },
        ]
        picked = select_section_sources(self.SECTION, [], equally_relevant, limit=2)
        assert picked[0]["url"] == "https://example.gov/docker"

    def test_high_stakes_section_prioritizes_relevant_authority_over_chapter_blog(self):
        section = {"title": "Patient treatment", "key_points": ["clinical evidence"]}
        chapter_blog = {
            "title": "Patient treatment evidence",
            "url": "https://medium.com/treatment",
            "summary": "patient treatment clinical evidence",
        }
        global_authority = {
            "title": "Patient treatment evidence",
            "url": "https://nih.gov/treatment",
            "summary": "patient treatment clinical evidence",
        }
        picked = select_section_sources(
            section, [chapter_blog], [global_authority], limit=2
        )
        assert picked[0]["url"] == "https://nih.gov/treatment"


def test_section_writer_requests_and_returns_evidence_ledger(monkeypatch):
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[-1]["content"]
        return (
            json.dumps(
                {
                    "markdown": "### 1.1 Docker network\n\nBridge mode connects containers [1].",
                    "summary": {
                        "section_id": "1.1",
                        "summary": "Bridge mode overview",
                        "claims": ["Bridge mode connects containers"],
                        "terms": ["bridge mode"],
                        "open_threads": [],
                        "next_section_handoff": "Continue to routing.",
                    },
                    "evidence": [
                        {
                            "claim": "Bridge mode connects containers",
                            "source_id": 1,
                            "passage_id": "P1",
                            "evidence": "Docker network bridge mode connects containers on one host.",
                        }
                    ],
                }
            ),
            None,
        )

    monkeypatch.setattr(llm, "_chat_content", fake_chat)
    markdown, summary, _ = write_section_with_summary(
        SimpleNamespace(title="Docker guide"),
        {"topic": "Docker", "style": "formal"},
        {"id": "1.1", "title": "Docker network", "key_points": ["bridge mode"]},
        None,
        [
            {
                "title": "Docker standard",
                "url": "https://example.gov/docker",
                "summary": "Docker network bridge mode connects containers on one host.",
            }
        ],
        [],
    )
    assert "[1.P1] Docker network bridge mode" in captured["prompt"]
    assert "[1][trust=authoritative]" in captured["prompt"]
    assert "decision_logic" in captured["prompt"]
    assert summary["evidence"][0]["source_id"] == 1
    assert set(summary["memory"]) == {"findings", "decision_logic", "constraints"}
    assert "[1]" in markdown


def test_evidence_repair_returns_replacement_ledger(monkeypatch):
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[-1]["content"]
        return (
            json.dumps(
                {
                    "markdown": "### 1.1 Docker\n\nBridge mode connects containers [1].",
                    "evidence": [
                        {
                            "claim": "Bridge mode connects containers",
                            "source_id": 1,
                            "passage_id": "P1",
                            "evidence": "Docker bridge mode connects containers on one host.",
                        }
                    ],
                }
            ),
            {"total_tokens": 100},
        )

    monkeypatch.setattr(llm, "_chat_content", fake_chat)
    markdown, evidence, usage = repair_section_evidence(
        SimpleNamespace(title="Docker guide"),
        {"style": "formal"},
        {"id": "1.1", "title": "Docker"},
        "### 1.1 Docker\n\nUnsupported cloud claim [1].",
        [
            {
                "title": "Docker standard",
                "url": "https://example.gov/docker",
                "summary": "Docker bridge mode connects containers on one host.",
            }
        ],
        {"unverified_citation_ids": [1]},
    )
    assert "Do not merely" in captured["prompt"]
    assert evidence[0]["passage_id"] == "P1"
    assert "Bridge mode" in markdown
    assert usage == {"total_tokens": 100}


def test_sentence_quality_repair_accepts_only_document_level_improvement(monkeypatch):
    repeated = (
        "The deployment controller checks the desired state and updates every running "
        "instance until the configured version is active."
    )
    drafts = [
        {"section": {"id": "1.1", "title": "Overview"}, "markdown": f"### 1.1 Overview\n\n{repeated}", "sources": []},
        {"section": {"id": "2.1", "title": "Operations"}, "markdown": f"### 2.1 Operations\n\n{repeated}", "sources": []},
    ]

    def fake_chat(_messages):
        return (
            json.dumps(
                {
                    "markdown": (
                        "### 2.1 Operations\n\nThe operations section explains rollback "
                        "monitoring and alert thresholds for failed deployments."
                    ),
                    "evidence": [],
                }
            ),
            {"total_tokens": 50},
        )

    monkeypatch.setattr(llm, "_chat_content", fake_chat)
    repaired, report, usage = repair_sentence_quality_sections(
        SimpleNamespace(title="Deployment guide"),
        {"style": "formal"},
        drafts,
        sentence_quality_stats(drafts),
        limit=1,
    )
    assert repaired[1]["markdown"].startswith("### 2.1 Operations")
    assert report["initial_issue_count"] == 1
    assert report["final_issue_count"] == 0
    assert report["repaired_section_count"] == 1
    assert usage == {"section_calls": [{"section_id": "2.1", "total_tokens": 50}]}


def test_sentence_quality_repair_rejects_dropped_citation(monkeypatch):
    repeated = (
        "The treatment protocol reduces symptoms for selected adult patients under "
        "specialist monitoring [1]."
    )
    drafts = [
        {"section": {"id": "1.1"}, "markdown": f"### 1.1 A\n\n{repeated}", "sources": []},
        {"section": {"id": "2.1"}, "markdown": f"### 2.1 B\n\n{repeated}", "sources": []},
    ]
    monkeypatch.setattr(
        llm,
        "_chat_content",
        lambda _messages: (
            json.dumps(
                {
                    "markdown": "### 2.1 B\n\nThis section now discusses monitoring only.",
                    "evidence": [],
                }
            ),
            None,
        ),
    )
    repaired, report, _usage = repair_sentence_quality_sections(
        SimpleNamespace(title="Medical guide"),
        {"style": "formal"},
        drafts,
        sentence_quality_stats(drafts, high_stakes=True),
        high_stakes=True,
        limit=1,
    )
    assert repaired == drafts
    assert report["repaired_section_count"] == 0
    assert "citation markers" in report["results"][0]["reason"]
