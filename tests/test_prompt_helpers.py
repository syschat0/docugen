from app.services.llm import (
    _clip,
    _clip_summary,
    select_relevant_sources,
    select_section_sources,
)


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
