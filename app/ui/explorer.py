"""Data Explorer: a graphical, zero-SQL view for non-technical reviewers.

Lists every reflected table (schema-qualified), shows row counts, column
names/types, and an interactive dataframe preview. All reads go through
`app.database.console.run_readonly_query` — the same SELECT-only,
rolled-back path as the SQL Console. Identifiers come from the reflected
catalog (never user input) and are quoted per dialect.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st
from sqlalchemy import MetaData, inspect, text

from app.database.console import (
    CONSOLE_MAX_ROWS,
    MAX_CELL_CHARS,
    quote_identifier,
    run_readonly_query,
)
from app.database.uri import POSTGRES_DIALECT

_EXPLORER_ROW_DEFAULT = 100


def _catalog(engine, schemas: list) -> MetaData:
    """Reflect the given schemas into a fresh catalog (cheap on Neon-scale
    data; SQLAlchemy caches nothing here so each render re-reads DDL only)."""
    metadata = MetaData()
    for schema in schemas:
        try:
            metadata.reflect(bind=engine, schema=schema, views=False)
        except Exception:  # noqa: BLE001 - one odd schema must not kill the view
            continue
    return metadata


def _row_count(conn, qualified: str, dialect: str) -> Optional[int]:
    try:
        result = run_readonly_query(
            conn, f"SELECT COUNT(*) FROM {qualified}", dialect, max_rows=1
        )
        if result.ok and result.rows:
            return int(result.rows[0][0])
    except Exception:  # noqa: BLE001
        pass
    return None


def render_data_explorer(db, dialect: str) -> None:
    """Render the Data Explorer view.

    Args:
        db: The shared MultiSchemaSQLDatabase (reflected catalog).
        dialect: Resolved dialect of the active connection.
    """
    st.subheader("📊 Data Explorer")
    st.caption(
        "Browse the tables behind the demo — no SQL needed. Pick a table to "
        "see its columns and sample its rows."
    )

    tables = sorted(db.get_usable_table_names())
    if not tables:
        st.info("No tables are visible to the app. Check the database configuration.")
        return

    metadata = db._metadata  # noqa: SLF001 - same package family; catalog reuse
    engine = db._engine

    selected = st.selectbox(
        "Table",
        options=tables,
        index=0,
        format_func=lambda t: t,
        help="Schema-qualified table names (e.g. sales.orders).",
    )

    table = metadata.tables.get(selected)
    if table is None:
        st.info("Table details are unavailable for this selection.")
        return

    # -- column overview -----------------------------------------------------
    with st.expander("Columns", expanded=True):
        col_rows = [
            {"Column": c.name, "Type": str(c.type), "Nullable": "yes" if c.nullable else "no"}
            for c in table.columns
        ]
        st.dataframe(pd.DataFrame(col_rows), hide_index=True, use_container_width=True)

    # -- data preview ----------------------------------------------------------
    quoted = quote_identifier(table.name, dialect)
    if table.schema:
        quoted = f"{quote_identifier(table.schema, dialect)}.{quoted}"

    preview_rows = st.slider(
        "Rows to preview",
        min_value=25,
        max_value=CONSOLE_MAX_ROWS,
        value=min(_EXPLORER_ROW_DEFAULT, CONSOLE_MAX_ROWS),
        step=25,
    )

    sql = f"SELECT * FROM {quoted} LIMIT {preview_rows}"
    if dialect != POSTGRES_DIALECT:
        sql = f"SELECT TOP {preview_rows} * FROM {quoted}"

    if st.button("Load preview", type="primary", use_container_width=True):
        st.session_state["explorer_preview_sql"] = sql

    sql_to_run = st.session_state.get("explorer_preview_sql")
    if not sql_to_run:
        st.caption("Click **Load preview** to fetch rows.")
        return
    if not sql_to_run.endswith(str(preview_rows)):
        # Slider changed since the last load — refresh automatically so the
        # preview always matches the visible control.
        st.session_state["explorer_preview_sql"] = sql
        sql_to_run = sql

    with engine.connect() as conn:
        result = run_readonly_query(conn, sql_to_run, dialect, max_rows=preview_rows)

    if not result.ok:
        st.warning(result.message)
        return

    if not result.rows:
        st.info("This table has no rows.")
        return

    df = pd.DataFrame(result.rows, columns=result.columns)
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.caption(
        f"Showing {len(df):,} of the table's rows "
        f"(cells longer than {MAX_CELL_CHARS} characters are truncated)."
    )

    # Row count for context (cheap aggregate, read-only path).
    with engine.connect() as conn:
        total = _row_count(conn, quoted, dialect)
    if total is not None:
        st.caption(f"Table row count: **{total:,}**")
