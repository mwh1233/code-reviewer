"""SCM adapters."""

from codereviewer.adapters.scm.github import GitHubProvider
from codereviewer.adapters.scm.gitlab import GitLabProvider

__all__ = ["GitHubProvider", "GitLabProvider"]
