"""Stable LLM provider contract."""

from __future__ import annotations

from typing import Protocol

from codereviewer.domain.models import (
    LLMReviewResult,
    ToolChatRequest,
    ToolChatResponse,
)


class LLMProvider(Protocol):
    """Contract implemented by one configured LLM provider."""

    def estimate_prompt_tokens(self, text: str, *, budget_mode: str = "normal") -> int:
        """Estimate prompt tokens conservatively for budget planning."""

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        budget_mode: str = "normal",
    ) -> float:
        """Estimate request cost for budget planning and accounting."""

    def review(self, prompt: str, *, budget_mode: str = "normal") -> LLMReviewResult:
        """Execute one review prompt and return normalized usage + content."""

    def chat_with_tools(
        self,
        request: ToolChatRequest,
        *,
        budget_mode: str = "normal",
    ) -> ToolChatResponse:
        """Execute one tool-enabled chat completion and return parsed tool calls."""
