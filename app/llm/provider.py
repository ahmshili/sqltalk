"""LLM provider layer.

SQLTalk talks to language models exclusively through LangChain
`BaseLanguageModel` clients, one per provider. Supported providers, ordered
by inference speed for the demo fallback chain (see app/agent/fallback.py):

    1. Groq        (default / fastest free tier)
    2. Gemini      (Google AI Studio free tier)
    3. OpenRouter  (OpenAI-compatible aggregator)

Nothing outside this module knows which concrete client is in use: callers
only ever receive a genuine `BaseLanguageModel` instance. That matters
because LangChain's SQL toolkit requires a real model object — wrapper types
such as `RunnableWithFallbacks` (i.e. `ChatOpenAI.with_fallbacks(...)`) are
rejected by its Pydantic validation — so provider fallback must happen at
the agent-invocation level, not by chaining models here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from langchain_core.language_models import BaseLanguageModel

from app.config.settings import (
    DEFAULT_PROVIDER_MODELS,
    Settings,
    get_groq_max_tokens,
    get_openrouter_max_tokens,
    get_provider_keys,
    get_provider_order,
    normalize_provider_order,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


@dataclass
class ProviderSpec:
    """One concrete LLM endpoint the fallback chain can invoke."""

    provider: str          # "groq" | "gemini" | "openrouter"
    model: str             # provider-specific model slug
    api_key: str
    base_url: Optional[str] = None  # OpenAI-compatible endpoints only

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


def create_llm(settings: Settings) -> BaseLanguageModel:
    """Create the chat model used by the SQL agent.

    Kept for backwards compatibility with the original single-provider
    wiring: returns an OpenRouter-backed `ChatOpenAI`.

    Raises:
        ValueError: if no OpenRouter API key is configured.
    """
    if not settings.openrouter_api_key:
        raise ValueError(
            "No OpenRouter API key configured. Set OPENROUTER_API_KEY in "
            "your .env file or the sidebar."
        )

    return _create_openrouter_llm(
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        base_url=settings.openrouter_base_url,
        temperature=settings.temperature,
    )


def _create_openrouter_llm(
    *,
    api_key: str,
    model: str,
    base_url: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
) -> BaseLanguageModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url or "https://openrouter.ai/api/v1",
        temperature=temperature,
        # Cap the advertised completion budget: OpenRouter admits/prices
        # requests against max_tokens, and the library default (100k+)
        # makes near-zero-credit accounts fail with 402 "can only afford N".
        max_tokens=max_tokens,
        default_headers={
            # Optional but recommended by OpenRouter so usage shows up
            # correctly attributed on their dashboards/leaderboards.
            "HTTP-Referer": "https://ashili.pages.dev",
            "X-Title": "SQLTalk",
        },
    )


def _create_groq_llm(
    *,
    api_key: str,
    model: str,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    max_retries: Optional[int] = None,
) -> BaseLanguageModel:
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=model,
        api_key=api_key,
        temperature=temperature,
        # Cap the advertised completion budget: Groq's free tier enforces
        # small per-model output-tokens-per-minute quotas (e.g. 1,000 OTPM),
        # and the uncapped default makes requests get rejected with a 429
        # before generation even starts. See app.config.settings.
        max_tokens=get_groq_max_tokens() if max_tokens is None else max_tokens,
        # Do not let the Groq SDK retry internally: its default backoff is
        # tens of seconds per attempt, which burns the very per-minute token
        # window that tripped the limit. Fail fast so the agent-level
        # fallback chain (app.agent.fallback) can move to the next provider
        # immediately.
        max_retries=0 if max_retries is None else max_retries,
    )


def _create_gemini_llm(
    *,
    api_key: str,
    model: str,
    temperature: float = 0.0,
) -> BaseLanguageModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=temperature,
    )


def create_llm_for_provider(spec: ProviderSpec, temperature: float = 0.0) -> BaseLanguageModel:
    """Instantiate a genuine `BaseLanguageModel` for one provider spec.

    Every returned object is a real LangChain chat model (never a fallback
    wrapper), so it can be handed to LangChain's SQL toolkit directly.
    """
    if spec.provider == "groq":
        return _create_groq_llm(
            api_key=spec.api_key,
            model=spec.model,
            temperature=temperature,
            max_tokens=get_groq_max_tokens(),
            max_retries=0,
        )
    if spec.provider == "gemini":
        return _create_gemini_llm(api_key=spec.api_key, model=spec.model, temperature=temperature)
    if spec.provider == "openrouter":
        return _create_openrouter_llm(
            api_key=spec.api_key,
            model=spec.model,
            base_url=spec.base_url,
            temperature=temperature,
            max_tokens=get_openrouter_max_tokens(),
        )
    raise ValueError(f"Unknown LLM provider: '{spec.provider}'")


def collect_provider_specs(
    temperature: float = 0.0,
    provider_models: Optional[dict] = None,
    provider_keys: Optional[dict] = None,
    provider_order: Optional[List[str]] = None,
) -> List[ProviderSpec]:
    """Build the prioritized provider list for the agent fallback chain.

    Providers are tried in the given priority order — by inference speed
    (Groq -> Gemini -> OpenRouter) unless overridden via `provider_order`
    or the `LLM_PROVIDER_ORDER` environment variable — and expanded over
    every configured API key per provider, e.g. `GROQ_API_KEY=key1,key2`
    yields two Groq specs (key1 tried first). See
    `app.config.settings._get_keys` for the accepted key forms.

    Args:
        temperature: Sampling temperature for all specs.
        provider_models: Optional per-provider model overrides, e.g.
            `{"groq": "llama-3.1-8b-instant"}` (dev-mode sidebar).
        provider_keys: Optional per-provider extra keys prepended ahead of
            the env-configured ones, e.g. `{"groq": ["temp-key"]}`
            (dev-mode sidebar temporary keys).
        provider_order: Optional provider priority order (names as in
            `PROVIDER_ORDER`). Falls back to `get_provider_order()` —
            which honors `LLM_PROVIDER_ORDER` — when omitted.
    """
    model_overrides = provider_models or {}
    key_overrides = provider_keys or {}
    env_var_names = {
        "groq": "GROQ_MODEL",
        "gemini": "GEMINI_MODEL",
        "openrouter": "OPENROUTER_MODEL",
    }

    # An explicit order is normalized (deduped, unknown names dropped,
    # missing providers appended); None defers to LLM_PROVIDER_ORDER / the
    # default speed order.
    order = (
        normalize_provider_order(provider_order)
        if provider_order is not None
        else get_provider_order()
    )
    specs: List[ProviderSpec] = []
    for provider in order:
        keys: List[str] = list(key_overrides.get(provider) or [])
        for env_key in get_provider_keys(provider):
            if env_key not in keys:
                keys.append(env_key)
        if not keys:
            continue
        default_model = os.getenv(env_var_names[provider]) or DEFAULT_PROVIDER_MODELS[provider]
        model = model_overrides.get(provider) or default_model
        for key in keys:
            specs.append(
                ProviderSpec(
                    provider=provider,
                    model=model,
                    api_key=key,
                    base_url=os.getenv("OPENROUTER_BASE_URL") if provider == "openrouter" else None,
                )
            )
    return specs
