"""Unit tests for shared review budget enforcement."""

from __future__ import annotations

from codereviewer.domain.models import BudgetSnapshot
from codereviewer.services.budget_manager import BudgetManager


def test_budget_manager_enters_degraded_range_at_sixty_percent():
    manager = BudgetManager(BudgetSnapshot(token_limit=1000, token_used=500))

    decision = manager.plan_llm_call(estimated_input_tokens=100, estimated_cost=0.0)

    assert decision.should_call_llm is True
    assert decision.degrade_level == "degraded"
    assert manager.snapshot.degrade_level == "degraded"


def test_budget_manager_enters_essential_only_range_at_eighty_five_percent():
    manager = BudgetManager(BudgetSnapshot(token_limit=1000, token_used=700))

    decision = manager.plan_llm_call(estimated_input_tokens=150, estimated_cost=0.0)

    assert decision.should_call_llm is True
    assert decision.degrade_level == "essential_only"
    assert manager.snapshot.degrade_level == "essential_only"


def test_budget_manager_stops_before_llm_call_at_or_above_hundred_percent():
    manager = BudgetManager(BudgetSnapshot(token_limit=1000, token_used=950))

    decision = manager.plan_llm_call(estimated_input_tokens=50, estimated_cost=0.0)

    assert decision.should_call_llm is False
    assert decision.degrade_level == "stopped"
    assert manager.snapshot.stop_reason == "token budget exceeded before LLM call."


def test_budget_manager_records_actual_usage():
    manager = BudgetManager(BudgetSnapshot(token_limit=1000, cost_limit=2.0))

    snapshot = manager.record_usage(input_tokens=100, output_tokens=40, cost=0.12)

    assert snapshot.token_used == 140
    assert snapshot.cost_used == 0.12


def test_budget_manager_records_stop_reason_after_actual_overrun():
    manager = BudgetManager(BudgetSnapshot(token_limit=140, cost_limit=2.0))

    snapshot = manager.record_usage(input_tokens=100, output_tokens=50, cost=0.12)

    assert snapshot.token_used == 150
    assert snapshot.degrade_level == "stopped"
    assert snapshot.stop_reason == "token budget exceeded after LLM call."
