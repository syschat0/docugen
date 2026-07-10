# LLM Document Agent

Agent-based document generation system. The current MVP provides a FastAPI
backend, SQLite persistence, and project creation/listing APIs. The database
schema is prepared for later workflow threads, user questions, artifacts,
summaries, and agent run logs.

## Local Development

```bat
.\scripts\setup.bat
.\scripts\run-api.bat
```

Open the UI at:

```text
http://127.0.0.1:8000/ui/
```

`setup.bat` creates or repairs the project-local `.venv`, installs
dependencies, copies `.env.example` to `.env` when needed, and initializes the
SQLite database.

Run checks:

```bat
.\scripts\check.bat
.\scripts\smoke-api.bat
```

Initialize the SQLite database only:

```bat
.\scripts\init-db.bat
```

Health check:

```text
GET /
GET /ui/
GET /health
```

Project APIs:

```text
POST /projects
GET /projects
GET /projects/{project_id}
DELETE /projects/{project_id}
POST /projects/{project_id}/run

POST /projects/{project_id}/questions
GET /projects/{project_id}/questions
GET /projects/{project_id}/questions/{question_id}
POST /projects/{project_id}/questions/{question_id}/answer

POST /projects/{project_id}/artifacts
GET /projects/{project_id}/artifacts
GET /projects/{project_id}/artifacts/{artifact_id}
```

Example create payload:

```json
{
  "title": "Market research brief",
  "initial_request": "Create a structured document about the target market."
}
```

## Current Scope

- FastAPI app startup with database initialization
- Static web UI served at `/ui/`
- SQLite schema for project and workflow metadata
- Project create/list/read endpoints
- Project delete endpoint with related workflow data cleanup
- Staged LLM writing pipeline with progress tracking
- Pending question create/list/read/answer endpoints
- Artifact create/list/read endpoints
- Batch scripts for setup, API run, DB initialization, checks, and smoke test

## Start Writing

1. Run the API:

```bat
.\scripts\run-api.bat
```

2. Open the UI:

```text
http://127.0.0.1:8000/ui/
```

3. Create or select a project, then click `Start Writing`.
4. If the LLM needs more context, answer the generated questions.
5. Click `Start Writing` again to generate the document with those answers.

When `LLM_ENABLED=true`, the workflow calls the configured OpenAI-compatible
chat completions endpoint. The first run asks material intake questions when
the request is too vague. After answers are saved, the next run incorporates
those answers and runs a staged writing pipeline:

The core writing model is hierarchical:

1. Create a high-level outline for the topic.
2. Expand each outline node into subtopics or structural child nodes.
3. Keep subdividing broad nodes until every leaf node is small enough to write
   with focused context.
4. Generate content for each writable leaf node.
5. Insert the generated leaf content back into the full outline tree to produce
   the final Markdown document.

```text
intake -> research -> source_summary -> brief -> outline -> outline_review
       -> section_plan -> section_plan_review -> chapter_research
       -> section_writing -> section_summary -> feedback_revision
       -> continuity_review -> targeted_revision -> final_merge
```

The UI shows these stages as a progress bar. The pipeline stores intermediate
artifacts such as `research_sources`, `source_summaries`, `brief`, `outline`,
`outline_review`, `section_plan`, `section_plan_review`, `section_draft`,
`continuity_review`, `targeted_revision`, and the final merged `draft`.
Search results are passed into the LLM prompts.

`final_merge` always assembles the document deterministically: it concatenates
the section drafts in order and appends a `Sources` section. Because each
section is written against its own small source list, the merge step remaps
every inline `[1]`-style marker onto one global source numbering, deduplicated
by URL, and turns each marker into a clickable link (`[[3]](https://...)`).
The `Sources` section lists only the sources actually cited, with numbers that
match the inline citations. Set `LLM_MERGE_ENABLED=true` to additionally smooth
chapter transitions: one small LLM call per chapter boundary rewrites the next
chapter's opening paragraph (never the whole document), and a rewrite that
drops citations or balloons in length is discarded.

Section writing returns both the section markdown and its handoff summary in a
single LLM call. The separate `section_summary` stage records those summaries
without making another model call, which reduces latency and token use.

To keep small models from forgetting earlier content, the writer carries a
layered memory: each finished chapter is compressed into a short digest (one
small call per chapter), and every section prompt receives the previous
chapters' digests, the previous section's handoff summary, and a glossary of
the most frequent established terms. `continuity_review` runs in two stages
sized for small models: one call per chapter over its section overviews, plus
one cross-chapter call over the chapter digests.

Completed pipeline artifacts are reused when they are still fresh. If a project
already has current `research_sources`, `brief`, `outline`, `section_plan`,
`section_draft`, summaries, and final `draft`, a later run records the stages as
`reused` instead of calling the model again. New user answers invalidate older
upstream artifacts because the freshness cutoff is based on the latest saved
decision.

When `LLM_ENABLED=false`, the smoke test uses a local deterministic fallback so
checks do not depend on a running LLM server.

Default LLM settings:

```text
LLM_BASE_URL=http://localhost:8088/v1
LLM_MODEL=qwen/qwen3.6-35b-a3b
LLM_API_KEY=local
LLM_MERGE_ENABLED=false
SEARCH_ENABLED=true
SEARCH_MAX_RESULTS=5
SECTION_SEARCH_ENABLED=false
SECTION_SEARCH_TOPUP_LIMIT=10
DIAGRAMS_ENABLED=false
CITATION_STYLE=numeric
```

## Document Types

Each project has a document type that shapes planning, writing, and
rendering. Six types ship in `app/services/doc_types.py`:

- `report` (default): structured informational report with citations.
- `academic_paper`: 소논문-style thesis (서론/이론적 배경/본론/결론), strict
  academic register, citations required.
- `blog_post`: hook-driven chapters, conversational register, plain
  (unnumbered) headings.
- `essay`: single-voice reflective prose; web research and citations are
  off by default.
- `tech_doc`: task-oriented manual sections with steps and code blocks.
- `presentation_script`: spoken segments with transitions and stage
  directions; no citations, no numbered headings.

Pick a type at project creation or leave it on auto detect: the first run
classifies the request (one small LLM call) and stores the result, which
the settings panel shows and lets you change. A profile only alters prompt
guidance and rendering/search defaults - the pipeline stages are the same
for every type - so changing the type invalidates cached artifacts the
same way editing the request does.

## Rubric Review

After continuity review, a `rubric_review` stage grades the draft against
the document type's rubric (four criteria per type, declared in
`doc_types.py` - e.g. spoken naturalness and signposting for scripts,
argumentation and academic register for a mini-thesis). Grading runs one
call per chapter over clipped section text, aggregates 1-5 scores per
criterion into a `rubric_review` artifact, and merges its findings with
the continuity review's (deduplicated, capped at five sections) so one
targeted-revision pass fixes both. Rubric grading is best-effort: failed
chapters are noted and skipped, and a fully failed review is recorded as
`incomplete` instead of silently passing or blocking the writing run.

## Deterministic Quality Summary

The draft screen complements model-based reviews with deterministic quality
signals: strong and low-quality source counts, the percentage of eligible body
paragraphs containing citations, and the number of review findings. Government,
standards, and primary-research hosts rank above academic/institutional hosts,
general web pages, and wiki/blog/community sources. High-stakes topics without
a strong source are flagged explicitly.

Search also applies that signal before writing. If medical, legal, or financial
research returns no government or academic source, DocuGen runs a bounded
authority-domain query and ranks those results ahead of weaker pages when they
are relevant. Section-level research repeats the safeguard when a specific
section still lacks strong evidence. Source trust labels are included in the
writer context so a small model can treat blogs and unverified web pages as
background rather than as primary support for high-stakes claims.

Reviewer output is normalized before revision: issues cannot coexist with a
`pass` verdict, and section ids mentioned in issues become revision targets
even when a small model leaves `revision_targets` empty. New runs finish with
project status `review_needed` whenever deterministic warnings remain; the
pipeline itself can still reach 100% because generation completed normally.

Section research is reduced to a few passages ranked against the current
section before it reaches the writer. Alongside Markdown, the writer returns an
evidence ledger containing the supported claim, local source number, passage
id, and an exact excerpt. The application verifies that the excerpt really
appeared in the passage shown to the model and reports the percentage of cited
sources backed by valid ledger entries. A later section rewrite marks its old
ledger as stale instead of presenting outdated evidence as current.

When a freshly written section has an invalid ledger or an unverified citation,
the pipeline makes at most one evidence-repair call for that section. The repair
may only use the supplied passages; an unsupported factual claim must be removed
rather than kept without its citation. The repaired Markdown and ledger are
validated again deterministically. Remaining failures stay visible in the
quality summary, so the bounded repair loop cannot silently declare success.

The same summary performs a bounded sentence-level pass without another model
call. It flags near-duplicate prose, highly similar statements whose polarity
is reversed, and uncited absolute claims in medical, legal, or financial
documents. These signals are deliberately presented as review flags rather
than semantic proof; the API includes section ids and short excerpts so the UI
can show where a person should inspect the draft.

When `SENTENCE_QUALITY_REPAIR_ENABLED=true`, the targeted-revision stage makes
at most `SENTENCE_QUALITY_REPAIR_LIMIT` small repair calls (three by default),
one per flagged section. A candidate is kept only when the document-wide issue
count decreases, its first heading and citation markers are unchanged, and its
evidence ledger validates against the supplied passages. Failed or ineffective
repairs are discarded, while remaining flags continue to produce
`review_needed`.

A document-type-aware structure pass also checks sentence and paragraph
density, sections dominated by lists, and missing or extra Markdown headings.
For reports and academic papers with at least four sections and substantial
body text, it additionally checks whether the opening titles identify context
or purpose and whether the closing titles identify a conclusion, summary, or
recommendation. Blog, script, essay, and technical-document thresholds remain
separate so their intended formats are not judged by report conventions.

Sentence, structure, and reviewer targets in the quality panel are actionable:
selecting one switches from an older version or raw Markdown to the latest
rendered draft, scrolls to the matching section, and briefly highlights the
specific sentence or paragraph when its excerpt can be located. Numeric section
headings provide a fallback when cached section artifacts are unavailable.

Deterministic sentence and structure flags can be marked as reviewed or given
a documented exception. A reviewed flag stays active; an exception is removed
from the active count only when its reason is saved. The decision is keyed to
the current draft artifact and a stable issue fingerprint, so restoring or
generating another draft never inherits an old exception. If every occurrence
behind one warning is excepted, that warning no longer blocks `ready`; undoing
the decision restores the warning and project status.

An actionable quality item can also be converted directly into section
feedback. The UI opens the matching section's existing feedback panel and
prefills a comment with the issue label, affected section ids, and excerpt.
Nothing is saved until the user presses the panel's save button, so navigating
or previewing the suggested request has no pipeline side effect.

## Offline Quality Benchmark

Run the deterministic regression set without calling an LLM or search engine:

```bat
scripts\benchmark-quality.bat
```

The fixture at `benchmarks/quality_cases.json` covers all six document types
and compares a known regression against an improved candidate. A case can
require metrics to decrease or increase, cap the candidate's total flags, and
forbid specific warnings. The command exits non-zero when a check regresses.

To evaluate actual SLM output, place `<case-id>.json` files in a directory and
pass it as the candidate source. Each file accepts `sources` plus either the
fixture's compact `sections` form or pipeline-shaped `section_drafts`:

```bat
scripts\benchmark-quality.bat --candidate-dir data\benchmark-candidates --output data\quality-report.json
```

The JSON report contains baseline/candidate metrics, deltas, warnings, and each
failed expectation, making it suitable for CI or model/prompt comparisons.

## Style Samples

Upload your own writing (.txt/.md) in the "Style samples" panel and the
pipeline derives a style card from it - register, voice, person, tense,
sentence rhythm, vocabulary, plus a few verbatim exemplar sentences. The
card is stored as a `style_card` artifact, injected into every
section-writing prompt, and its register overrides the brief's, so
revision and seam-smoothing prompts follow it too. Style samples never
enter the research source pool (they are voice exemplars, not facts, so
they are never cited). Without samples the stage is skipped; a failed
derivation records the error and the run continues without a card.

## Document Length

Set a total body-length budget (characters) in the project settings panel,
or just state it in the request ("3000자 내외로") - the brief stage extracts
stated lengths into `target_length_chars`. An explicit setting wins over
the extracted value. The budget flows into outline and chapter-expansion
prompts (so structure size fits it) and is distributed proportionally
across planned sections at run time, clamped to 150-3000 characters per
section. Stored plan artifacts keep the model's original lengths, so
changing the budget re-flows sections without rewriting the plan.

## Citation Styles

The merged draft renders citations in one of two styles, selectable per
project in the settings panel (or globally via `CITATION_STYLE`):

- `numeric` (default): inline `[1]` links with a numbered source list in
  first-citation order, e.g. `1. [Title](url). example.com (accessed
  2026-07-08)`.
- `author_date` (APA-like): inline `(example.com, n.d.)` links with an
  alphabetized source list, e.g. `- example.com. (n.d.). [Title](url)`.
  Multiple sources from the same site are disambiguated as `n.d.-a`,
  `n.d.-b`, ... in title order.

When a fetched page declares an author, publication date, or site name
(meta tags or schema.org JSON-LD), citations upgrade automatically:
`(홍길동, 2024)` instead of `(example.com, n.d.)`, with `2024a`/`2024b`
disambiguation for same-author-same-year sources. Extraction is
deterministic (`app/services/page_meta.py`) — no model calls — and pages
without metadata fall back to the site name and the access date recorded
when the research fetch ran. User-uploaded file references are listed
without a link as `(user-provided reference)`. Because both styles are
rendered deterministically in `final_merge`, changing the style keeps
every cached artifact and only re-merges the document on the next run.

## Section Feedback

Each section heading in the rendered draft preview has a comment button.
A comment is stored as a `section_feedback` decision with
`applies_to.section_id` (also available via
`POST /projects/{id}/sections/{section_id}/feedback`). Unlike intake answers,
section feedback does not invalidate the whole pipeline: the next run keeps
every cached artifact and only rewrites the commented sections in the
`feedback_revision` stage, then re-runs continuity review and the final merge.
A feedback item counts as applied once its section draft is newer than the
comment.

## Section Top-up Search

With `SECTION_SEARCH_ENABLED=true`, sections whose planned sources share no
keywords with the section topic get one extra targeted web search during
section writing (at most `SECTION_SEARCH_TOPUP_LIMIT` extra queries per run).
The results replace the irrelevant sources for that section and flow into the
same citation pipeline.

## Diagrams

With `DIAGRAMS_ENABLED=true`, the section writer may emit one `mermaid` code
block per section where a diagram helps. The draft preview renders mermaid
blocks with a bundled `mermaid.min.js` (no CDN needed); blocks that fail to
parse fall back to a plain code block. Exported Markdown keeps the fences, so
GitHub and most viewers render them natively.

## Math Rendering

The draft preview and the shareable document view render LaTeX math with a
bundled `katex.min.js`/`katex.min.css` (no CDN needed). Use `$...$` for
inline math (e.g. `$\sqrt{d_k}$`) and a `$$` fence on its own line, or a
single line wrapped in `$$...$$`, for block math. To avoid misreading plain
text like `$5 and $10` as math, inline math only matches when both dollar
signs are hard against non-space characters. Expressions that fail to parse
render as plain text instead of breaking the page.

## Planned Next Pieces

- Export service
- LangGraph-based document generation loop
- Multi-step LLM writing agents
