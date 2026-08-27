"""Provider selection for SCM adapters."""

from __future__ import annotations

from codereviewer.adapters.scm.github import GitHubProvider
from codereviewer.adapters.scm.gitlab import GitLabProvider
from codereviewer.config import AppConfig
from codereviewer.domain.enums import ProviderKind
from codereviewer.domain.errors import UnsupportedProviderError
from codereviewer.domain.interfaces.scm import SCMProvider


def build_scm_provider(provider: ProviderKind, config: AppConfig) -> SCMProvider:
    """Return the concrete provider implementation for the requested SCM."""

    if provider == ProviderKind.GITHUB:
        return GitHubProvider(config.github)
    if provider == ProviderKind.GITLAB:
        return GitLabProvider(config.gitlab)

    raise UnsupportedProviderError(
        f"provider {provider.value} is not implemented yet."
    )
