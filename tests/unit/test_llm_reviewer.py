"""Unit tests for LLM review orchestration and parsing."""

from __future__ import annotations

import pytest

from codereviewer.domain.enums import ProviderKind, ReviewSourceKind, Severity
from codereviewer.domain.errors import LLMResponseParseError
from codereviewer.domain.models import LLMReviewResult, ReviewSnapshot
from codereviewer.services.llm_reviewer import LLMReviewer


class _StubLLMProvider:
    def __init__(self, raw_content: str) -> None:
        self._raw_content = raw_content
        self.prompts: list[str] = []

    def review(self, prompt: str, *, budget_mode: str = "normal") -> LLMReviewResult:
        self.prompts.append(prompt)
        return LLMReviewResult(
            raw_content=self._raw_content,
            input_tokens=200,
            output_tokens=50,
            estimated_cost=0.25,
        )


def _build_snapshot() -> ReviewSnapshot:
    return ReviewSnapshot(
        review_id="review-llm123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/1",
        change_number=1,
        input_hash="b" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/app.py"],
        diff_text="diff --git a/src/app.py b/src/app.py\n+print(value)\n",
    )


def test_llm_reviewer_parses_structured_findings():
    provider = _StubLLMProvider(
        '{"findings":[{"summary":"Potential bug","severity":"medium","confidence":"high","file":"src/app.py","line":12,"explanation":"The new branch may skip validation.","suggested_fix":"Add a guard clause."}]}'
    )
    reviewer = LLMReviewer(provider)

    result = reviewer.review(_build_snapshot())

    assert provider.prompts
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.MEDIUM
    assert result.findings[0].file == "src/app.py"


def test_llm_reviewer_rejects_invalid_json():
    reviewer = LLMReviewer(_StubLLMProvider("not json"))

    with pytest.raises(LLMResponseParseError, match="not valid JSON"):
        reviewer.review(_build_snapshot())


def test_llm_reviewer_builds_smaller_prompt_for_degraded_modes():
    reviewer = LLMReviewer(_StubLLMProvider('{"findings":[]}'))
    snapshot = _build_snapshot()
    snapshot.diff_text = (
        "diff --git a/src/app.py b/src/app.py\n"
        + ("+print(value)\n" * 3000)
    )

    normal_prompt = reviewer.build_prompt(snapshot, max_chars=12000, budget_mode="normal")
    degraded_prompt = reviewer.build_prompt(snapshot, max_chars=6000, budget_mode="degraded")
    essential_prompt = reviewer.build_prompt(
        snapshot,
        max_chars=2500,
        budget_mode="essential_only",
    )

    assert len(degraded_prompt) < len(normal_prompt)
    assert len(essential_prompt) < len(degraded_prompt)
    assert "Budget mode: degraded." in degraded_prompt
    assert "Budget mode: essential_only." in essential_prompt
