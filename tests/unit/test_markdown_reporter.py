"""Unit tests for markdown review report output."""

from __future__ import annotations

from codereviewer.domain.enums import Confidence, ProviderKind, ReviewSourceKind, Severity
from codereviewer.domain.models import BudgetSnapshot, EvidenceRef, Finding, ReviewRequest, ReviewSnapshot
from codereviewer.reporters.markdown import write_markdown_report


def test_write_markdown_report_contains_core_sections(tmp_path):
    output_path = write_markdown_report(
        tmp_path,
        review_id="review-123",
        request=ReviewRequest(
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.REVIEW_URL,
            review_url="https://github.com/owner/repo/pull/1",
            repo="owner/repo",
            change_number=1,
        ),
        snapshot=ReviewSnapshot(
            review_id="review-123",
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.REVIEW_URL,
            repo="owner/repo",
            review_url="https://github.com/owner/repo/pull/1",
            change_number=1,
            input_hash="a" * 64,
            base_ref="main",
            head_ref="feature/test",
            base_sha="base123",
            head_sha="head456",
            changed_files=["src/app.py"],
            diff_text="diff --git a/src/app.py b/src/app.py\n+print('ok')\n",
        ),
        findings=[
            Finding(
                id="finding-1",
                summary="Example finding",
                severity=Severity.LOW,
                confidence=Confidence.REFERENCE,
                file="src/app.py",
                line=1,
                explanation="Example explanation.",
                evidence=[
                    EvidenceRef(
                        source_type="llm_prompt",
                        source_id="llm_review",
                        file="src/app.py",
                        line_start=1,
                        line_end=1,
                        excerpt="print('ok')",
                        verified=False,
                    )
                ],
            )
        ],
        budget=BudgetSnapshot(
            token_limit=1000,
            token_used=123,
            cost_limit=1.0,
            cost_used=0.12,
        ),
        trace_id="trace-123",
    )

    content = output_path.read_text(encoding="utf-8")

    assert output_path.name == "report.md"
    assert "# Review Report: review-123" in content
    assert "## Findings" in content
    assert "Example finding" in content
    assert "Location Valid: `true`" in content
    assert "## Budget" in content
    assert "## Trace" in content
