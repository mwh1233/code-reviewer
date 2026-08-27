"""Execution helpers for explicitly registered review tools."""

from __future__ import annotations

from pydantic import BaseModel

from codereviewer.domain.enums import ReviewStage
from codereviewer.domain.interfaces.scm import SCMProvider
from codereviewer.domain.interfaces.tool import ToolExecutor
from codereviewer.domain.models import (
    ReviewSnapshot,
    ReviewTrace,
    ToolExecutionContext,
    ToolResult,
)
from codereviewer.services.trace_manager import TraceManager
from codereviewer.tools.registry import ToolRegistry


class ToolEngine(ToolExecutor):
    """Execute registered tools and normalize their failure behavior."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        trace_manager: TraceManager | None = None,
        trace: ReviewTrace | None = None,
        review_id: str | None = None,
        trace_stage: ReviewStage = ReviewStage.DETERMINISTIC_CHECKS_DONE,
    ) -> None:
        self._registry = registry
        self._trace_manager = trace_manager
        self._trace = trace
        self._review_id = review_id
        self._trace_stage = trace_stage

    def run_tool(
        self,
        name: str,
        payload: BaseModel,
        *,
        snapshot: ReviewSnapshot,
        provider: SCMProvider | None = None,
    ) -> ToolResult:
        self._trace_message(f"Tool {name} started.")
        arguments = (
            payload.model_dump()
            if isinstance(payload, BaseModel)
            else dict(payload)
        )
        result = self._registry.execute(
            name,
            arguments=arguments,
            context=ToolExecutionContext(snapshot=snapshot, provider=provider),
        )

        if result.error is not None:
            self._trace_message(f"Tool {name} failed: {result.error}")
            return result

        status = "truncated" if result.truncated else "completed"
        self._trace_message(f"Tool {name} {status}.")
        return result

    def _trace_message(self, message: str) -> None:
        if (
            self._trace_manager is None
            or self._trace is None
            or self._review_id is None
        ):
            return
        self._trace_manager.append_event(
            review_id=self._review_id,
            trace=self._trace,
            stage=self._trace_stage,
            message=message,
        )
