from app.services.quality import (
    authoritative_search_queries,
    build_quality_summary,
    citation_stats,
    evidence_stats,
    grade_source,
    is_high_stakes_topic,
    issue_section_ids,
    relevant_evidence_passages,
    sentence_quality_stats,
    structure_quality_stats,
    summarize_source_quality,
    validate_evidence_ledger,
)


def test_high_stakes_detection_uses_whole_english_words_and_korean_terms():
    assert is_high_stakes_topic("환자 치료 안내")
    assert is_high_stakes_topic("medical treatment guide")
    assert not is_high_stakes_topic("illegal filename cleanup")


def test_authority_queries_are_domain_scoped_and_short():
    queries = authoritative_search_queries(
        "고혈압 진단과 치료 " + "긴검색어 " * 30,
        "환자 의료 안내",
    )
    assert queries[0].startswith("site:go.kr ")
    assert queries[1].startswith("site:ac.kr ")
    assert all(len(query) <= 100 for query in queries)


def test_source_grades_are_deterministic():
    assert grade_source({"url": "https://www.cdc.gov/topic"})["tier"] == "authoritative"
    assert grade_source({"url": "https://example.edu/paper"})["tier"] == "institutional"
    assert grade_source({"url": "https://blog.naver.com/example"})["tier"] == "low"
    assert grade_source({"url": "https://example.com/article"})["tier"] == "general"
    assert grade_source({"url": "https://www.bok.or.kr/report"})["tier"] == "authoritative"


def test_source_summary_dedupes_urls():
    summary = summarize_source_quality(
        [
            {"title": "A", "url": "https://who.int/a"},
            {"title": "A duplicate", "url": "https://who.int/a"},
            {"title": "B", "url": "https://namu.wiki/b"},
        ]
    )
    assert summary["total"] == 2
    assert summary["strong_source_count"] == 1
    assert summary["low_quality_count"] == 1


def test_issue_section_ids_recovers_structured_and_text_targets():
    assert issue_section_ids(
        [
            {"affected_ids": ["1.2", "1.3"], "description": "Overlap"},
            "Section 2.1 lacks evidence",
        ]
    ) == ["1.2", "1.3", "2.1"]


def test_citation_stats_counts_body_paragraphs_only():
    stats = citation_stats(
        [
            {
                "markdown": (
                    "### Heading\n\n"
                    "This is a sufficiently long factual paragraph with a citation [1] supporting it.\n\n"
                    "This second paragraph is also sufficiently long but has no citation marker at all."
                )
            }
        ]
    )
    assert stats["eligible_paragraphs"] == 2
    assert stats["cited_paragraphs"] == 1
    assert stats["cited_paragraph_percent"] == 50


def test_relevant_passages_prefer_section_terms_over_page_lead():
    passages = relevant_evidence_passages(
        {"title": "Docker network bridge"},
        {
            "summary": (
                "This unrelated introduction discusses gardening and flowers. "
                "Docker network bridge mode connects containers on one host. "
                "Another unrelated sentence discusses cooking and recipes."
            )
        },
        limit=1,
    )
    assert passages == [
        {
            "passage_id": "P1",
            "text": "Docker network bridge mode connects containers on one host.",
        }
    ]


def test_evidence_ledger_requires_exact_excerpt_and_valid_source_number():
    section = {"title": "Docker network bridge"}
    sources = [
        {
            "url": "https://example.gov/docker",
            "summary": "Docker network bridge mode connects containers on one host.",
        }
    ]
    valid = validate_evidence_ledger(
        markdown="### Docker\n\nBridge mode connects local containers [1].",
        evidence=[
            {
                "claim": "Bridge mode connects local containers",
                "source_id": 1,
                "passage_id": "P1",
                "evidence": "Docker network bridge mode connects containers on one host.",
            }
        ],
        sources=sources,
        section=section,
    )
    assert valid["status"] == "valid"
    assert valid["verified_citation_percent"] == 100

    invalid = validate_evidence_ledger(
        markdown="### Docker\n\nBridge mode connects local containers [1].",
        evidence=[
            {
                "claim": "Bridge mode connects every cloud",
                "source_id": 1,
                "passage_id": "P1",
                "evidence": "This sentence was never present in the source passage.",
            }
        ],
        sources=sources,
        section=section,
    )
    assert invalid["status"] == "needs_review"
    assert invalid["invalid_entries"][0]["reason"] == "evidence_not_in_passage"
    assert invalid["unverified_citation_ids"] == [1]


def test_evidence_stats_detects_stale_and_missing_ledgers():
    stats = evidence_stats(
        [
            {
                "markdown": "Claim [1].",
                "evidence_validation": {"status": "stale"},
                "evidence_repair": {"attempted": True, "succeeded": False},
            },
            {"markdown": "Another cited factual claim [[2]](https://example.com)."},
        ]
    )
    assert stats["stale_section_count"] == 1
    assert stats["missing_ledger_section_count"] == 1
    assert stats["repair_attempted_section_count"] == 1
    assert stats["repair_failed_section_count"] == 1


def test_sentence_quality_detects_repeated_content_across_sections():
    repeated = (
        "The deployment controller checks the desired state and updates every running "
        "instance until the configured version is active."
    )
    stats = sentence_quality_stats(
        [
            {"section": {"id": "1.1"}, "markdown": repeated},
            {"section": {"id": "2.1"}, "markdown": repeated},
        ]
    )
    assert stats["duplicate_pair_count"] == 1
    assert stats["issues"][0]["type"] == "duplicate"
    assert stats["issues"][0]["section_ids"] == ["1.1", "2.1"]


def test_sentence_quality_flags_opposing_polarity():
    stats = sentence_quality_stats(
        [
            {
                "section": {"id": "1.1"},
                "markdown": "This medicine is safe for all adult patients when used exactly as directed.",
            },
            {
                "section": {"id": "2.1"},
                "markdown": "This medicine is not safe for all adult patients when used exactly as directed.",
            },
        ]
    )
    assert stats["possible_contradiction_count"] == 1
    assert stats["duplicate_pair_count"] == 0


def test_high_stakes_overclaim_requires_missing_inline_citation():
    sentence = "This treatment is guaranteed to cure every patient without any risk."
    unsupported = sentence_quality_stats(
        [{"section": {"id": "1.1"}, "markdown": sentence}], high_stakes=True
    )
    supported = sentence_quality_stats(
        [
            {
                "section": {"id": "1.1"},
                "markdown": sentence.replace(".", " [1]."),
            }
        ],
        high_stakes=True,
    )
    assert unsupported["unsupported_overclaim_count"] == 1
    assert supported["unsupported_overclaim_count"] == 0

    citation_after_period = sentence_quality_stats(
        [{"section": {"id": "1.1"}, "markdown": f"{sentence} [1]"}],
        high_stakes=True,
    )
    assert citation_after_period["unsupported_overclaim_count"] == 0


def test_sentence_quality_warnings_make_summary_review_needed():
    repeated = (
        "This architecture sends every request through the gateway before routing it "
        "to the selected internal service."
    )
    summary = build_quality_summary(
        project_text="technical architecture",
        sources=[],
        section_drafts=[
            {"section": {"id": "1.1"}, "markdown": repeated},
            {"section": {"id": "2.1"}, "markdown": repeated},
        ],
        continuity={"verdict": "pass", "issues": []},
        rubric={"verdict": "pass", "issues": [], "criteria": []},
        citations_enabled=False,
    )
    assert summary["status"] == "review_needed"
    assert summary["writing_quality"]["issue_count"] == 1
    assert "duplicate_content" in summary["warnings"]


def test_structure_quality_detects_long_sentence_and_dense_blog_paragraph():
    long_sentence = "This sentence " + "contains another descriptive word " * 24 + "."
    dense_paragraph = " ".join(
        [
            "Readers need a short concrete example before moving to the next idea."
            for _ in range(5)
        ]
    )
    stats = structure_quality_stats(
        [
            {
                "section": {"id": "1.1", "title": "Opening"},
                "markdown": f"### Opening\n\n{long_sentence}\n\n{dense_paragraph}",
            }
        ],
        document_type="blog_post",
    )
    assert stats["long_sentence_count"] >= 1
    assert stats["long_paragraph_count"] >= 1


def test_structure_quality_detects_list_heavy_and_heading_problems():
    items = "\n".join(
        f"- Item {index} explains one small operational consideration in detail."
        for index in range(10)
    )
    stats = structure_quality_stats(
        [
            {
                "section": {"id": "1.1", "title": "Checklist"},
                "markdown": f"### Checklist\n\n{items}",
            },
            {
                "section": {"id": "2.1", "title": "Broken"},
                "markdown": "Body without its required section heading.",
            },
        ]
    )
    assert stats["list_heavy_section_count"] == 1
    assert stats["heading_issue_count"] == 1


def test_report_bookends_are_required_only_for_long_form_profiles():
    paragraph = (
        "This section develops one part of the analysis with enough context for the "
        "reader to understand the evidence and its practical meaning. " * 4
    )
    drafts = [
        {
            "section": {"id": f"{index}.1", "title": f"Analysis part {index}"},
            "markdown": f"### Analysis part {index}\n\n{paragraph}",
        }
        for index in range(1, 5)
    ]
    report = structure_quality_stats(drafts, document_type="report")
    technical = structure_quality_stats(drafts, document_type="tech_doc")
    assert report["missing_introduction"] is True
    assert report["missing_conclusion"] is True
    assert technical["missing_introduction"] is False
    assert technical["missing_conclusion"] is False


def test_report_bookend_titles_satisfy_structure_gate():
    paragraph = (
        "This section explains the topic using concrete context and a focused analysis "
        "that supports the document's overall decision. " * 4
    )
    titles = ["Introduction and scope", "Evidence", "Analysis", "Conclusion and next steps"]
    drafts = [
        {
            "section": {"id": f"{index}.1", "title": title},
            "markdown": f"### {title}\n\n{paragraph}",
        }
        for index, title in enumerate(titles, start=1)
    ]
    stats = structure_quality_stats(drafts, document_type="report")
    assert stats["missing_introduction"] is False
    assert stats["missing_conclusion"] is False


def test_high_stakes_quality_requires_strong_sources_and_honors_review_issues():
    summary = build_quality_summary(
        project_text="환자 진단과 치료 가이드",
        sources=[{"title": "Blog", "url": "https://blog.naver.com/post"}],
        section_drafts=[{"markdown": "### A\n\n충분히 긴 의료 설명 문단이지만 인용 근거가 포함되어 있지 않습니다. 독자가 사실로 오인할 수 있습니다."}],
        continuity={"verdict": "pass", "issues": [{"affected_ids": ["1.1"]}]},
        rubric={"verdict": "pass", "issues": [], "criteria": []},
    )
    assert summary["status"] == "review_needed"
    assert "low_quality_sources" in summary["warnings"]
    assert "high_stakes_without_strong_sources" in summary["warnings"]
    assert summary["review"]["revision_targets"] == ["1.1"]


def test_clean_quality_can_be_ready():
    summary = build_quality_summary(
        project_text="기술 개요",
        sources=[{"title": "Standard", "url": "https://example.gov/spec"}],
        section_drafts=[
            {
                "markdown": "### A\n\nThis sufficiently long paragraph is grounded in the supplied standard and cites it [1].",
                "evidence_validation": {
                    "status": "valid",
                    "cited_source_ids": [1],
                    "unverified_citation_ids": [],
                    "invalid_entry_count": 0,
                },
            }
        ],
        continuity={"verdict": "pass", "issues": []},
        rubric={"verdict": "pass", "issues": [], "criteria": []},
    )
    assert summary["status"] == "ready"
    assert summary["warnings"] == []
