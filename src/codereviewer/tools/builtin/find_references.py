"""Built-in tool for bounded string reference search across changed files."""

from __future__ import annotations

from pydantic import BaseModel, Field

from codereviewer.domain.errors import ToolExecutionError
from codereviewer.domain.interfaces.scm import SCMProvider
from codereviewer.domain.models import ReviewSnapshot, ToolResult
from codereviewer.tools.declarative import tool


class FindReferencesInput(BaseModel):
    """Input payload for find_references."""

    query: str
    file_paths: list[str] | None = None
    max_matches: int = Field(default=20, ge=1, le=100)


@tool(
    name="find_references",
    description="Find literal string matches in changed files only.",
    execution_policy="provider_read_only_changed_files_only",
    max_output_chars=8000,
    failure_behavior="return_error_result",
    output_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "searched_files": {"type": "array", "items": {"type": "string"}},
            "matches": {"type": "array"},
        },
    },
    context_params=("snapshot", "provider"),
)
def find_references(
    query: str,
    file_paths: list[str] | None = None,
    max_matches: int = 20,
    snapshot: ReviewSnapshot | None = None,
    provider: SCMProvider | None = None,
) -> ToolResult:
    """Search one literal string within changed files only."""

    if snapshot is None:
        raise ToolExecutionError("find_references requires a snapshot execution context.")
    if provider is None:
        raise ToolExecutionError(
            "find_references requires a provider-backed execution context."
        )
    if snapshot.head_sha is None:
        raise ToolExecutionError(
            "find_references requires snapshot.head_sha to be populated."
        )

    request = FindReferencesInput(
        query=query,
        file_paths=file_paths,
        max_matches=max_matches,
    )
    requested_paths = request.file_paths or list(snapshot.changed_files)
    allowed_paths = set(snapshot.changed_files)
    search_paths = [path for path in requested_paths if path in allowed_paths]
    matches: list[dict[str, object]] = []
    truncated = False

    for path in search_paths:
        content = provider.get_file_content(snapshot.repo, path, snapshot.head_sha)
        for line_number, line in enumerate(content.splitlines(), start=1):
            if request.query not in line:
                continue
            matches.append(
                {
                    "file": path,
                    "line": line_number,
                    "excerpt": line[:200],
                }
            )
            if len(matches) >= request.max_matches:
                truncated = True
                break
        if truncated:
            break

    return ToolResult(
        tool_name="find_references",
        payload={
            "query": request.query,
            "searched_files": search_paths,
            "matches": matches,
        },
        truncated=truncated,
    )
