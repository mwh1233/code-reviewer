"""Tests for provider comment rendering."""

from codereviewer.domain.enums import Confidence, FindingSource, ProviderKind, ReviewSourceKind, Severity
from codereviewer.domain.models import Finding, ReviewSnapshot
from codereviewer.reporters.comment import render_review_comment


def test_render_review_comment_includes_findings_summary():
    snapshot = ReviewSnapshot(
        review_id="review-test123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/123",
        change_number=123,
        input_hash="a" * 64,
        head_sha="head456",
    )
    findings = [
        Finding(
            id="finding-1",
            summary="Potential bug",
            severity=Severity.MEDIUM,
            confidence=Confidence.REFERENCE,
            file="src/app.py",
            line=10,
            explanation="Something looks suspicious.",
            suggested_fix="Check the branch condition.",
            source_type=FindingSource.LLM,
        )
    ]

    body = render_review_comment(
        review_id="review-test123",
        snapshot=snapshot,
        findings=findings,
    )

    assert "## 自动审查结论" in body
    assert "Review ID: `review-test123`" in body
    assert "Head SHA: `head456`" in body
    assert "问题总数: 1" in body
    assert "Potential bug" in body
    assert "src/app.py:10" in body


def test_render_review_comment_outputs_mergeable_summary_when_no_findings():
    snapshot = ReviewSnapshot(
        review_id="review-test123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/123",
        change_number=123,
        input_hash="a" * 64,
        head_sha="head456",
    )

    body = render_review_comment(
        review_id="review-test123",
        snapshot=snapshot,
        findings=[],
    )

    assert "## 自动审查结论" in body
    assert "问题总数: 0" in body
    assert "未发现需要阻塞合并的高置信度问题，可以合并。" in body
