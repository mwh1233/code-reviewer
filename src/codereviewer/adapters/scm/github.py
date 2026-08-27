"""GitHub SCM provider implementation for M2."""

from __future__ import annotations

import base64
import json
import re
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from codereviewer.config import GitHubConfig
from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.errors import ProviderResolutionError
from codereviewer.domain.models import CommentPayload, ReviewRequest, ReviewSnapshot
from codereviewer.services.snapshot_builder import build_input_hash, build_review_id, build_snapshot


_DIFF_HEADER_PATTERN = re.compile(r"^diff --git a/(.*?) b/(.*?)$")


class GitHubProvider:
    """Resolve GitHub review targets into immutable snapshots."""

    def __init__(self, config: GitHubConfig) -> None:
        self._config = config

    def resolve_snapshot_target(self, request: ReviewRequest) -> ReviewSnapshot:
        """Resolve a GitHub review request into a populated snapshot."""

        if request.provider != ProviderKind.GITHUB:
            raise ProviderResolutionError("GitHubProvider can only resolve github requests.")
        if not request.repo:
            raise ProviderResolutionError("GitHub review requests must include repo.")

        endpoint_path = self._resolve_endpoint_path(request)
        response_json = self._request_json(endpoint_path)
        diff_text = self._request_text(
            endpoint_path,
            accept="application/vnd.github.diff",
        )
        return self._build_snapshot_from_response(request, response_json, diff_text)

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        """Read one text file from GitHub at one immutable ref."""

        endpoint_path = (
            f"/repos/{self._quote_repo_path(repo)}/contents/{quote(path, safe='/')}"
            f"?ref={quote(ref, safe='')}"
        )
        response_json = self._request_json(endpoint_path)
        content = self._expect_string(response_json.get("content"), "content")
        encoding = self._expect_string(response_json.get("encoding"), "encoding")
        if encoding != "base64":
            raise ProviderResolutionError(
                f"GitHub file content for {path} returned unsupported encoding {encoding}."
            )
        try:
            decoded = base64.b64decode(content, validate=False)
        except ValueError as exc:
            raise ProviderResolutionError(
                f"GitHub file content for {path} returned invalid base64 content."
            ) from exc
        return decoded.decode("utf-8", errors="replace")

    def get_current_head_sha(self, snapshot: ReviewSnapshot) -> str:
        """Read the current head SHA for one GitHub pull request."""

        if snapshot.source_kind != ReviewSourceKind.REVIEW_URL:
            raise ProviderResolutionError(
                "GitHub head SHA refresh only supports review_url snapshots."
            )
        if snapshot.change_number is None:
            raise ProviderResolutionError("GitHub review snapshot is missing change_number.")
        response_json = self._request_json(
            f"/repos/{self._quote_repo_path(snapshot.repo)}/pulls/{snapshot.change_number}"
        )
        head = self._expect_mapping(response_json.get("head"), "head")
        return self._expect_string(head.get("sha"), "head.sha")

    def publish_review_comment(self, payload: CommentPayload) -> str:
        """Publish one top-level issue comment for a GitHub pull request."""

        response_json = self._request_json(
            f"/repos/{self._quote_repo_path(payload.repo)}/issues/{payload.change_number}/comments",
            method="POST",
            data=json.dumps({"body": payload.body}).encode("utf-8"),
            content_type="application/json",
        )
        comment_id = response_json.get("id")
        if isinstance(comment_id, int):
            return str(comment_id)
        raise ProviderResolutionError("GitHub comment publish response is missing integer field id.")

    def _resolve_endpoint_path(self, request: ReviewRequest) -> str:
        if request.source_kind == ReviewSourceKind.REVIEW_URL:
            if request.change_number is None:
                raise ProviderResolutionError(
                    "GitHub pull request input must include change_number."
                )
            if not request.repo:
                raise ProviderResolutionError("GitHub pull request input must include repo.")
            return (
                f"/repos/{self._quote_repo_path(request.repo)}"
                f"/pulls/{request.change_number}"
            )

        if request.source_kind == ReviewSourceKind.BRANCH_COMPARE:
            if not request.base_branch or not request.head_branch:
                raise ProviderResolutionError(
                    "GitHub branch compare input must include base_branch and head_branch."
                )
            if not request.repo:
                raise ProviderResolutionError("GitHub branch compare input must include repo.")
            comparison = (
                f"{quote(request.base_branch, safe='')}...{quote(request.head_branch, safe='')}"
            )
            return f"/repos/{self._quote_repo_path(request.repo)}/compare/{comparison}"

        raise ProviderResolutionError(
            f"GitHub does not support source_kind={request.source_kind.value} in M2."
        )

    def _build_snapshot_from_response(
        self,
        request: ReviewRequest,
        response_json: dict[str, object],
        diff_text: str,
    ) -> ReviewSnapshot:
        input_hash = build_input_hash(request)
        snapshot = build_snapshot(
            request,
            review_id_prefix="review",
            review_id=build_review_id(request, input_hash=input_hash),
            input_hash=input_hash,
        )
        snapshot.diff_text = diff_text
        snapshot.changed_files = self._extract_changed_files(diff_text)

        if request.source_kind == ReviewSourceKind.REVIEW_URL:
            base = self._expect_mapping(response_json.get("base"), "base")
            head = self._expect_mapping(response_json.get("head"), "head")
            user = self._optional_mapping(response_json.get("user"))

            snapshot.base_ref = self._expect_string(base.get("ref"), "base.ref")
            snapshot.head_ref = self._expect_string(head.get("ref"), "head.ref")
            snapshot.base_sha = self._expect_string(base.get("sha"), "base.sha")
            snapshot.head_sha = self._expect_string(head.get("sha"), "head.sha")
            snapshot.review_title = self._optional_string(response_json.get("title"))
            snapshot.author_login = self._optional_string(user.get("login")) if user else None
            snapshot.web_url = self._optional_string(response_json.get("html_url"))
            return snapshot

        if request.source_kind == ReviewSourceKind.BRANCH_COMPARE:
            base_commit = self._expect_mapping(response_json.get("base_commit"), "base_commit")
            commits = response_json.get("commits")

            snapshot.base_ref = request.base_branch
            snapshot.head_ref = request.head_branch
            snapshot.base_sha = self._expect_string(base_commit.get("sha"), "base_commit.sha")
            snapshot.head_sha = self._resolve_compare_head_sha(
                commits=commits,
                fallback_sha=snapshot.base_sha,
            )
            snapshot.web_url = self._optional_string(response_json.get("html_url"))
            return snapshot

        raise ProviderResolutionError(
            f"GitHub does not support source_kind={request.source_kind.value} in M2."
        )

    def _request_json(
        self,
        endpoint_path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, object]:
        payload = self._perform_request(
            endpoint_path=endpoint_path,
            accept="application/vnd.github+json",
            method=method,
            data=data,
            content_type=content_type,
        )
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProviderResolutionError(
                f"GitHub returned invalid JSON for {endpoint_path}."
            ) from exc
        if not isinstance(decoded, dict):
            raise ProviderResolutionError(
                f"GitHub returned unexpected JSON payload for {endpoint_path}."
            )
        return decoded

    def _request_text(self, endpoint_path: str, *, accept: str) -> str:
        payload = self._perform_request(endpoint_path=endpoint_path, accept=accept)
        return payload.decode("utf-8", errors="replace")

    def _perform_request(
        self,
        *,
        endpoint_path: str,
        accept: str,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> bytes:
        request = Request(
            url=f"{self._config.api_base_url.rstrip('/')}{endpoint_path}",
            headers=self._build_headers(accept, content_type=content_type),
            method=method,
            data=data,
        )
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            raise ProviderResolutionError(
                f"GitHub API request failed with HTTP {exc.code} for {endpoint_path}."
            ) from exc
        except (SocketTimeout, TimeoutError) as exc:
            raise ProviderResolutionError(
                f"GitHub API request timed out for {endpoint_path}."
            ) from exc
        except URLError as exc:
            reason = str(exc.reason)
            raise ProviderResolutionError(
                f"GitHub API request failed for {endpoint_path}: {reason}."
            ) from exc

    def _build_headers(self, accept: str, *, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": "codereviewer/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        return headers

    @staticmethod
    def _quote_repo_path(repo: str) -> str:
        return "/".join(quote(part, safe="") for part in repo.split("/"))

    @staticmethod
    def _extract_changed_files(diff_text: str) -> list[str]:
        changed_files: list[str] = []
        seen: set[str] = set()

        for line in diff_text.splitlines():
            match = _DIFF_HEADER_PATTERN.match(line)
            if match is None:
                continue

            candidate = match.group(2)
            if candidate == "/dev/null":
                candidate = match.group(1)
            if candidate not in seen:
                seen.add(candidate)
                changed_files.append(candidate)

        return changed_files

    @staticmethod
    def _expect_mapping(value: object, field_name: str) -> dict[str, object]:
        if isinstance(value, dict):
            return value
        raise ProviderResolutionError(f"GitHub response is missing object field {field_name}.")

    @staticmethod
    def _optional_mapping(value: object) -> dict[str, object] | None:
        if isinstance(value, dict):
            return value
        return None

    @staticmethod
    def _expect_string(value: object, field_name: str) -> str:
        if isinstance(value, str) and value:
            return value
        raise ProviderResolutionError(f"GitHub response is missing string field {field_name}.")

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    @classmethod
    def _resolve_compare_head_sha(cls, *, commits: object, fallback_sha: str) -> str:
        if isinstance(commits, list) and commits:
            last_commit = commits[-1]
            if isinstance(last_commit, dict):
                return cls._expect_string(last_commit.get("sha"), "commits[-1].sha")
            raise ProviderResolutionError(
                "GitHub response is missing object field commits[-1]."
            )

        return fallback_sha
