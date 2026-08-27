"""Stable tool and rule contracts."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from codereviewer.domain.interfaces.scm import SCMProvider
from codereviewer.domain.models import (
    Finding,
    ReviewSnapshot,
    RuleSpec,
    ToolResult,
    ToolSpec,
)


class ToolExecutor(Protocol):
    """Minimal executor surface that rules can depend on."""

    def run_tool(
        self,
        name: str,
        payload: BaseModel,
        *,
        snapshot: ReviewSnapshot,
        provider: SCMProvider | None = None,
    ) -> ToolResult:
        """Execute one registered tool by name."""


class ReviewTool(Protocol):
    """Contract implemented by all review tools."""

    meta: ToolSpec

    def run(
        self,
        payload: BaseModel,
        *,
        snapshot: ReviewSnapshot,
        provider: SCMProvider | None = None,
    ) -> ToolResult:
        """Execute the tool against one immutable snapshot."""


class ReviewRule(Protocol):
    """Contract implemented by deterministic review rules."""

    meta: RuleSpec

    def evaluate(
        self,
        *,
        snapshot: ReviewSnapshot,
        tool_executor: ToolExecutor,
        provider: SCMProvider | None = None,
    ) -> list[Finding]:
        """Produce rule-backed findings for one immutable snapshot."""
