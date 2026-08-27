"""Minimal evidence validation for M7 findings verification."""

from __future__ import annotations

from codereviewer.domain.enums import Confidence
from codereviewer.domain.models import Finding


class EvidenceValidator:
    """Filter unsupported findings and normalize confidence from evidence."""

    def validate(self, findings: list[Finding]) -> list[Finding]:
        validated: list[Finding] = []
        for finding in findings:
            if not finding.evidence:
                continue

            if not finding.location_valid:
                confidence = Confidence.REFERENCE
            else:
                has_verified_evidence = any(
                    evidence.verified for evidence in finding.evidence
                )
                confidence = (
                    Confidence.HIGH if has_verified_evidence else Confidence.REFERENCE
                )
            validated.append(
                finding.model_copy(
                    update={
                        "confidence": confidence,
                    }
                )
            )
        return validated
