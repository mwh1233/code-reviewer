"""Built-in read-only review tools."""

from codereviewer.tools.auto_discover import discover_and_register
from codereviewer.tools.builtin.find_references import (
    FindReferencesInput,
    find_references,
)
from codereviewer.tools.builtin.list_changed_files import (
    ListChangedFilesInput,
    list_changed_files,
)
from codereviewer.tools.builtin.read_diff import ReadDiffInput, read_diff
from codereviewer.tools.builtin.read_file import ReadFileInput, read_file
from codereviewer.tools.registry import ToolRegistry


def build_builtin_tool_registry() -> ToolRegistry:
    """Build a registry containing all built-in read-only tools."""

    registry = ToolRegistry()
    discover_and_register(registry, package=__package__, directory=__path__[0])
    return registry


__all__ = [
    "FindReferencesInput",
    "ListChangedFilesInput",
    "ReadDiffInput",
    "ReadFileInput",
    "find_references",
    "list_changed_files",
    "read_diff",
    "read_file",
    "build_builtin_tool_registry",
]
