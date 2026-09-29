"""Agent-level LLM fallback chain.

Why this exists: LangChain's SQL toolkit requires a genuine
`BaseLanguageModel` and rejects `RunnableWithFallbacks` (i.e. the result of
`ChatOpenAI.with_fallbacks(...)`) during Pydantic validation, so model
fallback cannot live inside the model object. Instead, fallback happens at
the agent-invocation level:

  1. Build one complete, ready-to-invoke LangChain SQL Agent per
     provider + API key, in speed priority order
     (Groq -> Gemini -> OpenRouter, expanded over every configured key).
  2. When a user asks a question, invoke the first agent.
  3. If it throws (rate limit, auth error, provider outage, parsing
     failure), catch the exception and fall back to the next agent.

Every agent shares one `SQLDatabase` reflection, so switching providers
mid-question never changes what the agent knows about the schema.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from langchain.agents.agent import AgentExecutor
from langchain_community.utilities import SQLDatabase
from langchain_core.language_models import BaseLanguageModel

from app.agent.executor import create_sql_agent_executor
from app.database.connection import create_database
from app.database.uri import dialect_from_connection_string
from app.llm.provider import (
    ProviderSpec,
    collect_provider_specs,
    create_llm_for_provider,
)

# Prompt used to ping each provider's LLM when the UI health-checks the
# chain. Kept deliberately trivial: one tiny completion, no tools, no SQL.
_HEALTH_CHECK_PROMPT = "Reply with the single word OK"
# Largest token budget a health-check completion is allowed to use.
_HEALTH_CHECK_MAX_TOKENS = 16

logger = logging.getLogger("sqltalk")

# Substrings that mark an agent's *returned* output as unusable even though
# no exception was raised. The worst offender: when a ReAct agent exhausts
# max_iterations, LangChain returns "Agent stopped due to iteration limit..."
# instead of raising — without this gate the fallback chain would accept a
# non-answer as a success and never try the next provider.
_INVALID_OUTPUT_MARKERS = (
    "agent stopped due to iteration limit",
    # Leaked ReAct scaffolding in a *final* answer means the model broke
    # format and the executor bailed (seen with weak fallback models:
    # stray 'Thought:'/'Action Input:' lines, or the executor's own
    # 'Invalid Format' complaint pasted into the output).
    "thought:",
    "action input:",
    "invalid format",
)


def is_invalid_output(output: object) -> bool:
    """Heuristically decide whether an agent's returned output is unusable.

    Only clear failure signals disqualify an answer here — never content:
    the question itself may legitimately mention SQL keywords, 'Thought:',
    or the word 'Action', so matching is deliberately conservative
    (case-insensitive marker substrings, nothing more).

    Returns True for:
      * empty / whitespace-only output,
      * the silent "Agent stopped due to iteration limit" give-up,
      * leaked ReAct scaffolding (Thought:/Action Input:/Invalid Format).
    """
    if not isinstance(output, str):
        return True
    text = output.strip()
    if not text:
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _INVALID_OUTPUT_MARKERS)


def is_retryable(exc: BaseException) -> bool:
    """Should this exception move us to the next provider?

    Deliberately broad: any provider error — rate limit, auth failure,
    outage, even a mid-run parsing blowup — is worth one attempt elsewhere,
    which is exactly the behavior the fallback chain promises. Only
    KeyboardInterrupt / SystemExit (the operator or platform shutting us
    down) is honored immediately.
    """
    return not isinstance(exc, (KeyboardInterrupt, SystemExit))


@dataclass
class FallbackAgentChain:
    """A prioritized list of fully-built SQL agent executors.

    Invoke like a single agent: `chain.invoke({"input": question})`.
    """

    agents: List[AgentExecutor]
    specs: List[ProviderSpec]
    # The shared database reflection every agent's toolkit was built on.
    # Exposed so UI views beyond the chat (Data Explorer, SQL Console) can
    # reuse the same read-only catalog instead of re-reflecting the DB.
    # Excluded from repr/comparison like the other runtime state.
    db: Optional[SQLDatabase] = field(default=None, repr=False, compare=False)
    # LLM clients aligned index-for-index with agents/specs. Stored so the
    # health check can ping each provider directly without running the full
    # SQL agent; excluded from repr/comparison like other runtime state.
    llms: List[BaseLanguageModel] = field(default_factory=list, repr=False, compare=False)
    _index_attr: str = field(default="_active_agent_index", repr=False)

    def __post_init__(self) -> None:
        if not self.agents:
            raise ValueError(
                "No LLM provider could be initialized. Configure at least one "
                "of GROQ_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY."
            )
        # Specs/LLMs may legitimately be longer (extra clients built for
        # providers whose agents failed to construct); trim to the agent
        # count so specs[i] / llms[i] / agents[i] stay aligned.
        if len(self.specs) > len(self.agents):
            self.specs = self.specs[: len(self.agents)]
        if len(self.llms) > len(self.agents):
            self.llms = self.llms[: len(self.agents)]

    # -- introspection -----------------------------------------------------

    @property
    def active_label(self) -> str:
        """Human-readable label of the provider that will serve the next
        question (or the one currently serving it)."""
        if not self.specs:
            return "no provider"
        index = min(getattr(self, self._index_attr, 0), len(self.specs) - 1)
        return self.specs[index].label

    # -- invocation ----------------------------------------------------------

    def invoke(self, inputs: dict, **kwargs) -> dict:
        """Run the question through the chain, falling back on failure.

        Mirrors `AgentExecutor.invoke`'s return shape: the first agent that
        produces a usable output wins. "Failure" covers both raised
        exceptions (rate limit, auth error, outage, parsing blowup) and
        returned-but-unusable outputs (empty answers, the silent
        "Agent stopped due to iteration limit" message, or leaked ReAct
        scaffolding — see `is_invalid_output`). If every agent fails, the
        last exception is re-raised so the UI's existing error handling can
        render it; if every agent returned garbage without raising, a
        RuntimeError describing the situation is raised instead so the user
        sees a real error rather than a hollow non-answer.
        """
        last_error: Optional[BaseException] = None
        total = len(self.agents)
        setattr(self, self._index_attr, 0)

        for attempt, (agent, spec) in enumerate(zip(self.agents, self.specs)):
            try:
                logger.info("LLM attempt %d/%d via %s", attempt + 1, total, spec.label)
                result = agent.invoke(inputs, **kwargs)
                output = result.get("output") if isinstance(result, dict) else None
                if is_invalid_output(output):
                    # A provider can "succeed" while producing garbage (a
                    # silent iteration-limit stop, or leaked ReAct
                    # scaffolding from a weak model). Treat it like a raised
                    # error so the next provider gets a chance to answer.
                    logger.warning(
                        "Provider %s returned an invalid output (empty or "
                        "iteration-limit/ReAct leak); %s",
                        spec.label,
                        "falling back" if attempt < total - 1 else "no providers left",
                    )
                    continue
                setattr(self, self._index_attr, attempt)
                return result
            except Exception as exc:  # noqa: BLE001 - fallback is the whole point
                last_error = exc
                logger.warning(
                    "Provider %s failed (%s: %s); %s",
                    spec.label,
                    type(exc).__name__,
                    exc,
                    "falling back" if attempt < total - 1 else "no providers left",
                )
                if not is_retryable(exc):
                    raise

        if last_error is not None:
            raise last_error
        # Every agent "completed" but none produced a usable answer. A plain
        # Exception (not a provider SDK type) keeps the UI's generic error
        # path; the message explains what actually happened.
        raise RuntimeError(
            "Every configured LLM provider returned an unusable answer "
            "(empty, iteration-limit stop, or malformed agent output). "
            "Please retry — or simplify the question."
        )

    # -- health checking ---------------------------------------------------

    def health_check(self) -> bool:
        """Ping the chain's LLM clients in priority order.

        Returns True as soon as one provider answers a trivial prompt
        ("Reply with OK"); False if none do. Deliberately reveals nothing
        about which provider(s) were used — production callers only get a
        yes/no signal, while dev mode may add per-provider detail separately.

        The SQL agent and its tools are never touched: no query is executed
        and no database call is made.
        """
        for llm in self.llms:
            try:
                # Keep the probe cheap: stop at the first newline and cap the
                # output token budget wherever the client exposes one.
                invoke_kwargs: dict = {"stop": ["\n"]}
                for attr in ("max_tokens", "max_output_tokens"):
                    if hasattr(llm, attr):
                        invoke_kwargs[attr] = _HEALTH_CHECK_MAX_TOKENS
                llm.invoke(_HEALTH_CHECK_PROMPT, **invoke_kwargs)
                return True
            except Exception:  # noqa: BLE001 - any single provider error moves on
                logger.info("Health-check attempt failed; trying next provider", exc_info=True)
                continue
        return False

    # Convenience passthrough so the chain can be dropped in wherever an
    # AgentExecutor was expected by the UI layer.
    @property
    def tools(self) -> list:
        """Tools of the active agent — used by the UI to attach the
        transparency callback (all agents share the same underlying tools)."""
        return self.agents[0].tools if self.agents else []


def build_fallback_agent_chain(
    connection_string: str,
    temperature: float = 0.0,
    # Aligned with app.config.settings.DEFAULT_MAX_ITERATIONS (raised from 6
    # to 10): multi-step questions routinely need more than 6 steps, and a
    # silent iteration-limit stop now reads as an invalid output (see
    # is_invalid_output) rather than a half-answer.
    max_iterations: int = 10,
    max_rows: int = 200,
    read_only: bool = True,
    db_schemas: Optional[list] = None,
    provider_models: Optional[dict] = None,
    provider_keys: Optional[dict] = None,
    provider_order: Optional[List[str]] = None,
    dialect: Optional[str] = None,
    on_query: Optional[Callable[[str, str, bool], None]] = None,
) -> FallbackAgentChain:
    """Build one ready-to-invoke SQL agent per provider/key, in priority order.

    Args:
        connection_string: SQLAlchemy URI for the database.
        provider_models: Optional per-provider model overrides, e.g.
            `{"groq": "llama-3.1-8b-instant"}` (dev-mode sidebar).
        provider_keys: Optional per-provider extra keys, prepended ahead of
            env-configured keys, e.g. `{"groq": ["temp-session-key"]}`
            (dev-mode sidebar).
        provider_order: Optional provider priority order (names as in
            `PROVIDER_ORDER`), e.g. `["openrouter", "groq", "gemini"]`.
            Falls back to `LLM_PROVIDER_ORDER`, then the default speed order.
        dialect: `mssql` or `postgres`; detected from the URI when omitted.

    Raises:
        ValueError: if no provider API key is configured at all.
        DatabaseConnectionError: if the database cannot be reached (raised
            once here rather than per-provider inside the loop).
    """
    resolved_dialect = dialect or dialect_from_connection_string(connection_string)

    specs = collect_provider_specs(
        temperature=temperature,
        provider_models=provider_models,
        provider_keys=provider_keys,
        provider_order=provider_order,
    )
    if not specs:
        raise ValueError(
            "No LLM API keys configured. Set GROQ_API_KEY (recommended — "
            "fastest), GEMINI_API_KEY, and/or OPENROUTER_API_KEY in your "
            ".env or Streamlit secrets."
        )

    db: SQLDatabase = create_database(connection_string, schemas=db_schemas, dialect=resolved_dialect)

    agents: List[AgentExecutor] = []
    built_specs: List[ProviderSpec] = []
    built_llms: List[BaseLanguageModel] = []
    for spec in specs:
        try:
            llm = create_llm_for_provider(spec, temperature=temperature)
            agent = create_sql_agent_executor(
                llm=llm,
                max_iterations=max_iterations,
                max_rows=max_rows,
                read_only=read_only,
                on_query=on_query,
                db=db,
                dialect=resolved_dialect,
            )
        except Exception as exc:  # noqa: BLE001 - one bad key must not sink the chain
            logger.warning("Skipping provider %s — failed to build agent: %s", spec.label, exc)
            continue
        agents.append(agent)
        built_specs.append(spec)
        built_llms.append(llm)

    return FallbackAgentChain(agents=agents, specs=built_specs, llms=built_llms, db=db)
