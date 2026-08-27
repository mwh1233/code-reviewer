"""Write structured findings artifacts to disk."""

from __future__ import annotations

import json
from pathlib import Path

from codereviewer.domain.models import Finding


def write_findings_json(review_root: Path, findings: list[Finding]) -> Path:
    """Write the final structured findings to findings.json."""

    review_root.mkdir(parents=True, exist_ok=True)
    output_path = review_root / "findings.json"
    payload = {
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "count": len(findings),
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return output_path
