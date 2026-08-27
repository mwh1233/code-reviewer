"""Unit tests for declarative tool registration and execution."""

from __future__ import annotations

import importlib
import sys

from pydantic import BaseModel
import pytest

from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.errors import ToolExecutionError
from codereviewer.domain.models import ReviewSnapshot, ToolExecutionContext
from codereviewer.services.tool_engine import ToolEngine
from codereviewer.tools.auto_discover import discover_and_register
from codereviewer.tools.declarative import tool
from codereviewer.tools.registry import ToolRegistry


class _DummyPayload(BaseModel):
    value: str


def _build_snapshot() -> ReviewSnapshot:
    return ReviewSnapshot(
        review_id="review-declarative123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/1",
        change_number=1,
        input_hash="c" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/example.py"],
        diff_text="diff --git a/src/example.py b/src/example.py\n",
    )


def test_registry_executes_declarative_tool_with_context_injection():
    @tool(
        description="Echo the input with snapshot metadata.",
        execution_policy="test_only",
        max_output_chars=100,
        failure_behavior="return_error_result",
        context_params=("snapshot", "provider"),
    )
    def echo_tool(
        value: str,
        snapshot,
        provider=None,
    ) -> dict[str, object]:
        return {
            "value": value,
            "repo": snapshot.repo,
            "provider_present": provider is not None,
        }

    registry = ToolRegistry()
    registry.register(echo_tool)

    schema = registry.get_schema("echo_tool")
    assert schema["name"] == "echo_tool"
    assert "value" in schema["parameters"]["properties"]
    assert "snapshot" not in schema["parameters"]["properties"]
    assert "provider" not in schema["parameters"]["properties"]

    result = registry.execute(
        "echo_tool",
        arguments={"value": "ok"},
        context=ToolExecutionContext(
            snapshot=_build_snapshot(),
            provider=object(),
        ),
    )

    assert result.error is None
    assert result.payload == {
        "value": "ok",
        "repo": "owner/repo",
        "provider_present": True,
    }


def test_tool_engine_runs_declarative_tools_through_compatibility_layer():
    @tool(
        description="Upper-case one input string.",
        execution_policy="test_only",
        max_output_chars=100,
        failure_behavior="return_error_result",
    )
    def uppercase_tool(value: str) -> dict[str, object]:
        return {"value": value.upper()}

    registry = ToolRegistry()
    registry.register(uppercase_tool)
    engine = ToolEngine(registry)

    result = engine.run_tool(
        "uppercase_tool",
        _DummyPayload(value="hello"),
        snapshot=_build_snapshot(),
    )

    assert result.error is None
    assert result.payload == {"value": "HELLO"}


def test_registry_wraps_declarative_tool_errors_into_tool_result():
    @tool(
        description="Always fail for testing.",
        execution_policy="test_only",
        max_output_chars=100,
        failure_behavior="return_error_result",
    )
    def failing_tool() -> dict[str, object]:
        raise ToolExecutionError("boom")

    registry = ToolRegistry()
    registry.register(failing_tool)

    result = registry.execute(
        "failing_tool",
        arguments={},
        context=ToolExecutionContext(snapshot=_build_snapshot()),
    )

    assert result.error == "boom"


def test_registry_validates_declarative_tool_arguments():
    @tool(
        description="Validate integer input.",
        execution_policy="test_only",
        max_output_chars=100,
        failure_behavior="return_error_result",
    )
    def typed_tool(count: int) -> dict[str, object]:
        return {"count": count}

    registry = ToolRegistry()
    registry.register(typed_tool)

    result = registry.execute(
        "typed_tool",
        arguments={"count": "not-an-int"},
        context=ToolExecutionContext(snapshot=_build_snapshot()),
    )

    assert result.error is not None
    assert "invalid value for 'count'" in result.error


def test_discover_and_register_finds_only_decorated_public_modules(tmp_path):
    package_dir = tmp_path / "temp_tools_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "visible_tool.py").write_text(
        "\n".join(
            [
                "from codereviewer.tools.declarative import tool",
                "",
                "@tool(",
                "    description='visible',",
                "    execution_policy='test_only',",
                "    max_output_chars=100,",
                "    failure_behavior='return_error_result',",
                "    name='visible_tool',",
                ")",
                "def visible_tool(value: str) -> dict[str, object]:",
                "    return {'value': value}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (package_dir / "_hidden_tool.py").write_text(
        "\n".join(
            [
                "from codereviewer.tools.declarative import tool",
                "",
                "@tool(",
                "    description='hidden',",
                "    execution_policy='test_only',",
                "    max_output_chars=100,",
                "    failure_behavior='return_error_result',",
                "    name='hidden_tool',",
                ")",
                "def hidden_tool(value: str) -> dict[str, object]:",
                "    return {'value': value}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    try:
        registry = ToolRegistry()
        registered = discover_and_register(
            registry,
            package="temp_tools_pkg",
            directory=str(package_dir),
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("temp_tools_pkg", None)
        sys.modules.pop("temp_tools_pkg.visible_tool", None)
        sys.modules.pop("temp_tools_pkg._hidden_tool", None)

    assert registered == 1
    assert registry.list_tools() == ["visible_tool"]
