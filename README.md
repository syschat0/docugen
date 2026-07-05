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
       -> section_plan -> section_plan_review -> section_writing
       -> section_summary -> continuity_review -> targeted_revision -> final_merge
```

The UI shows these stages as a progress bar. The pipeline stores intermediate
artifacts such as `research_sources`, `source_summaries`, `brief`, `outline`,
`outline_review`, `section_plan`, `section_plan_review`, `section_draft`,
`continuity_review`, `targeted_revision`, and the final merged `draft`.
Search results are passed into the LLM prompts.

By default, `final_merge` does not call the LLM. It concatenates the section
drafts in order and appends a `Sources` section from the collected search
results. This avoids sending the full document back through the model. Set
`LLM_MERGE_ENABLED=true` only when you want the model to rewrite transitions
and polish the whole document during final merge.

Section writing returns both the section markdown and its handoff summary in a
single LLM call. The separate `section_summary` stage records those summaries
without making another model call, which reduces latency and token use.

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
```

## Planned Next Pieces

- Export service
- LangGraph-based document generation loop
- Multi-step LLM writing agents
