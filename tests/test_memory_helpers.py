from app.db.repositories import (
    _chapter_titles_from_plan,
    _local_chapter_digest,
    _section_title_context,
)

SECTIONS = [
    {"id": "1.1", "title": "Background"},
    {"id": "1.2", "title": "Scope"},
    {"id": "2.1", "title": "Install"},
    {"id": "2.2", "title": "Configure"},
    {"id": "3.1", "title": "Operate"},
]

CHAPTER_TITLES = {"1": "Intro", "2": "Setup", "3": "Operations"}


class TestSectionTitleContext:
    def test_siblings_full_other_chapters_compressed(self):
        titles = _section_title_context(SECTIONS[2], SECTIONS, CHAPTER_TITLES)
        assert titles == [
            "1 Intro (entire chapter)",
            "2.2 Configure",
            "3 Operations (entire chapter)",
        ]

    def test_excludes_current_section(self):
        titles = _section_title_context(SECTIONS[0], SECTIONS, CHAPTER_TITLES)
        assert "1.1 Background" not in titles
        assert "1.2 Scope" in titles

    def test_each_other_chapter_listed_once(self):
        titles = _section_title_context(SECTIONS[4], SECTIONS, CHAPTER_TITLES)
        assert titles.count("2 Setup (entire chapter)") == 1
        assert titles.count("1 Intro (entire chapter)") == 1


class TestChapterTitlesFromPlan:
    def test_maps_ids_to_titles(self):
        plan = {
            "outline_tree": [
                {"id": "1", "title": "Intro", "children": []},
                {"id": "2", "title": "Setup", "children": []},
                "junk",
            ]
        }
        assert _chapter_titles_from_plan(plan) == {"1": "Intro", "2": "Setup"}

    def test_empty_plan(self):
        assert _chapter_titles_from_plan({}) == {}


class TestLocalChapterDigest:
    SUMMARIES = [
        {
            "section_id": "1.1",
            "summary": "Defined the problem.",
            "claims": ["c1", "c2", "c3"],
            "terms": ["t1", "t2", "t3", "t4", "t5"],
        },
        {
            "section_id": "1.2",
            "summary": "Set the scope.",
            "claims": ["c4", "c5", "c6"],
            "terms": ["t6", "t7", "t8", "t9"],
        },
    ]

    def test_joins_summaries_and_caps_lists(self):
        digest = _local_chapter_digest("1", "Intro", self.SUMMARIES)
        assert digest["chapter_id"] == "1"
        assert digest["title"] == "Intro"
        assert "Defined the problem." in digest["digest"]
        assert "Set the scope." in digest["digest"]
        assert len(digest["claims"]) == 5
        assert len(digest["terms"]) == 8

    def test_empty_summaries(self):
        digest = _local_chapter_digest("2", "Setup", [])
        assert digest["digest"] == ""
        assert digest["claims"] == []
