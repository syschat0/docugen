import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _bool_env(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "LLM Document Agent")
    app_env: str = os.getenv("APP_ENV", "development")
    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/app.sqlite3"))
    llm_enabled: bool = _bool_env("LLM_ENABLED", "true")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:8088/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "local")
    llm_model: str = os.getenv("LLM_MODEL", "qwen/qwen3.6-35b-a3b")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
    llm_merge_enabled: bool = _bool_env("LLM_MERGE_ENABLED", "false")
    # One bounded cleanup call per flagged section after reviewer revisions.
    # Each candidate is accepted only when deterministic issue counts decrease
    # and headings, citations, and evidence validation remain intact.
    sentence_quality_repair_enabled: bool = _bool_env(
        "SENTENCE_QUALITY_REPAIR_ENABLED", "true"
    )
    sentence_quality_repair_limit: int = int(
        os.getenv("SENTENCE_QUALITY_REPAIR_LIMIT", "3")
    )
    # Pause after outline review and wait for the user to approve the outline
    # before the expensive section-writing phase.
    require_outline_approval: bool = _bool_env("REQUIRE_OUTLINE_APPROVAL", "false")
    search_enabled: bool = _bool_env("SEARCH_ENABLED", "true")
    # "auto": headless browser first, HTTP fallback. "browser" / "http": that backend only.
    search_backend: str = os.getenv("SEARCH_BACKEND", "auto").strip().lower()
    # Engine priority, comma-separated (e.g. "google_pse,bing,daum"). Engines
    # are tried in order; on a bot challenge or error the next one is used. See
    # _ENGINES in services/browser_search.py.
    search_engine: str = os.getenv("SEARCH_ENGINE", "daum").strip().lower()
    search_max_results: int = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    chapter_search_results: int = int(os.getenv("CHAPTER_SEARCH_RESULTS", "2"))
    # Cleaned page body kept on each source artifact so the passage selector can
    # pick relevant sentences instead of an arbitrary leading block.
    source_full_text_chars: int = int(os.getenv("SOURCE_FULL_TEXT_CHARS", "5000"))
    # LLM "judge" over search sources: one call per eligible page gates (usable),
    # compresses (summary/key_facts), and scores (info_density). Automatically
    # disabled when the LLM itself is off.
    source_eval_enabled: bool = _bool_env("SOURCE_EVAL_ENABLED", "true")
    # Maximum real LLM evaluation calls per pipeline stage invocation. Cache hits
    # do not count against this budget.
    source_eval_limit: int = int(os.getenv("SOURCE_EVAL_LIMIT", "8"))
    # Total character budget for the source block in a section-writing prompt.
    source_context_budget_chars: int = int(
        os.getenv("SOURCE_CONTEXT_BUDGET_CHARS", "3000")
    )
    # Listwise section-fit judge: just before a section is written, one LLM call
    # scores every candidate source 0-3 for relevance to that section. The writer
    # uses the score as its top ranking key and drops sources scored <= 1. Off
    # automatically when the LLM itself is off.
    section_eval_enabled: bool = _bool_env("SECTION_EVAL_ENABLED", "true")
    # Maximum real listwise LLM calls per section-writing run. Sections past the
    # cap fall back to heuristic ranking; cache hits do not count.
    section_eval_limit: int = int(os.getenv("SECTION_EVAL_LIMIT", "20"))
    # Per-section top-up search: when a section's selected sources have no
    # keyword overlap with the section, run one extra web search for it.
    section_search_enabled: bool = _bool_env("SECTION_SEARCH_ENABLED", "false")
    section_search_topup_limit: int = int(os.getenv("SECTION_SEARCH_TOPUP_LIMIT", "10"))
    # Let the section writer emit mermaid diagram code blocks. Small models
    # produce broken mermaid syntax often enough that this is opt-in; the UI
    # falls back to a plain code block when a diagram fails to render.
    diagrams_enabled: bool = _bool_env("DIAGRAMS_ENABLED", "false")
    # Bibliography style for the merged draft: "numeric" ([1] + numbered list)
    # or "author_date" ((site, n.d.) + alphabetized list). Rendering only, so
    # changing it never invalidates cached pipeline artifacts.
    citation_style: str = os.getenv("CITATION_STYLE", "numeric").strip().lower()
    search_timeout_seconds: int = int(os.getenv("SEARCH_TIMEOUT_SECONDS", "15"))
    # Browser-search runtime controls. Headless is the safe default; running
    # headed (SEARCH_HEADLESS=false) plus stealth (SEARCH_STEALTH=true) helps
    # get past engines that block automated/headless browsers, but headed needs
    # a display and pops a window per search. Stealth needs playwright-stealth.
    search_headless: bool = _bool_env("SEARCH_HEADLESS", "true")
    search_stealth: bool = _bool_env("SEARCH_STEALTH", "false")
    # Browser context locale; drives the engine's result language.
    search_locale: str = os.getenv("SEARCH_LOCALE", "ko-KR")
    # Search-query language: "native" (request language), "english", or "both"
    # (a mix, so results span e.g. Korean and English sources). Pairs well with
    # a bilingual engine priority and SEARCH_LOCALE.
    search_query_language: str = os.getenv(
        "SEARCH_QUERY_LANGUAGE", "native"
    ).strip().lower()
    # Google Programmable Search Engine (Custom Search JSON API) credentials for
    # the "google_pse" engine: an API key with the Custom Search API enabled and
    # the engine ID (cx) from programmablesearchengine.google.com.
    google_pse_api_key: str = os.getenv("GOOGLE_PSE_API_KEY", "").strip()
    google_pse_cx: str = os.getenv("GOOGLE_PSE_CX", "").strip()


settings = Settings()
