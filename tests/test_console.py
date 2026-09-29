"""Tests for the read-only direct-query layer (console + data explorer)."""

from unittest.mock import MagicMock, patch

import pytest

from app.database.console import (
    CONSOLE_MAX_ROWS,
    check_query,
    quote_identifier,
    run_readonly_query,
)


# ---------------------------------------------------------------------------
# check_query: the allowlist + keyword gate
# ---------------------------------------------------------------------------

def test_plain_select_allowed():
    assert check_query("SELECT * FROM t") is None


def test_cte_select_allowed():
    assert check_query("WITH x AS (SELECT 1 AS n) SELECT * FROM x") is None


def test_show_and_explain_allowed():
    assert check_query("SHOW TABLES") is None
    assert check_query("EXPLAIN SELECT 1") is None


def test_direct_delete_rejected():
    reason = check_query("DELETE FROM sales.orders")
    assert reason is not None and "Blocked" in reason
    # Explicit no-writes messaging: the user is told modification is
    # impossible, not just that the statement failed.
    assert "cannot modify, insert, or delete" in reason


def test_non_select_statement_gets_no_writes_message():
    reason = check_query("VACUUM")
    assert reason is not None
    assert "cannot modify, insert, or delete" in reason


def test_cte_wrapped_delete_rejected():
    # Regression: a WITH-wrapped DELETE must never pass — the keyword gate
    # fires on the DELETE token regardless of CTE wrapping.
    reason = check_query(
        "WITH moved AS (DELETE FROM sales.orders RETURNING *) SELECT * FROM moved"
    )
    assert reason is not None and "Blocked" in reason


def test_cte_wrapped_update_rejected():
    assert check_query(
        "WITH x AS (UPDATE t SET a = 1) SELECT * FROM x"
    ) is not None


def test_cte_wrapped_insert_rejected():
    assert check_query(
        "WITH x AS (INSERT INTO t VALUES (1)) SELECT * FROM x"
    ) is not None


def test_block_comment_prefix_smuggling_rejected():
    # A block comment must not hide the statement's true prefix.
    assert check_query("/* harmless */ DELETE FROM t") is not None


def test_leading_comment_then_select_allowed():
    assert check_query("-- lookup\nSELECT * FROM t") is None


def test_drop_rejected():
    assert check_query("DROP TABLE t") is not None


# ---------------------------------------------------------------------------
# run_readonly_query: gating, capping, rollback
# ---------------------------------------------------------------------------

def _result(returns_rows=True, rows=None, keys=None):
    res = MagicMock()
    res.returns_rows = returns_rows
    res.fetchmany.return_value = rows or []
    res.keys.return_value = keys or []
    return res


def test_unsafe_query_short_circuits_before_db():
    conn = MagicMock()
    result = run_readonly_query(conn, "DELETE FROM t", "postgres")
    assert result.ok is False
    assert "Blocked" in result.message
    conn.execute.assert_not_called()


def test_safe_query_runs_inside_rolled_back_transaction():
    conn = MagicMock()
    trans = MagicMock()
    conn.begin.return_value = trans
    conn.execute.return_value = _result(rows=[(1,), (2,)], keys=["n"])

    result = run_readonly_query(conn, "SELECT n FROM t", "postgres", max_rows=10)

    assert result.ok is True
    assert result.rows == [(1,), (2,)]
    assert result.columns == ["n"]
    trans.rollback.assert_called_once()
    trans.commit.assert_not_called()


def test_db_error_is_normalized_and_rolled_back():
    conn = MagicMock()
    trans = MagicMock()
    conn.begin.return_value = trans
    conn.execute.side_effect = RuntimeError("host db.internal leaked detail")

    result = run_readonly_query(conn, "SELECT 1", "postgres")

    assert result.ok is False
    assert result.message == "Query failed. Check the statement and try again."
    # Raw detail stays out of the friendly message (dev-mode panels may use it).
    assert "db.internal" not in result.message
    trans.rollback.assert_called_once()


def test_postgres_row_limit_injected():
    conn = MagicMock()
    trans = MagicMock()
    conn.begin.return_value = trans
    conn.execute.return_value = _result()

    run_readonly_query(conn, "SELECT * FROM t", "postgres")

    sql = conn.execute.call_args.args[0].text
    assert "LIMIT 500" in sql


def test_mssql_row_limit_injected():
    conn = MagicMock()
    trans = MagicMock()
    conn.begin.return_value = trans
    conn.execute.return_value = _result()

    run_readonly_query(conn, "SELECT * FROM t", "mssql")

    sql = conn.execute.call_args.args[0].text
    assert "SELECT TOP 500" in sql


def test_hard_cap_never_exceeded():
    conn = MagicMock()
    trans = MagicMock()
    conn.begin.return_value = trans
    conn.execute.return_value = _result()

    run_readonly_query(conn, "SELECT * FROM t", "postgres", max_rows=999_999)

    sql = conn.execute.call_args.args[0].text
    assert f"LIMIT {CONSOLE_MAX_ROWS}" in sql


def test_long_text_cells_truncated():
    conn = MagicMock()
    trans = MagicMock()
    conn.begin.return_value = trans
    long_value = "x" * 500
    conn.execute.return_value = _result(rows=[(long_value,)], keys=["v"])

    result = run_readonly_query(conn, "SELECT v FROM t", "postgres")

    assert len(result.rows[0][0]) <= 201  # 200 chars + ellipsis


# ---------------------------------------------------------------------------
# quote_identifier
# ---------------------------------------------------------------------------

def test_quote_identifier_per_dialect():
    assert quote_identifier("orders", "postgres") == '"orders"'
    assert quote_identifier("Orders", "mssql") == "[Orders]"
