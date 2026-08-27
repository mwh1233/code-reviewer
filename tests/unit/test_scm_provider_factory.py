"""Unit tests for SCM provider selection."""

from codereviewer.adapters.scm.github import GitHubProvider
from codereviewer.adapters.scm.gitlab import GitLabProvider
from codereviewer.config import build_app_config
from codereviewer.domain.enums import ProviderKind
from codereviewer.services.scm_provider_factory import build_scm_provider


def test_build_scm_provider_returns_github_provider():
    config = build_app_config()

    provider = build_scm_provider(ProviderKind.GITHUB, config)

    assert isinstance(provider, GitHubProvider)


def test_build_scm_provider_returns_gitlab_provider():
    config = build_app_config()

    provider = build_scm_provider(ProviderKind.GITLAB, config)

    assert isinstance(provider, GitLabProvider)
