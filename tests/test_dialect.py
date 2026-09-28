"""Tests for the database dialect abstraction (mssql vs postgres)."""

from unittest.mock import MagicMock, patch

import pytest

from app.database.uri import (
    build_connection_string,
    build_mssql_connection_string,
    build_postgres_connection_string,
    dialect_from_connection_string,
    resolve_dialect,
)
from app.database.safety import enforce_row_limit
from app.agent.toolkit import get_query_checker_template


# ---------------------------------------------------------------------------
# Connection-string builders
# ---------------------------------------------------------------------------

def test_resolve_dialect_defaults_to_mssql():
    assert resolve_dialect(None) == "mssql"
    assert resolve_dialect("") == "mssql"
    assert resolve_dialect("  ") == "mssql"


def test_resolve_dialect_accepts_aliases():
    assert resolve_dialect("postgres") == "postgres"
    assert resolve_dialect("PostgreSQL") == "postgres"
    assert resolve_dialect("pg") == "postgres"
    assert resolve_dialect("MSSQL") == "mssql"
    assert resolve_dialect("sqlserver") == "mssql"


def test_resolve_dialect_rejects_unknown():
    with pytest.raises(ValueError, match="DB_DIALECT"):
        resolve_dialect("mysql")


def test_mssql_builder_escapes_specials_and_sets_driver():
    uri = build_mssql_connection_string(
        username="sa", password="p@ss:word", host="localhost",
        database="adventureWorks",
    )
    assert uri == (
        "mssql+pyodbc://sa:p%40ss%3Aword@localhost/adventureWorks"
        "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
    )


def test_mssql_builder_with_port():
    uri = build_mssql_connection_string(
        username="sa", password="x", host="localhost", database="db", port=1433,
    )
    assert "@localhost,1433/" in uri


def test_postgres_builder_neon_style_username_and_ssl():
    uri = build_postgres_connection_string(
        username="app_owner@ep-cool-123",
        password="p%ss",
        host="ep-cool-123.aws.neon.tech",
        database="neondb",
    )
    assert uri == (
        "postgresql+psycopg2://app_owner%40ep-cool-123:p%25ss"
        "@ep-cool-123.aws.neon.tech:5432/neondb?sslmode=require"
    )


def test_postgres_builder_sslmode_opt_out():
    uri = build_postgres_connection_string(
        username="u", password="p", host="h", database="d", sslmode=None,
    )
    assert "sslmode" not in uri


def test_build_connection_string_dispatch(monkeypatch):
    monkeypatch.setenv("DB_DIALECT", "postgres")
    uri = build_connection_string(username="u", password="p", host="h", database="d")
    assert uri.startswith("postgresql+psycopg2://")


# ---------------------------------------------------------------------------
# Dialect detection from existing URIs
# ---------------------------------------------------------------------------

def test_dialect_detection():
    assert dialect_from_connection_string(
        "mssql+pyodbc://sa:x@h/db?driver=ODBC+Driver+18+for+SQL+Server"
    ) == "mssql"
    assert dialect_from_connection_string(
        "postgresql+psycopg2://u@ep:p@h/db?sslmode=require"
    ) == "postgres"
    assert dialect_from_connection_string("postgresql://u:p@h/db") == "postgres"
    # Unknown schemes fall back to the project default.
    assert dialect_from_connection_string("sqlite:///foo.db") == "mssql"


# ---------------------------------------------------------------------------
# Row-limit clause per dialect
# ---------------------------------------------------------------------------

def test_mssql_row_limit_unchanged_behavior():
    assert enforce_row_limit("SELECT * FROM Production.Product", 50) == "SELECT TOP 50 * FROM Production.Product"


def test_postgres_row_limit_appends_limit():
    assert enforce_row_limit("SELECT * FROM sales.orders", 50, "postgres") == "SELECT * FROM sales.orders LIMIT 50"


def test_postgres_row_limit_multiline_appends_to_last_sql_line():
    sql = "SELECT o.order_id\nFROM sales.orders o\nWHERE o.total_due > 100"
    assert enforce_row_limit(sql, 25, "postgres").endswith("WHERE o.total_due > 100 LIMIT 25")


def test_postgres_row_limit_skips_existing_limit():
    original = "SELECT * FROM t LIMIT 5"
    assert enforce_row_limit(original, 50, "postgres") == original


def test_postgres_row_limit_skips_fetch_first():
    original = "SELECT * FROM t FETCH FIRST 10 ROWS ONLY"
    assert enforce_row_limit(original, 50, "postgres") == original


def test_mssql_row_limit_skips_offset():
    original = "SELECT * FROM t ORDER BY x OFFSET 0 ROWS"
    assert enforce_row_limit(original, 50) == original


def test_row_limit_skipped_for_non_select():
    sql = "INSERT INTO t VALUES (1)"
    assert enforce_row_limit(sql, 10) == sql


# ---------------------------------------------------------------------------
# Query-checker prompt per dialect
# ---------------------------------------------------------------------------

def test_mssql_checker_mentions_top_and_getdate():
    template = get_query_checker_template("mssql")
    assert "TOP instead of LIMIT" in template
    assert "GETDATE()" in template
    assert "Microsoft SQL Server" in template


def test_postgres_checker_mentions_limit_and_current_date():
    template = get_query_checker_template("postgres")
    assert "LIMIT instead of TOP" in template
    assert "CURRENT_DATE" in template
    assert "PostgreSQL" in template
    # The T-SQL-only lines never appear in the postgres template:
    assert "Using TOP instead of LIMIT (this is T-SQL" not in template
    assert "Using GETDATE() instead of NOW()" not in template


# ---------------------------------------------------------------------------
# Schema discovery across dialects
# ---------------------------------------------------------------------------

def test_pg_system_schemas_excluded():
    from app.database.multi_schema import discover_business_schemas, PG_SYSTEM_SCHEMAS

    engine = MagicMock()
    engine.dialect.name = "postgresql"
    inspector = MagicMock()
    inspector.get_schema_names.return_value = [
        "public", "production", "sales", "pg_catalog", "pg_toast", "information_schema",
    ]
    with patch("app.database.multi_schema.inspect", return_value=inspector):
        schemas = discover_business_schemas(engine, "postgres")
    assert schemas == ["production", "public", "sales"]
    assert not any(s in PG_SYSTEM_SCHEMAS for s in schemas)


def test_mssql_system_schemas_still_excluded():
    from app.database.multi_schema import discover_business_schemas, SYSTEM_SCHEMAS

    engine = MagicMock()
    engine.dialect.name = "mssql"
    inspector = MagicMock()
    inspector.get_schema_names.return_value = ["dbo", "Production", "sys", "INFORMATION_SCHEMA"]
    with patch("app.database.multi_schema.inspect", return_value=inspector):
        schemas = discover_business_schemas(engine, "mssql")
    assert "Production" in schemas and "dbo" in schemas
    assert not any(s.lower() in SYSTEM_SCHEMAS for s in schemas)


def test_create_database_pg_error_message_mentions_postgres():
    from app.database.connection import create_database, DatabaseConnectionError

    with patch("app.database.connection.create_engine") as mock_engine:
        mock_engine.side_effect = Exception("password authentication failed")
        with pytest.raises(DatabaseConnectionError) as exc_info:
            create_database("postgresql+psycopg2://u:p@h/db")
    assert "PostgreSQL" in exc_info.value.message
