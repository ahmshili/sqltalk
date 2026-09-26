"""SQL agent construction.

Builds a classic LangChain ReAct SQL agent (`ZERO_SHOT_REACT_DESCRIPTION`)
wired up with the SQLTalk toolkit. This mirrors the original project's agent
style deliberately — it's simple, well-understood, and produces the
step-by-step reasoning trace the UI's transparency panel relies on.
"""

from __future__ import annotations

from typing import Callable, Optional

from langchain.agents.agent import AgentExecutor
from langchain.agents.types import AgentType
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_openai import ChatOpenAI

from app.agent.toolkit import SQLTalkToolkit
from app.database.connection import create_database

SQLTALK_SUFFIX = """Begin!

Question: {input}
Thought: I should look at the tables in the database to see what I can query, then check the schema of the relevant tables before writing a query.
{agent_scratchpad}"""


def create_sql_agent_executor(
    llm: ChatOpenAI,
    connection_string: str,
    max_iterations: int = 6,
    max_rows: int = 200,
    read_only: bool = True,
    on_query: Optional[Callable[[str, str, bool], None]] = None,
    **kwargs,
) -> AgentExecutor:
    """Create a ready-to-invoke SQL agent.

    Args:
        llm: A LangChain chat model (see app.llm.provider).
        connection_string: SQLAlchemy connection string for the database.
        max_iterations: Cap on agent reasoning steps before it gives up.
        max_rows: Row cap enforced on executed SELECT statements.
        read_only: If True (default), destructive statements are rejected.
        on_query: Optional callback invoked as (sql, result, ok) every time
            the agent executes a query — used to feed the UI's "Generated
            SQL" / "Query Results" panels.
    """
    db = create_database(connection_string)

    toolkit = SQLTalkToolkit(
        db=db,
        llm=llm,
        read_only=read_only,
        max_rows=max_rows,
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
