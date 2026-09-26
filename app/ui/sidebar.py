"""Sidebar: connection status, LLM settings, agent settings, about."""

from __future__ import annotations

import streamlit as st

from app.config.settings import Settings
from app.database.connection import describe_connection, test_connection, DatabaseConnectionError


def _status_pill(state: str, label: str) -> str:
    return (
        f'<span class="status-pill">'
        f'<span class="status-dot {state}"></span>{label}</span>'
    )


def render_database_section(settings: Settings) -> None:
    st.subheader("Database")

    if not settings.db_connection_string:
        st.markdown(_status_pill("disconnected", "Not configured"), unsafe_allow_html=True)
        st.caption("Set `DB_CONNECTION_STRING` in `.env` to connect.")
        return

    info = describe_connection(settings.db_connection_string)
    status_key = f"conn_status_{hash(settings.db_connection_string)}"

    if status_key not in st.session_state:
        st.session_state[status_key] = None  # None = untested

    status = st.session_state[status_key]
    if status == "ok":
        st.markdown(_status_pill("connected", "Connected"), unsafe_allow_html=True)
    elif status == "fail":
        st.markdown(_status_pill("disconnected", "Disconnected"), unsafe_allow_html=True)
    else:
        st.markdown(_status_pill("unknown", "Not tested"), unsafe_allow_html=True)

    st.caption(f"Server: `{info.server}`")
    st.caption(f"Database: `{info.database}`")
    st.caption(f"Driver: `{info.driver}`")

    if st.button("Test connection", use_container_width=True):
        with st.spinner("Testing connection..."):
            try:
                test_connection(settings.db_connection_string)
                st.session_state[status_key] = "ok"
                st.success("Connection successful.")
            except DatabaseConnectionError as exc:
                st.session_state[status_key] = "fail"
                st.error(exc.message)
                with st.expander("Technical details"):
                    st.code(exc.detail or "No further details available.")


def render_llm_section(settings: Settings) -> None:
    st.subheader("Language Model")
    st.caption("Provider: **OpenRouter** (OpenAI-compatible API)")
    st.caption(f"Model: `{settings.openrouter_model}`")
    st.caption(f"Temperature: `{settings.temperature}`")
    if not settings.openrouter_api_key:
        st.warning("No `OPENROUTER_API_KEY` configured.")


def render_agent_section() -> dict:
    st.subheader("Agent")

    read_only = st.toggle(
        "Read-only mode",
        value=st.session_state.get("read_only", True),
        help="When enabled, statements like DROP, DELETE, TRUNCATE, ALTER, "
        "INSERT, and UPDATE are rejected before they reach the database.",
    )
    max_iterations = st.slider(
        "Max iterations",
        min_value=2,
        max_value=15,
        value=st.session_state.get("max_iterations", 6),
        help="Maximum number of reasoning/tool-call steps before the agent "
        "stops and reports what it found so far.",
    )
    max_rows = st.slider(
        "Max returned rows",
        min_value=10,
        max_value=1000,
        step=10,
        value=st.session_state.get("max_rows", 200),
        help="Upper bound on rows pulled back by a single query.",
    )

    st.session_state["read_only"] = read_only
    st.session_state["max_iterations"] = max_iterations
    st.session_state["max_rows"] = max_rows

    if not read_only:
        st.warning(
            "Read-only mode is OFF. The AI-generated SQL could modify or "
            "delete data. Only disable this against a database you can "
            "afford to lose."
        )

    return {
        "read_only": read_only,
        "max_iterations": max_iterations,
        "max_rows": max_rows,
    }


def render_about_section() -> None:
    st.subheader("About")
    st.caption("SQLTalk turns natural-language questions into T-SQL, runs "
                "them against Microsoft SQL Server, and explains the results.")
    st.markdown(
        "[GitHub](https://github.com/ahmshili) · "
        "[Portfolio](https://ashili.pages.dev)"
    )
    with st.expander("Notices"):
        st.write(
            "- Generated SQL is AI-produced — always sanity-check anything "
            "run outside read-only mode.\n"
            "- If you see *\"Agent stopped due to iteration limit\"*, raise "
            "**Max iterations** above.\n"
            "- Based on / inspired by the open-source `trinhvanminh/SQL_Agent` "
            "project."
        )


def render_sidebar(settings: Settings) -> dict:
    with st.sidebar:
        st.markdown("### Settings")
        render_database_section(settings)
        st.divider()
        render_llm_section(settings)
        st.divider()
        agent_overrides = render_agent_section()
        st.divider()
        render_about_section()
    return agent_overrides
