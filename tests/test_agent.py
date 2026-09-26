from unittest.mock import MagicMock, patch

import pytest
from langchain_community.utilities import SQLDatabase
from langchain_core.language_models import BaseLanguageModel

from app.config.settings import load_settings
from app.llm.provider import create_llm


def test_create_llm_raises_without_api_key():
    settings = load_settings(db_connection_string="mssql+pyodbc://x", openrouter_api_key=None)
    with pytest.raises(ValueError):
        create_llm(settings)


@patch("app.llm.provider.ChatOpenAI")
def test_create_llm_uses_openrouter_base_url_and_model(mock_chat_openai):
    settings = load_settings(
        db_connection_string="mssql+pyodbc://x",
        openrouter_api_key="sk-or-test",
        openrouter_model="meta-llama/llama-3.1-405b-instruct:free",
    )
    create_llm(settings)
    _, kwargs = mock_chat_openai.call_args
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert kwargs["model"] == "meta-llama/llama-3.1-405b-instruct:free"
    assert kwargs["api_key"] == "sk-or-test"


@patch("app.agent.executor.create_sql_agent")
@patch("app.agent.executor.create_database")
def test_create_sql_agent_executor_wires_toolkit(mock_create_db, mock_create_sql_agent):
    from app.agent.executor import create_sql_agent_executor

    mock_create_db.return_value = MagicMock(spec=SQLDatabase)
    mock_create_sql_agent.return_value = "agent-executor-stub"

    llm = MagicMock(spec=BaseLanguageModel)
    result = create_sql_agent_executor(
        llm=llm,
        connection_string="mssql+pyodbc://x",
        max_iterations=4,
        max_rows=25,
        read_only=True,
    )

    assert result == "agent-executor-stub"
    _, kwargs = mock_create_sql_agent.call_args
    assert kwargs["max_iterations"] == 4
    toolkit = kwargs["toolkit"]
    assert toolkit.read_only is True
    assert toolkit.max_rows == 25
