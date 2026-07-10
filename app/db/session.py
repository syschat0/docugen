import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import settings


def _database_path() -> Path:
    path = settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Additive migration for databases created before the column existed."""
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              initial_request TEXT NOT NULL,
              document_type TEXT,
              status TEXT NOT NULL,
              current_phase TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_references (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              source TEXT NOT NULL,
              title TEXT,
              content_text TEXT,
              status TEXT NOT NULL,
              error TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS workflow_threads (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              langgraph_thread_id TEXT NOT NULL,
              status TEXT NOT NULL,
              checkpoint_ref TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS pending_questions (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              phase TEXT NOT NULL,
              question_json TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              answered_at TEXT,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS user_decisions (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              phase TEXT NOT NULL,
              question_id TEXT,
              question TEXT NOT NULL,
              answer TEXT NOT NULL,
              applies_to_json TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS artifacts (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              node_id TEXT,
              type TEXT NOT NULL,
              title TEXT,
              content_json TEXT,
              file_path TEXT,
              version INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS summaries (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              scope TEXT NOT NULL,
              summary_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS app_settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_settings (
              project_id TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS quality_issue_decisions (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              draft_id TEXT NOT NULL,
              issue_key TEXT NOT NULL,
              decision TEXT NOT NULL,
              reason TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(project_id, draft_id, issue_key),
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              agent_name TEXT NOT NULL,
              phase TEXT NOT NULL,
              input_json TEXT,
              output_json TEXT,
              status TEXT NOT NULL,
              token_usage_json TEXT,
              error TEXT,
              created_at TEXT NOT NULL,
              completed_at TEXT,
              FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            """
        )
        _ensure_column(conn, "projects", "document_type", "document_type TEXT")

