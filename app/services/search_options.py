"""Per-run search configuration.

The browser and LLM search helpers read a handful of knobs (engine, headless,
stealth, locale, query language) that a project can override. Those helpers run
deep inside one synchronous pipeline call, so instead of threading the values
through every signature the pipeline resolves a project's effective options once
and installs them for the duration of the run via a context variable. Anything
that runs outside a run (or a test) transparently falls back to the env defaults.
"""

import contextvars
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class SearchOptions:
    # Browser engines to try in priority order (fallback on bot challenge/error).
    engines: tuple[str, ...]
    headless: bool
    stealth: bool
    locale: str
    # "native" | "english" | "both" — see _query_language_instruction in llm.py.
    query_language: str


def parse_engines(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated engine priority list, deduped in order.

    Falls back to ("daum",) when nothing usable is given.
    """
    engines: list[str] = []
    for name in (raw or "").split(","):
        name = name.strip().lower()
        if name and name not in engines:
            engines.append(name)
    return tuple(engines) or ("daum",)


_current: contextvars.ContextVar[SearchOptions | None] = contextvars.ContextVar(
    "search_options", default=None
)


def default_search_options() -> SearchOptions:
    """Options from the global env defaults (used when nothing is installed)."""
    return SearchOptions(
        engines=parse_engines(settings.search_engine),
        headless=settings.search_headless,
        stealth=settings.search_stealth,
        locale=settings.search_locale,
        query_language=settings.search_query_language,
    )


def current_search_options() -> SearchOptions:
    """The options installed for the current run, or the env defaults."""
    return _current.get() or default_search_options()


def use_search_options(options: SearchOptions) -> contextvars.Token:
    """Install options for the current context; returns a token for reset()."""
    return _current.set(options)


def reset_search_options(token: contextvars.Token) -> None:
    _current.reset(token)
