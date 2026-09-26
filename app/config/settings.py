"""Application configuration.

All runtime configuration is sourced from environment variables (optionally
loaded from a local `.env` file). Nothing here should ever be hard-coded to a
specific provider, model, or credential — see the project README for the
full list of supported variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv
import os

# Load `.env` once, at import time. Real environment variables (e.g. set by
# the OS, a container, or a CI system) always take precedence over `.env`.
load_dotenv()


DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.1-405b-instruct:free"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_ITERATIONS = 6
DEFAULT_MAX_ROWS = 200
DEFAULT_READ_ONLY = True

# Statement keywords blocked by default when read-only mode is enabled.
# See app/database/safety.py for how this is enforced.
DEFAULT_BLOCKED_KEYWORDS = (
    "DROP",
    "DELETE",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "INSERT",
    "UPDATE",
    "MERGE",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "REVOKE",
    "DENY",
)


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    """Snapshot of all configuration the application needs to run."""

    db_connection_string: Optional[str]
    openrouter_api_key: Optional[str]
    openrouter_model: str
    openrouter_base_url: str
    temperature: float
    max_iterations: int
    max_rows: int
    read_only: bool
    db_schemas: Optional[List[str]] = None
    blocked_keywords: List[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_KEYWORDS)
    )

    def missing_required(self) -> List[str]:
        """Return a list of human-readable names of required settings that
        are absent. Used to show a clear setup message in the UI instead of
        a stack trace.
        """
        missing = []
        if not self.db_connection_string:
            missing.append("DB_CONNECTION_STRING")
        if not self.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")
        return missing

    def is_ready(self) -> bool:
        return not self.missing_required()


def load_settings(
    *,
    db_connection_string: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    openrouter_model: Optional[str] = None,
    max_iterations: Optional[int] = None,
    read_only: Optional[bool] = None,
    max_rows: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Settings:
    """Build a `Settings` object.

    Any explicit keyword argument (typically coming from Streamlit sidebar
    overrides) wins over the corresponding environment variable, which in
    turn wins over the built-in default.
    """

    return Settings(
        db_connection_string=db_connection_string or os.getenv("DB_CONNECTION_STRING"),
        openrouter_api_key=openrouter_api_key or os.getenv("OPENROUTER_API_KEY"),
        openrouter_model=openrouter_model or os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL,
        openrouter_base_url=os.getenv("OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL,
        temperature=temperature if temperature is not None else _get_float("OPENROUTER_TEMPERATURE", DEFAULT_TEMPERATURE),
        max_iterations=max_iterations or _get_int("AGENT_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS),
        max_rows=max_rows or _get_int("AGENT_MAX_ROWS", DEFAULT_MAX_ROWS),
        read_only=read_only if read_only is not None else _get_bool("READ_ONLY_MODE", DEFAULT_READ_ONLY),
        db_schemas=_get_schemas(),
    )


def _get_schemas() -> Optional[List[str]]:
    raw = os.getenv("DB_SCHEMAS")
    if not raw or not raw.strip():
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]
