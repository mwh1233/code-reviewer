"""Application configuration for the M3 skeleton."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class GitHubConfig(BaseModel):
    """Configuration required by the GitHub SCM adapter."""

    api_base_url: str = "https://api.github.com"
    token: str | None = None
    timeout_seconds: float = 10.0


class GitLabConfig(BaseModel):
    """Configuration required by the GitLab SCM adapter."""

    api_base_url: str = "https://gitlab.com/api/v4"
    token: str | None = None
    timeout_seconds: float = 10.0


class LLMConfig(BaseModel):
    """Configuration required by the budget-routed M6 LLM provider."""

    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    timeout_seconds: float = 30.0
    fallback_api_key: str | None = None
    fallback_base_url: str | None = None
    fallback_model: str | None = None
    fallback_timeout_seconds: float | None = None
    max_total_tokens: int = 20000
    max_total_cost: float = 5.0

    def primary_model_config(self) -> LLMConfig:
        """Return the primary model endpoint config."""

        return LLMConfig(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            timeout_seconds=self.timeout_seconds,
            max_total_tokens=self.max_total_tokens,
            max_total_cost=self.max_total_cost,
        )

    def fallback_model_config(self) -> LLMConfig:
        """Return the fallback model endpoint config, defaulting to primary values."""

        return LLMConfig(
            api_key=self.fallback_api_key or self.api_key,
            base_url=self.fallback_base_url or self.base_url,
            model=self.fallback_model or self.model,
            timeout_seconds=self.fallback_timeout_seconds or self.timeout_seconds,
            max_total_tokens=self.max_total_tokens,
            max_total_cost=self.max_total_cost,
        )


class PublishConfig(BaseModel):
    """Configuration for provider comment publishing."""

    enabled: bool = False


class AppConfig(BaseModel):
    """Minimal config surface needed to run the current pipeline."""

    app_name: str = "codereviewer"
    artifact_root: Path = Field(default=Path("artifacts"))
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    gitlab: GitLabConfig = Field(default_factory=GitLabConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)


def _parse_bool_env(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def build_app_config(
    *,
    artifact_root: str | Path | None = None,
    github_token: str | None = None,
    github_api_base_url: str | None = None,
    github_timeout_seconds: float | None = None,
    gitlab_token: str | None = None,
    gitlab_api_base_url: str | None = None,
    gitlab_timeout_seconds: float | None = None,
    llm_primary_api_key: str | None = None,
    llm_primary_base_url: str | None = None,
    llm_primary_model: str | None = None,
    llm_primary_timeout_seconds: float | None = None,
    llm_fallback_api_key: str | None = None,
    llm_fallback_base_url: str | None = None,
    llm_fallback_model: str | None = None,
    llm_fallback_timeout_seconds: float | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
    llm_timeout_seconds: float | None = None,
    llm_max_total_tokens: int | None = None,
    llm_max_total_cost: float | None = None,
    publish_enabled: bool | None = None,
) -> AppConfig:
    """Construct config from explicit inputs and environment defaults."""

    resolved_github_timeout = github_timeout_seconds
    if resolved_github_timeout is None:
        timeout_value = os.getenv("GITHUB_TIMEOUT_SECONDS")
        resolved_github_timeout = float(timeout_value) if timeout_value else 10.0

    resolved_gitlab_timeout = gitlab_timeout_seconds
    if resolved_gitlab_timeout is None:
        timeout_value = os.getenv("GITLAB_TIMEOUT_SECONDS")
        resolved_gitlab_timeout = float(timeout_value) if timeout_value else 10.0

    resolved_llm_timeout = llm_primary_timeout_seconds
    if resolved_llm_timeout is None:
        resolved_llm_timeout = llm_timeout_seconds
    if resolved_llm_timeout is None:
        timeout_value = os.getenv("LLM_PRIMARY_TIMEOUT_SECONDS") or os.getenv(
            "LLM_TIMEOUT_SECONDS"
        )
        resolved_llm_timeout = float(timeout_value) if timeout_value else 30.0

    resolved_llm_fallback_timeout = llm_fallback_timeout_seconds
    if resolved_llm_fallback_timeout is None:
        timeout_value = os.getenv("LLM_FALLBACK_TIMEOUT_SECONDS")
        resolved_llm_fallback_timeout = float(timeout_value) if timeout_value else None

    resolved_llm_max_total_tokens = llm_max_total_tokens
    if resolved_llm_max_total_tokens is None:
        token_value = os.getenv("LLM_MAX_TOTAL_TOKENS")
        resolved_llm_max_total_tokens = int(token_value) if token_value else 20000

    resolved_llm_max_total_cost = llm_max_total_cost
    if resolved_llm_max_total_cost is None:
        cost_value = os.getenv("LLM_MAX_TOTAL_COST")
        resolved_llm_max_total_cost = float(cost_value) if cost_value else 5.0

    resolved_llm_api_key = llm_primary_api_key
    if resolved_llm_api_key is None:
        resolved_llm_api_key = llm_api_key
    if resolved_llm_api_key is None:
        resolved_llm_api_key = os.getenv("LLM_PRIMARY_API_KEY") or os.getenv("LLM_API_KEY")

    resolved_llm_base_url = llm_primary_base_url
    if resolved_llm_base_url is None:
        resolved_llm_base_url = llm_base_url
    if resolved_llm_base_url is None:
        resolved_llm_base_url = os.getenv("LLM_PRIMARY_BASE_URL") or os.getenv(
            "LLM_BASE_URL", "https://api.openai.com/v1"
        )

    resolved_llm_model = llm_primary_model
    if resolved_llm_model is None:
        resolved_llm_model = llm_model
    if resolved_llm_model is None:
        resolved_llm_model = os.getenv("LLM_PRIMARY_MODEL") or os.getenv(
            "LLM_MODEL", "gpt-4.1-mini"
        )

    resolved_llm_fallback_api_key = llm_fallback_api_key
    if resolved_llm_fallback_api_key is None:
        resolved_llm_fallback_api_key = os.getenv("LLM_FALLBACK_API_KEY")

    resolved_llm_fallback_base_url = llm_fallback_base_url
    if resolved_llm_fallback_base_url is None:
        resolved_llm_fallback_base_url = os.getenv("LLM_FALLBACK_BASE_URL")

    resolved_llm_fallback_model = llm_fallback_model
    if resolved_llm_fallback_model is None:
        resolved_llm_fallback_model = os.getenv("LLM_FALLBACK_MODEL")

    resolved_publish_enabled = publish_enabled
    if resolved_publish_enabled is None:
        resolved_publish_enabled = _parse_bool_env(
            os.getenv("PUBLISH_ENABLED"),
            default=False,
        )

    return AppConfig(
        artifact_root=Path(artifact_root) if artifact_root is not None else Path("artifacts"),
        github=GitHubConfig(
            token=github_token if github_token is not None else os.getenv("GITHUB_TOKEN"),
            api_base_url=(
                github_api_base_url
                if github_api_base_url is not None
                else os.getenv("GITHUB_API_BASE_URL", "https://api.github.com")
            ),
            timeout_seconds=resolved_github_timeout,
        ),
        gitlab=GitLabConfig(
            token=gitlab_token if gitlab_token is not None else os.getenv("GITLAB_TOKEN"),
            api_base_url=(
                gitlab_api_base_url
                if gitlab_api_base_url is not None
                else os.getenv("GITLAB_API_BASE_URL", "https://gitlab.com/api/v4")
            ),
            timeout_seconds=resolved_gitlab_timeout,
        ),
        llm=LLMConfig(
            api_key=resolved_llm_api_key,
            base_url=resolved_llm_base_url,
            model=resolved_llm_model,
            timeout_seconds=resolved_llm_timeout,
            fallback_api_key=resolved_llm_fallback_api_key,
            fallback_base_url=resolved_llm_fallback_base_url,
            fallback_model=resolved_llm_fallback_model,
            fallback_timeout_seconds=resolved_llm_fallback_timeout,
            max_total_tokens=resolved_llm_max_total_tokens,
            max_total_cost=resolved_llm_max_total_cost,
        ),
        publish=PublishConfig(
            enabled=resolved_publish_enabled,
        ),
    )
