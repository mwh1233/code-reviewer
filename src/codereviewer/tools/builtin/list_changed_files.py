"""Built-in tool for listing changed files from the immutable snapshot."""

from __future__ import annotations

from pydantic import BaseModel

from codereviewer.domain.errors import ToolExecutionError
from codereviewer.domain.models import ReviewSnapshot, ToolResult
from codereviewer.tools.declarative import tool


class ListChangedFilesInput(BaseModel):
    """Input payload for list_changed_files."""


@tool(
    name="list_changed_files",
    description="List the changed files already present in the immutable snapshot.",
    execution_policy="snapshot_read_only",
    max_output_chars=4000,
    failure_behavior="return_error_result",
    output_schema={
        "type": "object",
        "properties": {
            "files": {"type": "array", "items": {"type": "string"}},
        },
    },
    context_params=("snapshot",),
)
def list_changed_files(snapshot: ReviewSnapshot | None = None) -> ToolResult:
    """Return the changed-file list already present in the snapshot."""

    if snapshot is None:
        raise ToolExecutionError("list_changed_files requires a snapshot execution context.")

    return ToolResult(
        tool_name="list_changed_files",
        payload={"files": list(snapshot.changed_files)},
    )
