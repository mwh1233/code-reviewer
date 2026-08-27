"""GitLab SCM provider implementation for M3."""

from __future__ import annotations

import json
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from codereviewer.config import GitLabConfig
from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.errors import ProviderResolutionError
from codereviewer.domain.models import CommentPayload, ReviewRequest, ReviewSnapshot
from codereviewer.services.snapshot_builder import build_input_hash, build_review_id, build_snapshot


class GitLabProvider:
    """Resolve GitLab review targets into immutable snapshots."""

    def __init__(self, config: GitLabConfig) -> None:
        self._config = config

    def resolve_snapshot_target(self, request: ReviewRequest) -> ReviewSnapshot:
        """Resolve a GitLab review request into a populated snapshot."""

        if request.provider != ProviderKind.GITLAB:
            raise ProviderResolutionError("GitLabProvider can only resolve gitlab requests.")
        if not request.repo:
            raise ProviderResolutionError("GitLab review requests must include repo.")

        if request.source_kind == ReviewSourceKind.REVIEW_URL:
            return self._resolve_merge_request_snapshot(request)
        if request.source_kind == ReviewSourceKind.BRANCH_COMPARE:
            return self._resolve_branch_compare_snapshot(request)

        raise ProviderResolutionError(
            f"GitLab does not support source_kind={request.source_kind.value} in M3."
        )

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        """Read one text file from GitLab at one immutable ref."""

        project_id = self._encode_project_id(repo)
        encoded_path = quote(path, safe="")
        endpoint_path = (
            f"/projects/{project_id}/repository/files/{encoded_path}/raw"
            f"?{urlencode({'ref': ref})}"
        )
        payload = self._perform_request(endpoint_path)
        return payload.decode("utf-8", errors="replace")

    def get_current_head_sha(self, snapshot: ReviewSnapshot) -> str:
        """Read the current head SHA for one GitLab merge request."""

        if snapshot.source_kind != ReviewSourceKind.REVIEW_URL:
            raise ProviderResolutionError(
                "GitLab head SHA refresh only supports review_url snapshots."
            )
        if snapshot.change_number is None:
            raise ProviderResolutionError("GitLab review snapshot is missing change_number.")

        project_id = self._encode_project_id(snapshot.repo)
        merge_request = self._request_json(
            f"/projects/{project_id}/merge_requests/{snapshot.change_number}"
        )
        diff_refs = self._expect_mapping(merge_request.get("diff_refs"), "diff_refs")
        return self._expect_string(diff_refs.get("head_sha"), "diff_refs.head_sha")

    def publish_review_comment(self, payload: CommentPayload) -> str:
        """Publish one top-level note for a GitLab merge request."""

        project_id = self._encode_project_id(payload.repo)
        response_json = self._request_json(
            f"/projects/{project_id}/merge_requests/{payload.change_number}/notes",
            method="POST",
            data=json.dumps({"body": payload.body}).encode("utf-8"),
            content_type="application/json",
        )
        note_id = response_json.get("id")
        if isinstance(note_id, int):
            return str(note_id)
        raise ProviderResolutionError("GitLab comment publish response is missing integer field id.")

    def _resolve_merge_request_snapshot(self, request: ReviewRequest) -> ReviewSnapshot:
        if request.change_number is None:
            raise ProviderResolutionError("GitLab merge request input must include change_number.")

        project_id = self._encode_project_id(request.repo)
        merge_request = self._request_json(
            f"/projects/{project_id}/merge_requests/{request.change_number}"
        )
        merge_request_changes = self._request_json(
            f"/projects/{project_id}/merge_requests/{request.change_number}/changes"
        )

        input_hash = build_input_hash(request)
        snapshot = build_snapshot(
            request,
            review_id_prefix="review",
            review_id=build_review_id(request, input_hash=input_hash),
            input_hash=input_hash,
        )
        diff_refs = self._expect_mapping(merge_request.get("diff_refs"), "diff_refs")
        changes = self._expect_list(merge_request_changes.get("changes"), "changes")

        snapshot.base_ref = self._expect_string(
            merge_request.get("target_branch"), "target_branch"
        )
        snapshot.head_ref = self._expect_string(
            merge_request.get("source_branch"), "source_branch"
        )
        snapshot.base_sha = self._expect_string(diff_refs.get("base_sha"), "diff_refs.base_sha")
        snapshot.head_sha = self._expect_string(diff_refs.get("head_sha"), "diff_refs.head_sha")
        snapshot.changed_files = self._extract_changed_files(changes)
        snapshot.diff_text = self._build_diff_text(changes)
        snapshot.review_title = self._optional_string(merge_request.get("title"))
        snapshot.author_login = self._extract_author_login(merge_request.get("author"))
        snapshot.web_url = self._optional_string(merge_request.get("web_url"))
        return snapshot

    def _resolve_branch_compare_snapshot(self, request: ReviewRequest) -> ReviewSnapshot:
        if not request.base_branch or not request.head_branch:
            raise ProviderResolutionError(
                "GitLab branch compare input must include base_branch and head_branch."
            )

        project_id = self._encode_project_id(request.repo or "")
        base_branch = self._request_json(
            f"/projects/{project_id}/repository/branches/{quote(request.base_branch, safe='')}"
        )
        head_branch = self._request_json(
            f"/projects/{project_id}/repository/branches/{quote(request.head_branch, safe='')}"
        )
        compare_payload = self._request_json(
            f"/projects/{project_id}/repository/compare?"
            f"{urlencode({'from': request.base_branch, 'to': request.head_branch, 'straight': 'true'})}"
        )

        input_hash = build_input_hash(request)
        snapshot = build_snapshot(
            request,
            review_id_prefix="review",
            review_id=build_review_id(request, input_hash=input_hash),
            input_hash=input_hash,
        )
        diffs = self._expect_list(compare_payload.get("diffs"), "diffs")

        snapshot.base_ref = request.base_branch
        snapshot.head_ref = request.head_branch
        snapshot.base_sha = self._expect_commit_id(base_branch, "base_branch")
        snapshot.head_sha = self._expect_commit_id(head_branch, "head_branch")
        snapshot.changed_files = self._extract_changed_files(diffs)
        snapshot.diff_text = self._build_diff_text(diffs)
        snapshot.web_url = self._optional_string(compare_payload.get("web_url"))
        return snapshot

    def _request_json(
        self,
        endpoint_path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, object]:
        payload = self._perform_request(
            endpoint_path,
            method=method,
            data=data,
            content_type=content_type,
        )
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProviderResolutionError(
                f"GitLab returned invalid JSON for {endpoint_path}."
            ) from exc
        if not isinstance(decoded, dict):
            raise ProviderResolutionError(
                f"GitLab returned unexpected JSON payload for {endpoint_path}."
            )
        return decoded

    def _perform_request(
        self,
        endpoint_path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> bytes:
        request = Request(
            url=f"{self._config.api_base_url.rstrip('/')}{endpoint_path}",
            headers=self._build_headers(content_type=content_type),
            method=method,
            data=data,
        )
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            raise ProviderResolutionError(
                self._format_http_error(exc, endpoint_path)
            ) from exc
        except (SocketTimeout, TimeoutError) as exc:
            raise ProviderResolutionError(
                f"GitLab API request timed out for {endpoint_path}."
            ) from exc
        except URLError as exc:
            reason = str(exc.reason)
            raise ProviderResolutionError(
                f"GitLab API request failed for {endpoint_path}: {reason}."
            ) from exc

    def _build_headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "codereviewer/0.1",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        if self._config.token:
            headers["PRIVATE-TOKEN"] = self._config.token
        return headers

    @staticmethod
    def _encode_project_id(repo: str) -> str:
        if not repo:
            raise ProviderResolutionError("GitLab project id cannot be empty.")
        return quote(repo, safe="")

    @staticmethod
    def _format_http_error(exc: HTTPError, endpoint_path: str) -> str:
        message = f"GitLab API request failed with HTTP {exc.code} for {endpoint_path}."
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""

        if not body:
            return message

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return f"{message} Response body: {body}"

        if isinstance(payload, dict):
            error = payload.get("error")
            error_description = payload.get("error_description")
            details: list[str] = []
            if isinstance(error, str) and error:
                details.append(f"error={error}")
            if isinstance(error_description, str) and error_description:
                details.append(f"error_description={error_description}")
            if details:
                return f"{message} {'; '.join(details)}"

        return f"{message} Response body: {body}"

    @classmethod
    def _expect_commit_id(cls, branch_payload: dict[str, object], field_name: str) -> str:
        commit = cls._expect_mapping(branch_payload.get("commit"), f"{field_name}.commit")
        return cls._expect_string(commit.get("id"), f"{field_name}.commit.id")

    @classmethod
    def _extract_author_login(cls, value: object) -> str | None:
        author = cls._optional_mapping(value)
        if author is None:
            return None
        return cls._optional_string(author.get("username"))

    @classmethod
    def _extract_changed_files(cls, diffs: list[object]) -> list[str]:
        changed_files: list[str] = []
        seen: set[str] = set()

        for diff_entry in diffs:
            diff_mapping = cls._expect_mapping(diff_entry, "diff")
            candidate = cls._diff_display_path(diff_mapping)
            if candidate not in seen:
                seen.add(candidate)
                changed_files.append(candidate)

        return changed_files

    @classmethod
    def _build_diff_text(cls, diffs: list[object]) -> str:
        parts: list[str] = []

        for diff_entry in diffs:
            diff_mapping = cls._expect_mapping(diff_entry, "diff")
            old_path = cls._expect_path(diff_mapping.get("old_path"), "old_path")
            new_path = cls._expect_path(diff_mapping.get("new_path"), "new_path")
            diff_body = cls._optional_string(diff_mapping.get("diff")) or ""

            parts.append(f"diff --git a/{old_path} b/{new_path}")
            if cls._truthy(diff_mapping.get("renamed_file")) and old_path != new_path:
                parts.append(f"rename from {old_path}")
                parts.append(f"rename to {new_path}")

            if cls._truthy(diff_mapping.get("new_file")):
                parts.append("--- /dev/null")
                parts.append(f"+++ b/{new_path}")
            elif cls._truthy(diff_mapping.get("deleted_file")):
                parts.append(f"--- a/{old_path}")
                parts.append("+++ /dev/null")
            else:
                parts.append(f"--- a/{old_path}")
                parts.append(f"+++ b/{new_path}")

            if diff_body:
                parts.append(diff_body.rstrip("\n"))

        return "\n".join(parts) + ("\n" if parts else "")

    @classmethod
    def _diff_display_path(cls, diff_mapping: dict[str, object]) -> str:
        deleted_file = cls._truthy(diff_mapping.get("deleted_file"))
        if deleted_file:
            return cls._expect_path(diff_mapping.get("old_path"), "old_path")
        return cls._expect_path(diff_mapping.get("new_path"), "new_path")

    @staticmethod
    def _truthy(value: object) -> bool:
        return value is True

    @staticmethod
    def _expect_mapping(value: object, field_name: str) -> dict[str, object]:
        if isinstance(value, dict):
            return value
        raise ProviderResolutionError(f"GitLab response is missing object field {field_name}.")

    @staticmethod
    def _optional_mapping(value: object) -> dict[str, object] | None:
        if isinstance(value, dict):
            return value
        return None

    @staticmethod
    def _expect_list(value: object, field_name: str) -> list[object]:
        if isinstance(value, list):
            return value
        raise ProviderResolutionError(f"GitLab response is missing list field {field_name}.")

    @staticmethod
    def _expect_string(value: object, field_name: str) -> str:
        if isinstance(value, str) and value:
            return value
        raise ProviderResolutionError(f"GitLab response is missing string field {field_name}.")

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    @classmethod
    def _expect_path(cls, value: object, field_name: str) -> str:
        return cls._expect_string(value, field_name)
