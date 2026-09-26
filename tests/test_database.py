from unittest.mock import MagicMock, patch

import pytest

from app.database.connection import (
    DatabaseConnectionError,
    describe_connection,
    create_database,
    test_connection as probe_connection,
)

CONN_STR = (
    "mssql+pyodbc://sa:StrongPass1@localhost/adventureWorks"
    "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
)


def test_describe_connection_extracts_safe_details():
    info = describe_connection(CONN_STR)
    assert info.server == "localhost"
    assert info.database == "adventureworks" or info.database == "adventureWorks"
    assert "ODBC Driver 18" in info.driver


def test_describe_connection_never_leaks_password():
    info = describe_connection(CONN_STR)
    rendered = f"{info.server} {info.database} {info.driver}"
    assert "StrongPass1" not in rendered


@patch("app.database.connection.SQLDatabase.from_uri")
def test_create_database_success(mock_from_uri):
    mock_from_uri.return_value = MagicMock()
    db = create_database(CONN_STR)
    assert db is not None
    mock_from_uri.assert_called_once_with(CONN_STR)


@patch("app.database.connection.SQLDatabase.from_uri")
def test_create_database_wraps_failures(mock_from_uri):
    mock_from_uri.side_effect = Exception("login failed for user 'sa'")
    with pytest.raises(DatabaseConnectionError) as exc_info:
        create_database(CONN_STR)
    assert "connect" in exc_info.value.message.lower()
    assert "login failed" in exc_info.value.detail


@patch("app.database.connection.SQLDatabase.from_uri")
def test_probe_connection_runs_probe_query(mock_from_uri):
    mock_db = MagicMock()
    mock_from_uri.return_value = mock_db
    info = probe_connection(CONN_STR)
    mock_db.run.assert_called_once_with("SELECT 1")
    assert info.server == "localhost"


@patch("app.database.connection.SQLDatabase.from_uri")
def test_probe_connection_reports_query_failure(mock_from_uri):
    mock_db = MagicMock()
    mock_db.run.side_effect = Exception("permission denied")
    mock_from_uri.return_value = mock_db
    with pytest.raises(DatabaseConnectionError):
        probe_connection(CONN_STR)
