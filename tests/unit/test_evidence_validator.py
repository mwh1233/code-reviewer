"""Unit tests for M7 evidence validation."""

from __future__ import annotations

from codereviewer.domain.enums import Confidence, FindingSource, Severity
from codereviewer.domain.models import EvidenceRef, Finding
from codereviewer.services.evidence_validator import EvidenceValidator


def test_evidence_validator_filters_findings_without_evidence():
    validator = EvidenceValidator()

    findings = [
        Finding(
            id="missing-evidence",
            summary="No evidence attached",
            severity=Severity.LOW,
            confidence=Confidence.HIGH,
            file="src/app.py",
            line=10,
            explanation="Should be filtered.",
            evidence=[],
            source_type=FindingSource.LLM,
        )
    ]

    assert validator.validate(findings) == []


def test_evidence_validator_downgrades_unverified_evidence_to_reference():
    validator = EvidenceValidator()
    finding = Finding(
        id="llm-finding",
        summary="Candidate issue",
        severity=Severity.MEDIUM,
        confidence=Confidence.HIGH,
        file="src/app.py",
        line=12,
        explanation="LLM-only evidence should remain reference.",
        evidence=[
            EvidenceRef(
                source_type="llm_prompt",
                source_id="llm_review",
                file="src/app.py",
                line_start=12,
                line_end=12,
                excerpt="candidate issue",
                verified=False,
            )
        ],
        source_type=FindingSource.LLM,
    )

    validated = validator.validate([finding])

    assert len(validated) == 1
    assert validated[0].confidence == Confidence.REFERENCE


def test_evidence_validator_promotes_verified_evidence_to_high():
    validator = EvidenceValidator()
    finding = Finding(
        id="rule-finding",
        summary="Verified issue",
        severity=Severity.HIGH,
        confidence=Confidence.REFERENCE,
        file=".env",
        explanation="Verified evidence should become high confidence.",
        evidence=[
            EvidenceRef(
                source_type="tool",
                source_id="list_changed_files",
                file=".env",
                excerpt="Changed file: .env",
                verified=True,
            )
        ],
        source_type=FindingSource.RULE,
    )

    validated = validator.validate([finding])

    assert len(validated) == 1
    assert validated[0].confidence == Confidence.HIGH


def test_evidence_validator_keeps_invalid_locations_at_reference():
    validator = EvidenceValidator()
    finding = Finding(
        id="invalid-location",
        summary="Wrong line mapping",
        severity=Severity.MEDIUM,
        confidence=Confidence.HIGH,
        file="src/app.py",
        line=99,
        explanation="The finding points outside added diff lines.",
        evidence=[
            EvidenceRef(
                source_type="diff",
                source_id="read_diff",
                file="src/app.py",
                line_start=99,
                line_end=99,
                excerpt="candidate issue",
                verified=True,
            )
        ],
        source_type=FindingSource.RULE,
        location_valid=False,
    )

    validated = validator.validate([finding])

    assert len(validated) == 1
    assert validated[0].confidence == Confidence.REFERENCE
    assert validated[0].location_valid is False
