"""Provider-neutral SCM interface skeleton for later milestones."""

from __future__ import annotations

from typing import Protocol

from codereviewer.domain.models import CommentPayload, ReviewRequest, ReviewSnapshot


class SCMProvider(Protocol):
    """Stable interface for SCM providers.

    Concrete implementations arrive in M2 and M3.
    """

    def resolve_snapshot_target(self, request: ReviewRequest) -> ReviewSnapshot:
        """Resolve a normalized request into a provider-backed snapshot."""

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        """Read one text file from the provider at the requested ref."""

    def get_current_head_sha(self, snapshot: ReviewSnapshot) -> str:
        """Resolve the current immutable head SHA for the review target."""

    def publish_review_comment(self, payload: CommentPayload) -> str:
        """Publish one provider comment and return the provider comment id."""
