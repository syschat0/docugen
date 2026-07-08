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
    # Pause after outline review and wait for the user to approve the outline
    # before the expensive section-writing phase.
    require_outline_approval: bool = _bool_env("REQUIRE_OUTLINE_APPROVAL", "false")
    search_enabled: bool = _bool_env("SEARCH_ENABLED", "true")
    # "auto": headless browser first, HTTP fallback. "browser" / "http": that backend only.
    search_backend: str = os.getenv("SEARCH_BACKEND", "auto").strip().lower()
    # Engine for the browser backend; see _ENGINES in services/browser_search.py.
    search_engine: str = os.getenv("SEARCH_ENGINE", "daum").strip().lower()
    search_max_results: int = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    chapter_search_results: int = int(os.getenv("CHAPTER_SEARCH_RESULTS", "2"))
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


settings = Settings()
