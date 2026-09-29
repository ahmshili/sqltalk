from app.database.safety import find_violations, is_safe, enforce_row_limit


def test_safe_select_is_accepted():
    assert is_safe("SELECT TOP 10 ProductID, Name FROM Production.Product")


def test_cte_wrapped_write_is_caught_by_keyword_gate():
    # Regression: WITH-wrapped writes (Postgres data-modifying CTEs) must
    # trip the keyword gate — CTE wrapping must not hide writes from the
    # read-only guard shared by the agent and the SQL console.
    assert not is_safe("WITH moved AS (DELETE FROM t RETURNING *) SELECT * FROM moved")
    assert not is_safe("WITH x AS (UPDATE t SET a = 1) SELECT * FROM x")
    assert not is_safe("WITH x AS (INSERT INTO t VALUES (1)) SELECT * FROM x")


def test_block_comment_smuggling_is_caught():
    # A leading block comment must not hide a destructive statement; the
    # gate inspects the full statement text.
    assert not is_safe("/* note */ DELETE FROM t")


def test_select_with_column_named_like_keyword_is_safe():
    # "created_at" must not falsely trigger the CREATE guard.
    assert is_safe("SELECT created_at FROM Orders")


def test_drop_statement_is_rejected():
    violations = find_violations("DROP TABLE Production.Product")
    assert any(v.keyword == "DROP" for v in violations)
    assert not is_safe("DROP TABLE Production.Product")


def test_delete_statement_is_rejected():
    assert not is_safe("DELETE FROM Sales.Customer WHERE CustomerID = 1")


def test_truncate_statement_is_rejected():
    assert not is_safe("TRUNCATE TABLE Sales.Customer")


def test_update_statement_is_rejected():
    assert not is_safe("UPDATE Production.Product SET ListPrice = 0")


def test_insert_statement_is_rejected():
    assert not is_safe("INSERT INTO Sales.Customer (Name) VALUES ('x')")


def test_row_limit_injected_into_plain_select():
    result = enforce_row_limit("SELECT * FROM Production.Product", max_rows=50)
    assert result.upper().startswith("SELECT TOP 50")


def test_row_limit_not_duplicated_when_top_already_present():
    original = "SELECT TOP 5 * FROM Production.Product"
    assert enforce_row_limit(original, max_rows=50) == original


def test_row_limit_skipped_for_non_select():
    original = "SELECT 1; SELECT 2"
    # Still a SELECT-led statement; ensure no crash and TOP is applied once.
    result = enforce_row_limit(original, max_rows=10)
    assert result.upper().startswith("SELECT TOP 10")
