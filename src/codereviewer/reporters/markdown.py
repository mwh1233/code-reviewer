"""Render a minimal markdown review report."""

from __future__ import annotations

from pathlib import Path

from codereviewer.domain.models import BudgetSnapshot, Finding, ReviewRequest, ReviewSnapshot


def write_markdown_report(
    review_root: Path,
    *,
    review_id: str,
    request: ReviewRequest,
    snapshot: ReviewSnapshot,
    findings: list[Finding],
    budget: BudgetSnapshot,
    trace_id: str,
) -> Path:
    """Write a minimal local markdown report for one review."""

    review_root.mkdir(parents=True, exist_ok=True)
    output_path = review_root / "report.md"
    lines: list[str] = [
        f"# Review Report: {review_id}",
        "",
        "## Review",
        f"- Provider: `{request.provider.value}`",
        f"- Source Kind: `{request.source_kind.value}`",
        f"- Repo: `{snapshot.repo}`",
        f"- Base SHA: `{snapshot.base_sha}`",
        f"- Head SHA: `{snapshot.head_sha}`",
        f"- Changed Files: {len(snapshot.changed_files)}",
        "",
        "## Findings Summary",
        f"- Total Findings: {len(findings)}",
        "",
        "## Findings",
    ]

    if not findings:
        lines.extend(
            [
                "- No final findings were produced.",
            ]
        )
    else:
        for finding in findings:
            location = (
                f"{finding.file}:{finding.line}"
                if finding.file and finding.line is not None
                else finding.file or "unknown"
            )
            lines.extend(
                [
                    f"### {finding.summary}",
                    f"- Severity: `{finding.severity.value}`",
                    f"- Confidence: `{finding.confidence.value}`",
                    f"- Source: `{finding.source_type.value}`",
                    f"- Location: `{location}`",
                    f"- Location Valid: `{str(finding.location_valid).lower()}`",
                    f"- Explanation: {finding.explanation}",
                    f"- Evidence Count: {len(finding.evidence)}",
                ]
            )
            if finding.suggested_fix:
                lines.append(f"- Suggested Fix: {finding.suggested_fix}")
            lines.append("")

    lines.extend(
        [
            "## Budget",
            f"- Token Used: {budget.token_used}",
            f"- Token Limit: {budget.token_limit}",
            f"- Cost Used: {budget.cost_used}",
            f"- Cost Limit: {budget.cost_limit}",
            f"- Stop Reason: {budget.stop_reason or 'none'}",
            "",
            "## Trace",
            f"- Trace ID: `{trace_id}`",
            f"- Checkpoint: `checkpoint.json`",
            f"- Findings JSON: `findings.json`",
            f"- Report: `report.md`",
            "",
        ]
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
