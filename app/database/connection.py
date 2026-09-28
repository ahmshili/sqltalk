"""Database connection layer.

Wraps LangChain's `SQLDatabase` utility (via `MultiSchemaSQLDatabase`) with
connection-testing and error-normalizing helpers so the UI never has to deal
with raw SQLAlchemy/pyodbc/psycopg2 exceptions directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine

from app.database.multi_schema import MultiSchemaSQLDatabase, discover_business_schemas
from app.database.uri import MSSQL_DIALECT, POSTGRES_DIALECT, dialect_from_connection_string


class DatabaseConnectionError(Exception):
    """Raised when SQLTalk cannot connect to, or query, the configured
    database. Carries a user-facing message plus the original technical
    detail (shown only in the expandable diagnostics section)."""

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or ""


@dataclass
class ConnectionInfo:
    """Non-secret connection details safe to display in the UI."""

    server: str
    database: str
    driver: str


def describe_connection(connection_string: str) -> ConnectionInfo:
    """Extract display-safe connection details (never the password) from a
    SQLAlchemy connection string, for the sidebar's status panel.
    """
    try:
        parsed = urlparse(connection_string)
        server = parsed.hostname or "unknown"
        database = (parsed.path or "").lstrip("/") or "unknown"
        query = parsed.query or ""
        dialect = dialect_from_connection_string(connection_string)
        driver = "unknown"
        if dialect == POSTGRES_DIALECT:
            driver = "psycopg2 (PostgreSQL)"
            for part in query.split("&"):
                if part.lower().startswith("sslmode="):
                    driver += f" — sslmode={part.split('=', 1)[1]}"
                    break
        else:
            for part in query.split("&"):
                if part.lower().startswith("driver="):
                    driver = part.split("=", 1)[1].replace("+", " ")
                    break
        return ConnectionInfo(server=server, database=database, driver=driver)
    except Exception:
        return ConnectionInfo(server="unknown", database="unknown", driver="unknown")


def create_database(
    connection_string: str,
    schemas: Optional[List[str]] = None,
    dialect: Optional[str] = None,
) -> SQLDatabase:
    """Create a `SQLDatabase` instance reflecting every relevant schema
    (auto-discovered by default), translating connection failures into a
    `DatabaseConnectionError` with a clear, non-technical message.

    Args:
        connection_string: SQLAlchemy connection string.
        schemas: Explicit list of schemas to reflect. If omitted, every
            schema in the database is used except the dialect's built-in
            system schemas (see app.database.multi_schema).
        dialect: `mssql` or `postgres`. Detected from the connection string
            when omitted.
    """
    resolved_dialect = dialect or dialect_from_connection_string(connection_string)
    server_kind = "PostgreSQL" if resolved_dialect == POSTGRES_DIALECT else "SQL Server"
    try:
        engine = create_engine(connection_string)
        resolved_schemas = schemas or discover_business_schemas(engine, resolved_dialect)
        if not resolved_schemas:
            resolved_schemas = ["dbo"]
        return MultiSchemaSQLDatabase(engine, schemas=resolved_schemas)
    except Exception as exc:  # noqa: BLE001 - we deliberately normalize all errors here
        raise DatabaseConnectionError(
            f"Could not connect to {server_kind}. Check your connection "
            "string, credentials, and that the server is reachable.",
            detail=str(exc),
        ) from exc


def test_connection(connection_string: str) -> ConnectionInfo:
    """Attempt a lightweight round-trip against the database. Returns
    connection info on success, raises `DatabaseConnectionError` on failure.
    """
    db = create_database(connection_string)
    try:
        db.run("SELECT 1")  # valid on both MSSQL and PostgreSQL
    except Exception as exc:  # noqa: BLE001
        raise DatabaseConnectionError(
            "Connected, but a test query failed. The database user may lack "
            "permissions, or the database name may be wrong.",
            detail=str(exc),
        ) from exc
    return describe_connection(connection_string)
