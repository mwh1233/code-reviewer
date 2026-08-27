"""Factory helpers for the configured M6 LLM provider."""

from __future__ import annotations

from codereviewer.adapters.llm import BudgetRoutedLLMProvider
from codereviewer.config import AppConfig
from codereviewer.domain.interfaces.llm import LLMProvider


def build_llm_provider(config: AppConfig) -> LLMProvider:
    """Build the budget-routed LLM provider for M6."""

    return BudgetRoutedLLMProvider.from_config(config.llm)
