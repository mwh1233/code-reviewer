"""Unit tests for explicit tool registration."""

from __future__ import annotations

from pydantic import BaseModel
import pytest

from codereviewer.domain.errors import ToolExecutionError, ToolRegistrationError
from codereviewer.domain.models import ToolResult, ToolSpec
from codereviewer.tools.registry import ToolRegistry


class _DummyInput(BaseModel):
    value: str = "ok"


class _DummyTool:
    meta = ToolSpec(
        name="dummy",
        description="dummy tool",
        input_schema={},
        output_schema={},
        execution_policy="test_only",
        max_output_chars=100,
        failure_behavior="return_error_result",
    )

    def run(self, payload: BaseModel, *, snapshot, provider=None) -> ToolResult:
        request = _DummyInput.model_validate(payload)
        return ToolResult(tool_name=self.meta.name, payload={"value": request.value})


def test_tool_registry_rejects_duplicate_names():
    registry = ToolRegistry()
    registry.register(_DummyTool())

    with pytest.raises(ToolRegistrationError, match="already registered"):
        registry.register(_DummyTool())


def test_tool_registry_rejects_unknown_tool_lookup():
    registry = ToolRegistry()

    with pytest.raises(ToolExecutionError, match="not registered"):
        registry.get("missing")


def test_tool_registry_exposes_openai_function_schemas_for_legacy_tools():
    registry = ToolRegistry()
    registry.register(_DummyTool())

    schema = registry.get_schema("dummy")

    assert schema["name"] == "dummy"
    assert schema["description"] == "dummy tool"
    assert schema["parameters"] == {}
