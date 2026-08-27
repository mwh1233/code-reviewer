"""Normalize user input into provider-neutral review requests."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.models import ReviewRequest


@dataclass(frozen=True)
class ResolvedReviewInput:
    """Raw input values accepted by the CLI and pipeline."""

    review_url: str | None = None
    provider: str | None = None
    repo: str | None = None
    base_branch: str | None = None
    head_branch: str | None = None


def resolve_review_request(raw: ResolvedReviewInput) -> ReviewRequest:
    """Resolve raw inputs into a normalized review request."""

    if raw.review_url:
        if any([raw.provider, raw.repo, raw.base_branch, raw.head_branch]):
            raise ValueError(
                "review_url cannot be combined with provider/repo/branch inputs."
            )
        return _resolve_review_url(raw.review_url)

    if raw.provider or raw.repo or raw.base_branch or raw.head_branch:
        return _resolve_branch_compare(raw)

    raise ValueError(
        "either review_url or provider+repo+base_branch+head_branch is required."
    )


def _resolve_review_url(review_url: str) -> ReviewRequest:
    parsed = urlparse(review_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("review_url must be an absolute URL.")

    path_parts = [part for part in parsed.path.strip("/").split("/") if part]

    github_request = _try_parse_github_review_url(review_url, path_parts)
    if github_request is not None:
        return github_request

    gitlab_request = _try_parse_gitlab_review_url(review_url, path_parts)
    if gitlab_request is not None:
        return gitlab_request

    raise ValueError("unsupported review_url format for GitHub PR or GitLab MR.")


def _try_parse_github_review_url(
    review_url: str, path_parts: list[str]
) -> ReviewRequest | None:
    if len(path_parts) < 4 or path_parts[2] != "pull":
        return None

    repo = "/".join(path_parts[:2])
    change_number = _parse_positive_int(path_parts[3], "GitHub pull request number")
    return ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url=review_url,
        repo=repo,
        change_number=change_number,
    )


def _try_parse_gitlab_review_url(
    review_url: str, path_parts: list[str]
) -> ReviewRequest | None:
    if len(path_parts) < 4:
        return None

    try:
        dash_index = path_parts.index("-")
    except ValueError:
        return None

    if dash_index < 2 or dash_index + 2 >= len(path_parts):
        return None
    if path_parts[dash_index + 1] != "merge_requests":
        return None

    repo = "/".join(path_parts[:dash_index])
    change_number = _parse_positive_int(
        path_parts[dash_index + 2], "GitLab merge request number"
    )
    return ReviewRequest(
        provider=ProviderKind.GITLAB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url=review_url,
        repo=repo,
        change_number=change_number,
    )


def _resolve_branch_compare(raw: ResolvedReviewInput) -> ReviewRequest:
    missing_fields = [
        field_name
        for field_name, value in (
            ("provider", raw.provider),
            ("repo", raw.repo),
            ("base_branch", raw.base_branch),
            ("head_branch", raw.head_branch),
        )
        if not value
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise ValueError(f"branch compare input is missing required fields: {joined}.")

    provider_value = _parse_provider(raw.provider)
    return ReviewRequest(
        provider=provider_value,
        source_kind=ReviewSourceKind.BRANCH_COMPARE,
        repo=raw.repo,
        base_branch=raw.base_branch,
        head_branch=raw.head_branch,
    )


def _parse_provider(value: str | None) -> ProviderKind:
    try:
        return ProviderKind((value or "").lower())
    except ValueError as exc:
        raise ValueError("provider must be one of: github, gitlab.") from exc


def _parse_positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be positive.")
    return parsed
