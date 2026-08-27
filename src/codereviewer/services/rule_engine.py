"""Deterministic rule engine for M5/P2-M5 candidate findings."""

from __future__ import annotations

import hashlib
import re

from codereviewer.domain.enums import Confidence, FindingSource, Severity
from codereviewer.domain.errors import ToolExecutionError
from codereviewer.domain.interfaces.scm import SCMProvider
from codereviewer.domain.interfaces.tool import ReviewRule, ToolExecutor
from codereviewer.domain.models import EvidenceRef, Finding, ReviewSnapshot, RuleSpec
from codereviewer.services.diff_preprocessor import extract_added_lines
from codereviewer.tools.builtin import ListChangedFilesInput, ReadDiffInput


_SECRET_FILE_PATTERNS = (
    re.compile(r"(^|/)\.env(\..+)?$", re.IGNORECASE),
    re.compile(r"(^|/).+\.pem$", re.IGNORECASE),
    re.compile(r"(^|/).+\.key$", re.IGNORECASE),
    re.compile(r"(^|/)id_rsa$", re.IGNORECASE),
    re.compile(r"(^|/)id_dsa$", re.IGNORECASE),
)
_SECRET_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"), "GitHub token"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-\.]{20,}\b"), "GitLab token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "API token"),
)


class SecretLikeFilenameRule:
    """Flag changed filenames that look like credentials or secrets."""

    meta = RuleSpec(
        name="secret_like_filename_changed",
        description="Detect changed filenames that look like secrets or credentials.",
        input_scope="changed_files",
        default_confidence=Confidence.HIGH,
        failure_behavior="continue_without_finding",
    )

    def evaluate(
        self,
        *,
        snapshot: ReviewSnapshot,
        tool_executor: ToolExecutor,
        provider: SCMProvider | None = None,
    ) -> list[Finding]:
        result = tool_executor.run_tool(
            "list_changed_files",
            ListChangedFilesInput(),
            snapshot=snapshot,
            provider=provider,
        )
        files = _require_files(result, self.meta.name)

        findings: list[Finding] = []
        for path in files:
            if not any(pattern.search(path) for pattern in _SECRET_FILE_PATTERNS):
                continue
            findings.append(
                Finding(
                    id=_finding_id(self.meta.name, path, None),
                    summary="Sensitive-looking file appears in the change set.",
                    severity=Severity.HIGH,
                    confidence=self.meta.default_confidence,
                    file=path,
                    line=None,
                    explanation=(
                        "This change includes a file path that commonly stores secrets or "
                        "credentials. Review whether the file should be committed at all."
                    ),
                    evidence=[
                        EvidenceRef(
                            source_type="tool",
                            source_id="list_changed_files",
                            file=path,
                            excerpt=f"Changed file: {path}",
                            verified=True,
                        )
                    ],
                    source_type=FindingSource.RULE,
                )
            )
        return findings


class AddedPatternRule:
    """Flag one specific added-line pattern in changed file diffs."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        pattern: str,
        label: str,
        severity: Severity = Severity.LOW,
    ) -> None:
        self.meta = RuleSpec(
            name=name,
            description=description,
            input_scope="diff_lines",
            default_confidence=Confidence.HIGH,
            failure_behavior="continue_without_finding",
        )
        self._pattern = re.compile(pattern)
        self._label = label
        self._severity = severity

    def evaluate(
        self,
        *,
        snapshot: ReviewSnapshot,
        tool_executor: ToolExecutor,
        provider: SCMProvider | None = None,
    ) -> list[Finding]:
        files_result = tool_executor.run_tool(
            "list_changed_files",
            ListChangedFilesInput(),
            snapshot=snapshot,
            provider=provider,
        )
        files = _require_files(files_result, self.meta.name)

        findings: list[Finding] = []
        for path in files:
            diff_result = tool_executor.run_tool(
                "read_diff",
                ReadDiffInput(file_path=path),
                snapshot=snapshot,
                provider=provider,
            )
            if diff_result.error is not None:
                raise ToolExecutionError(
                    f"rule '{self.meta.name}' could not read diff for {path}: {diff_result.error}"
                )
            diff_text = str(diff_result.payload.get("diff_text", ""))
            if bool(diff_result.payload.get("is_binary")):
                continue

            for added_line in extract_added_lines(diff_text):
                if not self._pattern.search(added_line.content):
                    continue
                findings.append(
                    Finding(
                        id=_finding_id(self.meta.name, path, added_line.line_number),
                        summary="Debug statement added in the changed code.",
                        severity=self._severity,
                        confidence=self.meta.default_confidence,
                        file=path,
                        line=added_line.line_number,
                        explanation=(
                            f"The added line contains a {self._label}. Confirm it is not an "
                            "accidental debug artifact before merging."
                        ),
                        evidence=[
                            EvidenceRef(
                                source_type="diff",
                                source_id="read_diff",
                                file=path,
                                line_start=added_line.line_number,
                                line_end=added_line.line_number,
                                excerpt=added_line.content,
                                verified=True,
                            )
                        ],
                        source_type=FindingSource.RULE,
                    )
                )
        return findings


class RuleEngine:
    """Register and execute deterministic rules."""

    def __init__(self) -> None:
        self._rules: dict[str, ReviewRule] = {}

    def register(self, rule: ReviewRule) -> None:
        self._rules[rule.meta.name] = rule

    def evaluate(
        self,
        *,
        snapshot: ReviewSnapshot,
        tool_executor: ToolExecutor,
        provider: SCMProvider | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for rule in self._rules.values():
            findings.extend(
                rule.evaluate(
                    snapshot=snapshot,
                    tool_executor=tool_executor,
                    provider=provider,
                )
            )
        return findings


class HardcodedSecretValueRule:
    """Flag newly added lines that contain token-like secret values."""

    meta = RuleSpec(
        name="hardcoded_secret_value_added",
        description="Detect token-like secret values added directly in the diff.",
        input_scope="diff_lines",
        default_confidence=Confidence.HIGH,
        failure_behavior="continue_without_finding",
    )

    def evaluate(
        self,
        *,
        snapshot: ReviewSnapshot,
        tool_executor: ToolExecutor,
        provider: SCMProvider | None = None,
    ) -> list[Finding]:
        files_result = tool_executor.run_tool(
            "list_changed_files",
            ListChangedFilesInput(),
            snapshot=snapshot,
            provider=provider,
        )
        files = _require_files(files_result, self.meta.name)

        findings: list[Finding] = []
        for path in files:
            diff_result = tool_executor.run_tool(
                "read_diff",
                ReadDiffInput(file_path=path),
                snapshot=snapshot,
                provider=provider,
            )
            if diff_result.error is not None:
                raise ToolExecutionError(
                    f"rule '{self.meta.name}' could not read diff for {path}: {diff_result.error}"
                )
            diff_text = str(diff_result.payload.get("diff_text", ""))
            if bool(diff_result.payload.get("is_binary")):
                continue

            for added_line in extract_added_lines(diff_text):
                secret_label = _match_secret_label(added_line.content)
                if secret_label is None:
                    continue
                findings.append(
                    Finding(
                        id=_finding_id(self.meta.name, path, added_line.line_number),
                        summary="Token-like secret value added in the changed code.",
                        severity=Severity.CRITICAL,
                        confidence=self.meta.default_confidence,
                        file=path,
                        line=added_line.line_number,
                        explanation=(
                            f"The added line contains a value that matches a {secret_label} "
                            "pattern. Confirm it is not a real credential before merging."
                        ),
                        evidence=[
                            EvidenceRef(
                                source_type="diff",
                                source_id="read_diff",
                                file=path,
                                line_start=added_line.line_number,
                                line_end=added_line.line_number,
                                excerpt=added_line.content,
                                verified=True,
                            )
                        ],
                        source_type=FindingSource.RULE,
                    )
                )
        return findings


def build_builtin_rule_engine() -> RuleEngine:
    """Build a rule engine with the built-in M5 deterministic rules."""

    engine = RuleEngine()
    engine.register(SecretLikeFilenameRule())
    engine.register(
        AddedPatternRule(
            name="console_log_added",
            description="Detect newly added console.log statements in the diff.",
            pattern=r"\bconsole\.log\(",
            label="console.log call",
        )
    )
    engine.register(
        AddedPatternRule(
            name="debugger_statement_added",
            description="Detect newly added debugger statements in the diff.",
            pattern=r"\bdebugger;",
            label="debugger statement",
        )
    )
    engine.register(
        AddedPatternRule(
            name="pdb_set_trace_added",
            description="Detect newly added pdb.set_trace calls in the diff.",
            pattern=r"\bpdb\.set_trace\(",
            label="pdb.set_trace call",
        )
    )
    engine.register(HardcodedSecretValueRule())
    return engine


def _require_files(result, rule_name: str) -> list[str]:
    if result.error is not None:
        raise ToolExecutionError(
            f"rule '{rule_name}' could not list changed files: {result.error}"
        )
    files = result.payload.get("files")
    if not isinstance(files, list) or not all(isinstance(file, str) for file in files):
        raise ToolExecutionError(
            f"rule '{rule_name}' received an invalid changed-file payload."
        )
    return list(files)


def _finding_id(rule_name: str, path: str, line: int | None) -> str:
    digest = hashlib.sha1(f"{rule_name}:{path}:{line}".encode("utf-8")).hexdigest()
    return f"{rule_name}-{digest[:10]}"


def _match_secret_label(content: str) -> str | None:
    for pattern, label in _SECRET_VALUE_PATTERNS:
        if pattern.search(content):
            return label
    return None
