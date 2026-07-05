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
    search_timeout_seconds: int = int(os.getenv("SEARCH_TIMEOUT_SECONDS", "15"))


settings = Settings()
