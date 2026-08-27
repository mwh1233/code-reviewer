"""Explicit tool registry for deterministic and declarative review tools."""

from __future__ import annotations

from typing import Any

from codereviewer.domain.errors import (
    CodeReviewerError,
    ToolExecutionError,
    ToolRegistrationError,
)
from codereviewer.domain.interfaces.tool import ReviewTool
from codereviewer.domain.models import ToolExecutionContext, ToolResult
from codereviewer.tools.declarative import (
    get_context_params,
    get_tool_signature,
    get_tool_spec,
    is_declarative_tool,
)


class ToolRegistry:
    """Register and resolve tools by stable name."""

    def __init__(self) -> None:
        self._tools: dict[str, object] = {}
        self._schemas: dict[str, dict[str, object]] = {}

    def register(self, tool: object) -> None:
        if is_declarative_tool(tool):
            spec = get_tool_spec(tool)
            name = spec.name
            schema = {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_schema,
            }
        else:
            meta = getattr(tool, "meta", None)
            if meta is None:
                raise ToolRegistrationError(
                    "registered tool must define 'meta' or be decorated with @tool."
                )
            name = meta.name
            schema = {
                "name": meta.name,
                "description": meta.description,
                "parameters": meta.input_schema,
            }
        if name in self._tools:
            raise ToolRegistrationError(f"tool '{name}' is already registered.")
        self._tools[name] = tool
        self._schemas[name] = schema

    def get(self, name: str) -> object:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolExecutionError(f"tool '{name}' is not registered.")
        return tool

    def get_schema(self, name: str) -> dict[str, object]:
        return self._schemas[name]

    def get_all_schemas(self) -> list[dict[str, object]]:
        return [self._schemas[name] for name in sorted(self._schemas)]

    def execute(
        self,
        name: str,
        *,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        try:
            tool = self.get(name)
            if is_declarative_tool(tool):
                return self._execute_declarative_tool(
                    tool,
                    arguments=arguments,
                    context=context,
                )

            result = tool.run(
                arguments,
                snapshot=context.snapshot,
                provider=context.provider,
            )
            if isinstance(result, ToolResult):
                return result
            if not isinstance(result, dict):
                result = {"result": result}
            return ToolResult(tool_name=name, payload=result)
        except CodeReviewerError as exc:
            return ToolResult(tool_name=name, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive safety net
            return ToolResult(tool_name=name, error=f"Unexpected tool failure: {exc}")

    def list_tools(self) -> list[str]:
        return sorted(self._tools)

    def _execute_declarative_tool(
        self,
        tool_func,
        *,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        spec = get_tool_spec(tool_func)
        signature = get_tool_signature(tool_func)
        context_params = set(get_context_params(tool_func))
        call_kwargs: dict[str, Any] = {}

        for parameter in signature.parameters.values():
            if parameter.name in context_params:
                call_kwargs[parameter.name] = getattr(context, parameter.name)
                continue

            if parameter.name in arguments:
                value = arguments[parameter.name]
            elif parameter.default is not parameter.empty:
                value = parameter.default
            else:
                raise ToolExecutionError(
                    f"tool '{spec.name}' missing required argument '{parameter.name}'."
                )

            if parameter.annotation is not parameter.empty:
                value = self._validate_argument(
                    spec.name,
                    parameter.name,
                    parameter.annotation,
                    value,
                )
            call_kwargs[parameter.name] = value

        result = tool_func(**call_kwargs)
        if isinstance(result, ToolResult):
            return result
        if not isinstance(result, dict):
            result = {"result": result}
        return ToolResult(tool_name=spec.name, payload=result)

    @staticmethod
    def _validate_argument(
        tool_name: str,
        argument_name: str,
        annotation: object,
        value: Any,
    ) -> Any:
        try:
            from pydantic import TypeAdapter

            return TypeAdapter(annotation).validate_python(value)
        except Exception as exc:
            raise ToolExecutionError(
                f"tool '{tool_name}' received an invalid value for "
                f"'{argument_name}': {exc}"
            ) from exc
