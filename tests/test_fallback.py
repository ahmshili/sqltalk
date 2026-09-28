"""Tests for the multi-provider agent fallback chain (mocked LLMs/DBs)."""

from unittest.mock import MagicMock, patch

import pytest

from app.agent.fallback import (
    FallbackAgentChain,
    build_fallback_agent_chain,
    is_invalid_output,
    is_retryable,
)
from app.llm.provider import ProviderSpec, collect_provider_specs


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # Thorough env isolation: the developer's local .env may carry several
    # numbered keys per provider (GROQ_API_KEY_1..N etc.), and any one of
    # them leaking in changes collect_provider_specs' expansion. Delete the
    # base keys, the models, and a generous numbered range for all providers.
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
                "GROQ_MODEL", "GEMINI_MODEL", "OPENROUTER_MODEL",
                "GROQ_MAX_TOKENS", "LLM_PROVIDER_ORDER"):
        monkeypatch.delenv(var, raising=False)
    for provider in ("GROQ", "GEMINI", "OPENROUTER"):
        for i in range(1, 11):
            monkeypatch.delenv(f"{provider}_API_KEY_{i}", raising=False)


def _agent(output: str | None = None, error: Exception | None = None):
    agent = MagicMock()
    agent.tools = []
    if error is not None:
        agent.invoke.side_effect = error
    else:
        agent.invoke.return_value = {"output": output or "answer"}
    return agent


# ---------------------------------------------------------------------------
# collect_provider_specs
# ---------------------------------------------------------------------------

def test_specs_priority_order_groq_gemini_openrouter(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    specs = collect_provider_specs()
    assert [s.provider for s in specs] == ["groq", "gemini", "openrouter"]


def test_specs_multi_key_expansion(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k1,k2")
    monkeypatch.setenv("GEMINI_API_KEY_1", "m1")
    specs = collect_provider_specs()
    assert [s.api_key for s in specs] == ["k1", "k2", "m1"]
    assert all(s.provider == "groq" for s in specs[:2])


def test_specs_skip_unconfigured_providers():
    assert collect_provider_specs() == []


def test_specs_model_overrides(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    specs = collect_provider_specs(provider_models={"groq": "llama-3.1-8b-instant"})
    assert specs[0].model == "llama-3.1-8b-instant"


def test_specs_extra_keys_prepend_env_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "env-key")
    specs = collect_provider_specs(provider_keys={"groq": ["temp-key"]})
    assert [s.api_key for s in specs] == ["temp-key", "env-key"]


def test_specs_honor_custom_provider_order(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    specs = collect_provider_specs(provider_order=["openrouter", "groq", "gemini"])
    assert [s.provider for s in specs] == ["openrouter", "groq", "gemini"]


def test_specs_order_falls_back_to_env_var(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gemini,openrouter,groq")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    specs = collect_provider_specs()
    assert [s.provider for s in specs] == ["gemini", "openrouter", "groq"]


def test_specs_partial_order_appends_remaining(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    specs = collect_provider_specs(provider_order=["gemini"])
    assert [s.provider for s in specs] == ["gemini", "groq", "openrouter"]


def test_specs_all_providers_present_despite_bad_order(monkeypatch):
    # Unknown tokens are dropped by normalize_provider_order; no provider
    # ever silently disappears from the chain because of a typo'd order.
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    specs = collect_provider_specs(provider_order=["cohere", "bogus"])
    assert [s.provider for s in specs] == ["groq", "gemini", "openrouter"]


def test_created_llm_is_genuine_base_language_model():
    # The whole point: no fallback wrappers — each spec yields a real model.
    from langchain_core.language_models import BaseLanguageModel
    spec = ProviderSpec(provider="groq", model="llama-3.3-70b-versatile", api_key="test")
    llm = __import__("app.llm.provider", fromlist=["create_llm_for_provider"]).create_llm_for_provider(spec)
    assert isinstance(llm, BaseLanguageModel)
    assert not hasattr(llm, "with_fallbacks") or type(llm).__name__ != "RunnableWithFallbacks"


# ---------------------------------------------------------------------------
# FallbackAgentChain invocation-level behavior
# ---------------------------------------------------------------------------

def test_first_agent_success_no_fallback():
    a1, a2 = _agent("from-groq"), _agent("from-gemini")
    chain = FallbackAgentChain(
        agents=[a1, a2],
        specs=[ProviderSpec("groq", "m", "k1"), ProviderSpec("gemini", "m", "k2")],
    )
    result = chain.invoke({"input": "q"})
    assert result["output"] == "from-groq"
    a2.invoke.assert_not_called()


def test_fallback_on_rate_limit_error():
    a1 = _agent(error=Exception("Error code: 429 - rate limit exceeded"))
    a2 = _agent("from-gemini")
    chain = FallbackAgentChain(
        agents=[a1, a2],
        specs=[ProviderSpec("groq", "m", "k1"), ProviderSpec("gemini", "m", "k2")],
    )
    result = chain.invoke({"input": "q"})
    assert result["output"] == "from-gemini"
    assert chain.active_label == "gemini/m"


def test_fallback_through_all_failures_reraises_last():
    a1 = _agent(error=Exception("429"))
    a2 = _agent(error=Exception("quota exceeded"))
    a3 = _agent(error=Exception("503 service unavailable"))
    chain = FallbackAgentChain(
        agents=[a1, a2, a3],
        specs=[
            ProviderSpec("groq", "m", "k1"),
            ProviderSpec("gemini", "m", "k2"),
            ProviderSpec("openrouter", "m", "k3"),
        ],
    )
    with pytest.raises(Exception, match="503"):
        chain.invoke({"input": "q"})
    # Every agent was attempted; the chain did NOT silently advance to the
    # failing provider — the label still reflects the first (entry) agent.
    a3.invoke.assert_called_once()
    assert chain.active_label == "groq/m"


def test_empty_chain_rejected():
    with pytest.raises(ValueError):
        FallbackAgentChain(agents=[], specs=[])


def test_is_retryable_covers_provider_errors():
    assert is_retryable(Exception("429 rate limit"))
    assert is_retryable(Exception("invalid api key"))
    assert is_retryable(Exception("something unexpected"))
    assert not is_retryable(KeyboardInterrupt())


# ---------------------------------------------------------------------------
# Output sanity gate: returned-but-unusable outputs must fall through
# ---------------------------------------------------------------------------

def test_invalid_output_empty_and_whitespace():
    assert is_invalid_output("")
    assert is_invalid_output("   \n\t ")
    assert is_invalid_output(None)
    assert is_invalid_output(123)


def test_invalid_output_silent_iteration_limit():
    # LangChain *returns* this instead of raising when the agent exhausts
    # max_iterations — it must read as a failure, not a success.
    assert is_invalid_output(
        "Agent stopped due to iteration limit or time limit."
    )


def test_invalid_output_leaked_react_scaffolding():
    # What weak fallback models actually emit (seen in production traces).
    assert is_invalid_output(
        "Thought: I should query the table now\nAction: sql_db_query\n"
        "Action Input: SELECT 1"
    )
    assert is_invalid_output("Invalid Format: Missing 'Action:' after 'Thought:'")


def test_valid_output_answers_are_accepted():
    # Real answers — even ones that *mention* SQL or the word 'Action' —
    # must pass; the gate only flags failure scaffolding.
    assert not is_invalid_output("There are 504 products in the database.")
    assert not is_invalid_output(
        "The top customer is Customer 29825 with 45 orders totaling $123,456.78."
    )
    assert not is_invalid_output(
        "You could answer this with: SELECT COUNT(*) FROM Sales.Customer"
    )


def test_fallback_on_iteration_limit_output():
    # The silent give-up must behave like a raised error: the next provider
    # answers instead of the chain accepting a non-answer.
    a1 = _agent(output="Agent stopped due to iteration limit or time limit.")
    a2 = _agent("from-gemini")
    chain = FallbackAgentChain(
        agents=[a1, a2],
        specs=[ProviderSpec("groq", "m", "k1"), ProviderSpec("gemini", "m", "k2")],
    )
    result = chain.invoke({"input": "q"})
    assert result["output"] == "from-gemini"


def test_fallback_on_garbage_then_all_garbage_raises():
    # Every agent "completes" but none produces a usable answer: the chain
    # must raise (so the UI shows an error) rather than return garbage.
    a1 = _agent(output="Thought: hmm\nAction Input: x")
    a2 = _agent(output="   ")
    a3 = _agent(output="")
    chain = FallbackAgentChain(
        agents=[a1, a2, a3],
        specs=[
            ProviderSpec("groq", "m", "k1"),
            ProviderSpec("gemini", "m", "k2"),
            ProviderSpec("openrouter", "m", "k3"),
        ],
    )
    with pytest.raises(RuntimeError, match="unusable answer"):
        chain.invoke({"input": "q"})


def test_shared_tools_exposed_for_ui_callback():
    shared_tool = MagicMock()
    a1 = _agent("ok")
    a1.tools = [shared_tool]
    chain = FallbackAgentChain(agents=[a1], specs=[ProviderSpec("groq", "m", "k")])
    assert chain.tools == [shared_tool]


# ---------------------------------------------------------------------------
# Health check (production-safe LLM status signal)
# ---------------------------------------------------------------------------

def test_health_check_true_when_first_llm_responds():
    llm1, llm2 = MagicMock(), MagicMock()
    chain = FallbackAgentChain(
        agents=[_agent(), _agent()],
        specs=[ProviderSpec("groq", "m", "k1"), ProviderSpec("gemini", "m", "k2")],
        llms=[llm1, llm2],
    )
    assert chain.health_check() is True
    llm1.invoke.assert_called_once()
    llm2.invoke.assert_not_called()


def test_health_check_falls_through_failing_llms():
    llm1 = MagicMock()
    llm1.invoke.side_effect = Exception("429 rate limit")
    llm2, llm3 = MagicMock(), MagicMock()
    chain = FallbackAgentChain(
        agents=[_agent(), _agent(), _agent()],
        specs=[
            ProviderSpec("groq", "m", "k1"),
            ProviderSpec("gemini", "m", "k2"),
            ProviderSpec("openrouter", "m", "k3"),
        ],
        llms=[llm1, llm2, llm3],
    )
    assert chain.health_check() is True
    llm1.invoke.assert_called_once()
    llm2.invoke.assert_called_once()
    llm3.invoke.assert_not_called()


def test_health_check_false_when_all_fail():
    llms = []
    for _ in range(3):
        llm = MagicMock()
        llm.invoke.side_effect = Exception("outage")
        llms.append(llm)
    chain = FallbackAgentChain(
        agents=[_agent(), _agent(), _agent()],
        specs=[ProviderSpec("groq", "m", "k"), ProviderSpec("gemini", "m", "k"), ProviderSpec("openrouter", "m", "k")],
        llms=llms,
    )
    assert chain.health_check() is False


def test_health_check_false_with_no_llms():
    # Nothing to probe -> health cannot be confirmed -> False. Honest
    # semantics: the UI then shows "Unavailable" rather than a hollow "Ready".
    # (The production builder always stores llms, so this only arises for
    # hand-built chains.) Must not raise either way.
    chain = FallbackAgentChain(agents=[_agent()], specs=[ProviderSpec("groq", "m", "k")])
    assert chain.health_check() is False


def test_health_check_passes_only_to_first_llm_whose_call_succeeds():
    # The probe must stay trivial: a tiny prompt, no SQL, no tools.
    llm = MagicMock()
    chain = FallbackAgentChain(agents=[_agent()], specs=[ProviderSpec("groq", "m", "k")], llms=[llm])
    chain.health_check()
    args, kwargs = llm.invoke.call_args
    prompt = args[0] if args else kwargs.get("input")
    assert "OK" in str(prompt).upper()


def test_chain_trims_misaligned_specs_and_llms():
    # Defensive: extra specs/llms beyond the agent count get truncated so
    # specs[i]/llms[i]/agents[i] stay index-aligned.
    chain = FallbackAgentChain(
        agents=[_agent()],
        specs=[ProviderSpec("groq", "m", "k1"), ProviderSpec("gemini", "m", "k2")],
        llms=[MagicMock(), MagicMock()],
    )
    assert len(chain.specs) == 1
    assert len(chain.llms) == 1
    assert chain.active_label == "groq/m"


# ---------------------------------------------------------------------------
# build_fallback_agent_chain: wiring only (DB + agents mocked)
# ---------------------------------------------------------------------------

# NOTE: @patch decorators apply bottom-up — the argument order below is
# (create_llm_for_provider, create_sql_agent_executor, create_database).
@patch("app.agent.fallback.create_sql_agent_executor")
@patch("app.agent.fallback.create_llm_for_provider")
@patch("app.agent.fallback.create_database")
def test_build_chain_collects_llms_for_health_check(mock_db, mock_llm, mock_executor, monkeypatch):
    mock_db.return_value = MagicMock()
    mock_executor.return_value = MagicMock()
    mock_llm.side_effect = lambda spec, temperature: MagicMock(name=f"llm-{spec.provider}")
    monkeypatch.setenv("GROQ_API_KEY", "g1")
    monkeypatch.setenv("GEMINI_API_KEY", "m1")

    chain = build_fallback_agent_chain(connection_string="postgresql+psycopg2://u:p@h/db")

    assert len(chain.llms) == len(chain.agents) == len(chain.specs) == 2


@patch("app.agent.fallback.create_sql_agent_executor")
@patch("app.agent.fallback.create_llm_for_provider")
@patch("app.agent.fallback.create_database")
def test_build_chain_threads_provider_order(mock_db, mock_llm, mock_executor, monkeypatch):
    mock_db.return_value = MagicMock()
    mock_executor.return_value = MagicMock()
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")

    build_fallback_agent_chain(
        connection_string="postgresql+psycopg2://u:p@h/db",
        provider_order=["openrouter", "gemini", "groq"],
    )

    specs_used = [call.args[0] for call in mock_llm.call_args_list]
    assert [s.provider for s in specs_used] == ["openrouter", "gemini", "groq"]


@patch("app.agent.fallback.create_sql_agent_executor")
@patch("app.agent.fallback.create_llm_for_provider")
@patch("app.agent.fallback.create_database")
def test_build_chain_one_agent_per_key(mock_db, mock_llm, mock_executor, monkeypatch):
    mock_db.return_value = MagicMock()
    mock_executor.return_value = MagicMock()
    monkeypatch.setenv("GROQ_API_KEY", "g1,g2")
    monkeypatch.setenv("GEMINI_API_KEY", "m1")

    chain = build_fallback_agent_chain(connection_string="postgresql+psycopg2://u:p@h/db")

    assert len(chain.agents) == 3
    assert [s.provider for s in chain.specs] == ["groq", "groq", "gemini"]
    # Every agent shares the same single database reflection.
    assert mock_db.call_count == 1
    assert all(call.kwargs.get("db") is mock_db.return_value for call in mock_executor.call_args_list)


@patch("app.agent.fallback.create_sql_agent_executor")
@patch("app.agent.fallback.create_llm_for_provider")
@patch("app.agent.fallback.create_database")
def test_build_chain_skips_failing_provider(mock_db, mock_llm, mock_executor, monkeypatch):
    mock_db.return_value = MagicMock()
    good = MagicMock()
    mock_executor.side_effect = [Exception("boom"), good]
    monkeypatch.setenv("GROQ_API_KEY", "bad-key")
    monkeypatch.setenv("GEMINI_API_KEY", "good-key")

    chain = build_fallback_agent_chain(connection_string="postgresql+psycopg2://u:p@h/db")

    assert [s.provider for s in chain.specs] == ["gemini"]
    assert chain.agents == [good]


@patch("app.agent.fallback.create_database")
def test_build_chain_no_keys_raises(mock_db, monkeypatch):
    with pytest.raises(ValueError, match="No LLM API keys"):
        build_fallback_agent_chain(connection_string="postgresql+psycopg2://u:p@h/db")
    mock_db.assert_not_called()


@patch("app.agent.fallback.create_sql_agent_executor")
@patch("app.agent.fallback.create_llm_for_provider")
@patch("app.agent.fallback.create_database")
def test_build_chain_passes_dialect_and_overrides(mock_db, mock_llm, mock_executor, monkeypatch):
    mock_db.return_value = MagicMock()
    mock_executor.return_value = MagicMock()
    monkeypatch.setenv("GROQ_API_KEY", "g")

    build_fallback_agent_chain(
        connection_string="postgresql+psycopg2://u:p@h/db",
        provider_models={"groq": "llama-3.1-8b-instant"},
    )

    assert mock_executor.call_args.kwargs["dialect"] == "postgres"
    spec = mock_llm.call_args.args[0] if mock_llm.call_args.args else mock_llm.call_args.kwargs.get("spec")
    assert spec.model == "llama-3.1-8b-instant"
