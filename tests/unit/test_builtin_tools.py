"""Unit tests for built-in M5 tools and engine behavior."""

from __future__ import annotations

from pydantic import BaseModel

from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.errors import ProviderResolutionError
from codereviewer.domain.models import ReviewSnapshot, ReviewTrace
from codereviewer.services.tool_engine import ToolEngine
from codereviewer.services.trace_manager import TraceManager
from codereviewer.adapters.storage.file_store import FileTraceStore
from codereviewer.config import build_app_config
from codereviewer.tools.builtin import (
    FindReferencesInput,
    ListChangedFilesInput,
    ReadDiffInput,
    ReadFileInput,
    build_builtin_tool_registry,
)


class _StubProvider:
    def __init__(self, files: dict[str, str], *, fail_path: str | None = None) -> None:
        self._files = files
        self._fail_path = fail_path

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        if path == self._fail_path:
            raise ProviderResolutionError(f"failed to read {path}")
        return self._files[path]


def _build_snapshot(diff_text: str) -> ReviewSnapshot:
    return ReviewSnapshot(
        review_id="review-tools123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/1",
        change_number=1,
        input_hash="a" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/example.py"],
        diff_text=diff_text,
    )


def test_tool_engine_traces_tool_calls_and_truncates_diff(tmp_path):
    snapshot = _build_snapshot(
        "diff --git a/src/example.py b/src/example.py\n"
        + "+x\n" * 7000
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create(snapshot.review_id)
    engine = ToolEngine(
        build_builtin_tool_registry(),
        trace_manager=trace_manager,
        trace=trace,
        review_id=snapshot.review_id,
    )

    result = engine.run_tool(
        "read_diff",
        ReadDiffInput(),
        snapshot=snapshot,
    )
    saved_trace = trace_manager.load(snapshot.review_id)

    assert result.truncated is True
    assert "truncated" in str(result.payload["diff_text"])
    assert saved_trace is not None
    assert any("Tool read_diff truncated." in event.message for event in saved_trace.events)


def test_builtin_registry_exposes_only_declarative_read_only_tools():
    registry = build_builtin_tool_registry()

    assert registry.list_tools() == [
        "find_references",
        "list_changed_files",
        "read_diff",
        "read_file",
    ]


def test_tool_engine_returns_error_result_for_provider_failures():
    snapshot = _build_snapshot("diff --git a/src/example.py b/src/example.py\n")
    engine = ToolEngine(build_builtin_tool_registry())

    result = engine.run_tool(
        "read_file",
        ReadFileInput(file_path="src/example.py"),
        snapshot=snapshot,
        provider=_StubProvider({"src/example.py": "print('hello')\n"}, fail_path="src/example.py"),
    )

    assert result.error == "failed to read src/example.py"


def test_read_file_returns_file_content_from_provider():
    snapshot = _build_snapshot("diff --git a/src/example.py b/src/example.py\n")
    engine = ToolEngine(build_builtin_tool_registry())

    result = engine.run_tool(
        "read_file",
        ReadFileInput(file_path="src/example.py"),
        snapshot=snapshot,
        provider=_StubProvider({"src/example.py": "print('hello')\n"}),
    )

    assert result.error is None
    assert result.truncated is False
    assert result.payload == {
        "file_path": "src/example.py",
        "content": "print('hello')\n",
    }


def test_list_changed_files_returns_snapshot_paths():
    snapshot = _build_snapshot("diff --git a/src/example.py b/src/example.py\n")
    engine = ToolEngine(build_builtin_tool_registry())

    result = engine.run_tool(
        "list_changed_files",
        ListChangedFilesInput(),
        snapshot=snapshot,
    )

    assert result.error is None
    assert result.payload == {"files": ["src/example.py"]}


def test_find_references_searches_changed_files_only():
    snapshot = ReviewSnapshot(
        review_id="review-tools456",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/1",
        change_number=1,
        input_hash="b" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/example.py"],
        diff_text="diff --git a/src/example.py b/src/example.py\n",
    )
    engine = ToolEngine(build_builtin_tool_registry())

    result = engine.run_tool(
        "find_references",
        FindReferencesInput(
            query="needle",
            file_paths=["src/example.py", "src/ignored.py"],
        ),
        snapshot=snapshot,
        provider=_StubProvider(
            {
                "src/example.py": "needle here\nanother line\n",
                "src/ignored.py": "needle should not be searched\n",
            }
        ),
    )

    assert result.error is None
    assert result.payload["searched_files"] == ["src/example.py"]
    assert len(result.payload["matches"]) == 1


def test_read_diff_returns_error_for_unknown_changed_file():
    snapshot = _build_snapshot("diff --git a/src/example.py b/src/example.py\n")
    engine = ToolEngine(build_builtin_tool_registry())

    result = engine.run_tool(
        "read_diff",
        ReadDiffInput(file_path="src/missing.py"),
        snapshot=snapshot,
    )

    assert result.error == "changed file 'src/missing.py' is not present in the snapshot diff."
