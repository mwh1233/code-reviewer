"""Built-in tool for reading one file through the SCM provider."""

from __future__ import annotations

from pydantic import BaseModel

from codereviewer.domain.errors import ToolExecutionError
from codereviewer.domain.interfaces.scm import SCMProvider
from codereviewer.domain.models import ReviewSnapshot, ToolResult
from codereviewer.tools.declarative import tool


class ReadFileInput(BaseModel):
    """Input payload for read_file."""

    file_path: str


@tool(
    name="read_file",
    description="Read one changed file at the immutable head sha.",
    execution_policy="provider_read_only",
    max_output_chars=12000,
    failure_behavior="return_error_result",
    output_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
    },
    context_params=("snapshot", "provider"),
)
def read_file(
    file_path: str,
    snapshot: ReviewSnapshot,
    provider: SCMProvider | None = None,
) -> ToolResult:
    """Read one text file from the provider at the snapshot head sha."""

    if provider is None:
        raise ToolExecutionError("read_file requires a provider-backed execution context.")
    if snapshot.head_sha is None:
        raise ToolExecutionError("read_file requires snapshot.head_sha to be populated.")

    content = provider.get_file_content(snapshot.repo, file_path, snapshot.head_sha)
    truncated_content, truncated = _truncate_text(content, 12000)
    return ToolResult(
        tool_name="read_file",
        payload={
            "file_path": file_path,
            "content": truncated_content,
        },
        truncated=truncated,
    )


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[: max_chars - 15] + "\n...[truncated]", True
