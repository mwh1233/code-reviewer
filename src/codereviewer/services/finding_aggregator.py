"""Minimal finding aggregation for M7 verification."""

from __future__ import annotations

from codereviewer.domain.enums import Confidence, FindingSource, Severity
from codereviewer.domain.models import EvidenceRef, Finding

_SEVERITY_ORDER = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


class FindingAggregator:
    """Deduplicate structurally identical findings and keep the stronger one."""

    def aggregate(self, findings: list[Finding]) -> list[Finding]:
        deduped: dict[tuple[str, int, str], Finding] = {}
        ordered_keys: list[tuple[str, int, str]] = []

        for finding in findings:
            key = self._dedupe_key(finding)
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = finding
                ordered_keys.append(key)
                continue
            deduped[key] = self._merge(existing, finding)

        return [deduped[key] for key in ordered_keys]

    def _merge(self, left: Finding, right: Finding) -> Finding:
        stronger, weaker = sorted(
            (left, right),
            key=self._strength_key,
            reverse=True,
        )
        merged_evidence = self._merge_evidence(stronger.evidence, weaker.evidence)
        merged_source = (
            stronger.source_type
            if stronger.source_type == weaker.source_type
            else FindingSource.HYBRID
        )

        return stronger.model_copy(
            update={
                "evidence": merged_evidence,
                "source_type": merged_source,
                "suggested_fix": stronger.suggested_fix or weaker.suggested_fix,
            }
        )

    @staticmethod
    def _dedupe_key(finding: Finding) -> tuple[str, int, str]:
        return (
            finding.file or "",
            finding.line or 0,
            finding.summary.strip().lower(),
        )

    @staticmethod
    def _strength_key(finding: Finding) -> tuple[int, int, int, int, int]:
        verified_count = sum(1 for evidence in finding.evidence if evidence.verified)
        total_evidence = len(finding.evidence)
        confidence_rank = 1 if finding.confidence == Confidence.HIGH else 0
        source_rank = 1 if finding.source_type == FindingSource.RULE else 0
        severity_rank = _SEVERITY_ORDER[finding.severity]
        return (
            verified_count,
            total_evidence,
            confidence_rank,
            source_rank,
            severity_rank,
        )

    @staticmethod
    def _merge_evidence(
        primary: list[EvidenceRef],
        secondary: list[EvidenceRef],
    ) -> list[EvidenceRef]:
        merged: list[EvidenceRef] = []
        seen: set[tuple[object, ...]] = set()
        for evidence in [*primary, *secondary]:
            key = (
                evidence.source_type,
                evidence.source_id,
                evidence.file,
                evidence.line_start,
                evidence.line_end,
                evidence.excerpt,
                evidence.verified,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(evidence)
        return merged
