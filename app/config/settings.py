"""Application configuration.

All runtime configuration is sourced from environment variables (optionally
loaded from a local `.env` file). Nothing here should ever be hard-coded to a
specific provider, model, or credential — see the project README for the
full list of supported variables.

Two backend profiles are supported via `DB_DIALECT`:

  * `mssql` (default) — the original local development workflow against
    SQL Server, configured with a full `DB_CONNECTION_STRING` exactly as
    before. Leaving `DB_DIALECT` unset reproduces the previous behavior.
  * `postgres` — the free public demo (Neon), configured either with a full
    `DB_CONNECTION_STRING` (Neon's own URI works as-is) or from individual
    `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` parts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv
import os

# Load `.env` once, at import time. Real environment variables (e.g. set by
# the OS, a container, or a CI system) always take precedence over `.env`.
# `override=False` keeps that precedence when Streamlit Community Cloud has
# already expanded `st.secrets` into real environment variables.
load_dotenv(override=False)

from app.database.uri import (
    MSSQL_DIALECT,
    POSTGRES_DIALECT,
    DEFAULT_POSTGRES_SSLMODE,
    resolve_dialect,
)

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TEMPERATURE = 0.0
# Raised from 6: multi-step questions (list tables -> schema -> check -> run
# -> interpret) routinely need more than 6 steps, and a silent iteration-limit
# stop is indistinguishable from a failed answer for the user.
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MAX_ROWS = 200
DEFAULT_READ_ONLY = True

# Output-token budget per Groq request. Groq's free tier enforces small
# *output* tokens-per-minute (OTPM) quotas per model (1,000 on several), and
# the uncapped library default makes requests get rejected with a 429 before
# generation even starts. See get_groq_max_tokens() below.
DEFAULT_GROQ_MAX_TOKENS = 768

# LLM providers, ordered by inference speed for the default fallback chain:
# Groq (fastest) -> Gemini -> OpenRouter. See app/llm/provider.py.
PROVIDER_ORDER = ("groq", "gemini", "openrouter")

# Environment variable that overrides the fallback order (optional). Accepted
# value: a comma-separated list of provider names in priority order, e.g.
#   LLM_PROVIDER_ORDER=openrouter,groq,gemini
PROVIDER_ORDER_ENV_VAR = "LLM_PROVIDER_ORDER"

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
# gemini-1.5-flash is past its end-of-life window (Google retired the 1.5
# generation during 2026); 2.5-flash is the current stable fast tier.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
# NOTE: OpenRouter retires free models frequently. This default was updated
# in 2026-09 after `meta-llama/llama-3.1-405b-instruct:free` was removed
# (requests started failing with 404 "No endpoints found"). If it dies too,
# pick another slug from https://openrouter.ai/models?max_price=0.
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"

DEFAULT_PROVIDER_MODELS = {
    "groq": DEFAULT_GROQ_MODEL,
    "gemini": DEFAULT_GEMINI_MODEL,
    "openrouter": DEFAULT_OPENROUTER_MODEL,
}

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

DEV_MODE_ENV_VAR = "DEV_MODE"


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


def _get_keys(provider: str) -> List[str]:
    """Collect every API key configured for a provider, in priority order.

    Two accepted forms, both supported so a single key "just works":

      GROQ_API_KEY=key1,key2        # comma-separated fallback keys
      GROQ_API_KEY_1=key1           # ...or explicitly numbered keys
      GROQ_API_KEY_2=key2

    Streamlit Cloud does not allow the same secret key twice, which is why
    the numbered form exists.
    """
    keys: List[str] = []
    raw = os.getenv(f"{provider.upper()}_API_KEY", "")
    if raw:
        keys.extend(k.strip() for k in raw.split(",") if k.strip())
    # Numbered keys are appended after the comma list (never deduplicated
    # against it — being in the chain twice wastes one attempt at worst).
    index = 1
    while True:
        numbered = os.getenv(f"{provider.upper()}_API_KEY_{index}")
        if not numbered or not numbered.strip():
            break
        keys.append(numbered.strip())
        index += 1
    return keys


def normalize_provider_order(raw: object) -> List[str]:
    """Normalize a raw provider-order value to a valid ordering list.

    Rules (designed so a bad override can never break the fallback chain):

      * Names are case-insensitive and whitespace-tolerant.
      * Unknown names are ignored.
      * Known providers missing from the input are appended, in default
        priority order, at the end of the chain — an ordering override
        re-prioritizes but never silently disables a configured provider.
      * An empty / None / wholly-invalid input returns the default order.
    """
    if raw is None:
        return list(PROVIDER_ORDER)
    if isinstance(raw, str):
        tokens = [t.strip().lower() for t in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        tokens = [str(t).strip().lower() for t in raw]
    else:
        return list(PROVIDER_ORDER)

    known = [t for t in tokens if t in PROVIDER_ORDER]
    ordered: List[str] = []
    for t in known:
        if t not in ordered:
            ordered.append(t)
    if not ordered:
        return list(PROVIDER_ORDER)
    for provider in PROVIDER_ORDER:
        if provider not in ordered:
            ordered.append(provider)
    return ordered


def get_provider_order() -> List[str]:
    """Resolve the LLM fallback order: `LLM_PROVIDER_ORDER` when valid,
    otherwise the default speed order (Groq -> Gemini -> OpenRouter)."""
    return normalize_provider_order(os.getenv(PROVIDER_ORDER_ENV_VAR, ""))

DEFAULT_OPENROUTER_MAX_TOKENS = 8192


def get_groq_max_tokens() -> int:
    """Completion-token budget advertised on each Groq request.

    Groq's free tier enforces per-model *output* tokens-per-minute (OTPM)
    budgets (e.g. 1,000 on several qwen/moonshot models). With the uncapped
    library default, a request's expected output can exceed that budget and
    the API rejects it with a 429 before a single token is generated — the
    fallback chain then needlessly rotates providers. 768 sits safely under
    the tightest common free-tier OTPM while leaving room for ReAct steps.
    Override with `GROQ_MAX_TOKENS`.
    """
    return _get_int("GROQ_MAX_TOKENS", DEFAULT_GROQ_MAX_TOKENS)


def get_openrouter_max_tokens() -> int:
    """Completion-token budget advertised on each OpenRouter request.

    OpenRouter admits/prices requests against the advertised `max_tokens`;
    the library default (100k+) makes near-zero-credit accounts fail with
    402 "You requested up to N tokens, but can only afford M". A modest cap
    keeps free-tier usage working - SQL agent steps produce short outputs.
    Override with `OPENROUTER_MAX_TOKENS`.
    """
    return _get_int("OPENROUTER_MAX_TOKENS", DEFAULT_OPENROUTER_MAX_TOKENS)


def get_provider_keys(provider: str) -> List[str]:
    """Public alias for `_get_keys` (documented form; used by the fallback
    chain builder and the dev-mode sidebar)."""
    return _get_keys(provider)


def get_db_dialect() -> str:
    """Resolve the active database dialect from `DB_DIALECT` (default mssql)."""
    return _get_db_dialect()


def _get_db_dialect() -> str:
    """Resolve the active database dialect from `DB_DIALECT` (default mssql)."""
    return resolve_dialect(os.getenv("DB_DIALECT"))


def _get_db_connection_string() -> Optional[str]:
    """Resolve the database connection string.

    Precedence:
      1. An explicit `DB_CONNECTION_STRING` (the long-standing form; works
         for both dialects and is never second-guessed).
      2. `postgres` dialect parts (DB_HOST/DB_NAME/DB_USER/DB_PASSWORD) —
         the recommended form for the Neon demo.
      3. `mssql` dialect parts (DB_HOST/DB_NAME/DB_USER/DB_PASSWORD).
    """
    explicit = os.getenv("DB_CONNECTION_STRING")
    if explicit:
        return explicit

    dialect = _get_db_dialect()
    host = os.getenv("DB_HOST")
    database = os.getenv("DB_NAME") or os.getenv("DB_DATABASE")
    if not host or not database:
        return None
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    if not user or password is None:
        return None

    if dialect == POSTGRES_DIALECT:
        from app.database.uri import build_postgres_connection_string

        return build_postgres_connection_string(
            username=user,
            password=password,
            host=host,
            database=database,
            port=_get_int("DB_PORT", 5432),
            sslmode=os.getenv("DB_SSLMODE") or DEFAULT_POSTGRES_SSLMODE,
        )

    from app.database.uri import build_mssql_connection_string

    port = os.getenv("DB_PORT")
    return build_mssql_connection_string(
        username=user,
        password=password,
        host=host,
        database=database,
        port=int(port) if port and port.strip() else None,
    )


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
            missing.append("DB_CONNECTION_STRING (or DB_HOST/DB_NAME/DB_USER/DB_PASSWORD)")
        if not self.openrouter_api_key:
            if any(get_provider_keys(p) for p in PROVIDER_ORDER):
                # A Groq/Gemini key covers the requirement; OpenRouter stays
                # optional so the app runs on any single provider.
                pass
            else:
                missing.append("an LLM API key (GROQ_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY)")
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
        db_connection_string=db_connection_string or _get_db_connection_string(),
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
