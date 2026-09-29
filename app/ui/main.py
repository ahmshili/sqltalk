"""SQLTalk Streamlit application entrypoint."""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from app.agent.fallback import build_fallback_agent_chain
from app.config.settings import (
    DEV_MODE_ENV_VAR,
    PROVIDER_ORDER,
    get_db_dialect,
    get_provider_keys,
    get_provider_order,
    load_settings,
    normalize_provider_order,
)
from app.database.connection import DatabaseConnectionError
from app.ui.chat import handle_chat_turn, render_empty_state, render_messages, render_example_strip
from app.ui.sidebar import LLM_HEALTH_KEY, LLM_HEALTH_SIG_KEY, render_sidebar
from app.ui.theme import CUSTOM_CSS, banner_img, mascot_img

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def init_session_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    # Dev-mode overrides live only in session state: they never write back to
    # .env / secrets, and they vanish on rerun-in-a-new-session.
    st.session_state.setdefault("dev_mode", False)
    st.session_state.setdefault("dev_provider_models", {})
    st.session_state.setdefault("dev_api_keys", {})
    st.session_state.setdefault("dev_disabled_providers", ())
    # Session-only fallback order (dev-mode reorder editor). None = default.
    st.session_state.setdefault("dev_provider_order", None)
    # SQL transparency panels (Generated SQL / Query Results / Execution
    # Details): hidden by default for a clean chat; toggle in the sidebar.
    st.session_state.setdefault("show_sql_details", True)
    # LLM health indicator (production sidebar): None = not tested yet.
    st.session_state.setdefault(LLM_HEALTH_KEY, None)
    st.session_state.setdefault(LLM_HEALTH_SIG_KEY, None)


def render_header() -> None:
    # The full banner (mascot + wordmark + tagline) is the app's visual
    # identity; it falls back to the plain-text title when the asset is
    # missing. The subtitle stays as an accessible text line either way.
    banner = banner_img()
    if banner:
        st.markdown(
            f"""
            <div class="sqltalk-banner">{banner}</div>
            <p class="sqltalk-subtitle">Natural-language interface for your database</p>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="sqltalk-header">
                <div>
                    <p class="sqltalk-title">SQLTalk</p>
                </div>
            </div>
            <p class="sqltalk-subtitle">Natural-language interface for your database</p>
            """,
            unsafe_allow_html=True,
        )


def render_footer(settings, active_label: str, *, dev_mode: bool, llm_ok: bool | None) -> None:
    db_state = "● Connected" if settings.db_connection_string else "● Not configured"
    if dev_mode:
        # Developers see exactly which provider/model served the last answer.
        llm_state = f"Model: {active_label}"
    elif llm_ok is True:
        llm_state = "LLM: ● Ready"
    elif llm_ok is False:
        llm_state = "LLM: ● Unavailable"
    else:
        llm_state = "LLM: ● Not tested"
    st.markdown(
        f"""
        <div class="sqltalk-footer">
            <span>DB: {db_state} &nbsp;·&nbsp; {llm_state}</span>
            <span class="sqltalk-attribution">
                Built by <a href="https://ashili.pages.dev">Ahmed Shili</a> ·
                <a href="https://github.com/ahmshili">GitHub</a>
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource(show_spinner=False)
def _build_agent_chain(
    connection_string: str,
    provider_signature: str,
    temperature: float,
    max_iterations: int,
    max_rows: int,
    read_only: bool,
    db_schemas: tuple | None,
    dialect: str,
    provider_models: tuple,
    provider_keys: tuple,
    provider_order: tuple,
):
    """Build (and cache) the fallback agent chain for a given configuration.

    Cached on the full set of parameters that affect behavior, so changing
    any setting transparently rebuilds the chain instead of reusing a stale
    one. `provider_signature` covers every (provider, key, model) triple and
    the effective provider order, so dev-mode overrides, multiple keys per
    provider, and reordering rebuild correctly without leaking keys into
    Streamlit's cache key.

    Note: builds one complete LangChain SQL agent per provider/key — model
    fallback happens at invocation level (see app/agent/fallback.py), never
    via `with_fallbacks`, which LangChain's SQL toolkit rejects.
    """
    return build_fallback_agent_chain(
        connection_string=connection_string,
        temperature=temperature,
        max_iterations=max_iterations,
        max_rows=max_rows,
        read_only=read_only,
        db_schemas=list(db_schemas) if db_schemas else None,
        provider_models=dict(provider_models),
        provider_keys=dict(provider_keys),
        provider_order=list(provider_order) if provider_order else None,
        dialect=dialect,
    )


def _is_dev_mode() -> bool:
    """Dev mode is env-gated: only a truthy `DEV_MODE` enables it. It is
    never inferred from session state, so a production deployment without
    the variable cannot opt in from the UI."""
    import os

    return os.getenv(DEV_MODE_ENV_VAR, "").strip().lower() in {"1", "true", "yes", "on"}


def _collect_dev_overrides() -> dict:
    """Merge dev-mode session overrides into arguments for the chain builder.

    Returns a stable hashable signature for the cache key (labels + key
    fingerprints + models — never the raw keys), the per-provider model
    overrides, the per-provider temporary keys (session-only, kept in
    memory and passed explicitly to the builder — never written to env vars
    or disk), and the effective provider order.
    """
    order = normalize_provider_order(
        st.session_state.get("dev_provider_order") or get_provider_order()
    )
    keys_by_provider: dict = {}
    signature_parts: list = ["order:" + ",".join(order)]
    for provider in order:
        if provider in st.session_state.dev_disabled_providers:
            continue
        temp_keys = list(st.session_state.dev_api_keys.get(provider) or [])
        env_keys = [k for k in get_provider_keys(provider) if k not in temp_keys]
        all_keys = temp_keys + env_keys
        if all_keys:
            keys_by_provider[provider] = all_keys
            fingerprint = ",".join(f"{k[:4]}…{len(k)}" for k in all_keys)
            signature_parts.append(f"{provider}:{fingerprint}")

    signature = "|".join(signature_parts)
    models = {p: m for p, m in st.session_state.dev_provider_models.items() if m}
    return {
        "signature": signature,
        "provider_models": models,
        "keys_by_provider": keys_by_provider,
        "provider_order": order,
    }


def _render_missing_config(missing: list) -> None:
    st.error(
        "Missing required configuration: "
        + ", ".join(f"`{m}`" for m in missing)
        + ". Add these to your `.env` file (see `.env.example`) — or to "
        "Streamlit secrets when deploying."
    )


def _run_auto_llm_check(chain) -> None:
    """One-time-per-session automatic LLM health check.

    First-time visitors should land on a real signal (Ready or Unavailable)
    instead of "Not tested". Runs at most once per chain signature per
    session; the sidebar button still allows a manual re-check, and passive
    signals from chat turns keep the status current afterwards.
    """
    sig = st.session_state.get("llm_chain_signature")
    if st.session_state.get(LLM_HEALTH_KEY) is not None:
        return
    if st.session_state.get("llm_auto_check_sig") == sig:
        return
    st.session_state["llm_auto_check_sig"] = sig
    with st.spinner("Checking the model layer..."):
        try:
            ok = bool(chain.health_check())
        except Exception:  # noqa: BLE001 - the pill is the interface
            ok = False
    st.session_state[LLM_HEALTH_KEY] = ok
    st.session_state[LLM_HEALTH_SIG_KEY] = sig


def _run_pending_llm_test(chain) -> None:
    """Run a queued "Test LLM" request from the sidebar (production only).

    Uses the chain's health check: pings the model layer with a trivial
    prompt and records only the yes/no outcome. Provider identity, models,
    and chain order are never surfaced to the user.
    """
    if not st.session_state.pop("pending_llm_test", False):
        return
    with st.spinner("Testing the model layer..."):
        try:
            ok = bool(chain.health_check())
        except Exception:  # noqa: BLE001 - the pill is the interface, not the traceback
            ok = False
    st.session_state[LLM_HEALTH_KEY] = ok
    st.session_state[LLM_HEALTH_SIG_KEY] = st.session_state.get("llm_chain_signature")
    st.rerun()


def main() -> None:
    # Favicon: a PNG raster of assets/mascot.svg (Streamlit favicons must be
    # raster images; SVG is not supported). Falls back to an emoji if the
    # generated asset is missing.
    st.set_page_config(
        page_title="SQLTalk",
        page_icon="assets/mascot-favicon.png" if Path("assets/mascot-favicon.png").is_file() else "🗃️",
        layout="centered",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    init_session_state()
    settings = load_settings()
    render_header()

    agent_overrides = render_sidebar(settings)
    settings.read_only = agent_overrides["read_only"]
    settings.max_iterations = agent_overrides["max_iterations"]
    settings.max_rows = agent_overrides["max_rows"]

    dev_mode = _is_dev_mode()
    dialect = get_db_dialect()
    if dev_mode:
        dev = _collect_dev_overrides()
    else:
        # Production: env-configured keys only, in the default (or
        # LLM_PROVIDER_ORDER) order. No provider/model information is
        # exposed to the UI beyond a yes/no health signal.
        dev = {
            "signature": "env:" + ",".join(get_provider_order()),
            "provider_models": {},
            "keys_by_provider": {},
            "provider_order": get_provider_order(),
        }

    missing = settings.missing_required()
    if missing:
        _render_missing_config(missing)
        if dev_mode:
            st.info("Dev mode is active: a temporary session key + DB config in the sidebar get you running without touching `.env`.")
        return

    try:
        chain = _build_agent_chain(
            settings.db_connection_string,
            dev["signature"],
            settings.temperature,
            settings.max_iterations,
            settings.max_rows,
            settings.read_only,
            tuple(settings.db_schemas) if settings.db_schemas else None,
            dialect,
            tuple(sorted(dev["provider_models"].items())),
            tuple(sorted((p, tuple(k)) for p, k in dev["keys_by_provider"].items())),
            tuple(dev["provider_order"]),
        )
    except DatabaseConnectionError as exc:
        st.error(exc.message)
        with st.expander("Technical details"):
            st.code(exc.detail or "No further details available.")
        return
    except ValueError as exc:
        st.error(str(exc))
        return

    # Track the chain signature so the LLM health pill can be invalidated
    # when the configuration behind it changes (keys, models, order).
    st.session_state["llm_chain_signature"] = dev["signature"]
    if st.session_state.get(LLM_HEALTH_SIG_KEY) not in (None, dev["signature"]):
        st.session_state[LLM_HEALTH_KEY] = None

    _run_auto_llm_check(chain)
    _run_pending_llm_test(chain)

    if not st.session_state.messages:
        render_empty_state()
    else:
        render_messages(show_sql_details=st.session_state.get("show_sql_details", False))

    prompt = st.chat_input("Ask your database...")
    pending = st.session_state.pop("pending_prompt", None)
    prompt = prompt or pending

    if prompt:
        handle_chat_turn(chain, prompt)
        st.rerun()

    # Persistent example strip: rendered every rerun below the input so the
    # example prompts survive past the first message (see app/ui/chat.py).
    render_example_strip()

    render_footer(
        settings,
        chain.active_label,
        dev_mode=dev_mode,
        llm_ok=st.session_state.get(LLM_HEALTH_KEY),
    )


if __name__ == "__main__":
    main()
