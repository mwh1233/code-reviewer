"""Unit tests for the GitLab SCM adapter."""

from __future__ import annotations

from io import BytesIO
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError

import pytest

from codereviewer.adapters.scm import gitlab as gitlab_module
from codereviewer.adapters.scm.gitlab import GitLabProvider
from codereviewer.config import GitLabConfig
from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.errors import ProviderResolutionError
from codereviewer.domain.models import CommentPayload, ReviewRequest, ReviewSnapshot


def test_gitlab_provider_resolves_merge_request_snapshot(monkeypatch):
    provider = GitLabProvider(GitLabConfig())
    request = ReviewRequest(
        provider=ProviderKind.GITLAB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url="https://gitlab.com/group/project/-/merge_requests/1",
        repo="group/project",
        change_number=1,
    )

    def fake_request_json(endpoint_path: str) -> dict[str, object]:
        if endpoint_path.endswith("/merge_requests/1"):
            return {
                "title": "Add feature",
                "web_url": "https://gitlab.com/group/project/-/merge_requests/1",
                "source_branch": "feature/x",
                "target_branch": "main",
                "diff_refs": {
                    "base_sha": "base-sha-123",
                    "head_sha": "head-sha-456",
                },
                "author": {"username": "marvin"},
            }
        if endpoint_path.endswith("/merge_requests/1/changes"):
            return {
                "changes": [
                    {
                        "old_path": "src/app.py",
                        "new_path": "src/app.py",
                        "diff": "@@ -1 +1 @@\n-old\n+new\n",
                        "new_file": False,
                        "deleted_file": False,
                        "renamed_file": False,
                    }
                ]
            }
        raise AssertionError(f"unexpected endpoint {endpoint_path}")

    monkeypatch.setattr(provider, "_request_json", fake_request_json)

    snapshot = provider.resolve_snapshot_target(request)

    assert snapshot.repo == "group/project"
    assert snapshot.base_ref == "main"
    assert snapshot.head_ref == "feature/x"
    assert snapshot.base_sha == "base-sha-123"
    assert snapshot.head_sha == "head-sha-456"
    assert snapshot.review_title == "Add feature"
    assert snapshot.author_login == "marvin"
    assert snapshot.changed_files == ["src/app.py"]
    assert snapshot.diff_text.startswith("diff --git")


def test_gitlab_provider_resolves_branch_compare_snapshot(monkeypatch):
    provider = GitLabProvider(GitLabConfig())
    request = ReviewRequest(
        provider=ProviderKind.GITLAB,
        source_kind=ReviewSourceKind.BRANCH_COMPARE,
        repo="group/project",
        base_branch="main",
        head_branch="dev",
    )

    def fake_request_json(endpoint_path: str) -> dict[str, object]:
        if endpoint_path.endswith("/repository/branches/main"):
            return {"name": "main", "commit": {"id": "base-tip-sha"}}
        if endpoint_path.endswith("/repository/branches/dev"):
            return {"name": "dev", "commit": {"id": "head-tip-sha"}}
        if endpoint_path.startswith(
            "/projects/group%2Fproject/repository/compare?"
        ) and "straight=true" in endpoint_path:
            return {
                "web_url": "https://gitlab.com/group/project/-/compare/main...dev",
                "diffs": [
                    {
                        "old_path": "README.md",
                        "new_path": "README.md",
                        "diff": "@@ -1 +1 @@\n-old\n+new\n",
                        "new_file": False,
                        "deleted_file": False,
                        "renamed_file": False,
                    }
                ],
            }
        raise AssertionError(f"unexpected endpoint {endpoint_path}")

    monkeypatch.setattr(provider, "_request_json", fake_request_json)

    snapshot = provider.resolve_snapshot_target(request)

    assert snapshot.base_ref == "main"
    assert snapshot.head_ref == "dev"
    assert snapshot.base_sha == "base-tip-sha"
    assert snapshot.head_sha == "head-tip-sha"
    assert snapshot.web_url == "https://gitlab.com/group/project/-/compare/main...dev"
    assert snapshot.changed_files == ["README.md"]


def test_gitlab_provider_builds_authorization_header():
    provider = GitLabProvider(
        GitLabConfig(
            token="gitlab-token",
            api_base_url="https://gitlab.example.com/api/v4",
            timeout_seconds=10.0,
        )
    )

    headers = provider._build_headers()

    assert headers["Accept"] == "application/json"
    assert headers["PRIVATE-TOKEN"] == "gitlab-token"
    assert headers["User-Agent"] == "codereviewer/0.1"


def test_gitlab_provider_reads_file_content(monkeypatch):
    provider = GitLabProvider(GitLabConfig())

    monkeypatch.setattr(
        provider,
        "_perform_request",
        lambda endpoint_path: b"console.log('hello');\n",
    )

    content = provider.get_file_content("group/project", "src/app.js", "head-sha-456")

    assert content == "console.log('hello');\n"


def test_gitlab_provider_gets_current_head_sha(monkeypatch):
    provider = GitLabProvider(GitLabConfig())
    snapshot = ReviewSnapshot(
        review_id="review-test123",
        provider=ProviderKind.GITLAB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="group/project",
        review_url="https://gitlab.com/group/project/-/merge_requests/1",
        change_number=1,
        input_hash="a" * 64,
    )
    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda endpoint_path, **kwargs: {
            "diff_refs": {"head_sha": "current-head-sha"},
        },
    )

    assert provider.get_current_head_sha(snapshot) == "current-head-sha"


def test_gitlab_provider_publishes_review_comment(monkeypatch):
    provider = GitLabProvider(GitLabConfig())
    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda endpoint_path, **kwargs: {"id": 13579},
    )

    comment_id = provider.publish_review_comment(
        CommentPayload(
            provider=ProviderKind.GITLAB,
            repo="group/project",
            change_number=1,
            head_sha="head-sha-123",
            body="test comment",
        )
    )

    assert comment_id == "13579"


def test_gitlab_provider_maps_http_errors(monkeypatch):
    provider = GitLabProvider(GitLabConfig())
    http_error = HTTPError(
        url="https://gitlab.com/api/v4/projects/group%2Fproject/merge_requests/1",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=BytesIO(b""),
    )

    def raise_http_error(*args, **kwargs):
        raise http_error

    monkeypatch.setattr(gitlab_module, "urlopen", raise_http_error)

    with pytest.raises(ProviderResolutionError, match="HTTP 404"):
        provider._perform_request("/projects/group%2Fproject/merge_requests/1")


def test_gitlab_provider_includes_http_error_body_details(monkeypatch):
    provider = GitLabProvider(GitLabConfig())
    http_error = HTTPError(
        url="https://gitlab.com/api/v4/projects/group%2Fproject/merge_requests/1/notes",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=BytesIO(
            (
                b'{"error":"insufficient_granular_scope","error_description":"'
                b'Access denied: This operation requires a fine-grained personal '
                b'access token with the following project permissions: '
                b'[Work Item: Create]."}'
            )
        ),
    )

    def raise_http_error(*args, **kwargs):
        raise http_error

    monkeypatch.setattr(gitlab_module, "urlopen", raise_http_error)

    with pytest.raises(
        ProviderResolutionError,
        match="insufficient_granular_scope.*Work Item: Create",
    ):
        provider._perform_request("/projects/group%2Fproject/merge_requests/1/notes")


def test_gitlab_provider_maps_url_errors(monkeypatch):
    provider = GitLabProvider(GitLabConfig())

    def raise_url_error(*args, **kwargs):
        raise URLError("network unreachable")

    monkeypatch.setattr(gitlab_module, "urlopen", raise_url_error)

    with pytest.raises(ProviderResolutionError, match="network unreachable"):
        provider._perform_request("/projects/group%2Fproject/merge_requests/1")


def test_gitlab_provider_maps_timeouts(monkeypatch):
    provider = GitLabProvider(GitLabConfig())

    def raise_timeout(*args, **kwargs):
        raise SocketTimeout("timed out")

    monkeypatch.setattr(gitlab_module, "urlopen", raise_timeout)

    with pytest.raises(ProviderResolutionError, match="timed out"):
        provider._perform_request("/projects/group%2Fproject/merge_requests/1")


def test_gitlab_provider_rejects_missing_merge_request_number():
    provider = GitLabProvider(GitLabConfig())
    request = ReviewRequest(
        provider=ProviderKind.GITLAB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="group/project",
    )

    with pytest.raises(ProviderResolutionError, match="change_number"):
        provider.resolve_snapshot_target(request)


def test_gitlab_provider_rejects_missing_compare_branches():
    provider = GitLabProvider(GitLabConfig())
    request = ReviewRequest(
        provider=ProviderKind.GITLAB,
        source_kind=ReviewSourceKind.BRANCH_COMPARE,
        repo="group/project",
        base_branch="main",
    )

    with pytest.raises(ProviderResolutionError, match="base_branch and head_branch"):
        provider.resolve_snapshot_target(request)
