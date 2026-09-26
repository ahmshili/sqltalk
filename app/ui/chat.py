"""Main chat interface: message history, transparency panels, empty state."""

from __future__ import annotations

import logging
import time
import traceback
from typing import List

import streamlit as st
from langchain.agents.agent import AgentExecutor

from app.ui.theme import EXAMPLE_QUESTIONS

logger = logging.getLogger("sqltalk")


def render_empty_state() -> None:
    st.markdown(
        """
        <div class="empty-state">
            <h2>Ask your database anything.</h2>
            <p>Turn natural language into T-SQL, run it against SQL Server,
            and get a human-readable answer.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Try one of these:")
    cols = st.columns(2)
    clicked: str | None = None
    for i, question in enumerate(EXAMPLE_QUESTIONS):
        with cols[i % 2]:
            if st.button(question, key=f"example_{i}", use_container_width=True):
                clicked = question
    if clicked:
        st.session_state["pending_prompt"] = clicked
        st.rerun()


def _render_transparency(sql_log: List[dict], duration: float | None) -> None:
    if not sql_log:
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


def render_messages() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("error_detail"):
                with st.expander("Error details (technical)"):
                    st.code(message["error_detail"])
            if message["role"] == "assistant" and message.get("sql_log"):
                _render_transparency(message["sql_log"], message.get("duration"))


def _friendly_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "authentication" in text or "login failed" in text:
        return "Could not authenticate with SQL Server. Check your connection settings."
    if "timeout" in text or "timed out" in text:
        return "The request timed out. Try a simpler question or increase max iterations."
    if "rate limit" in text or "429" in text:
        return "The LLM provider rate-limited this request. Wait a moment and try again."
    if "api key" in text or "unauthorized" in text or "401" in text:
        return "Unable to reach the configured LLM provider. Check your OpenRouter API key."
    if "connection" in text or "could not connect" in text:
        return "Unable to reach the configured LLM provider or database."
    return "Something went wrong while processing that question."


def handle_chat_turn(agent_executor: AgentExecutor, prompt: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    sql_log: List[dict] = []
    error_detail: str | None = None

    def on_query(sql: str, result: str, ok: bool) -> None:
        sql_log.append({"sql": sql, "result": result, "ok": ok})

    # Wire the callback into every guarded query tool for this run.
    for tool in agent_executor.tools:
        if hasattr(tool, "on_query"):
            tool.on_query = on_query

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            start = time.time()
            try:
                response = agent_executor.invoke({"input": prompt})
                output = response.get("output", "I couldn't produce an answer for that.")
            except Exception as exc:  # noqa: BLE001
                output = _friendly_error(exc)
                error_detail = traceback.format_exc()
                # Always log the full traceback server-side, regardless of
                # whether the UI's debug expander is opened, so the terminal
                # running `streamlit run` always has the real cause.
                logger.exception("Agent execution failed")
            duration = time.time() - start

        st.markdown(output)
        if error_detail:
            with st.expander("Error details (technical)"):
                st.code(error_detail)
        _render_transparency(sql_log, duration)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": output,
            "sql_log": sql_log,
            "duration": duration,
            "error_detail": error_detail,
        }
    )
