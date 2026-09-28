"""Main chat interface: message history, transparency panels, empty state."""

from __future__ import annotations

import logging
import time
import traceback
from typing import List

import streamlit as st

from app.ui.theme import EXAMPLE_QUESTIONS, mascot_img

logger = logging.getLogger("sqltalk")


def render_example_strip() -> None:
    """Persistent example-question strip.

    Rendered on every rerun (above the chat input, below the transcript) so
    the example prompts remain clickable for the whole session — not just
    the empty state before the first message.
    """
    with st.expander("💡 Example questions", expanded=False):
        cols = st.columns(2)
        clicked: str | None = None
        for i, question in enumerate(EXAMPLE_QUESTIONS):
            with cols[i % 2]:
                if st.button(question, key=f"example_{i}", use_container_width=True):
                    clicked = question
    if clicked:
        st.session_state["pending_prompt"] = clicked
        st.rerun()


def render_empty_state() -> None:
    # Branding accent: the SQLTalk mascot above the empty-state copy (plain
    # text fallback keeps the layout intact if the asset is missing).
    mascot = mascot_img(size=96)
    if mascot:
        st.markdown(
            f"""
            <div class="empty-state">
                {mascot}
                <h2>Ask your database anything.</h2>
                <p>Turn natural language into SQL, run it against the database,
                and get a human-readable answer.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="empty-state">
                <h2>Ask your database anything.</h2>
                <p>Turn natural language into SQL, run it against the database,
                and get a human-readable answer.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.caption(
        "⏳ First load may take ~15-30s while the free infrastructure wakes up "
        "(Neon computes and free LLM tiers are paused when idle). Subsequent "
        "questions are much faster."
    )


def _render_transparency(sql_log: List[dict], duration: float | None, show: bool) -> None:
    if not sql_log:
        return

    if not show:
        return

    tab_sql, tab_results, tab_exec = st.tabs(
        ["▸ Generated SQL", "▸ Query Results", "▸ Execution Details"]
    )

    with tab_sql:
        for entry in sql_log:
            st.code(entry["sql"], language="sql")

    with tab_results:
        for entry in sql_log:
            if entry["ok"]:
                st.text(entry["result"])
            else:
                st.error(entry["result"])

    with tab_exec:
        total = len(sql_log)
        failed = sum(1 for e in sql_log if not e["ok"])
        st.write(f"Queries executed: **{total}**")
        st.write(f"Failed attempts: **{failed}**")
        if duration is not None:
            st.write(f"Duration: **{duration:.1f}s**")
        st.write(f"Status: **{'Success' if failed < total or total == 0 else 'Failed'}**")


def render_messages(show_sql_details: bool = False) -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("error_detail"):
                with st.expander("Error details (technical)"):
                    st.code(message["error_detail"])
            if message["role"] == "assistant" and message.get("sql_log"):
                _render_transparency(message["sql_log"], message.get("duration"), show_sql_details)


def _friendly_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "authentication" in text or "login failed" in text:
        return "Could not authenticate with the database. Check your connection settings."
    if "timeout" in text or "timed out" in text:
        return "The request timed out. Try a simpler question or increase max iterations."
    if "free-models-per-day" in text:
        return (
            "The LLM provider's free daily quota is exhausted — the free "
            "tier allows only a small number of model requests per day, and "
            "the fallback chain already tried every configured provider. "
            "Please try again after the daily reset."
        )
    if "no endpoints found" in text or ("404" in text and "endpoints" in text):
        return (
            "The configured LLM model no longer exists on the provider "
            "(model retired). Update `OPENROUTER_MODEL` in your config to a "
            "slug from the provider's current model list."
        )
    if "payment required" in text or "requires more credits" in text or "402" in text:
        return (
            "The LLM provider rejected the request for lack of credits. The "
            "configured model may be paid-only; free-tier models are "
            "recommended for this demo."
        )
    if "rate limit" in text or "429" in text:
        return "The LLM provider rate-limited this request. Wait a moment and try again."
    if "cannot schedule new futures after interpreter shutdown" in text:
        # Streamlit restarted the script run while the agent was mid-flight
        # (file save, config change, or crash recovery) — not a provider or
        # database problem. The user just needs to send the question again.
        return (
            "The app restarted while your question was being processed. "
            "Please send it again."
        )
    if "api key" in text or "unauthorized" in text or "401" in text:
        return "Unable to reach the configured LLM provider. Check your API keys."
    if "connection" in text or "could not connect" in text:
        return "Unable to reach the configured LLM provider or database."
    return "Something went wrong while processing that question."


# Session-state keys that may exist from previous app versions; safe to
# ignore here, listed for discoverability.
_HEALTH_OK_KEY = "llm_health_ok"
_HEALTH_SIG_KEY = "llm_health_sig"


def _record_llm_ok() -> None:
    """Passively record that the LLM chain answered successfully."""
    st.session_state[_HEALTH_OK_KEY] = True


def _record_llm_down() -> None:
    """Passively record that the latest LLM attempt failed.

    Only downgrades the health signal; a later successful turn (or an
    explicit sidebar test) flips it back to Ready.
    """
    st.session_state[_HEALTH_OK_KEY] = False


def handle_chat_turn(agent_executor, prompt: str) -> None:
    """Run one question through the (fallback) agent chain.

    Accepts any object exposing `.invoke({"input": ...})` — either a plain
    `AgentExecutor` or the app's `FallbackAgentChain` — so the UI does not
    need to know whether one or many providers are configured.
    """
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    sql_log: List[dict] = []
    error_detail: str | None = None

    def on_query(sql: str, result: str, ok: bool) -> None:
        sql_log.append({"sql": sql, "result": result, "ok": ok})

    # Wire the callback into every guarded query tool for this run. The
    # fallback chain shares one underlying toolkit across all its agents, so
    # this single pass covers every provider's agent.
    for tool in agent_executor.tools:
        if hasattr(tool, "on_query"):
            tool.on_query = on_query

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            start = time.time()
            try:
                response = agent_executor.invoke({"input": prompt})
                output = response.get("output", "I couldn't produce an answer for that.")
                if output and not output.startswith("Error:"):
                    # A completed turn means the fallback chain reached at
                    # least one healthy provider. Recorded passively so the
                    # sidebar health pill can show "Ready" without the user
                    # having to run a separate test first.
                    _record_llm_ok()
            except Exception as exc:  # noqa: BLE001
                output = _friendly_error(exc)
                error_detail = traceback.format_exc()
                # Always log the full traceback server-side, regardless of
                # whether the UI's debug expander is opened, so the terminal
                # running `streamlit run` always has the real cause.
                logger.exception("Agent execution failed")
                _record_llm_down()
            duration = time.time() - start

        st.markdown(output)
        if error_detail:
            with st.expander("Error details (technical)"):
                st.code(error_detail)
        _render_transparency(sql_log, duration, st.session_state.get("show_sql_details", False))

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": output,
            "sql_log": sql_log,
            "duration": duration,
            "error_detail": error_detail,
        }
    )
