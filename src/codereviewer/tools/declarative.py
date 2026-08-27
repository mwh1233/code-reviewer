"""Declarative tool definitions and schema generation."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from pydantic import TypeAdapter

from codereviewer.domain.errors import ToolRegistrationError
from codereviewer.domain.models import ToolSpec


DeclarativeTool = Callable[..., Any]


def tool(
    *,
    description: str,
    execution_policy: str,
    max_output_chars: int,
    failure_behavior: str,
    name: str | None = None,
    output_schema: dict[str, object] | None = None,
    context_params: tuple[str, ...] = (),
) -> Callable[[DeclarativeTool], DeclarativeTool]:
    """Mark one function as a declarative review tool."""

    def decorator(func: DeclarativeTool) -> DeclarativeTool:
        signature = inspect.signature(func)
        input_schema = _build_input_schema(
            signature,
            context_params=set(context_params),
        )
        spec = ToolSpec(
            name=name or func.__name__,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema or {},
            execution_policy=execution_policy,
            max_output_chars=max_output_chars,
            failure_behavior=failure_behavior,
        )
        setattr(func, "_is_tool", True)
        setattr(func, "_tool_spec", spec)
        setattr(func, "_tool_signature", signature)
        setattr(func, "_tool_context_params", tuple(context_params))
        return func

    return decorator


def is_declarative_tool(obj: object) -> bool:
    """Return True when the object is a @tool-decorated function."""

    return callable(obj) and bool(getattr(obj, "_is_tool", False))


def get_tool_spec(tool_func: DeclarativeTool) -> ToolSpec:
    """Read the ToolSpec attached to a declarative tool."""

    spec = getattr(tool_func, "_tool_spec", None)
    if not isinstance(spec, ToolSpec):
        raise ToolRegistrationError("declarative tool is missing a valid ToolSpec.")
    return spec


def get_context_params(tool_func: DeclarativeTool) -> tuple[str, ...]:
    """Read the runtime-only injected context params for a declarative tool."""

    context_params = getattr(tool_func, "_tool_context_params", ())
    if not isinstance(context_params, tuple):
        raise ToolRegistrationError(
            "declarative tool has invalid context parameter metadata."
        )
    return tuple(context_params)


def get_tool_signature(tool_func: DeclarativeTool) -> inspect.Signature:
    """Read the inspected function signature attached to a declarative tool."""

    signature = getattr(tool_func, "_tool_signature", None)
    if not isinstance(signature, inspect.Signature):
        raise ToolRegistrationError(
            "declarative tool is missing a valid inspected signature."
        )
    return signature


def _build_input_schema(
    signature: inspect.Signature,
    *,
    context_params: set[str],
) -> dict[str, object]:
    properties: dict[str, object] = {}
    required: list[str] = []

    for parameter in signature.parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            raise ToolRegistrationError(
                "declarative tools must use named parameters only."
            )
        if parameter.name in context_params:
            continue
        if parameter.annotation is inspect.Signature.empty:
            raise ToolRegistrationError(
                f"tool parameter '{parameter.name}' must have a type annotation."
            )

        properties[parameter.name] = _annotation_to_schema(parameter.annotation)
        if parameter.default is inspect.Signature.empty:
            required.append(parameter.name)

    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _annotation_to_schema(annotation: object) -> dict[str, object]:
    try:
        schema = TypeAdapter(annotation).json_schema()
    except Exception:
        return {"type": "string"}
    if isinstance(schema, dict):
        return schema
    return {"type": "string"}
