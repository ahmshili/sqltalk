"""LLM provider layer.

SQLTalk talks to language models exclusively through LangChain's
OpenAI-compatible `ChatOpenAI` client. Today that client is pointed at
OpenRouter, but nothing outside this module knows that: the SQL agent layer
only ever receives a ready-to-use `ChatOpenAI` instance, so swapping in a
different OpenAI-compatible endpoint (OpenAI itself, a local Ollama server,
another aggregator, etc.) means changing this one factory function — not the
agent or UI code.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config.settings import Settings


def create_llm(settings: Settings) -> ChatOpenAI:
    """Create the chat model used by the SQL agent.

    Raises:
        ValueError: if no API key is configured.
    """
    if not settings.openrouter_api_key:
        raise ValueError(
            "No OpenRouter API key configured. Set OPENROUTER_API_KEY in "
            "your .env file or the sidebar."
        )

    return ChatOpenAI(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        temperature=settings.temperature,
        default_headers={
            # Optional but recommended by OpenRouter so usage shows up
            # correctly attributed on their dashboards/leaderboards.
            "HTTP-Referer": "https://ashili.pages.dev",
            "X-Title": "SQLTalk",
        },
    )
