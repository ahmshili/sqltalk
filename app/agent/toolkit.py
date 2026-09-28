"""Custom SQL agent toolkit.

Extends LangChain's `SQLDatabaseToolkit` with:
  * dialect-tightened query-checker prompts (T-SQL or PostgreSQL),
  * a safety gate that rejects destructive statements when read-only mode
    is on (app.database.safety),
  * a dialect-aware row cap applied to every executed SELECT,
  * a transparency hook so the UI can show exactly which SQL was executed
    and what came back, without needing `return_intermediate_steps`.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.tools import BaseTool
from langchain_community.tools.sql_database.tool import (
    InfoSQLDatabaseTool,
    ListSQLDatabaseTool,
    QuerySQLCheckerTool,
    QuerySQLDataBaseTool,
)

from app.database.safety import enforce_row_limit, find_violations
from app.database.uri import MSSQL_DIALECT, POSTGRES_DIALECT

CUSTOM_QUERY_CHECKER_MSSQL = """
    {query}
    Double check the {dialect} query above for common mistakes, including:
    - Using NOT IN with NULL values
    - Using UNION when UNION ALL should have been used
    - Using BETWEEN for exclusive ranges
    - Data type mismatch in predicates
    - Properly quoting identifiers
    - Using the correct number of arguments for functions
    - Casting to the correct data type
    - Using the proper columns for joins
    - Using TOP instead of LIMIT (this is T-SQL / Microsoft SQL Server)
    - Using GETDATE() instead of NOW() for the current date/time

    IMPORTANT: make sure the query matches {dialect} (Microsoft SQL Server) syntax.

    If there are any of the above mistakes, rewrite the query. If there are no
    mistakes, just reproduce the original query.

    Output the final SQL query only.

    SQL Query: """

CUSTOM_QUERY_CHECKER_POSTGRES = """
    {query}
    Double check the {dialect} query above for common mistakes, including:
    - Using NOT IN with NULL values
    - Using UNION when UNION ALL should have been used
    - Using BETWEEN for exclusive ranges
    - Data type mismatch in predicates
    - Properly quoting identifiers
    - Using the correct number of arguments for functions
    - Casting to the correct data type
    - Using the proper columns for joins
    - Using LIMIT instead of TOP (this is PostgreSQL, not T-SQL)
    - Using CURRENT_DATE instead of GETDATE() for today's date
    - Using ILIKE for case-insensitive matching

    IMPORTANT: make sure the query matches {dialect} (PostgreSQL) syntax.

    If there are any of the above mistakes, rewrite the query. If there are no
    mistakes, just reproduce the original query.

    Output the final SQL query only.

    SQL Query: """


def get_query_checker_template(dialect: str) -> str:
    """Return the query-checker prompt for the active database dialect.

    The two templates differ exactly where the dialects differ: row-limit
    syntax (`TOP N` vs `LIMIT N`) and date functions (`GETDATE()` vs
    `CURRENT_DATE`).
    """
    if dialect == POSTGRES_DIALECT:
        return CUSTOM_QUERY_CHECKER_POSTGRES
    return CUSTOM_QUERY_CHECKER_MSSQL


class GuardedQuerySQLDatabaseTool(QuerySQLDataBaseTool):
    """A query-execution tool that enforces read-only safety and a row cap
    before handing the statement to the database, and reports every attempt
    (successful or not) through an on_query callback for UI transparency.
    """

    read_only: bool = True
    max_rows: int = 200
    # NOTE: the field cannot be named `dialect` — BaseSQLDatabaseTool already
    # exposes a `dialect` property and pydantic v1 rejects shadowing it.
    sql_dialect: str = MSSQL_DIALECT
    on_query: Optional[Callable[[str, str, bool], None]] = None

    def _run(self, query: str, **kwargs) -> str:  # type: ignore[override]
        if self.read_only:
            violations = find_violations(query)
            if violations:
                message = " ".join(v.message for v in violations)
                if self.on_query:
                    self.on_query(query, message, False)
                return (
                    f"Error: {message} Rewrite the query as a read-only "
                    "SELECT statement."
                )

        capped_query = enforce_row_limit(query, self.max_rows, self.sql_dialect)
        result = super()._run(capped_query, **kwargs)

        if self.on_query:
            self.on_query(capped_query, result, True)

        return result


class SQLTalkToolkit(SQLDatabaseToolkit):
    """Toolkit for interacting with SQL Server or PostgreSQL, wired up for
    safety and transparency."""

    read_only: bool = True
    max_rows: int = 200
    sql_dialect: str = MSSQL_DIALECT
    on_query: Optional[Callable[[str, str, bool], None]] = None

    def get_tools(self) -> List[BaseTool]:
        list_sql_database_tool = ListSQLDatabaseTool(db=self.db)

        info_sql_database_tool = InfoSQLDatabaseTool(
            db=self.db,
            description=(
                "Input to this tool is a comma-separated list of tables, "
                "output is the schema and sample rows for those tables. "
                "Be sure that the tables actually exist by calling "
                f"{list_sql_database_tool.name} first! "
                "Example Input: table1, table2, table3"
            ),
        )

        sql_flavor = (
            "PostgreSQL query" if self.sql_dialect == POSTGRES_DIALECT else "T-SQL query"
        )
        query_sql_database_tool = GuardedQuerySQLDatabaseTool(
            db=self.db,
            read_only=self.read_only,
            max_rows=self.max_rows,
            sql_dialect=self.sql_dialect,
            on_query=self.on_query,
            description=(
                f"Input to this tool is a detailed and correct {sql_flavor}, "
                "output is a result from the database. If the query is not "
                "correct, an error message will be returned. If an error is "
                "returned, rewrite the query, check the query, and try "
                "again. If you encounter an issue with 'Invalid column "
                f"name', use {info_sql_database_tool.name} to query the "
                "correct table fields."
            ),
        )

        query_sql_checker_tool = QuerySQLCheckerTool(
            db=self.db,
            llm=self.llm,
            template=get_query_checker_template(self.sql_dialect),
            description=(
                "Use this tool to double check if your query is correct "
                "before executing it. Always use this tool before executing "
                f"a query with {query_sql_database_tool.name}!"
            ),
        )

        return [
            query_sql_database_tool,
            info_sql_database_tool,
            list_sql_database_tool,
            query_sql_checker_tool,
        ]
