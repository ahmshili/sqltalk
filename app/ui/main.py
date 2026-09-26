"""SQLTalk Streamlit application entrypoint."""

from __future__ import annotations

import logging

import streamlit as st

from app.agent.executor import create_sql_agent_executor
from app.config.settings import load_settings
from app.database.connection import DatabaseConnectionError
from app.llm.provider import create_llm
from app.ui.chat import handle_chat_turn, render_empty_state, render_messages
from app.ui.sidebar import render_sidebar
from app.ui.theme import CUSTOM_CSS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def init_session_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []


def render_header() -> None:
    st.markdown(
        """
        <div class="sqltalk-header">
            <div>
                <p class="sqltalk-title">SQLTalk</p>
            </div>
        </div>
        <p class="sqltalk-subtitle">Natural-language interface for Microsoft SQL Server</p>
        """,
        unsafe_allow_html=True,
    )


def render_footer(settings) -> None:
    db_state = "● Connected" if settings.db_connection_string else "● Not configured"
    st.markdown(
        f"""
        <div class="sqltalk-footer">
            <span>DB: {db_state} &nbsp;·&nbsp; Model: {settings.openrouter_model}</span>
            <span class="sqltalk-attribution">
                Built by <a href="https://ashili.pages.dev">Ahmed Shili</a> ·
                <a href="https://github.com/ahmshili">GitHub</a>
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource(show_spinner=False)
def _build_agent(connection_string: str, api_key: str, model: str, base_url: str,
                  temperature: float, max_iterations: int, max_rows: int, read_only: bool):
    """Build (and cache) the agent executor for a given configuration.

    Cached on the full set of parameters that affect behavior, so changing
    any sidebar setting transparently rebuilds the agent instead of reusing
    a stale one.
    """
    settings = load_settings(
        db_connection_string=connection_string,
        openrouter_api_key=api_key,
        openrouter_model=model,
        max_iterations=max_iterations,
        max_rows=max_rows,
        read_only=read_only,
        temperature=temperature,
    )
    llm = create_llm(settings)
    return create_sql_agent_executor(
        llm=llm,
        connection_string=connection_string,
        max_iterations=max_iterations,
        max_rows=max_rows,
        read_only=read_only,
    )


def main() -> None:
    st.set_page_config(page_title="SQLTalk", page_icon="🗃️", layout="centered")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    init_session_state()
    settings = load_settings()
    render_header()

    agent_overrides = render_sidebar(settings)
    settings.read_only = agent_overrides["read_only"]
    settings.max_iterations = agent_overrides["max_iterations"]
    settings.max_rows = agent_overrides["max_rows"]

    missing = settings.missing_required()
    if missing:
        st.error(
            "Missing required configuration: "
            + ", ".join(f"`{m}`" for m in missing)
            + ". Add these to your `.env` file (see `.env.example`)."
        )
        return

    try:
        agent_executor = _build_agent(
            settings.db_connection_string,
            settings.openrouter_api_key,
            settings.openrouter_model,
            settings.openrouter_base_url,
            settings.temperature,
            settings.max_iterations,
            settings.max_rows,
            settings.read_only,
        )
    except DatabaseConnectionError as exc:
        st.error(exc.message)
        with st.expander("Technical details"):
            st.code(exc.detail or "No further details available.")
        return
    except ValueError as exc:
        st.error(str(exc))
        return

    if not st.session_state.messages:
        render_empty_state()
    else:
        render_messages()

    prompt = st.chat_input("Ask your database...")
    pending = st.session_state.pop("pending_prompt", None)
    prompt = prompt or pending

    if prompt:
        handle_chat_turn(agent_executor, prompt)
        st.rerun()

    render_footer(settings)


if __name__ == "__main__":
    main()
