"""Database connection layer.

Wraps LangChain's `SQLDatabase` utility (via `MultiSchemaSQLDatabase`) with
connection-testing and error-normalizing helpers so the UI never has to deal
with raw SQLAlchemy/pyodbc exceptions directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine

from app.database.multi_schema import MultiSchemaSQLDatabase, discover_business_schemas


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
        driver = "unknown"
        for part in query.split("&"):
            if part.lower().startswith("driver="):
                driver = part.split("=", 1)[1].replace("+", " ")
                break
        return ConnectionInfo(server=server, database=database, driver=driver)
    except Exception:
        return ConnectionInfo(server="unknown", database="unknown", driver="unknown")


def create_database(connection_string: str, schemas: Optional[List[str]] = None) -> SQLDatabase:
    """Create a `SQLDatabase` instance reflecting every relevant schema
    (auto-discovered by default), translating connection failures into a
    `DatabaseConnectionError` with a clear, non-technical message.

    Args:
        connection_string: SQLAlchemy connection string.
        schemas: Explicit list of schemas to reflect. If omitted, every
            schema in the database is used except SQL Server's built-in
            system/role schemas (see app.database.multi_schema).
    """
    try:
        engine = create_engine(connection_string)
        resolved_schemas = schemas or discover_business_schemas(engine)
        if not resolved_schemas:
            resolved_schemas = ["dbo"]
        return MultiSchemaSQLDatabase(engine, schemas=resolved_schemas)
    except Exception as exc:  # noqa: BLE001 - we deliberately normalize all errors here
        raise DatabaseConnectionError(
            "Could not connect to SQL Server. Check your connection string, "
            "credentials, and that the server is reachable.",
            detail=str(exc),
        ) from exc


def test_connection(connection_string: str) -> ConnectionInfo:
    """Attempt a lightweight round-trip against the database. Returns
    connection info on success, raises `DatabaseConnectionError` on failure.
    """
    db = create_database(connection_string)
    try:
        db.run("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        raise DatabaseConnectionError(
            "Connected, but a test query failed. The database user may lack "
            "permissions, or the database name may be wrong.",
            detail=str(exc),
        ) from exc
    return describe_connection(connection_string)
