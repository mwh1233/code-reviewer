"""Unit tests for finding location validation against diff-added lines."""

from __future__ import annotations

from codereviewer.domain.enums import Confidence, ProviderKind, ReviewSourceKind, Severity
from codereviewer.domain.models import EvidenceRef, Finding, ReviewSnapshot
from codereviewer.services.comment_locator import CommentLocator


def _build_snapshot() -> ReviewSnapshot:
    return ReviewSnapshot(
        review_id="review-locator123",
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
        changed_files=["src/example.py", ".env"],
        diff_text=(
            "diff --git a/src/example.py b/src/example.py\n"
            "@@ -1,1 +1,3 @@\n"
            " old_line\n"
            "+first_added_line\n"
            "+second_added_line\n"
            "diff --git a/.env b/.env\n"
            "@@ -0,0 +1 @@\n"
            "+API_KEY=test\n"
        ),
    )


def _build_finding(*, file: str | None, line: int | None) -> Finding:
    return Finding(
        id="finding-1",
        summary="Example finding",
        severity=Severity.MEDIUM,
        confidence=Confidence.HIGH,
        file=file,
        line=line,
        explanation="Example explanation.",
        evidence=[
            EvidenceRef(
                source_type="diff",
                source_id="read_diff",
                file=file,
                line_start=line,
                line_end=line,
                excerpt="example",
                verified=True,
            )
        ],
    )


def test_comment_locator_keeps_valid_added_line_locations():
    locator = CommentLocator(_build_snapshot())

    validated = locator.validate([_build_finding(file="src/example.py", line=2)])

    assert len(validated) == 1
    assert validated[0].location_valid is True
    assert validated[0].confidence == Confidence.HIGH
    assert len(validated[0].evidence) == 1


def test_comment_locator_downgrades_findings_for_unchanged_files():
    locator = CommentLocator(_build_snapshot())

    validated = locator.validate([_build_finding(file="src/other.py", line=2)])

    assert len(validated) == 1
    assert validated[0].location_valid is False
    assert validated[0].confidence == Confidence.REFERENCE
    assert validated[0].evidence[-1].source_type == "location_check_failed"


def test_comment_locator_downgrades_findings_without_added_line_mapping():
    locator = CommentLocator(_build_snapshot())

    validated = locator.validate([_build_finding(file=".env", line=None)])

    assert len(validated) == 1
    assert validated[0].location_valid is False
    assert validated[0].confidence == Confidence.REFERENCE
    assert validated[0].evidence[-1].excerpt == (
        "finding line must point to an added line in the diff."
    )
