"""Budget-aware LLM router that switches between primary and fallback models."""

from __future__ import annotations

from dataclasses import dataclass

from codereviewer.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider
from codereviewer.config import LLMConfig
from codereviewer.domain.interfaces.llm import LLMProvider
from codereviewer.domain.models import LLMReviewResult, ToolChatRequest, ToolChatResponse


@dataclass(frozen=True)
class _ProviderSelection:
    tier: str
    model_name: str
    provider: LLMProvider


class BudgetRoutedLLMProvider:
    """Route LLM calls to primary or fallback providers based on budget mode."""

    def __init__(
        self,
        *,
        primary_provider: LLMProvider,
        fallback_provider: LLMProvider,
        primary_model: str,
        fallback_model: str,
    ) -> None:
        self._primary = _ProviderSelection(
            tier="primary",
            model_name=primary_model,
            provider=primary_provider,
        )
        self._fallback = _ProviderSelection(
            tier="fallback",
            model_name=fallback_model,
            provider=fallback_provider,
        )

    @classmethod
    def from_config(cls, config: LLMConfig) -> BudgetRoutedLLMProvider:
        """Build a routed provider from primary + fallback config."""

        primary_config = config.primary_model_config()
        fallback_config = config.fallback_model_config()
        return cls(
            primary_provider=OpenAICompatibleLLMProvider(primary_config),
            fallback_provider=OpenAICompatibleLLMProvider(fallback_config),
            primary_model=primary_config.model,
            fallback_model=fallback_config.model,
        )

    def estimate_prompt_tokens(self, text: str, *, budget_mode: str = "normal") -> int:
        return self._select_provider(budget_mode).provider.estimate_prompt_tokens(
            text,
            budget_mode=budget_mode,
        )

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        budget_mode: str = "normal",
    ) -> float:
        return self._select_provider(budget_mode).provider.estimate_cost(
            input_tokens,
            output_tokens,
            budget_mode=budget_mode,
        )

    def review(self, prompt: str, *, budget_mode: str = "normal") -> LLMReviewResult:
        return self._select_provider(budget_mode).provider.review(
            prompt,
            budget_mode=budget_mode,
        )

    def chat_with_tools(
        self,
        request: ToolChatRequest,
        *,
        budget_mode: str = "normal",
    ) -> ToolChatResponse:
        return self._select_provider(budget_mode).provider.chat_with_tools(
            request,
            budget_mode=budget_mode,
        )

    def resolve_model_name(self, *, budget_mode: str = "normal") -> str:
        """Expose the current routed model name for tracing."""

        return self._select_provider(budget_mode).model_name

    def resolve_model_tier(self, *, budget_mode: str = "normal") -> str:
        """Expose the current routed tier for tracing."""

        return self._select_provider(budget_mode).tier

    def _select_provider(self, budget_mode: str) -> _ProviderSelection:
        if budget_mode == "normal":
            return self._primary
        return self._fallback
