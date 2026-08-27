"""Tests for application config resolution."""

from __future__ import annotations

from codereviewer.config import build_app_config


def test_build_app_config_supports_primary_and_fallback_llm_env(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PRIMARY_BASE_URL", "https://primary.example.com")
    monkeypatch.setenv("LLM_PRIMARY_MODEL", "primary-model")
    monkeypatch.setenv("LLM_PRIMARY_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback.example.com")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "fallback-model")
    monkeypatch.setenv("LLM_FALLBACK_TIMEOUT_SECONDS", "20")

    config = build_app_config()

    assert config.llm.api_key == "primary-key"
    assert config.llm.base_url == "https://primary.example.com"
    assert config.llm.model == "primary-model"
    assert config.llm.timeout_seconds == 45.0
    assert config.llm.fallback_api_key == "fallback-key"
    assert config.llm.fallback_base_url == "https://fallback.example.com"
    assert config.llm.fallback_model == "fallback-model"
    assert config.llm.fallback_timeout_seconds == 20.0


def test_build_app_config_keeps_legacy_llm_env_as_primary_and_defaults_fallback(monkeypatch):
    monkeypatch.delenv("LLM_PRIMARY_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PRIMARY_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_PRIMARY_MODEL", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "legacy-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://legacy.example.com")
    monkeypatch.setenv("LLM_MODEL", "legacy-model")

    config = build_app_config()
    fallback = config.llm.fallback_model_config()

    assert config.llm.api_key == "legacy-key"
    assert config.llm.base_url == "https://legacy.example.com"
    assert config.llm.model == "legacy-model"
    assert fallback.api_key == "legacy-key"
    assert fallback.base_url == "https://legacy.example.com"
    assert fallback.model == "legacy-model"
