"""Unit tests for prompt redaction and excerpt preparation."""

from __future__ import annotations

from codereviewer.domain.enums import Confidence, ProviderKind, ReviewSourceKind, Severity
from codereviewer.domain.models import EvidenceRef, Finding, ReviewSnapshot
from codereviewer.services.security import (
    build_llm_diff_excerpt,
    redact_text,
    sanitize_findings,
    sanitize_snapshot,
)


def test_redact_text_masks_known_secret_patterns():
    text = (
        "github_pat_1234567890abcdefghijklmnopqrstuvwxyz\n"
        "glpat-GBs_x7v8sYcNNdfMIO1qAmM6MQpvOjEKdTpvdHRsOA8.01.170s8o4n0\n"
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n"
    )

    redacted = redact_text(text)

    assert "[REDACTED_SECRET]" in redacted
    assert "PRIVATE KEY" not in redacted


def test_build_llm_diff_excerpt_skips_env_files_and_truncates():
    snapshot = ReviewSnapshot(
        review_id="review-security123",
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
        changed_files=["src/app.py", ".env"],
        diff_text=(
            "diff --git a/src/app.py b/src/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "+print('ok')\n"
            "diff --git a/.env b/.env\n"
            "new file mode 100644\n"
            "index 0000000..3333333\n"
            "--- /dev/null\n"
            "+++ b/.env\n"
            "@@ -0,0 +1 @@\n"
            "+API_KEY=super-secret-value\n"
            + ("x" * 200)
        ),
    )

    excerpt = build_llm_diff_excerpt(snapshot, max_chars=100)

    assert ".env" not in excerpt
    assert "API_KEY=super-secret-value" not in excerpt
    assert "...[truncated]" in excerpt


def test_sanitize_snapshot_redacts_diff_and_skips_env_sections():
    snapshot = ReviewSnapshot(
        review_id="review-security124",
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
        changed_files=["src/app.py", ".env"],
        diff_text=(
            "diff --git a/src/app.py b/src/app.py\n"
            "@@ -1 +1 @@\n"
            '+token = "github_pat_1234567890abcdefghijklmnopqrstuvwxyz"\n'
            "diff --git a/.env b/.env\n"
            "@@ -0,0 +1 @@\n"
            "+LLM_API_KEY=sk-12345678901234567890\n"
        ),
    )

    sanitized = sanitize_snapshot(snapshot)

    assert "github_pat_1234567890abcdefghijklmnopqrstuvwxyz" not in sanitized.diff_text
    assert "sk-12345678901234567890" not in sanitized.diff_text
    assert ".env" not in sanitized.diff_text
    assert "[REDACTED_SECRET]" in sanitized.diff_text


def test_sanitize_findings_redacts_free_form_fields():
    findings = [
        Finding(
            id="finding-secret123",
            summary="Leaked github_pat_1234567890abcdefghijklmnopqrstuvwxyz",
            severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            file="src/app.py",
            line=1,
            explanation="Found sk-12345678901234567890 in output.",
            suggested_fix="Rotate glpat-GBs_x7v8sYcNNdfMIO1qAmM6MQpvOjEKdTpvdHRsOA8.01.170s8o4n0",
            evidence=[
                EvidenceRef(
                    source_type="diff",
                    source_id="evidence-1",
                    excerpt="github_pat_1234567890abcdefghijklmnopqrstuvwxyz",
                )
            ],
        )
    ]

    sanitized = sanitize_findings(findings)

    assert "[REDACTED_SECRET]" in sanitized[0].summary
    assert "sk-12345678901234567890" not in sanitized[0].explanation
    assert "glpat-GBs_x7v8sYcNNdfMIO1qAmM6MQpvOjEKdTpvdHRsOA8.01.170s8o4n0" not in (
        sanitized[0].suggested_fix or ""
    )
    assert sanitized[0].evidence[0].excerpt == "[REDACTED_SECRET]"
