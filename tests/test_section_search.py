from app.services.llm import best_overlap_score
from app.services.search import build_section_query


class TestBuildSectionQuery:
    def test_title_plus_first_key_point(self):
        section = {
            "title": "Market sizing",
            "key_points": ["TAM SAM SOM analysis", "growth"],
        }
        assert build_section_query(section) == "Market sizing TAM SAM SOM analysis"

    def test_title_only_when_key_point_duplicates_title(self):
        section = {"title": "Market sizing", "key_points": ["market sizing"]}
        assert build_section_query(section) == "Market sizing"

    def test_strips_sentence_prefix_before_colon(self):
        section = {"title": "서론: 인공지능의 역사", "key_points": []}
        assert build_section_query(section) == "인공지능의 역사"

    def test_empty_section(self):
        assert build_section_query({}) == ""

    def test_query_stays_short(self):
        section = {"title": "word " * 60, "key_points": []}
        assert len(build_section_query(section)) <= 100


class TestBestOverlapScore:
    SECTION = {"title": "electric vehicle batteries", "key_points": ["charging"]}

    def test_zero_when_no_overlap(self):
        sources = [{"url": "https://x", "title": "gardening tips", "snippet": "roses"}]
        assert best_overlap_score(self.SECTION, sources) == 0

    def test_counts_shared_keywords(self):
        sources = [
            {"url": "https://x", "title": "electric vehicle charging guide", "snippet": ""},
        ]
        assert best_overlap_score(self.SECTION, sources) >= 2

    def test_ignores_sources_without_url(self):
        sources = [{"title": "electric vehicle charging", "snippet": ""}]
        assert best_overlap_score(self.SECTION, sources) == 0

    def test_empty_sources(self):
        assert best_overlap_score(self.SECTION, []) == 0
