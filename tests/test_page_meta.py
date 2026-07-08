from app.services.page_meta import extract_page_meta, interpret_page_meta


class TestExtractPageMeta:
    def test_reads_meta_tags(self):
        html = """
        <html><head>
          <meta name="author" content="홍길동">
          <meta property="article:published_time" content="2024-03-15T09:00:00+09:00">
          <meta property="og:site_name" content="예제 뉴스">
        </head><body><p>본문</p></body></html>
        """
        assert extract_page_meta(html) == {
            "author": "홍길동",
            "published_year": "2024",
            "site_name": "예제 뉴스",
        }

    def test_json_ld_outranks_meta_tags(self):
        html = """
        <html><head>
          <meta name="author" content="meta-author">
          <script type="application/ld+json">
          {"@type": "NewsArticle", "author": {"@type": "Person", "name": "LD Author"},
           "datePublished": "2023-01-02", "publisher": {"@type": "Organization", "name": "LD Site"}}
          </script>
        </head><body></body></html>
        """
        assert extract_page_meta(html) == {
            "author": "LD Author",
            "published_year": "2023",
            "site_name": "LD Site",
        }

    def test_json_ld_graph_and_author_list(self):
        html = """
        <script type="application/ld+json">
        {"@graph": [
          {"@type": "WebSite", "name": "ignored"},
          {"@type": "BlogPosting", "author": [{"name": "A One"}, {"name": "B Two"}],
           "datePublished": "2022-11-30"}
        ]}
        </script>
        """
        meta = extract_page_meta(html)
        assert meta["author"] == "A One & B Two"
        assert meta["published_year"] == "2022"

    def test_three_authors_become_et_al(self):
        assert interpret_page_meta(
            {},
            ['{"@type": "Article", "author": ["A", "B", "C"]}'],
        )["author"] == "A et al."

    def test_rejects_url_authors(self):
        html = '<meta name="author" content="https://example.com/profile/kim">'
        assert "author" not in extract_page_meta(html)

    def test_broken_json_ld_is_ignored(self):
        html = """
        <script type="application/ld+json">{not json</script>
        <meta name="author" content="Fallback Author">
        """
        assert extract_page_meta(html)["author"] == "Fallback Author"

    def test_missing_everything_returns_empty(self):
        assert extract_page_meta("<html><body>plain</body></html>") == {}
        assert extract_page_meta("") == {}

    def test_year_requires_plausible_value(self):
        assert "published_year" not in interpret_page_meta({"date": "15th of March"}, [])
        assert interpret_page_meta({"date": "1999-12-31"}, [])["published_year"] == "1999"


class TestInterpretPageMeta:
    def test_only_non_empty_fields_returned(self):
        assert interpret_page_meta({"og:site_name": "Site"}, []) == {"site_name": "Site"}

    def test_meta_keys_case_insensitive(self):
        assert interpret_page_meta({"Author": "Kim"}, []) == {"author": "Kim"}
