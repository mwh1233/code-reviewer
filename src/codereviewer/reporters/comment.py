"""Render provider comment bodies from final findings."""

from __future__ import annotations

from codereviewer.domain.models import Finding, ReviewSnapshot


def render_review_comment(
    *,
    review_id: str,
    snapshot: ReviewSnapshot,
    findings: list[Finding],
) -> str:
    """Render one provider-facing markdown comment for the final findings."""

    lines: list[str] = [
        "## 自动审查结论",
        f"- Review ID: `{review_id}`",
        f"- Head SHA: `{snapshot.head_sha or 'unknown'}`",
        f"- 问题总数: {len(findings)}",
        "",
    ]

    if not findings:
        lines.extend(
            [
                "本次自动审查未发现需要阻塞合并的高置信度问题，可以合并。",
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    for index, finding in enumerate(findings, start=1):
        location = (
            f"{finding.file}:{finding.line}"
            if finding.file and finding.line is not None
            else finding.file or "unknown"
        )
        lines.extend(
            [
                f"{index}. `{finding.severity.value}` / `{finding.confidence.value}` {finding.summary}",
                f"   - 位置: `{location}`",
                f"   - 来源: `{finding.source_type.value}`",
                f"   - 说明: {finding.explanation}",
            ]
        )
        if finding.suggested_fix:
            lines.append(f"   - 建议修复: {finding.suggested_fix}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
