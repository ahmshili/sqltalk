from unittest.mock import MagicMock, patch

import pytest
from langchain_community.utilities import SQLDatabase
from langchain_core.language_models import BaseLanguageModel

from app.config.settings import load_settings
from app.llm.provider import create_llm


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    # Keep the developer's local .env from leaking into these assertions.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")


def test_create_llm_raises_without_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    settings = load_settings(db_connection_string="mssql+pyodbc://x", openrouter_api_key=None)
    with pytest.raises(ValueError):
        create_llm(settings)


@patch("langchain_openai.ChatOpenAI")
def test_create_llm_uses_openrouter_base_url_and_model(mock_chat_openai):
    settings = load_settings(
        db_connection_string="mssql+pyodbc://x",
        openrouter_api_key="sk-or-test",
        openrouter_model="nvidia/nemotron-3-ultra-550b-a55b:free",
    )
    create_llm(settings)
    _, kwargs = mock_chat_openai.call_args
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert kwargs["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert kwargs["api_key"] == "sk-or-test"


@patch("langchain_openai.ChatOpenAI")
def test_openrouter_spec_caps_max_tokens(mock_chat_openai, monkeypatch):
    from app.llm.provider import ProviderSpec, create_llm_for_provider

    monkeypatch.delenv("OPENROUTER_MAX_TOKENS", raising=False)
    create_llm_for_provider(ProviderSpec(provider="openrouter", model="m", api_key="k"))
    assert mock_chat_openai.call_args.kwargs["max_tokens"] == 8192


@patch("langchain_openai.ChatOpenAI")
def test_openrouter_spec_max_tokens_env_override(mock_chat_openai, monkeypatch):
    from app.llm.provider import ProviderSpec, create_llm_for_provider

    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "1024")
    create_llm_for_provider(ProviderSpec(provider="openrouter", model="m", api_key="k"))
    assert mock_chat_openai.call_args.kwargs["max_tokens"] == 1024


@patch("langchain_groq.ChatGroq")
def test_groq_spec_caps_max_tokens_and_disables_retries(mock_chat_groq, monkeypatch):
    # Groq's free tier enforces small output-tokens-per-minute quotas; the
    # request must advertise a capped budget so it isn't rejected with a 429
    # before generation starts. Internal SDK retries must be off so the
    # agent-level fallback chain gets control immediately.
    from app.llm.provider import ProviderSpec, create_llm_for_provider

    monkeypatch.delenv("GROQ_MAX_TOKENS", raising=False)
    create_llm_for_provider(ProviderSpec(provider="groq", model="m", api_key="k"))
    assert mock_chat_groq.call_args.kwargs["max_tokens"] == 768
    assert mock_chat_groq.call_args.kwargs["max_retries"] == 0


@patch("langchain_groq.ChatGroq")
def test_groq_max_tokens_env_override(mock_chat_groq, monkeypatch):
    from app.llm.provider import ProviderSpec, create_llm_for_provider

    monkeypatch.setenv("GROQ_MAX_TOKENS", "512")
    create_llm_for_provider(ProviderSpec(provider="groq", model="m", api_key="k"))
    assert mock_chat_groq.call_args.kwargs["max_tokens"] == 512


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


@patch("app.agent.executor.create_sql_agent")
@patch("app.agent.executor.create_database")
def test_create_sql_agent_executor_accepts_shared_db(mock_create_db, mock_create_sql_agent):
    """The fallback chain passes a pre-built DB: no new reflection, dialect
    threaded into the toolkit."""
    from app.agent.executor import create_sql_agent_executor

    shared_db = MagicMock(spec=SQLDatabase)
    mock_create_sql_agent.return_value = "agent-executor-stub"

    llm = MagicMock(spec=BaseLanguageModel)
    create_sql_agent_executor(
        llm=llm,
        max_iterations=4,
        max_rows=25,
        read_only=True,
        db=shared_db,
        dialect="postgres",
    )

    mock_create_db.assert_not_called()
    toolkit = mock_create_sql_agent.call_args.kwargs["toolkit"]
    assert toolkit.db is shared_db
    assert toolkit.sql_dialect == "postgres"
