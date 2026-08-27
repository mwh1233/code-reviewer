"""Built-in tool for reading diff content from the immutable snapshot."""

from __future__ import annotations

from pydantic import BaseModel

from codereviewer.domain.errors import ToolExecutionError
from codereviewer.domain.models import ReviewSnapshot, ToolResult
from codereviewer.services.diff_preprocessor import get_file_diff
from codereviewer.tools.declarative import tool


class ReadDiffInput(BaseModel):
    """Input payload for read_diff."""

    file_path: str | None = None


@tool(
    name="read_diff",
    description="Read the immutable review diff or one file section from it.",
    execution_policy="snapshot_read_only",
    max_output_chars=12000,
    failure_behavior="return_error_result",
    output_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": ["string", "null"]},
            "diff_text": {"type": "string"},
            "is_binary": {"type": "boolean"},
        },
    },
    context_params=("snapshot",),
)
def read_diff(
    file_path: str | None = None,
    snapshot: ReviewSnapshot | None = None,
) -> ToolResult:
    """Read the full diff or one changed-file diff from the snapshot."""

    if snapshot is None:
        raise ToolExecutionError("read_diff requires a snapshot execution context.")

    diff_text = snapshot.diff_text
    is_binary = False

    if file_path is not None:
        file_diff = get_file_diff(snapshot, file_path)
        if file_diff is None:
            raise ToolExecutionError(
                f"changed file '{file_path}' is not present in the snapshot diff."
            )
        diff_text = file_diff.diff_text
        is_binary = file_diff.is_binary

    truncated_text, truncated = _truncate_text(diff_text, 12000)
    return ToolResult(
        tool_name="read_diff",
        payload={
            "file_path": file_path,
            "diff_text": truncated_text,
            "is_binary": is_binary,
        },
        truncated=truncated,
    )


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[: max_chars - 15] + "\n...[truncated]", True
