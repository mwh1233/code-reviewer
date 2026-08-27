"""Shared review budget controls for LLM calls."""

from __future__ import annotations

from codereviewer.domain.models import BudgetDecision, BudgetSnapshot


_DEGRADE_RATIO = 0.60
_ESSENTIAL_RATIO = 0.85
_STOP_RATIO = 1.00

_PROMPT_CHARS_BY_LEVEL = {
    "normal": 12000,
    "degraded": 6000,
    "essential_only": 2500,
    "stopped": 0,
}


class BudgetManager:
    """Validate and update one shared review budget."""

    def __init__(self, snapshot: BudgetSnapshot) -> None:
        self._snapshot = snapshot

    @property
    def snapshot(self) -> BudgetSnapshot:
        return self._snapshot

    def plan_llm_call(
        self,
        *,
        estimated_input_tokens: int,
        estimated_cost: float,
    ) -> BudgetDecision:
        """Select the budget policy for the next LLM call."""

        projected_tokens = self._snapshot.token_used + estimated_input_tokens
        projected_cost = self._snapshot.cost_used + estimated_cost
        projected_ratio = self._usage_ratio(
            token_used=projected_tokens,
            cost_used=projected_cost,
        )
        current_ratio = self._usage_ratio(
            token_used=self._snapshot.token_used,
            cost_used=self._snapshot.cost_used,
        )

        if current_ratio >= _STOP_RATIO or projected_ratio >= _STOP_RATIO:
            reason = self._before_call_stop_reason(
                projected_tokens=projected_tokens,
                projected_cost=projected_cost,
            )
            self._snapshot.degrade_level = "stopped"
            self._snapshot.stop_reason = reason
            self._snapshot.last_decision = reason
            self._snapshot.last_projected_ratio = projected_ratio
            return BudgetDecision(
                should_call_llm=False,
                degrade_level="stopped",
                reason=reason,
                projected_ratio=projected_ratio,
                prompt_max_chars=_PROMPT_CHARS_BY_LEVEL["stopped"],
            )

        degrade_level = self._level_for_ratio(projected_ratio)
        reason = self._decision_reason_for_level(degrade_level)
        self._snapshot.degrade_level = degrade_level
        self._snapshot.last_decision = reason
        self._snapshot.last_projected_ratio = projected_ratio
        return BudgetDecision(
            should_call_llm=True,
            degrade_level=degrade_level,
            reason=reason,
            projected_ratio=projected_ratio,
            prompt_max_chars=_PROMPT_CHARS_BY_LEVEL[degrade_level],
        )

    def record_usage(self, *, input_tokens: int, output_tokens: int, cost: float) -> BudgetSnapshot:
        """Persist the actual LLM usage back into the shared review budget."""

        self._snapshot.token_used += input_tokens + output_tokens
        self._snapshot.cost_used += cost
        actual_ratio = self._usage_ratio(
            token_used=self._snapshot.token_used,
            cost_used=self._snapshot.cost_used,
        )
        self._snapshot.last_actual_ratio = actual_ratio
        self._snapshot.degrade_level = self._level_for_ratio(actual_ratio)
        if actual_ratio >= _STOP_RATIO:
            self._snapshot.degrade_level = "stopped"
            self._snapshot.stop_reason = self._after_call_stop_reason()
            self._snapshot.last_decision = self._snapshot.stop_reason
        else:
            self._snapshot.last_decision = self._decision_reason_for_level(
                self._snapshot.degrade_level
            )
        return self._snapshot

    def _usage_ratio(self, *, token_used: int, cost_used: float) -> float:
        ratios: list[float] = []
        if self._snapshot.token_limit not in (None, 0):
            ratios.append(token_used / self._snapshot.token_limit)
        if self._snapshot.cost_limit not in (None, 0):
            ratios.append(cost_used / self._snapshot.cost_limit)
        if not ratios:
            return 0.0
        return max(ratios)

    @staticmethod
    def _level_for_ratio(ratio: float) -> str:
        if ratio >= _STOP_RATIO:
            return "stopped"
        if ratio >= _ESSENTIAL_RATIO:
            return "essential_only"
        if ratio >= _DEGRADE_RATIO:
            return "degraded"
        return "normal"

    @staticmethod
    def _decision_reason_for_level(level: str) -> str:
        if level == "essential_only":
            return "budget entered essential-only range."
        if level == "degraded":
            return "budget entered degraded range."
        if level == "stopped":
            return "budget exhausted."
        return "budget remains in normal range."

    def _before_call_stop_reason(self, *, projected_tokens: int, projected_cost: float) -> str:
        if (
            self._snapshot.token_limit is not None
            and projected_tokens >= self._snapshot.token_limit
        ):
            return "token budget exceeded before LLM call."
        if (
            self._snapshot.cost_limit is not None
            and projected_cost >= self._snapshot.cost_limit
        ):
            return "cost budget exceeded before LLM call."
        return "budget exhausted before LLM call."

    def _after_call_stop_reason(self) -> str:
        if (
            self._snapshot.token_limit is not None
            and self._snapshot.token_used >= self._snapshot.token_limit
        ):
            return "token budget exceeded after LLM call."
        if (
            self._snapshot.cost_limit is not None
            and self._snapshot.cost_used >= self._snapshot.cost_limit
        ):
            return "cost budget exceeded after LLM call."
        return "budget exhausted after LLM call."
