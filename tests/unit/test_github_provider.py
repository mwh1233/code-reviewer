"""Unit tests for the GitHub SCM adapter."""

from __future__ import annotations

import base64
from io import BytesIO
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError

import pytest

from codereviewer.adapters.scm import github as github_module
from codereviewer.adapters.scm.github import GitHubProvider
from codereviewer.config import GitHubConfig
from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.errors import ProviderResolutionError
from codereviewer.domain.models import CommentPayload, ReviewRequest, ReviewSnapshot


def test_github_provider_resolves_pull_request_snapshot(monkeypatch):
    provider = GitHubProvider(GitHubConfig())
    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url="https://github.com/owner/repo/pull/123",
        repo="owner/repo",
        change_number=123,
    )

    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda endpoint_path: {
            "title": "Fix login flow",
            "html_url": "https://github.com/owner/repo/pull/123",
            "user": {"login": "octocat"},
            "base": {"ref": "main", "sha": "base-sha-123"},
            "head": {"ref": "feature/login-fix", "sha": "head-sha-456"},
        },
    )
    monkeypatch.setattr(
        provider,
        "_request_text",
        lambda endpoint_path, *, accept: (
            "diff --git a/src/login.py b/src/login.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/login.py\n"
            "+++ b/src/login.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        ),
    )

    snapshot = provider.resolve_snapshot_target(request)

    assert snapshot.repo == "owner/repo"
    assert snapshot.base_ref == "main"
    assert snapshot.head_ref == "feature/login-fix"
    assert snapshot.base_sha == "base-sha-123"
    assert snapshot.head_sha == "head-sha-456"
    assert snapshot.review_title == "Fix login flow"
    assert snapshot.author_login == "octocat"
    assert snapshot.changed_files == ["src/login.py"]
    assert snapshot.diff_text.startswith("diff --git")


def test_github_provider_resolves_branch_compare_snapshot(monkeypatch):
    provider = GitHubProvider(GitHubConfig())
    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.BRANCH_COMPARE,
        repo="owner/repo",
        base_branch="main",
        head_branch="feature/x",
    )

    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda endpoint_path: {
            "html_url": "https://github.com/owner/repo/compare/main...feature/x",
            "base_commit": {"sha": "base-tip-sha"},
            "commits": [{"sha": "head-tip-sha"}],
        },
    )
    monkeypatch.setattr(
        provider,
        "_request_text",
        lambda endpoint_path, *, accept: (
            "diff --git a/src/app.py b/src/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
        ),
    )

    snapshot = provider.resolve_snapshot_target(request)

    assert snapshot.base_ref == "main"
    assert snapshot.head_ref == "feature/x"
    assert snapshot.base_sha == "base-tip-sha"
    assert snapshot.head_sha == "head-tip-sha"
    assert snapshot.web_url == "https://github.com/owner/repo/compare/main...feature/x"
    assert snapshot.changed_files == ["src/app.py"]


def test_github_provider_uses_base_sha_when_compare_has_no_commits(monkeypatch):
    provider = GitHubProvider(GitHubConfig())
    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.BRANCH_COMPARE,
        repo="owner/repo",
        base_branch="main",
        head_branch="feature/x",
    )

    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda endpoint_path: {
            "html_url": "https://github.com/owner/repo/compare/main...feature/x",
            "base_commit": {"sha": "base-tip-sha"},
            "commits": [],
        },
    )
    monkeypatch.setattr(
        provider,
        "_request_text",
        lambda endpoint_path, *, accept: (
            "diff --git a/src/app.py b/src/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
        ),
    )

    snapshot = provider.resolve_snapshot_target(request)

    assert snapshot.base_sha == "base-tip-sha"
    assert snapshot.head_sha == "base-tip-sha"


def test_github_provider_maps_http_errors(monkeypatch):
    provider = GitHubProvider(GitHubConfig())
    http_error = HTTPError(
        url="https://api.github.com/repos/owner/repo/pulls/123",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=BytesIO(b""),
    )

    def raise_http_error(*args, **kwargs):
        raise http_error

    monkeypatch.setattr(github_module, "urlopen", raise_http_error)

    with pytest.raises(ProviderResolutionError, match="HTTP 404"):
        provider._perform_request(
            endpoint_path="/repos/owner/repo/pulls/123",
            accept="application/vnd.github+json",
        )


def test_github_provider_maps_url_errors(monkeypatch):
    provider = GitHubProvider(GitHubConfig())

    def raise_url_error(*args, **kwargs):
        raise URLError("network unreachable")

    monkeypatch.setattr(github_module, "urlopen", raise_url_error)

    with pytest.raises(ProviderResolutionError, match="network unreachable"):
        provider._perform_request(
            endpoint_path="/repos/owner/repo/pulls/123",
            accept="application/vnd.github+json",
        )


def test_github_provider_maps_timeouts(monkeypatch):
    provider = GitHubProvider(GitHubConfig())

    def raise_timeout(*args, **kwargs):
        raise SocketTimeout("timed out")

    monkeypatch.setattr(github_module, "urlopen", raise_timeout)

    with pytest.raises(ProviderResolutionError, match="timed out"):
        provider._perform_request(
            endpoint_path="/repos/owner/repo/pulls/123",
            accept="application/vnd.github+json",
        )


def test_github_provider_builds_authorization_header():
    provider = GitHubProvider(
        GitHubConfig(
            token="test-token",
            api_base_url="https://api.github.com",
            timeout_seconds=10.0,
        )
    )

    headers = provider._build_headers("application/vnd.github+json")

    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["User-Agent"] == "codereviewer/0.1"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_github_provider_reads_file_content(monkeypatch):
    provider = GitHubProvider(GitHubConfig())
    encoded = base64.b64encode(b"print('hello')\n").decode("ascii")

    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda endpoint_path: {"content": encoded, "encoding": "base64"},
    )

    content = provider.get_file_content("owner/repo", "src/app.py", "head-sha-123")

    assert content == "print('hello')\n"


def test_github_provider_gets_current_head_sha(monkeypatch):
    provider = GitHubProvider(GitHubConfig())
    snapshot = ReviewSnapshot(
        review_id="review-test123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/123",
        change_number=123,
        input_hash="a" * 64,
    )
    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda endpoint_path, **kwargs: {
            "head": {"sha": "current-head-sha"},
        },
    )

    assert provider.get_current_head_sha(snapshot) == "current-head-sha"


def test_github_provider_publishes_review_comment(monkeypatch):
    provider = GitHubProvider(GitHubConfig())
    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda endpoint_path, **kwargs: {"id": 98765},
    )

    comment_id = provider.publish_review_comment(
        CommentPayload(
            provider=ProviderKind.GITHUB,
            repo="owner/repo",
            change_number=123,
            head_sha="head-sha-123",
            body="test comment",
        )
    )

    assert comment_id == "98765"


def test_github_provider_rejects_missing_compare_branches():
    provider = GitHubProvider(GitHubConfig())
    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.BRANCH_COMPARE,
        repo="owner/repo",
        base_branch="main",
    )

    with pytest.raises(ProviderResolutionError, match="base_branch and head_branch"):
        provider.resolve_snapshot_target(request)
