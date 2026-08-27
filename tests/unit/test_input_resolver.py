"""Unit tests for provider-neutral input resolution."""

import pytest

from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.services.input_resolver import (
    ResolvedReviewInput,
    resolve_review_request,
)


def test_resolve_review_request_from_github_url():
    request = resolve_review_request(
        ResolvedReviewInput(review_url="https://github.com/owner/repo/pull/123")
    )

    assert request.provider == ProviderKind.GITHUB
    assert request.source_kind == ReviewSourceKind.REVIEW_URL
    assert request.repo == "owner/repo"
    assert request.change_number == 123


def test_resolve_review_request_from_gitlab_url():
    request = resolve_review_request(
        ResolvedReviewInput(
            review_url="https://gitlab.com/group/project/-/merge_requests/456"
        )
    )

    assert request.provider == ProviderKind.GITLAB
    assert request.source_kind == ReviewSourceKind.REVIEW_URL
    assert request.repo == "group/project"
    assert request.change_number == 456


def test_resolve_review_request_from_branch_compare():
    request = resolve_review_request(
        ResolvedReviewInput(
            provider="github",
            repo="owner/repo",
            base_branch="main",
            head_branch="feature/x",
        )
    )

    assert request.provider == ProviderKind.GITHUB
    assert request.source_kind == ReviewSourceKind.BRANCH_COMPARE
    assert request.base_branch == "main"
    assert request.head_branch == "feature/x"


def test_resolve_review_request_rejects_missing_inputs():
    with pytest.raises(ValueError, match="either review_url or provider"):
        resolve_review_request(ResolvedReviewInput())
