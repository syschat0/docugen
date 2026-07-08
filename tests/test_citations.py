from app.services.citations import (
    author_date_citations,
    citation_markers,
    format_sources_section,
    global_citation_numbers,
    render_citations,
    renumber_citations,
)

SOURCE_A = {"title": "Alpha", "url": "https://a.example.com"}
SOURCE_B = {"title": "Beta", "url": "https://b.example.com"}
SOURCE_C = {"title": "Gamma", "url": "https://c.example.com"}
FILE_SOURCE = {"title": "My Notes", "url": "file://notes.txt"}


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


class TestAuthorDateCitations:
    def test_rewrites_markers_into_author_date_links(self):
        drafts = [
            {"markdown": "First claim [1] and second [2].", "sources": [SOURCE_A, SOURCE_B]},
            {"markdown": "Another claim [1].", "sources": [SOURCE_C]},
        ]
        rewritten, used = author_date_citations(drafts)
        assert rewritten[0]["markdown"] == (
            "First claim [(a.example.com, n.d.)](https://a.example.com) "
            "and second [(b.example.com, n.d.)](https://b.example.com)."
        )
        assert rewritten[1]["markdown"] == (
            "Another claim [(c.example.com, n.d.)](https://c.example.com)."
        )
        assert [s["url"] for s in used] == [
            "https://a.example.com",
            "https://b.example.com",
            "https://c.example.com",
        ]
        assert used[0]["citation_author"] == "a.example.com"
        assert used[0]["citation_date"] == "n.d."

    def test_same_site_sources_get_title_ordered_suffixes(self):
        beta = {"title": "Beta piece", "url": "https://same.example.com/beta"}
        alpha = {"title": "Alpha piece", "url": "https://same.example.com/alpha"}
        # Beta is cited first, but suffixes follow title order: Alpha -> a.
        drafts = [{"markdown": "See [1] then [2].", "sources": [beta, alpha]}]
        rewritten, used = author_date_citations(drafts)
        assert rewritten[0]["markdown"] == (
            "See [(same.example.com, n.d.-b)](https://same.example.com/beta) "
            "then [(same.example.com, n.d.-a)](https://same.example.com/alpha)."
        )
        by_url = {s["url"]: s for s in used}
        assert by_url["https://same.example.com/alpha"]["citation_date"] == "n.d.-a"
        assert by_url["https://same.example.com/beta"]["citation_date"] == "n.d.-b"

    def test_deduplicates_repeated_sources_across_sections(self):
        drafts = [
            {"markdown": "See [1].", "sources": [SOURCE_A]},
            {"markdown": "See [1] again.", "sources": [SOURCE_A]},
        ]
        rewritten, used = author_date_citations(drafts)
        assert rewritten[0]["markdown"] == rewritten[1]["markdown"].replace(" again", "")
        assert len(used) == 1

    def test_strips_www_and_drops_unmatched_markers(self):
        source = {"title": "W", "url": "https://www.example.com/page"}
        drafts = [{"markdown": "Claim [1] and bogus [7].", "sources": [source]}]
        rewritten, _ = author_date_citations(drafts)
        assert rewritten[0]["markdown"] == (
            "Claim [(example.com, n.d.)](https://www.example.com/page) and bogus ."
        )

    def test_file_reference_uses_title_as_author(self):
        drafts = [{"markdown": "See [1].", "sources": [FILE_SOURCE]}]
        rewritten, used = author_date_citations(drafts)
        assert rewritten[0]["markdown"] == "See [(My Notes, n.d.)](file://notes.txt)."
        assert used[0]["citation_author"] == "My Notes"


class TestRenderCitations:
    def test_dispatches_by_style(self):
        drafts = [{"markdown": "See [1].", "sources": [SOURCE_A]}]
        numeric, _ = render_citations(drafts, "numeric")
        author_date, _ = render_citations(drafts, "author_date")
        assert numeric[0]["markdown"] == "See [[1]](https://a.example.com)."
        assert author_date[0]["markdown"] == (
            "See [(a.example.com, n.d.)](https://a.example.com)."
        )


class TestFormatSourcesSection:
    def test_numbers_match_input_order(self):
        section = format_sources_section([SOURCE_A, SOURCE_B])
        assert "1. [Alpha](https://a.example.com)" in section
        assert "2. [Beta](https://b.example.com)" in section
        assert section.startswith("\n\n## Sources\n\n")

    def test_numeric_includes_site_and_access_date(self):
        section = format_sources_section(
            [SOURCE_A], accessed_at="2026-07-08T12:00:00+00:00"
        )
        assert (
            "1. [Alpha](https://a.example.com). a.example.com (accessed 2026-07-08)"
            in section
        )

    def test_numeric_file_reference_has_no_link(self):
        section = format_sources_section(
            [FILE_SOURCE], accessed_at="2026-07-08T12:00:00+00:00"
        )
        assert "1. My Notes (user-provided reference)" in section
        assert "file://" not in section

    def test_author_date_sorts_by_author_label(self):
        _, used = author_date_citations(
            [{"markdown": "See [1] and [2].", "sources": [SOURCE_B, SOURCE_A]}]
        )
        section = format_sources_section(
            used, style="author_date", accessed_at="2026-07-08T12:00:00+00:00"
        )
        alpha_line = "- a.example.com. (n.d.). [Alpha](https://a.example.com) (accessed 2026-07-08)"
        beta_line = "- b.example.com. (n.d.). [Beta](https://b.example.com) (accessed 2026-07-08)"
        assert alpha_line in section
        assert beta_line in section
        assert section.index(alpha_line) < section.index(beta_line)

    def test_author_date_computes_labels_for_uncited_fallback(self):
        # The uncited-research fallback list has no citation_author fields.
        section = format_sources_section([SOURCE_A], style="author_date")
        assert "- a.example.com. (n.d.). [Alpha](https://a.example.com)" in section

    def test_author_date_file_reference(self):
        section = format_sources_section([FILE_SOURCE], style="author_date")
        assert "- My Notes. (n.d.). (user-provided reference)" in section
        assert "file://" not in section

    def test_empty_sources_render_nothing(self):
        assert format_sources_section([]) == ""
        assert format_sources_section([{"title": "no url"}]) == ""
        assert format_sources_section([], style="author_date") == ""


class TestCitationMarkers:
    def test_collects_numeric_links(self):
        text = "Claim [[1]](https://a.example.com) and [[12]](https://b.example.com)."
        assert citation_markers(text) == {"1", "12"}

    def test_collects_author_date_links(self):
        text = (
            "Claim [(a.example.com, n.d.)](https://a.example.com) and "
            "[(same.example.com, n.d.-b)](https://same.example.com/beta)."
        )
        assert citation_markers(text) == {
            "a.example.com, n.d.",
            "same.example.com, n.d.-b",
        }

    def test_ignores_plain_markers_and_links(self):
        assert citation_markers("Bare [1] and [link](https://x.example.com).") == set()

    def test_empty(self):
        assert citation_markers("") == set()
        assert citation_markers(None) == set()


class TestGlobalCitationNumbers:
    def test_collects_link_numbers(self):
        text = "Claim [[1]](https://a.example.com) and [[12]](https://b.example.com)."
        assert global_citation_numbers(text) == {"1", "12"}

    def test_ignores_plain_markers_and_links(self):
        assert global_citation_numbers("Bare [1] and [link](https://x.example.com).") == set()

    def test_empty(self):
        assert global_citation_numbers("") == set()
        assert global_citation_numbers(None) == set()
