"""Unit tests for M7 finding aggregation."""

from __future__ import annotations

from codereviewer.domain.enums import Confidence, FindingSource, Severity
from codereviewer.domain.models import EvidenceRef, Finding
from codereviewer.services.finding_aggregator import FindingAggregator


def test_finding_aggregator_deduplicates_and_prefers_stronger_evidence():
    aggregator = FindingAggregator()
    rule_finding = Finding(
        id="rule-debug",
        summary="Debug statement added in the changed code.",
        severity=Severity.LOW,
        confidence=Confidence.HIGH,
        file="src/example.py",
        line=2,
        explanation="Verified rule evidence.",
        evidence=[
            EvidenceRef(
                source_type="diff",
                source_id="read_diff",
                file="src/example.py",
                line_start=2,
                line_end=2,
                excerpt="console.log(value)",
                verified=True,
            )
        ],
        source_type=FindingSource.RULE,
    )
    llm_finding = Finding(
        id="llm-debug",
        summary="Debug statement added in the changed code.",
        severity=Severity.LOW,
        confidence=Confidence.REFERENCE,
        file="src/example.py",
        line=2,
        explanation="Unverified LLM evidence.",
        evidence=[
            EvidenceRef(
                source_type="llm_prompt",
                source_id="llm_review",
                file="src/example.py",
                line_start=2,
                line_end=2,
                excerpt="console.log(value)",
                verified=False,
            )
        ],
        suggested_fix="Remove the debug statement.",
        source_type=FindingSource.LLM,
    )

    aggregated = aggregator.aggregate([llm_finding, rule_finding])

    assert len(aggregated) == 1
    assert aggregated[0].id == "rule-debug"
    assert aggregated[0].source_type == FindingSource.HYBRID
    assert aggregated[0].suggested_fix == "Remove the debug statement."
    assert len(aggregated[0].evidence) == 2


def test_finding_aggregator_keeps_distinct_findings():
    aggregator = FindingAggregator()
    findings = [
        Finding(
            id="finding-1",
            summary="Sensitive-looking file appears in the change set.",
            severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            file=".env",
            explanation="Secret file.",
            evidence=[
                EvidenceRef(
                    source_type="tool",
                    source_id="list_changed_files",
                    file=".env",
                    excerpt="Changed file: .env",
                    verified=True,
                )
            ],
        ),
        Finding(
            id="finding-2",
            summary="Debug statement added in the changed code.",
            severity=Severity.LOW,
            confidence=Confidence.HIGH,
            file="src/example.py",
            line=2,
            explanation="Debug code.",
            evidence=[
                EvidenceRef(
                    source_type="diff",
                    source_id="read_diff",
                    file="src/example.py",
                    line_start=2,
                    line_end=2,
                    excerpt="console.log(value)",
                    verified=True,
                )
            ],
        ),
    ]

    aggregated = aggregator.aggregate(findings)

    assert len(aggregated) == 2
