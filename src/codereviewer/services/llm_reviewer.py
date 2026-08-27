"""LLM review orchestration for M6."""

from __future__ import annotations

import hashlib
import json

from codereviewer.domain.enums import Confidence, FindingSource, Severity
from codereviewer.domain.errors import LLMResponseParseError
from codereviewer.domain.interfaces.llm import LLMProvider
from codereviewer.domain.models import EvidenceRef, Finding, LLMReviewResult, ReviewSnapshot
from codereviewer.services.security import build_llm_diff_excerpt


class LLMReviewer:
    """Prepare prompts and parse structured LLM review output."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def build_prompt(
        self,
        snapshot: ReviewSnapshot,
        *,
        max_chars: int = 12000,
        budget_mode: str = "normal",
    ) -> str:
        """Build the M6 JSON-only review prompt."""

        diff_excerpt = build_llm_diff_excerpt(snapshot, max_chars=max_chars)
        mode_instruction = self._mode_instruction(budget_mode)
        return (
            "Review the following code diff and return JSON only.\n"
            "Schema:\n"
            "{\n"
            '  "findings": [\n'
            "    {\n"
            '      "summary": "string",\n'
            '      "severity": "critical|high|medium|low",\n'
            '      "confidence": "high|reference",\n'
            '      "file": "string|null",\n'
            '      "line": 123,\n'
            '      "explanation": "string",\n'
            '      "suggested_fix": "string|null"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Only report issues that are grounded in the diff.\n\n"
            f"{mode_instruction}\n\n"
            f"{diff_excerpt}"
        )

    def review(self, snapshot: ReviewSnapshot) -> LLMReviewResult:
        """Run one LLM review and parse its structured findings."""

        return self.review_prompt(self.build_prompt(snapshot))

    def review_prompt(self, prompt: str) -> LLMReviewResult:
        """Run one already-prepared review prompt and parse its findings."""

        result = self._provider.review(prompt)
        result.findings = self.parse_findings(result.raw_content)
        return result

    @staticmethod
    def _mode_instruction(budget_mode: str) -> str:
        if budget_mode == "essential_only":
            return (
                "Budget mode: essential_only. Focus only on the most likely, "
                "highest-signal correctness or security issues in the changed code."
            )
        if budget_mode == "degraded":
            return (
                "Budget mode: degraded. Prioritize high-signal findings and avoid "
                "speculative or low-value observations."
            )
        return "Budget mode: normal. Review the diff normally."

    def parse_findings(self, raw_content: str) -> list[Finding]:
        """Parse the JSON review payload into structured findings."""

        try:
            payload = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise LLMResponseParseError("LLM response was not valid JSON.") from exc

        if not isinstance(payload, dict):
            raise LLMResponseParseError("LLM response must be a JSON object.")
        findings_payload = payload.get("findings")
        if findings_payload is None:
            return []
        if not isinstance(findings_payload, list):
            raise LLMResponseParseError("LLM response field 'findings' must be a list.")

        findings: list[Finding] = []
        for item in findings_payload:
            if not isinstance(item, dict):
                raise LLMResponseParseError("Each LLM finding must be a JSON object.")

            summary = _require_string(item.get("summary"), "summary")
            severity = Severity(_require_string(item.get("severity"), "severity"))
            confidence = Confidence(_require_string(item.get("confidence"), "confidence"))
            file = _optional_string(item.get("file"))
            line = _optional_int(item.get("line"))
            explanation = _require_string(item.get("explanation"), "explanation")
            suggested_fix = _optional_string(item.get("suggested_fix"))

            findings.append(
                Finding(
                    id=_finding_id(summary, file, line),
                    summary=summary,
                    severity=severity,
                    confidence=confidence,
                    file=file,
                    line=line,
                    explanation=explanation,
                    evidence=[
                        EvidenceRef(
                            source_type="llm_prompt",
                            source_id="llm_review",
                            file=file,
                            line_start=line,
                            line_end=line,
                            excerpt=summary,
                            verified=False,
                        )
                    ],
                    suggested_fix=suggested_fix,
                    source_type=FindingSource.LLM,
                )
            )
        return findings


def _finding_id(summary: str, file: str | None, line: int | None) -> str:
    digest = hashlib.sha1(f"{summary}:{file}:{line}".encode("utf-8")).hexdigest()
    return f"llm-{digest[:10]}"


def _require_string(value: object, field_name: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise LLMResponseParseError(f"LLM finding field '{field_name}' must be a non-empty string.")


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None
