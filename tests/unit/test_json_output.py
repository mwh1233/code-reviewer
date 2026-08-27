"""Unit tests for findings JSON output."""

from __future__ import annotations

import json

from codereviewer.domain.enums import Confidence, Severity
from codereviewer.domain.models import EvidenceRef, Finding
from codereviewer.reporters.json_output import write_findings_json


def test_write_findings_json_writes_structured_payload(tmp_path):
    output_path = write_findings_json(
        tmp_path,
        [
            Finding(
                id="finding-1",
                summary="Example finding",
                severity=Severity.MEDIUM,
                confidence=Confidence.REFERENCE,
                file="src/app.py",
                line=10,
                explanation="Example explanation.",
                evidence=[
                    EvidenceRef(
                        source_type="llm_prompt",
                        source_id="llm_review",
                        file="src/app.py",
                        line_start=10,
                        line_end=10,
                        excerpt="example finding",
                        verified=False,
                    )
                ],
            )
        ],
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.name == "findings.json"
    assert payload["count"] == 1
    assert payload["findings"][0]["summary"] == "Example finding"
    assert payload["findings"][0]["location_valid"] is True
