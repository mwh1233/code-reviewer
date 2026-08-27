"""Shared application errors."""

from __future__ import annotations


class CodeReviewerError(Exception):
    """Base class for expected application failures."""


class ProviderResolutionError(CodeReviewerError):
    """Raised when a provider cannot resolve a review target."""


class UnsupportedProviderError(CodeReviewerError):
    """Raised when a provider is recognized but not implemented yet."""


class ToolRegistrationError(CodeReviewerError):
    """Raised when a tool cannot be registered safely."""


class ToolExecutionError(CodeReviewerError):
    """Raised when a tool cannot be executed."""


class BudgetExceededError(CodeReviewerError):
    """Raised when a review exceeds its configured token or cost budget."""


class LLMProviderError(CodeReviewerError):
    """Raised when the configured LLM provider fails."""


class LLMResponseParseError(CodeReviewerError):
    """Raised when an LLM response cannot be parsed into structured findings."""


class PublishError(CodeReviewerError):
    """Raised when a publish attempt is rejected or fails."""
