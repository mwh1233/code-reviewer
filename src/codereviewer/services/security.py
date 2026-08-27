"""Security helpers for redaction and prompt material preparation."""

from __future__ import annotations

import re

from codereviewer.domain.models import Finding, ReviewSnapshot
from codereviewer.services.diff_preprocessor import prepare_diff_analysis


_TOKEN_PATTERNS = (
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-\.]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(
        r"-{5}BEGIN [A-Z ]*PRIVATE KEY-{5}.*?-{5}END [A-Z ]*PRIVATE KEY-{5}",
        re.DOTALL,
    ),
)


def redact_text(text: str) -> str:
    """Redact likely secrets before sending data to an LLM."""

    redacted = text
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def sanitize_snapshot(snapshot: ReviewSnapshot) -> ReviewSnapshot:
    """Return one checkpoint-safe snapshot with redacted diff content."""

    return snapshot.model_copy(
        update={
            "diff_text": _build_redacted_diff(snapshot),
            "review_title": _optional_redact(snapshot.review_title),
            "author_login": _optional_redact(snapshot.author_login),
            "web_url": _optional_redact(snapshot.web_url),
        }
    )


def sanitize_findings(findings: list[Finding]) -> list[Finding]:
    """Return output-safe findings with redacted free-form text fields."""

    return [sanitize_finding(finding) for finding in findings]


def sanitize_finding(finding: Finding) -> Finding:
    """Return one output-safe finding."""

    return finding.model_copy(
        update={
            "summary": redact_text(finding.summary),
            "explanation": redact_text(finding.explanation),
            "suggested_fix": _optional_redact(finding.suggested_fix),
            "evidence": [
                evidence.model_copy(update={"excerpt": _optional_redact(evidence.excerpt)})
                for evidence in finding.evidence
            ],
        }
    )


def build_llm_diff_excerpt(snapshot: ReviewSnapshot, *, max_chars: int = 12000) -> str:
    """Prepare redacted diff content for the M6 LLM prompt."""

    diff_text = _build_redacted_diff(snapshot)
    if len(diff_text) > max_chars:
        diff_text = diff_text[: max_chars - 15] + "\n...[truncated]"
    header = (
        f"repo={snapshot.repo}\n"
        f"base_sha={snapshot.base_sha}\n"
        f"head_sha={snapshot.head_sha}\n"
        f"changed_files={_visible_changed_files(snapshot)}\n"
    )
    return header + "\n" + diff_text


def _build_redacted_diff(snapshot: ReviewSnapshot) -> str:
    diff_sections: list[str] = []
    analysis = prepare_diff_analysis(snapshot)

    for file_diff in analysis.text_files:
        if _is_env_path(file_diff.path):
            continue
        diff_sections.append(file_diff.diff_text)

    return redact_text("".join(diff_sections))


def _visible_changed_files(snapshot: ReviewSnapshot) -> list[str]:
    return [
        file_path
        for file_path in snapshot.changed_files
        if not _is_env_path(file_path)
    ]


def _is_env_path(path: str) -> bool:
    normalized_path = path.lower()
    return normalized_path.startswith(".env") or "/.env" in normalized_path


def _optional_redact(value: str | None) -> str | None:
    if value is None:
        return None
    return redact_text(value)
