from app.services.citations import format_sources_section, renumber_citations

SOURCE_A = {"title": "Alpha", "url": "https://a.example.com"}
SOURCE_B = {"title": "Beta", "url": "https://b.example.com"}
SOURCE_C = {"title": "Gamma", "url": "https://c.example.com"}


class TestRenumberCitations:
    def test_maps_local_markers_to_global_numbers(self):
        drafts = [
            {"markdown": "First claim [1] and second [2].", "sources": [SOURCE_A, SOURCE_B]},
            {"markdown": "Another claim [1].", "sources": [SOURCE_C]},
        ]
        renumbered, used = renumber_citations(drafts)
        assert renumbered[0]["markdown"] == (
            "First claim [[1]](https://a.example.com) and second [[2]](https://b.example.com)."
        )
        assert renumbered[1]["markdown"] == "Another claim [[3]](https://c.example.com)."
        assert used == [SOURCE_A, SOURCE_B, SOURCE_C]

    def test_deduplicates_repeated_sources_across_sections(self):
        drafts = [
            {"markdown": "See [1].", "sources": [SOURCE_A]},
            {"markdown": "See [1] again and [2].", "sources": [SOURCE_A, SOURCE_B]},
        ]
        renumbered, used = renumber_citations(drafts)
        assert renumbered[1]["markdown"] == (
            "See [[1]](https://a.example.com) again and [[2]](https://b.example.com)."
        )
        assert used == [SOURCE_A, SOURCE_B]

    def test_drops_markers_without_matching_source(self):
        drafts = [{"markdown": "Claim [1] and bogus [7].", "sources": [SOURCE_A]}]
        renumbered, used = renumber_citations(drafts)
        assert renumbered[0]["markdown"] == "Claim [[1]](https://a.example.com) and bogus ."
        assert used == [SOURCE_A]

    def test_handles_adjacent_markers(self):
        drafts = [{"markdown": "Claim [1][2].", "sources": [SOURCE_A, SOURCE_B]}]
        renumbered, _ = renumber_citations(drafts)
        assert renumbered[0]["markdown"] == (
            "Claim [[1]](https://a.example.com)[[2]](https://b.example.com)."
        )

    def test_leaves_markdown_links_and_years_alone(self):
        drafts = [
            {
                "markdown": "A [link](https://x.example.com) and year [2024] stay put.",
                "sources": [SOURCE_A],
            }
        ]
        renumbered, used = renumber_citations(drafts)
        assert renumbered[0]["markdown"] == (
            "A [link](https://x.example.com) and year [2024] stay put."
        )
        assert used == []

    def test_ignores_sources_without_url(self):
        drafts = [{"markdown": "See [1].", "sources": [{"title": "No URL"}, SOURCE_A]}]
        renumbered, used = renumber_citations(drafts)
        assert renumbered[0]["markdown"] == "See [[1]](https://a.example.com)."
        assert used == [SOURCE_A]

    def test_no_sources_strips_markers(self):
        drafts = [{"markdown": "Claim [1].", "sources": []}]
        renumbered, used = renumber_citations(drafts)
        assert renumbered[0]["markdown"] == "Claim ."
        assert used == []


class TestFormatSourcesSection:
    def test_numbers_match_input_order(self):
        section = format_sources_section([SOURCE_A, SOURCE_B])
        assert "1. [Alpha](https://a.example.com)" in section
        assert "2. [Beta](https://b.example.com)" in section
        assert section.startswith("\n\n## Sources\n\n")

    def test_empty_sources_render_nothing(self):
        assert format_sources_section([]) == ""
        assert format_sources_section([{"title": "no url"}]) == ""
