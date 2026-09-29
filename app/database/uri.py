"""Database connection-string builder (dialect-aware).

Every other layer builds its SQLAlchemy URI through `build_connection_string`,
so the app can run against either Microsoft SQL Server (local development)
or PostgreSQL (free public demo on Neon) without any call-site changes.

`DB_DIALECT` selects the target dialect:

  * `mssql` (default) — SQLAlchemy + pyodbc + ODBC Driver 18, exactly the
    URI format this project has always used locally. Nothing about the
    existing workflow changes when the dialect is left at its default.
  * `postgres` — SQLAlchemy + psycopg2 with TLS required, the format managed
    providers like Neon hand out.
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

MSSQL_DIALECT = "mssql"
POSTGRES_DIALECT = "postgres"

#: Canonical dialect tokens -> accepted aliases (case-insensitive, e.g.
#: DB_DIALECT=PostgreSQL also selects the postgres dialect).
DIALECT_ALIASES: dict[str, str] = {
    MSSQL_DIALECT: MSSQL_DIALECT,
    "mssql": MSSQL_DIALECT,
    "sqlserver": MSSQL_DIALECT,
    POSTGRES_DIALECT: POSTGRES_DIALECT,
    "postgresql": POSTGRES_DIALECT,
    "pg": POSTGRES_DIALECT,
}

DEFAULT_MSSQL_DRIVER = "ODBC Driver 18 for SQL Server"

# Free managed Postgres providers (Neon et al) require TLS on the public
# endpoint, so it is the default here rather than an opt-in.
DEFAULT_POSTGRES_SSLMODE = "require"


def resolve_dialect(raw: str | None) -> str:
    """Normalize a `DB_DIALECT` value to `mssql` or `postgres`.

    Unset/empty means the project default (mssql); unknown values raise so a
    typo can't silently point the app at the wrong database kind.
    """
    if raw is None or not raw.strip():
        return MSSQL_DIALECT
    key = raw.strip().lower()
    try:
        return DIALECT_ALIASES[key]
    except KeyError:
        raise ValueError(
            f"Unsupported DB_DIALECT '{raw}'. Expected '{MSSQL_DIALECT}' "
            f"or '{POSTGRES_DIALECT}' (aliases: "
            f"{', '.join(sorted(set(DIALECT_ALIASES)))})."
        ) from None


def dialect_from_connection_string(connection_string: str) -> str:
    """Best-effort dialect detection from an existing SQLAlchemy URI.

    Used when an explicit `DB_CONNECTION_STRING` is provided so the safety
    layer and prompts match the server the URI actually points at.
    """
    scheme = connection_string.split("://", 1)[0].lower()
    if "mssql" in scheme or "pyodbc" in scheme:
        return MSSQL_DIALECT
    if "postgres" in scheme:
        return POSTGRES_DIALECT
    return MSSQL_DIALECT


def build_mssql_connection_string(
    *,
    username: str,
    password: str,
    host: str,
    database: str,
    driver: str = DEFAULT_MSSQL_DRIVER,
    trust_server_certificate: bool = True,
    port: int | None = None,
) -> str:
    """Build the classic pyodbc URI this project has always used.

    Credentials are URL-escaped so passwords containing `@ : / ? # [ ] %`
    don't corrupt the URI (the README's long-standing advice, automated).
    """
    driver_param = driver.replace(" ", "+")
    trust_param = "&TrustServerCertificate=yes" if trust_server_certificate else ""
    host_part = f"{host},{port}" if port else host
    return (
        f"mssql+pyodbc://{quote_plus(username)}:{quote_plus(password)}"
        f"@{host_part}/{database}?driver={driver_param}{trust_param}"
    )


def build_postgres_connection_string(
    *,
    username: str,
    password: str,
    host: str,
    database: str,
    port: int = 5432,
    sslmode: str | None = DEFAULT_POSTGRES_SSLMODE,
) -> str:
    """Build a `postgresql+psycopg2` URI (the format Neon provides).

    Neon connection strings include the endpoint in the *username* as an
    options suffix (e.g. `user` becomes `user@ep-cool-name-123456`) — pass
    that whole string as `username` and it is escaped correctly.
    """
    params: list[str] = []
    if sslmode:
        params.append(f"sslmode={sslmode}")
    query = f"?{'&'.join(params)}" if params else ""
    return (
        f"postgresql+psycopg2://{quote_plus(username)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}{query}"
    )


def build_connection_string(dialect: str | None = None, **parts) -> str:
    """Dispatch to the dialect-specific builder (`parts` = username, password,
    host, database, plus dialect-specific extras)."""
    resolved = resolve_dialect(
        dialect if dialect is not None else os.getenv("DB_DIALECT")
    )
    if resolved == MSSQL_DIALECT:
        return build_mssql_connection_string(**parts)
    return build_postgres_connection_string(**parts)
