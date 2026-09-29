"""Read-only direct-query layer for the SQL Console and Data Explorer.

Everything here is SELECT-only by construction:

  * a statement allowlist (SELECT / WITH / SHOW / EXPLAIN prefixes),
  * the same blocked-keyword gate the LLM agent uses
    (`app.database.safety.find_violations`) — so even a WITH-wrapped
    DELETE/UPDATE/INSERT is rejected,
  * execution inside a transaction that is always rolled back, so no
    statement can have durable effects even if a gate were bypassed.

Used by two audiences: technical reviewers typing SQL, and the graphical
Data Explorer (which generates introspected SELECTs internally). Identifiers
in explorer-generated SQL are built from the reflected catalog (never from
raw user input) and quoted per dialect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from sqlalchemy import MetaData, text
from sqlalchemy.engine import Connection

from app.database.safety import enforce_row_limit, find_violations
from app.database.uri import MSSQL_DIALECT, POSTGRES_DIALECT

# Hard cap for direct queries (console previews and the explorer). The agent
# has its own configurable cap; these views keep a fixed, conservative one.
CONSOLE_MAX_ROWS = 500

# Long text cells are truncated before rendering so one wide column can't
# blow up the UI (or leak a whole document into a preview).
MAX_CELL_CHARS = 200

# Statements must start with one of these (case-insensitive) after stripping
# whitespace and leading comments. Everything else is rejected outright.
_ALLOWED_PREFIXES = ("select", "with", "show", "explain")

# Comments are stripped before prefix checks so `/* foo */ DELETE ...` or
# `-- note\nDELETE ...` cannot smuggle a disallowed statement past the
# allowlist. (The blocked-keyword gate inspects the full raw text either
# way; this only affects the convenience prefix check.)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


@dataclass
class ConsoleQueryResult:
    """Outcome of one read-only direct query."""

    ok: bool
    rows: List[Tuple] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    rowcount: int = 0
    message: str = ""            # friendly text for the UI
    detail: str = ""             # technical text (DEV_MODE panels only)


def _strip_comments(sql: str) -> str:
    return _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", sql))


def _is_allowed_statement(sql: str) -> bool:
    return (
        _strip_comments(sql).lstrip().lower().startswith(_ALLOWED_PREFIXES)
    )


def check_query(sql: str) -> Optional[str]:
    """Return a friendly rejection reason, or None if the statement is
    allowed. Applies the same blocked-keyword gate as the agent plus the
    direct-query allowlist."""
    violations = find_violations(sql)
    if violations:
        return (
            "Blocked: "
            + " ".join(v.message for v in violations)
            + " This console only runs read-only SELECT statements."
        )
    if not _is_allowed_statement(sql):
        return (
            "Only read-only queries are allowed here (SELECT / WITH / "
            "SHOW / EXPLAIN)."
        )
    return None


def run_readonly_query(
    conn: Connection,
    sql: str,
    dialect: str,
    max_rows: int = CONSOLE_MAX_ROWS,
) -> ConsoleQueryResult:
    """Execute one read-only query inside a rolled-back transaction.

    The caller supplies the connection; this function never commits. Even a
    statement that slipped past the keyword gates could not persist: the
    surrounding transaction is unconditionally rolled back.
    """
    reason = check_query(sql)
    if reason:
        return ConsoleQueryResult(ok=False, message=reason)

    capped = enforce_row_limit(sql, min(max_rows, CONSOLE_MAX_ROWS), dialect)

    trans = conn.begin()
    try:
        result = conn.execute(text(capped))
        if result.returns_rows:
            rows = result.fetchmany(CONSOLE_MAX_ROWS)
            columns = list(result.keys())
        else:
            rows, columns = [], []
        trans.rollback()  # always — this layer never persists anything

        truncated = [
            tuple(
                (v[:MAX_CELL_CHARS] + "…") if isinstance(v, str) and len(v) > MAX_CELL_CHARS else v
                for v in row
            )
            for row in rows
        ]
        return ConsoleQueryResult(
            ok=True,
            rows=truncated,
            columns=columns,
            rowcount=len(truncated),
        )
    except Exception as exc:  # noqa: BLE001 - surface as friendly message
        trans.rollback()
        return ConsoleQueryResult(
            ok=False,
            message="Query failed. Check the statement and try again.",
            detail=str(exc),
        )


def quote_identifier(name: str, dialect: str) -> str:
    """Quote a catalog-derived identifier for the active dialect.

    Only ever called with names coming from SQLAlchemy's reflected catalog
    (schema/table/column names), never from user input.
    """
    if dialect == POSTGRES_DIALECT:
        return f'"{name}"'
    return f"[{name}]" if dialect == MSSQL_DIALECT else f'"{name}"'
