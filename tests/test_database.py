from unittest.mock import MagicMock, patch

import pytest

from app.database.connection import (
    DatabaseConnectionError,
    describe_connection,
    create_database,
    test_connection as probe_connection,
)
from app.database.multi_schema import SYSTEM_SCHEMAS, discover_business_schemas

CONN_STR = (
    "mssql+pyodbc://sa:StrongPass1@localhost/adventureWorks"
    "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
)


def test_describe_connection_extracts_safe_details():
    info = describe_connection(CONN_STR)
    assert info.server == "localhost"
    assert info.database.lower() == "adventureworks"
    assert "ODBC Driver 18" in info.driver


def test_describe_connection_never_leaks_password():
    info = describe_connection(CONN_STR)
    rendered = f"{info.server} {info.database} {info.driver}"
    assert "StrongPass1" not in rendered


def test_discover_business_schemas_excludes_system_schemas():
    mock_inspector = MagicMock()
    mock_inspector.get_schema_names.return_value = [
        "dbo", "Production", "Sales", "sys", "INFORMATION_SCHEMA", "guest",
    ]
    with patch("app.database.multi_schema.inspect", return_value=mock_inspector):
        schemas = discover_business_schemas(MagicMock())
    assert "Production" in schemas
    assert "Sales" in schemas
    assert "dbo" in schemas
    assert not any(s.lower() in SYSTEM_SCHEMAS for s in schemas)


@patch("app.database.connection.MultiSchemaSQLDatabase")
@patch("app.database.connection.discover_business_schemas")
@patch("app.database.connection.create_engine")
def test_create_database_auto_discovers_schemas(mock_create_engine, mock_discover, mock_db_cls):
    mock_discover.return_value = ["Production", "Sales"]
    mock_db_cls.return_value = MagicMock()

    create_database(CONN_STR)

    mock_discover.assert_called_once()
    _, kwargs = mock_db_cls.call_args
    assert kwargs["schemas"] == ["Production", "Sales"]


@patch("app.database.connection.MultiSchemaSQLDatabase")
@patch("app.database.connection.discover_business_schemas")
@patch("app.database.connection.create_engine")
def test_create_database_respects_explicit_schemas(mock_create_engine, mock_discover, mock_db_cls):
    create_database(CONN_STR, schemas=["Production"])

    mock_discover.assert_not_called()
    _, kwargs = mock_db_cls.call_args
    assert kwargs["schemas"] == ["Production"]


@patch("app.database.connection.create_engine")
def test_create_database_wraps_failures(mock_create_engine):
    mock_create_engine.side_effect = Exception("login failed for user 'sa'")
    with pytest.raises(DatabaseConnectionError) as exc_info:
        create_database(CONN_STR)
    assert "connect" in exc_info.value.message.lower()
    assert "login failed" in exc_info.value.detail


@patch("app.database.connection.MultiSchemaSQLDatabase")
@patch("app.database.connection.discover_business_schemas")
@patch("app.database.connection.create_engine")
def test_probe_connection_runs_probe_query(mock_create_engine, mock_discover, mock_db_cls):
    mock_discover.return_value = ["dbo"]
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    info = probe_connection(CONN_STR)

    mock_db.run.assert_called_once_with("SELECT 1")
    assert info.server == "localhost"


@patch("app.database.connection.MultiSchemaSQLDatabase")
@patch("app.database.connection.discover_business_schemas")
@patch("app.database.connection.create_engine")
def test_probe_connection_reports_query_failure(mock_create_engine, mock_discover, mock_db_cls):
    mock_discover.return_value = ["dbo"]
    mock_db = MagicMock()
    mock_db.run.side_effect = Exception("permission denied")
    mock_db_cls.return_value = mock_db

    with pytest.raises(DatabaseConnectionError):
        probe_connection(CONN_STR)
