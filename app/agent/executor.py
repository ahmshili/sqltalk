"""SQL agent construction.

Builds a classic LangChain ReAct SQL agent (`ZERO_SHOT_REACT_DESCRIPTION`)
wired up with the SQLTalk toolkit. This mirrors the original project's agent
style deliberately — it's simple, well-understood, and produces the
step-by-step reasoning trace the UI's transparency panel relies on.

The builder accepts either a connection string (creates and owns its
database reflection) or an existing `db` instance — the fallback chain passes
one shared, schema-qualified DB so every provider's agent sees identical
schema info.
"""

from __future__ import annotations

from typing import Callable, Optional

from langchain.agents.agent import AgentExecutor
from langchain.agents.types import AgentType
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_core.language_models import BaseLanguageModel
from langchain_community.utilities import SQLDatabase

from app.agent.toolkit import SQLTalkToolkit
from app.database.connection import create_database
from app.database.uri import MSSQL_DIALECT

SQLTALK_SUFFIX = """Begin!

Question: {input}
Thought: I should look at the tables in the database to see what I can query, then check the schema of the relevant tables before writing a query.
{agent_scratchpad}"""


def create_sql_agent_executor(
    llm: BaseLanguageModel,
    connection_string: Optional[str] = None,
    max_iterations: int = 10,
    max_rows: int = 200,
    read_only: bool = True,
    db_schemas: Optional[list] = None,
    on_query: Optional[Callable[[str, str, bool], None]] = None,        db: Optional[SQLDatabase] = None,
        dialect: str = MSSQL_DIALECT,
    **kwargs,
) -> AgentExecutor:
    """Create a ready-to-invoke SQL agent.

    Args:
        llm: A genuine LangChain chat model (see app.llm.provider). Note:
            `RunnableWithFallbacks` (e.g. `ChatOpenAI.with_fallbacks(...)`)
            is NOT acceptable — LangChain's SQL toolkit validates the model
            as a `BaseLanguageModel` and rejects wrappers.
        connection_string: SQLAlchemy connection string for the database.
            Required unless an already-built `db` is passed.
        max_iterations: Cap on agent reasoning steps before it gives up.
        max_rows: Row cap enforced on executed SELECT statements.
        read_only: If True (default), destructive statements are rejected.
        db_schemas: Explicit schemas to reflect. Omit to auto-discover every
            non-system schema (recommended for databases like AdventureWorks
            whose business tables live outside `dbo`).
        on_query: Optional callback invoked as (sql, result, ok) every time
            the agent executes a query — used to feed the UI's "Generated
            SQL" / "Query Results" panels.
        db: Optional shared `SQLDatabase` (preferred by the fallback chain:
            one reflection reused by every provider's agent).
        dialect: `mssql` (default) or `postgres` — selects the row-limit
            syntax and the query-checker prompt.
    """
    if db is None:
        if not connection_string:
            raise ValueError("create_sql_agent_executor needs 'connection_string' or a pre-built 'db'.")
        db = create_database(connection_string, schemas=db_schemas, dialect=dialect)

    toolkit = SQLTalkToolkit(
        db=db,
        llm=llm,
        read_only=read_only,
        max_rows=max_rows,
        sql_dialect=dialect,
        on_query=on_query,
    )

    agent_executor = create_sql_agent(
        llm=llm,
        toolkit=toolkit,
        verbose=True,
        agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        agent_executor_kwargs={
            "handle_parsing_errors": True,
        },
        max_iterations=max_iterations,
        **kwargs,
    )

    return agent_executor
