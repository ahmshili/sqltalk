import os

import pytest

from app.config.settings import (
    load_settings,
    get_groq_max_tokens,
    get_provider_keys,
    get_db_dialect,
    get_openrouter_max_tokens,
    get_provider_order,
    normalize_provider_order,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_OPENROUTER_MODEL,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("DB_CONNECTION_STRING", "DB_DIALECT", "DB_HOST", "DB_NAME",
                "DB_DATABASE", "DB_USER", "DB_PASSWORD", "DB_PORT",
                "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "GROQ_API_KEY",
                "GEMINI_API_KEY", "AGENT_MAX_ITERATIONS", "READ_ONLY_MODE"):
        monkeypatch.delenv(var, raising=False)
    for provider in ("GROQ", "GEMINI", "OPENROUTER"):
        for i in range(1, 6):
            monkeypatch.delenv(f"{provider}_API_KEY_{i}", raising=False)


def test_missing_required_settings_are_reported():
    settings = load_settings()
    missing = settings.missing_required()
    assert any(m.startswith("DB_CONNECTION_STRING") for m in missing)
    assert any("GROQ_API_KEY" in m for m in missing)
    assert not settings.is_ready()


def test_settings_ready_with_openrouter_key(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION_STRING", "mssql+pyodbc://user:pass@host/db")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    settings = load_settings()
    assert settings.is_ready()
    assert settings.missing_required() == []


def test_settings_ready_with_groq_key_alone(monkeypatch):
    # Any single provider key satisfies the LLM requirement.
    monkeypatch.setenv("DB_CONNECTION_STRING", "mssql+pyodbc://user:pass@host/db")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    settings = load_settings()
    assert settings.is_ready()


def test_default_model_used_when_not_configured():
    settings = load_settings()
    assert settings.openrouter_model == DEFAULT_OPENROUTER_MODEL


def test_model_overridden_by_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "some/other-model:free")
    settings = load_settings()
    assert settings.openrouter_model == "some/other-model:free"


def test_explicit_argument_overrides_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "env-model")
    settings = load_settings(openrouter_model="explicit-model")
    assert settings.openrouter_model == "explicit-model"


def test_read_only_defaults_true():
    settings = load_settings()
    assert settings.read_only is True


def test_read_only_can_be_disabled_via_env(monkeypatch):
    monkeypatch.setenv("READ_ONLY_MODE", "false")
    settings = load_settings()
    assert settings.read_only is False


# ---------------------------------------------------------------------------
# Provider keys: comma-separated and numbered forms
# ---------------------------------------------------------------------------

def test_provider_keys_comma_separated(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "key1, key2 ,key3")
    assert get_provider_keys("groq") == ["key1", "key2", "key3"]


def test_provider_keys_numbered(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY_1", "a")
    monkeypatch.setenv("GEMINI_API_KEY_2", "b")
    assert get_provider_keys("gemini") == ["a", "b"]


def test_provider_keys_combined_forms_keep_order(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "first,second")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "third")
    assert get_provider_keys("openrouter") == ["first", "second", "third"]


def test_provider_keys_empty_when_unset():
    assert get_provider_keys("groq") == []


# ---------------------------------------------------------------------------
# Provider order: normalize + env resolution
# ---------------------------------------------------------------------------

def test_normalize_order_none_returns_default():
    assert normalize_provider_order(None) == ["groq", "gemini", "openrouter"]


def test_normalize_order_empty_string_returns_default():
    assert normalize_provider_order("") == ["groq", "gemini", "openrouter"]
    assert normalize_provider_order("   ") == ["groq", "gemini", "openrouter"]


def test_normalize_order_case_and_whitespace_insensitive():
    assert normalize_provider_order(" OpenRouter , GROQ , Gemini ") == [
        "openrouter", "groq", "gemini",
    ]


def test_normalize_order_full_reorder():
    assert normalize_provider_order("openrouter,gemini,groq") == [
        "openrouter", "gemini", "groq",
    ]


def test_normalize_order_deduplicates():
    assert normalize_provider_order("groq,groq,gemini") == ["groq", "gemini", "openrouter"]


def test_normalize_order_missing_providers_appended_in_default_order():
    # A partial override re-prioritizes but never silently disables a
    # configured provider.
    assert normalize_provider_order("gemini") == ["gemini", "groq", "openrouter"]


def test_normalize_order_unknown_tokens_ignored():
    assert normalize_provider_order("cohere,groq,bogus") == ["groq", "gemini", "openrouter"]


def test_normalize_order_wholly_invalid_returns_default():
    assert normalize_provider_order("cohere,mistral") == ["groq", "gemini", "openrouter"]


def test_normalize_order_accepts_list_input():
    assert normalize_provider_order(["openrouter", "groq"]) == [
        "openrouter", "groq", "gemini",
    ]


def test_provider_order_env_var(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "openrouter, groq, gemini")
    assert get_provider_order() == ["openrouter", "groq", "gemini"]


def test_provider_order_env_var_partial(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gemini")
    assert get_provider_order() == ["gemini", "groq", "openrouter"]


def test_provider_order_env_var_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "not-a-provider")
    assert get_provider_order() == ["groq", "gemini", "openrouter"]


def test_provider_order_env_var_unset(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER_ORDER", raising=False)
    assert get_provider_order() == ["groq", "gemini", "openrouter"]


# ---------------------------------------------------------------------------
# Dialect + DB parts resolution
# ---------------------------------------------------------------------------

def test_dialect_defaults_to_mssql():
    assert get_db_dialect() == "mssql"


def test_dialect_postgres_alias(monkeypatch):
    monkeypatch.setenv("DB_DIALECT", "PostgreSQL")
    assert get_db_dialect() == "postgres"


def test_dialect_invalid_value_raises(monkeypatch):
    monkeypatch.setenv("DB_DIALECT", "oracle")
    with pytest.raises(ValueError):
        get_db_dialect()


def test_explicit_connection_string_wins_over_parts(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION_STRING", "mssql+pyodbc://u:p@h/db")
    monkeypatch.setenv("DB_DIALECT", "postgres")
    monkeypatch.setenv("DB_HOST", "ignored.neon.tech")
    monkeypatch.setenv("DB_NAME", "other")
    monkeypatch.setenv("DB_USER", "other")
    monkeypatch.setenv("DB_PASSWORD", "other")
    settings = load_settings()
    assert settings.db_connection_string == "mssql+pyodbc://u:p@h/db"


def test_postgres_parts_build_uri(monkeypatch):
    monkeypatch.setenv("DB_DIALECT", "postgres")
    monkeypatch.setenv("DB_HOST", "ep-x.neon.tech")
    monkeypatch.setenv("DB_NAME", "neondb")
    monkeypatch.setenv("DB_USER", "app_owner@ep-x")
    monkeypatch.setenv("DB_PASSWORD", "s3cret")
    settings = load_settings()
    assert settings.db_connection_string == (
        "postgresql+psycopg2://app_owner%40ep-x:s3cret@ep-x.neon.tech:5432/neondb?sslmode=require"
    )


def test_mssql_parts_build_uri(monkeypatch):
    monkeypatch.setenv("DB_DIALECT", "mssql")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "adventureWorks")
    monkeypatch.setenv("DB_USER", "sa")
    monkeypatch.setenv("DB_PASSWORD", "p@ss")
    settings = load_settings()
    assert settings.db_connection_string == (
        "mssql+pyodbc://sa:p%40ss@localhost/adventureWorks"
        "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
    )


def test_parts_incomplete_returns_none(monkeypatch):
    monkeypatch.setenv("DB_DIALECT", "postgres")
    monkeypatch.setenv("DB_HOST", "ep-x.neon.tech")
    monkeypatch.setenv("DB_NAME", "neondb")
    # DB_USER / DB_PASSWORD missing
    assert load_settings().db_connection_string is None


# ---------------------------------------------------------------------------
# OpenRouter max_tokens cap
# ---------------------------------------------------------------------------

def test_openrouter_max_tokens_default(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MAX_TOKENS", raising=False)
    assert get_openrouter_max_tokens() == 8192


def test_openrouter_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "1024")
    assert get_openrouter_max_tokens() == 1024


# ---------------------------------------------------------------------------
# Groq max_tokens cap + raised iteration default
# ---------------------------------------------------------------------------

def test_groq_max_tokens_default(monkeypatch):
    monkeypatch.delenv("GROQ_MAX_TOKENS", raising=False)
    assert get_groq_max_tokens() == 768


def test_groq_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("GROQ_MAX_TOKENS", "512")
    assert get_groq_max_tokens() == 512


def test_default_max_iterations_raised_to_10():
    # Multi-step questions routinely exceed 6 steps; 10 is the new floor.
    assert DEFAULT_MAX_ITERATIONS == 10


def test_gemini_default_model_is_current_generation():
    # gemini-1.5-flash is retired; the fallback default must be a live slug.
    assert DEFAULT_GEMINI_MODEL == "gemini-2.5-flash"
