"""Sidebar: connection status, LLM status, agent settings, about, and the
env-gated developer section (only rendered when DEV_MODE=true).

Production privacy: the non-developer LLM section intentionally reveals
nothing about which providers are configured, which models are used, or how
the fallback chain is ordered — only whether the model layer is working.
Provider names, model slugs, keys, and ordering are exposed exclusively
inside the env-gated Developer Mode section.
"""

from __future__ import annotations

import os

import streamlit as st

from app.config.settings import (
    DEFAULT_PROVIDER_MODELS,
    PROVIDER_ORDER,
    Settings,
    get_db_dialect,
    get_provider_keys,
    normalize_provider_order,
)
from app.database.connection import describe_connection, test_connection, DatabaseConnectionError
from app.ui.theme import mascot_img

PROVIDER_LABELS = {
    "groq": "Groq",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
}

# Session-state keys for the LLM health indicator (see render_llm_section).
LLM_HEALTH_KEY = "llm_health_ok"       # True / False / None (untested)
LLM_HEALTH_SIG_KEY = "llm_health_sig"  # chain signature at test time


def _dev_mode_enabled() -> bool:
    """Dev mode is env-gated: only a truthy `DEV_MODE` enables it."""
    return os.getenv("DEV_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _status_pill(state: str, label: str) -> str:
    return (
        f'<span class="status-pill">'
        f'<span class="status-dot {state}"></span>{label}</span>'
    )


def render_database_section(settings: Settings) -> None:
    st.subheader("Database")

    if not settings.db_connection_string:
        st.markdown(_status_pill("disconnected", "Not configured"), unsafe_allow_html=True)
        st.caption("Set `DB_CONNECTION_STRING` (or DB_HOST/DB_NAME/DB_USER/DB_PASSWORD) in `.env` to connect.")
        return

    info = describe_connection(settings.db_connection_string)
    status_key = f"conn_status_{hash(settings.db_connection_string)}"

    if status_key not in st.session_state:
        st.session_state[status_key] = None  # None = untested

    if st.session_state[status_key] is None:
        # Auto-check on first load: visitors should see Connected (or a
        # real failure) immediately, never "Not tested". The button below
        # still allows an explicit re-check.
        with st.spinner("Checking connection..."):
            try:
                test_connection(settings.db_connection_string)
                st.session_state[status_key] = "ok"
            except DatabaseConnectionError:
                st.session_state[status_key] = "fail"

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
    st.caption(f"Dialect: `{get_db_dialect()}`")

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


def render_llm_section(settings: Settings, *, dev_mode: bool) -> None:
    """Render the Language Model section.

    Production (dev_mode=False): a single health status pill plus a
    "Test LLM" button — never provider names, model slugs, key counts, or
    chain order. The button only raises the `pending_llm_test` flag; main()
    runs the actual health check once the (cached) agent chain exists.

    Developer mode (dev_mode=True): full per-provider detail, since the
    operator is the one configuring the chain.
    """
    st.subheader("Language Model")

    if dev_mode:
        _render_llm_section_dev(settings)
        return

    status = st.session_state.get(LLM_HEALTH_KEY)
    if status is True:
        st.markdown(_status_pill("connected", "LLM · Ready"), unsafe_allow_html=True)
        st.caption("The model layer answered a health check.")
    elif status is False:
        st.markdown(_status_pill("disconnected", "LLM · Unavailable"), unsafe_allow_html=True)
        st.caption("The model layer did not answer the last check. It may be rate-limited or waking up — try again shortly.")
    else:
        st.markdown(_status_pill("unknown", "LLM · Not tested"), unsafe_allow_html=True)
        st.caption("An automatic check runs when the page loads — provider details stay private.")

    if st.button("Test LLM", use_container_width=True):
        st.session_state["pending_llm_test"] = True
        st.rerun()


def _render_llm_section_dev(settings: Settings) -> None:
    """Full provider detail — developer mode only."""
    for provider in PROVIDER_ORDER:
        keys = get_provider_keys(provider)
        count = len(keys)
        state = "connected" if count else "disconnected"
        plural = "key" if count == 1 else "keys"
        detail = f"{count} {plural}" if count else "not configured"
        st.markdown(_status_pill(state, f"{PROVIDER_LABELS[provider]} — {detail}"), unsafe_allow_html=True)

    order = st.session_state.get("dev_provider_order") or list(PROVIDER_ORDER)
    primary = next((p for p in order if get_provider_keys(p)), None)
    if primary:
        st.caption(f"Priority: {PROVIDER_LABELS[primary]} first, then fallbacks.")
    else:
        st.warning("No LLM API keys configured.")

    if settings.openrouter_model:
        st.caption(f"OpenRouter model: `{settings.openrouter_model}`")
    st.caption(f"Temperature: `{settings.temperature}`")


def render_agent_section() -> dict:
    st.subheader("Agent")

    show_sql_details = st.toggle(
        "Show SQL details",
        value=st.session_state.get("show_sql_details", True),
        help="Show the Generated SQL, Query Results, and Execution Details "
        "panels under each successful answer. On by default so every "
        "answer can be audited; turn off for a minimal chat. Errors are "
        "always shown regardless of this setting.",
    )
    st.session_state["show_sql_details"] = show_sql_details

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
        value=st.session_state.get("max_iterations", 10),
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


def render_provider_order_section() -> None:
    """Session-only reorder editor for the fallback chain (developer mode).

    Persists to `st.session_state["dev_provider_order"]` only. Reordering
    re-prioritizes providers; omitted providers are appended after the
    chosen ones by `normalize_provider_order`, so this can never silently
    disable a configured provider.
    """
    st.subheader("🛠️ Developer Mode")
    st.caption("Session-only overrides. Never persisted; hidden unless DEV_MODE=true.")

    default_order = list(PROVIDER_ORDER)
    current = st.session_state.get("dev_provider_order")
    current = normalize_provider_order(current) if current else default_order

    st.markdown("**Fallback order**")
    st.caption("Providers are tried top to bottom. Unknown names are ignored; "
               "unlisted providers keep a slot at the end of the chain.")
    for position, provider in enumerate(current):
        col_name, col_up, col_down = st.columns([4, 0.5, 0.5])
        col_name.markdown(
            f"<span class='status-pill'>{position + 1}. {PROVIDER_LABELS.get(provider, provider)}</span>",
            unsafe_allow_html=True,
        )
        with col_up:
            if st.button("↑", key=f"order_up_{provider}", disabled=(position == 0), use_container_width=True):
                current[position - 1], current[position] = current[position], current[position - 1]
                st.session_state["dev_provider_order"] = current
                st.rerun()
        with col_down:
            if st.button("↓", key=f"order_down_{provider}", disabled=(position == len(current) - 1), use_container_width=True):
                current[position], current[position + 1] = current[position + 1], current[position]
                st.session_state["dev_provider_order"] = current
                st.rerun()
    if st.button("Reset to default order"):
        st.session_state.pop("dev_provider_order", None)
        st.rerun()


# -- About: the author's personal contact card -----------------------------
# Placeholders are clearly marked; replace the URLs when the profiles exist.
_AUTHOR_NAME = "Ahmed Shili"
_AUTHOR_ROLE = "Builder of SQLTalk"
_CONTACT_LINKS = [
    ("🌐", "Portfolio", "https://ashili.pages.dev"),
    ("💻", "GitHub", "https://github.com/ahmshili"),
    ("❤️", "GitHub Sponsors", "https://github.com/sponsors/ahmshili"),
    ("✉️", "Email", "mailto:ahmed.shili.921@gmail.com"),
    ("💼", "LinkedIn", "https://www.linkedin.com/in/your-handle"),  # TODO(ahmed): replace with your LinkedIn profile URL
    ("𝕏", "X / Twitter", "https://x.com/your-handle"),  # TODO(ahmed): replace with your X profile URL
]


def render_about_section() -> None:
    st.subheader("About")
    st.caption(
        "SQLTalk turns natural-language questions into SQL, runs them "
        "against the configured database, and explains the results."
    )

    mascot = mascot_img(size=48)
    links_html = "".join(
        f'<a href="{href}" target="_blank" rel="noopener noreferrer">'
        f'{icon} {label}</a>'
        for icon, label, href in _CONTACT_LINKS
    )
    identity = (
        f'<div><div class="about-name">{_AUTHOR_NAME}</div>'
        f'<div class="about-role">{_AUTHOR_ROLE}</div></div>'
    )
    mascot_html = mascot or ""
    st.markdown(
        f"""
        <div class="about-card">
            <div class="about-identity">{mascot_html}{identity}</div>
            <div class="about-links">{links_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Notices"):
        st.write(
            "- Generated SQL is AI-produced — always sanity-check anything "
            "run outside read-only mode.\n"
            "- If answers stop early, raise **Max iterations** above."
        )


def render_dev_section() -> dict:
    """Session-only developer overrides, gated behind DEV_MODE=true.

    Everything here lives in `st.session_state` only — nothing is written
    back to `.env` or secrets, and the whole section disappears on any
    deployment where DEV_MODE is false or unset.
    """
    # -- fallback order (session-only reorder editor) -----------------------
    render_provider_order_section()

    # -- provider enable/disable -------------------------------------------
    disabled = st.multiselect(
        "Disabled providers",
        options=list(PROVIDER_ORDER),
        default=list(st.session_state.get("dev_disabled_providers", ())),
        format_func=lambda p: PROVIDER_LABELS[p],
        help="Remove a provider from the fallback chain entirely.",
    )
    st.session_state["dev_disabled_providers"] = tuple(disabled)

    # -- model selection per provider ----------------------------------------
    st.markdown("**Model overrides**")
    provider_models: dict = {}
    for provider in PROVIDER_ORDER:
        model = st.text_input(
            f"{PROVIDER_LABELS[provider]} model",
            value=st.session_state.get("dev_provider_models", {}).get(provider, ""),
            placeholder=f"default: {DEFAULT_PROVIDER_MODELS[provider]}",
            key=f"dev_model_{provider}",
        )
        if model.strip():
            provider_models[provider] = model.strip()
    st.session_state["dev_provider_models"] = provider_models

    # -- temporary session API keys ------------------------------------------
    st.markdown("**Temporary API keys (this session only)**")
    dev_keys: dict = {}
    for provider in PROVIDER_ORDER:
        key = st.text_input(
            f"{PROVIDER_LABELS[provider]} key",
            value="",
            type="password",
            placeholder="paste to override for this session",
            key=f"dev_key_{provider}",
        )
        if key.strip():
            dev_keys[provider] = [key.strip()]
    if dev_keys:
        st.session_state["dev_api_keys"] = dev_keys
    elif not st.session_state.get("_dev_keys_touched", False):
        st.session_state.setdefault("dev_api_keys", {})

    if dev_keys:
        st.caption("Keys live in memory for this browser session only. They are never written to disk or sent anywhere except the provider's own API.")

    # -- chain preview ---------------------------------------------------------
    with st.expander("Fallback chain preview"):
        chain_parts = []
        for provider in (st.session_state.get("dev_provider_order") or normalize_provider_order(None)):
            if provider in disabled:
                continue
            keys = dev_keys.get(provider) or get_provider_keys(provider)
            model = provider_models.get(provider) or DEFAULT_PROVIDER_MODELS[provider]
            for i, _ in enumerate(keys):
                chain_parts.append(f"{i + 1}. {PROVIDER_LABELS[provider]} · {model}")
        if chain_parts:
            st.code("\n".join(chain_parts), language=None)
        else:
            st.caption("No providers enabled.")

    return {
        "disabled": tuple(disabled),
        "provider_models": provider_models,
        "dev_keys": dev_keys,
    }


def render_sidebar(settings: Settings) -> dict:
    """Render the full sidebar and return agent-level overrides."""
    dev_mode = _dev_mode_enabled()
    with st.sidebar:
        st.markdown("### Settings")
        render_database_section(settings)
        st.divider()
        render_llm_section(settings, dev_mode=dev_mode)
        st.divider()
        agent_overrides = render_agent_section()
        st.divider()
        render_about_section()

        # Developer section: env-gated, session-only, completely hidden in
        # production (DEV_MODE false or missing).
        if dev_mode:
            st.divider()
            render_dev_section()

    return agent_overrides
