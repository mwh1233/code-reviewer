"""Validate finding locations against added lines in the immutable diff snapshot."""

from __future__ import annotations

from codereviewer.domain.enums import Confidence
from codereviewer.domain.models import EvidenceRef, Finding, ReviewSnapshot
from codereviewer.services.diff_preprocessor import prepare_diff_analysis


class CommentLocator:
    """Validate that findings point to added lines in changed files."""

    def __init__(self, snapshot: ReviewSnapshot) -> None:
        self._changed_files = set(snapshot.changed_files)
        self._added_lines_by_file: dict[str, set[int]] = {}

        analysis = prepare_diff_analysis(snapshot)
        for file_diff in analysis.files:
            self._added_lines_by_file[file_diff.path] = {
                added_line.line_number
                for added_line in file_diff.added_lines
                if added_line.line_number is not None
            }

    def validate(self, findings: list[Finding]) -> list[Finding]:
        """Mark invalid locations and downgrade them to reference confidence."""

        validated: list[Finding] = []
        for finding in findings:
            failure_reason = self._failure_reason(finding)
            if failure_reason is None:
                validated.append(finding.model_copy(update={"location_valid": True}))
                continue

            evidence = list(finding.evidence)
            evidence.append(
                EvidenceRef(
                    source_type="location_check_failed",
                    source_id="comment_locator",
                    file=finding.file,
                    line_start=finding.line,
                    line_end=finding.line,
                    excerpt=failure_reason,
                    verified=False,
                )
            )
            validated.append(
                finding.model_copy(
                    update={
                        "location_valid": False,
                        "confidence": Confidence.REFERENCE,
                        "evidence": evidence,
                    }
                )
            )
        return validated

    def _failure_reason(self, finding: Finding) -> str | None:
        if finding.file is None or finding.file not in self._changed_files:
            return "finding file is not a changed file in the snapshot."
        if finding.line is None:
            return "finding line must point to an added line in the diff."

        added_lines = self._added_lines_by_file.get(finding.file, set())
        if finding.line not in added_lines:
            return "finding line does not map to an added line in the diff."
        return None
