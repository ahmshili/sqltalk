import os

import pytest

from app.config.settings import load_settings, DEFAULT_OPENROUTER_MODEL


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("DB_CONNECTION_STRING", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
                "AGENT_MAX_ITERATIONS", "READ_ONLY_MODE"):
        monkeypatch.delenv(var, raising=False)


def test_missing_required_settings_are_reported():
    settings = load_settings()
    missing = settings.missing_required()
    assert "DB_CONNECTION_STRING" in missing
    assert "OPENROUTER_API_KEY" in missing
    assert not settings.is_ready()


def test_settings_ready_when_required_vars_present(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION_STRING", "mssql+pyodbc://user:pass@host/db")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    settings = load_settings()
    assert settings.is_ready()
    assert settings.missing_required() == []


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
