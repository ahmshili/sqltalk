"""SQL Console: a read-only query area for technical reviewers.

Accepts a single SELECT/WITH/SHOW/EXPLAIN statement, runs it through
`app.database.console` (keyword gate + allowlist + rolled-back transaction +
row cap) and renders the result as an interactive dataframe. Non-technical
visitors have the Data Explorer; this view is for people who want to poke at
the data directly.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.database.console import MAX_CELL_CHARS, check_query, run_readonly_query

_DEFAULT_QUERY = "SELECT * FROM sales.orders LIMIT 10"


def render_sql_console(db, dialect: str) -> None:
    """Render the SQL Console view.

    Args:
        db: The shared MultiSchemaSQLDatabase (uses its engine).
        dialect: Resolved dialect of the active connection.
    """
    st.subheader("🧪 SQL Console")
    st.caption(
        "Run your own read-only queries against the demo database. Only "
        "SELECT / WITH / SHOW / EXPLAIN statements are accepted — writes are "
        "blocked before they reach the database, and every query runs inside "
        "a rolled-back transaction."
    )

    sql = st.text_area(
        "Query",
        value=st.session_state.get("console_query", _DEFAULT_QUERY),
        key="console_input",
        height=140,
        help="One read-only statement per run.",
    )

    col_run, col_clear = st.columns([1, 1])
    run_clicked = col_run.button("Run query", type="primary", use_container_width=True)
    if col_clear.button("Clear", use_container_width=True):
        st.session_state["console_query"] = _DEFAULT_QUERY
        st.session_state["console_input"] = _DEFAULT_QUERY
        st.rerun()

    if not run_clicked:
        return

    if not sql or not sql.strip():
        st.warning("Type a query first — try the pre-filled example.")
        return

    # Pre-flight rejection: same gate the runner applies, shown before any
    # connection work so the reason is immediate.
    reason = check_query(sql)
    if reason:
        st.warning(reason)
        return

    st.session_state["console_query"] = sql

    engine = db._engine  # noqa: SLF001 - same package family
    with engine.connect() as conn:
        result = run_readonly_query(conn, sql, dialect)

    if not result.ok:
        st.warning(result.message)
        dev_mode = st.session_state.get("dev_mode", False)
        if dev_mode and result.detail:
            with st.expander("Technical detail"):
                st.code(result.detail)
        return

    if not result.rows:
        st.info("The query ran, but returned no rows.")
        return

    df = pd.DataFrame(result.rows, columns=result.columns)
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.caption(
        f"{len(df):,} row{'s' if len(df) != 1 else ''} returned · "
        f"read-only · cells longer than {MAX_CELL_CHARS} characters truncated"
    )
