"""Tests for budget-aware LLM routing between primary and fallback models."""

from __future__ import annotations

from codereviewer.adapters.llm.budget_routed import BudgetRoutedLLMProvider
from codereviewer.domain.models import LLMReviewResult, ToolChatMessage, ToolChatRequest, ToolChatResponse


class _FakeProvider:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[tuple[str, str]] = []

    def estimate_prompt_tokens(self, text: str, *, budget_mode: str = "normal") -> int:
        self.calls.append(("estimate_prompt_tokens", budget_mode))
        return 10

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        budget_mode: str = "normal",
    ) -> float:
        self.calls.append(("estimate_cost", budget_mode))
        return 0.01

    def review(self, prompt: str, *, budget_mode: str = "normal") -> LLMReviewResult:
        self.calls.append(("review", budget_mode))
        return LLMReviewResult(raw_content='{"findings":[]}')

    def chat_with_tools(
        self,
        request: ToolChatRequest,
        *,
        budget_mode: str = "normal",
    ) -> ToolChatResponse:
        self.calls.append(("chat_with_tools", budget_mode))
        return ToolChatResponse(content="done")


def test_budget_routed_provider_uses_primary_for_normal_mode():
    primary = _FakeProvider("primary-model")
    fallback = _FakeProvider("fallback-model")
    provider = BudgetRoutedLLMProvider(
        primary_provider=primary,
        fallback_provider=fallback,
        primary_model="primary-model",
        fallback_model="fallback-model",
    )

    cost = provider.estimate_cost(100, 50, budget_mode="normal")
    result = provider.chat_with_tools(
        ToolChatRequest(messages=[ToolChatMessage(role="user", content="prompt")]),
        budget_mode="normal",
    )

    assert cost == 0.01
    assert result.content == "done"
    assert primary.calls == [
        ("estimate_cost", "normal"),
        ("chat_with_tools", "normal"),
    ]
    assert fallback.calls == []
    assert provider.resolve_model_tier(budget_mode="normal") == "primary"
    assert provider.resolve_model_name(budget_mode="normal") == "primary-model"


def test_budget_routed_provider_uses_fallback_for_degraded_modes():
    primary = _FakeProvider("primary-model")
    fallback = _FakeProvider("fallback-model")
    provider = BudgetRoutedLLMProvider(
        primary_provider=primary,
        fallback_provider=fallback,
        primary_model="primary-model",
        fallback_model="fallback-model",
    )

    provider.review("prompt", budget_mode="degraded")
    provider.chat_with_tools(
        ToolChatRequest(messages=[ToolChatMessage(role="user", content="prompt")]),
        budget_mode="essential_only",
    )

    assert primary.calls == []
    assert fallback.calls == [
        ("review", "degraded"),
        ("chat_with_tools", "essential_only"),
    ]
    assert provider.resolve_model_tier(budget_mode="degraded") == "fallback"
    assert provider.resolve_model_name(budget_mode="essential_only") == "fallback-model"
